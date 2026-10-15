"""PDF → Markdown engine.

Strategy (offline-first, best fidelity with stable PyMuPDF primitives):

1. Measure the document's body font size (for heading heuristics).
2. Per page:
   - detect tables via PyMuPDF's built-in table finder → real Markdown tables
   - extract embedded images to the asset folder → embedded with relative links
   - classify the page as text-based or *scanned* (almost no text + full-page image)
   - scanned pages → optional AI vision conversion, else OCR (Tesseract), else warning
3. Layout-aware text extraction:
   - heading levels from font size / boldness
   - tight-leading lines merged into paragraphs, hyphenation joined
   - bullet characters converted to markdown lists
   - equation-like lines wrapped in $$ … $$ (best-effort, per plan §6)
4. Repeated page headers/footers (top/bottom bands on most pages) are dropped.

The optional AI path is loaded lazily (app.ai_helper arrives in milestone M7);
until then the engine simply falls back to OCR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import pymupdf as fitz  # PyMuPDF ≥ 1.24 (fitz alias kept for older versions)
except ImportError:  # pragma: no cover - dependency guard
    try:
        import fitz  # type: ignore
    except ImportError:
        fitz = None

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover - optional OCR dependency
    pytesseract = None
    Image = None

from app.engines.base import ConversionEngine, ConversionResult
from app.utils import assets_dir_for, escape_table_cell, unique_path


def _normalize_text(text: str) -> str:
    """Clean extracted text: real spaces instead of nbsp, drop control chars."""
    return (text.replace("\xa0", " ")
                .replace("\u00ad", "")   # soft hyphen
                .replace("\x00", "")      # nulls from broken font maps
                .translate({c: None for c in range(32) if c not in (9, 10, 13)}))

# Unicode characters that suggest a maths context
_MATH_CHARS = set("∑∏∫√∞≈≠≤≥±×÷→←↔∂∆∇∈∉⊂∪∩λμπσαβγδθφψωΩΣΔΦΘΛ")
_MATH_RELATIONS = ("≈", "≠", "≤", "≥")
_BULLET_CHARS = "•◦▪●–—"

_RE_TRAILING_HYPHEN = re.compile(r"(\w)-\s*$")

# "Page 3 of 12", "3/12", "- 3 -", bare page numbers in header/footer bands
_RE_PAGE_NUMBER = re.compile(
    r"^(?:page\s+)?\d{1,3}(?:\s*(?:/|of)\s*\d{1,3})?$|^[-–—]\s*\d{1,3}\s*[-–—]$|^\d{1,3}$",
    re.IGNORECASE,
)


@dataclass
class _Line:
    text: str
    size: float
    bold: bool
    y0: float
    y1: float


@dataclass
class _PageItems:
    """Everything extracted from one page, in vertical order."""

    height: float
    items: list[dict] = field(default_factory=list)  # dicts: kind=lines|table|image|text


class PdfEngine(ConversionEngine):
    """Convert a PDF file to Markdown."""

    name = "pdf (PyMuPDF)"
    extensions = (".pdf",)

    # ------------------------------------------------------------------ API
    def convert(self, input_path: Path, output_md_path: Path, options: dict[str, Any]) -> ConversionResult:
        if fitz is None:
            return ConversionResult(False, error="PyMuPDF is not installed (pip install PyMuPDF)")

        extract_images = bool(options.get("extract_images", True))
        ocr_enabled = bool(options.get("ocr_enabled", True))
        ai_enabled = bool(options.get("ai_enabled", False))
        warnings: list[str] = []
        assets_dir = assets_dir_for(output_md_path) if extract_images else None

        try:
            doc = fitz.open(input_path)
        except Exception as exc:
            return ConversionResult(False, error=f"Cannot open PDF: {exc}")

        if doc.needs_pass:
            doc.close()
            return ConversionResult(False, error="PDF is password-protected")

        try:
            body_size = self._body_font_size(doc)
            seen_xrefs: dict[int, str] = {}
            pages: list[_PageItems] = [
                self._process_page(doc, page, body_size, assets_dir, seen_xrefs,
                                   extract_images, ocr_enabled, ai_enabled, warnings)
                for page in doc
            ]
        finally:
            doc.close()

        recurring = self._recurring_band_texts(pages) if len(pages) >= 4 else set()
        rendered = [self._render_page(p, body_size, recurring) for p in pages]
        markdown = "\n\n".join(text for text in rendered if text).strip()
        if not markdown:
            warnings.append("No extractable content found in this PDF")
        markdown += "\n"

        metadata: dict[str, Any] = {"pages": len(pages)}
        return ConversionResult(True, markdown, warnings, metadata=metadata)

    # ------------------------------------------------------------ pass 1
    def _body_font_size(self, doc: Any) -> float:
        """Most-used font size (weighted by characters) over the first pages."""
        counts: dict[float, int] = {}
        for page in doc:
            if page.number >= 10:
                break
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        text_len = len(span["text"].strip())
                        if text_len:
                            counts[round(span["size"], 1)] = counts.get(round(span["size"], 1), 0) + text_len
        return max(counts, key=counts.get) if counts else 11.0

    def _process_page(self, doc: Any, page: Any, body_size: float, assets_dir: Optional[Path],
                      seen_xrefs: dict[int, str], extract_images: bool, ocr_enabled: bool,
                      ai_enabled: bool, warnings: list[str]) -> _PageItems:
        page_no = page.number + 1
        height = float(page.rect.height)
        result = _PageItems(height=height)

        text_dict = page.get_text("dict", sort=True)
        text_blocks = [b for b in text_dict["blocks"] if b.get("type") == 0]
        char_count = sum(len(b.get("text", "").strip()) for b in text_blocks)

        # --- scanned-page detection -------------------------------------
        if char_count < 30 and self._page_is_mostly_image(page):
            text = self._scanned_page_text(page, page_no, ai_enabled, ocr_enabled, warnings)
            if text:
                result.items.append({"kind": "text", "y": 0.0, "band": "body", "text": text})
            return result

        # --- tables -------------------------------------------------------
        raw_table_bboxes: list[tuple] = []
        for bbox, rows in self._find_tables(page):
            raw_table_bboxes.append(bbox)
            result.items.append({"kind": "table", "y": bbox[1], "rows": rows})

        # --- text blocks ---------------------------------------------------
        for block in text_blocks:
            bbox = block["bbox"]
            if self._inside_any_table(bbox, raw_table_bboxes):
                continue  # table text is rendered from the table rows themselves
            lines: list[_Line] = []
            for raw_line in block.get("lines", []):
                spans = raw_line.get("spans", [])
                text = _normalize_text("".join(s.get("text", "") for s in spans))
                if not text.strip():
                    continue
                size = max((s.get("size", 0.0) for s in spans), default=0.0)
                bold = any(bool(s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower()
                           for s in spans)
                lb = raw_line.get("bbox", bbox)
                lines.append(_Line(text.replace("\u00ad", ""), size, bold, lb[1], lb[3]))
            if not lines:
                continue
            band = "top" if bbox[1] < height * 0.08 else ("bottom" if bbox[3] > height * 0.92 else "body")
            result.items.append({"kind": "lines", "y": bbox[1], "band": band, "lines": lines})

        # --- images --------------------------------------------------------
        if extract_images and assets_dir is not None:
            result.items.extend(self._extract_images(doc, page, assets_dir, seen_xrefs, warnings))

        result.items.sort(key=lambda it: it["y"])
        return result

    @staticmethod
    def _page_is_mostly_image(page: Any) -> bool:
        """True when images cover >50% of the page (typical scanned page)."""
        page_area = max(page.rect.width * page.rect.height, 1.0)
        area = 0.0
        try:
            for info in page.get_image_info():
                area += info["bbox"].width * info["bbox"].height
        except Exception:
            return False
        return area > 0.5 * page_area

    def _find_tables(self, page: Any) -> list[tuple[tuple, list[list[Optional[str]]]]]:
        finder = getattr(page, "find_tables", None)
        if finder is None:
            return []
        try:
            found = finder()
        except Exception:
            return []
        tables = []
        for table in getattr(found, "tables", []):
            try:
                rows = table.extract()
            except Exception:
                continue
            if rows:
                tables.append((table.bbox, rows))
        return tables

    @staticmethod
    def _inside_any_table(bbox: tuple, tables: list[tuple]) -> bool:
        """True when a text block's center sits inside a detected table bbox."""
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        for tx0, ty0, tx1, ty1 in tables:
            if tx0 - 2 <= cx <= tx1 + 2 and ty0 - 2 <= cy <= ty1 + 2:
                return True
        return False

    def _extract_images(self, doc: Any, page: Any, assets_dir: Path, seen_xrefs: dict[int, str],
                        warnings: list[str]) -> list[dict]:
        items: list[dict] = []
        page_no = page.number + 1
        page_area = max(page.rect.width * page.rect.height, 1.0)
        try:
            images = page.get_images(full=True)
        except Exception:
            return items
        for info in images:
            xref = info[0]
            if not xref:
                continue
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            for rect in rects:
                if rect.width < 20 or rect.height < 20:
                    continue  # decoration / bullet glyph
                if rect.width * rect.height > 0.85 * page_area:
                    continue  # full-page background (already handled as scanned page)
                if xref in seen_xrefs:
                    rel = seen_xrefs[xref]
                else:
                    try:
                        extracted = doc.extract_image(xref)
                    except Exception as exc:
                        warnings.append(f"Could not extract image on page {page_no}: {exc}")
                        continue
                    ext = extracted.get("ext", "png")
                    path = unique_path(assets_dir, f"p{page_no}_img{xref}.{ext}")
                    try:
                        path.write_bytes(extracted["image"])
                    except OSError as exc:
                        warnings.append(f"Could not save image on page {page_no}: {exc}")
                        continue
                    rel = f"{assets_dir.name}/{path.name}"
                    seen_xrefs[xref] = rel
                items.append({"kind": "image", "y": float(rect.y0), "path": rel,
                              "alt": f"Image on page {page_no}"})
        return items

    # --------------------------------------------------------------- OCR
    def _scanned_page_text(self, page: Any, page_no: int, ai_enabled: bool,
                           ocr_enabled: bool, warnings: list[str]) -> str:
        # 1st choice: AI vision conversion (available from milestone M7)
        if ai_enabled:
            helper = self._get_ai_helper()
            if helper is not None:
                try:
                    png_bytes = page.get_pixmap(dpi=200).tobytes("png")
                    text = helper.page_image_to_markdown(png_bytes, context=f"PDF page {page_no}")
                    if text and text.strip():
                        return text.strip()
                except Exception as exc:
                    warnings.append(f"AI conversion failed on page {page_no} ({exc}); trying OCR")

        # 2nd choice: local OCR
        if ocr_enabled:
            if pytesseract is None:
                warnings.append(
                    f"Page {page_no} looks scanned; OCR unavailable "
                    "(install: pip install pytesseract + Tesseract-OCR)")
                return ""
            try:
                pix = page.get_pixmap(dpi=200)
                if hasattr(pix, "pil_image"):
                    image = pix.pil_image()
                else:
                    mode = "RGB" if pix.n < 4 else "RGBA"
                    image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
                return pytesseract.image_to_string(image).strip()
            except Exception as exc:
                warnings.append(f"OCR failed on page {page_no}: {exc}")
                return ""

        warnings.append(f"Page {page_no} looks scanned; content skipped (OCR disabled)")
        return ""

    @staticmethod
    def _get_ai_helper() -> Any:
        """Lazily load the optional AI helper (added in milestone M7)."""
        try:
            from app import ai_helper  # type: ignore
        except ImportError:
            return None
        return getattr(ai_helper, "AiHelper", None) and ai_helper.AiHelper()

    # ------------------------------------------------------- pass 2 / render
    @staticmethod
    def _recurring_band_texts(pages: list[_PageItems]) -> set[str]:
        """Normalized texts that appear in the top/bottom band on most pages (headers/footers)."""
        per_page: list[set[str]] = []
        for page in pages:
            norms: set[str] = set()
            for item in page.items:
                if item.get("band") in ("top", "bottom"):
                    if item["kind"] == "lines":
                        for line in item["lines"]:
                            text = re.sub(r"\s+", " ", line.text).strip().lower()
                            if 1 < len(text) < 80:
                                norms.add(text)
                    elif item["kind"] == "text":
                        text = re.sub(r"\s+", " ", item["text"]).strip().lower()
                        if 1 < len(text) < 80:
                            norms.add(text)
            per_page.append(norms)
        counts: dict[str, int] = {}
        for norms in per_page:
            for text in norms:
                counts[text] = counts.get(text, 0) + 1
        threshold = max(3, int(len(pages) * 0.6))
        return {text for text, count in counts.items() if count >= threshold}

    def _render_page(self, page: _PageItems, body_size: float, recurring: set[str]) -> str:
        parts: list[str] = []
        para: list[_Line] = []

        def flush() -> None:
            if para:
                parts.append(_join_paragraph(para))
                para.clear()

        for item in page.items:
            kind = item["kind"]
            if kind == "lines":
                for line in item["lines"]:
                    text = line.text.strip()
                    if not text:
                        continue
                    norm = re.sub(r"\s+", " ", text).lower()
                    if item.get("band") in ("top", "bottom") and (
                            norm in recurring or _RE_PAGE_NUMBER.match(norm)):
                        continue  # repeating header/footer or page number
                    if _is_equation(text):
                        flush()
                        parts.append(f"$$\n{text}\n$$")
                        continue
                    level = _heading_level(line.size, line.bold, body_size, text)
                    if level:
                        flush()
                        parts.append(f"{'#' * level} {text}")
                        continue
                    bullet = _bullet_prefix(text)
                    if bullet is not None:
                        flush()
                        parts.append(bullet)
                        continue
                    if para and _tightly_leading(para[-1], line):
                        para.append(line)
                    else:
                        flush()
                        para.append(line)
                flush()
            elif kind == "table":
                flush()
                rendered = _render_table(item["rows"])
                if rendered:
                    parts.append(rendered)
            elif kind == "image":
                flush()
                parts.append(f"![{item['alt']}]({item['path']})")
            elif kind == "text":
                flush()
                for chunk in item["text"].split("\n\n"):
                    chunk = chunk.strip()
                    if chunk:
                        parts.append(chunk)
        flush()
        return "\n\n".join(parts)


# ---------------------------------------------------------------- helpers

def _join_paragraph(lines: list[_Line]) -> str:
    """Merge tight-leading lines into one paragraph, fixing hyphenation."""
    text = lines[0].text.strip()
    for line in lines[1:]:
        piece = line.text.strip()
        match = _RE_TRAILING_HYPHEN.search(text)
        if match and piece[:1].islower():
            text = text[: match.start(1)] + piece  # de-hyphenate: "exam- ple" → "example"
        else:
            text = f"{text} {piece}"
    return re.sub(r"\s+", " ", text).strip()


def _tightly_leading(prev: _Line, line: _Line) -> bool:
    return (line.y0 - prev.y1) < max(prev.size, line.size) * 0.6


def _is_equation(text: str) -> bool:
    """Best-effort maths detection (plan §9: offline LaTeX is heuristic)."""
    stripped = text.strip()
    if not 2 <= len(stripped) <= 120:
        return False
    symbols = sum(1 for ch in stripped if ch in _MATH_CHARS)
    has_relation = ("=" in stripped) or any(op in stripped for op in _MATH_RELATIONS)
    return (symbols >= 3 and has_relation) or symbols >= 5


def _heading_level(size: float, bold: bool, body_size: float, text: str) -> int:
    if not text or len(text) > 120:
        return 0
    ratio = size / body_size if body_size else 1.0
    if ratio >= 1.75:
        return 1
    if ratio >= 1.4:
        return 2
    if ratio >= 1.18:
        return 3
    if bold and ratio >= 1.0 and not text.endswith((".", ",", ";")):
        if text.isupper() and len(text) <= 60:
            return 4
        if len(text) <= 80 and not text.startswith(("http://", "https://")):
            return 4
    return 0


def _bullet_prefix(text: str) -> Optional[str]:
    """Turn a bullet line into a markdown list item (None if not a bullet)."""
    stripped = text.lstrip()
    if not stripped:
        return None
    leading_spaces = len(text) - len(stripped)
    indent = "  " * min(3, leading_spaces // 2)
    if stripped[0] in _BULLET_CHARS or stripped.startswith("- "):
        body = stripped[1:].strip() if stripped[0] != "-" else stripped[2:].strip()
        return f"{indent}- {body}"
    if re.match(r"^\d{1,2}[.)]\s+", stripped):
        return f"{indent}{stripped}"  # ordered lists survive as-is
    return None


def _render_table(rows: list[list[Optional[str]]]) -> str:
    """Render extracted table rows as a GitHub-flavored markdown table."""
    cleaned = [[re.sub(r"\s+", " ", (cell or "")).strip() for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    header = [escape_table_cell(cell) or " " for cell in cleaned[0]]
    body = [[escape_table_cell(cell) for cell in row] for row in cleaned[1:]]
    lines = ["| " + " | ".join(header) + " |",
             "|" + "---|" * width]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)
