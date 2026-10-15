"""DOCX → Markdown engine.

Converts Word documents via python-docx (plan §6):

- Heading styles (Heading 1..6) → `#` … `######`
- body paragraphs              → text (bold/italic runs preserved as ** / __)
- bullet & number lists        → markdown list items (level-aware indent)
- tables                       → GitHub-flavored markdown tables
- inline images & drawings     → extracted to the asset folder, embedded
- page breaks                  → `---` horizontal rule
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    import docx
    from docx.oxml.ns import qn
except ImportError:  # pragma: no cover - dependency guard
    docx = None  # type: ignore

from app.engines.base import ConversionEngine, ConversionResult
from app.utils import assets_dir_for, escape_table_cell, unique_path

_RE_CLEAN = re.compile(r"[\x00-\x08\x0b-\x1f]")
_RE_LIST_NUM = re.compile(r"^\d+[.)]\s+")


class DocxEngine(ConversionEngine):
    """Convert a .docx file to Markdown."""

    name = "docx (python-docx)"
    extensions = (".docx",)

    # ------------------------------------------------------------------ API
    def convert(self, input_path: Path, output_md_path: Path, options: dict[str, Any]) -> ConversionResult:
        if docx is None:
            return ConversionResult(False, error="python-docx is not installed (pip install python-docx)")

        extract_images = bool(options.get("extract_images", True))
        assets_dir = assets_dir_for(output_md_path) if extract_images else None
        warnings: list[str] = []

        try:
            document = docx.Document(str(input_path))
        except Exception as exc:
            return ConversionResult(False, error=f"Cannot open DOCX: {exc}")

        parts: list[str] = []
        image_count = 0
        # iterate body elements in document order (paragraphs AND tables)
        for element in document.element.body.iterchildren():
            if element.tag == qn("w:p"):
                text, images = self._render_paragraph(document, element, assets_dir, warnings)
                image_count += images
                if text:
                    parts.append(text)
            elif element.tag == qn("w:tbl"):
                table_md = _render_table(element)
                if table_md:
                    parts.append(table_md)

        if not parts:
            warnings.append("No content found in this document")

        markdown = _join_parts(parts) + "\n"
        metadata = {"paragraphs": len(document.paragraphs), "images": image_count}
        return ConversionResult(True, markdown, warnings, metadata=metadata)

    # ---------------------------------------------------------- paragraphs
    def _render_paragraph(self, document: Any, element: Any, assets_dir: Optional[Path],
                          warnings: list[str]) -> tuple[str, int]:
        """Render one w:p element: heading, list item, page break or body text."""
        from docx.text.paragraph import Paragraph

        paragraph = Paragraph(element, document)
        style_name = (paragraph.style.name or "").lower() if paragraph.style else ""

        # page break → horizontal rule
        if self._is_page_break(element):
            return "---", 0

        # images (runs containing w:drawing / w:pict)
        text_parts: list[str] = []
        images = 0
        for run in paragraph.runs:
            run_text = _RE_CLEAN.sub("", run.text).replace("\xa0", " ")
            saved = self._extract_run_images(run, document, assets_dir, warnings)
            if saved:
                images += 1
                text_parts.append(saved)
            if run_text:
                text_parts.append(_emphasize(run, run_text))
        text = re.sub(r"[ \t]+", " ", "".join(text_parts)).strip()
        if not text:
            return "", images

        # headings: "Heading 1".."Heading 6"; Title becomes H1 so shift the rest
        heading = _heading_from_style(style_name)
        if heading:
            return f"{'#' * min(6, heading + 1)} {text}", images
        if style_name == "title":
            return f"# {text}", images
        if style_name == "subtitle":
            return f"## {text}", images

        # lists: paragraph-level numbering, or List Bullet/Number styles
        indent = self._list_indent(element)
        if indent is None and "list bullet" in style_name:
            indent = 0
        if indent is not None:
            return f"{'  ' * min(indent, 5)}- {text}", images
        if "list number" in style_name or _RE_LIST_NUM.match(text):
            return f"1. {text}", images
        if "quote" in style_name:
            return "\n".join(f"> {line}" for line in text.splitlines()), images

        return text, images

    @staticmethod
    def _list_indent(element: Any) -> int | None:
        """Return the list nesting level (0..) when the paragraph is a list item."""
        p_pr = element.find(qn("w:pPr"))
        if p_pr is None:
            return None
        num_pr = p_pr.find(qn("w:numPr"))
        if num_pr is None:
            return None
        ilvl = num_pr.find(qn("w:ilvl"))
        return int(ilvl.get(qn("w:val"))) if ilvl is not None else 0

    @staticmethod
    def _is_page_break(element: Any) -> bool:
        for br in element.iter(qn("w:br")):
            if br.get(qn("w:type")) == "page":
                return True
        return False

    # -------------------------------------------------------------- images
    def _extract_run_images(self, run: Any, document: Any, assets_dir: Optional[Path],
                            warnings: list[str]) -> str:
        """Save every image referenced by this run; return markdown image refs."""
        if assets_dir is None:
            return ""
        refs: list[str] = []
        blips = run._element.findall(f".//{{http://schemas.openxmlformats.org/drawingml/2006/main}}blip")
        for blip in blips:
            r_id = blip.get(qn("r:embed"))
            if not r_id:
                continue
            try:
                part = document.part.related_parts[r_id]
                blob = part.blob
                ext = (part.content_type or "image/png").split("/")[-1].lower()
                if ext == "jpeg":
                    ext = "jpg"
                filename = f"img{len(list(assets_dir.iterdir())) + 1}.{ext}"
                path = unique_path(assets_dir, filename)
                path.write_bytes(blob)
                refs.append(f"![image]({assets_dir.name}/{path.name})")
            except Exception as exc:
                warnings.append(f"Could not extract embedded image: {exc}")
        # legacy vml pictures
        for imagedata in run._element.findall(f".//{{urn:schemas-microsoft-com:vml}}imagedata"):
            r_id = imagedata.get(qn("r:id"))
            if not r_id:
                continue
            try:
                part = document.part.related_parts[r_id]
                path = unique_path(assets_dir, f"img{len(list(assets_dir.iterdir())) + 1}.png")
                path.write_bytes(part.blob)
                refs.append(f"![image]({assets_dir.name}/{path.name})")
            except Exception as exc:
                warnings.append(f"Could not extract legacy image: {exc}")
        return "\n\n".join(refs)


# ---------------------------------------------------------------- helpers

def _join_parts(parts: list[str]) -> str:
    """Join blocks; consecutive list items stay tight (single newline)."""
    if not parts:
        return ""
    result = parts[0]
    for part in parts[1:]:
        last_line = result.rsplit("\n", 1)[-1]
        if _is_list_line(last_line) and _is_list_line(part):
            result = f"{result}\n{part}"
        else:
            result = f"{result}\n\n{part}"
    return result


def _is_list_line(text: str) -> bool:
    return bool(re.match(r"^(?:\s*[-*]\s|\s*\d+[.)]\s)", text))


def _clean(text: str) -> str:
    return _RE_CLEAN.sub("", text).replace("\xa0", " ").strip()


def _emphasize(run: Any, text: str) -> str:
    """Wrap a run in markdown emphasis when the formatting asks for it.

    Trailing/leading spaces stay outside the markers so the markdown
    remains valid (`**bold** word`, not `**bold **word`).
    """
    try:
        bold, italic = bool(run.bold), bool(run.italic)
    except Exception:
        bold = italic = False
    if not (bold or italic):
        return text
    core = text.strip()
    if not core:
        return text
    left = text[: len(text) - len(text.lstrip())]
    right = text[len(text.rstrip()):]
    if bold and italic:
        return f"{left}***{core}***{right}"
    if bold:
        return f"{left}**{core}**{right}"
    return f"{left}*{core}*{right}"


def _heading_from_style(style_name: str) -> int:
    match = re.match(r"heading\s*(\d)", style_name)
    if match:
        return min(6, max(1, int(match.group(1))))
    if style_name in ("html preformatted", "quote"):
        return 0
    return 0


def _render_table(element: Any) -> str:
    """Render a w:tbl element as a markdown table (cell text joined by <br>)."""
    rows: list[list[str]] = []
    for tr in element.findall(qn("w:tr")):
        row: list[str] = []
        for tc in tr.findall(qn("w:tc")):
            cell_text = " ".join(
                _clean("".join(node.text or "" for node in p.iter(qn("w:t"))))
                for p in tc.findall(qn("w:p"))
            )
            row.append(cell_text)
        if any(row):
            rows.append(row)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header = [escape_table_cell(cell) or " " for cell in rows[0]]
    body = [[escape_table_cell(cell) for cell in row] for row in rows[1:]]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)
