"""PPTX → Markdown engine.

Converts PowerPoint presentations slide by slide (plan §6):

- slide title        → `## Slide N: Title`
- body placeholders  → bullet lists, nesting levels preserved (2 spaces/level)
- tables             → real Markdown tables
- pictures           → extracted to the asset folder, embedded with relative links
- embedded equations → best-effort: Office Math (OMML) text nodes joined as inline code
- speaker notes      → appended as a blockquote per slide (toggleable)

Shapes are processed in vertical reading order (top, then left) so multi-box
slides read naturally in the resulting document.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

try:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
except ImportError:  # pragma: no cover - dependency guard
    Presentation = None  # type: ignore

from app.engines.base import ConversionEngine, ConversionResult
from app.utils import assets_dir_for, escape_table_cell, unique_path

# DrawingML namespace used for Office Math (equations)
_NS_MATH = "{http://schemas.openxmlformats.org/drawingml/2006/math}"

_RE_CLEAN = re.compile(r"[\x00-\x08\x0b-\x1f]")


class PptxEngine(ConversionEngine):
    """Convert a .pptx file to Markdown."""

    name = "pptx (python-pptx)"
    extensions = (".pptx",)

    # ------------------------------------------------------------------ API
    def convert(self, input_path: Path, output_md_path: Path, options: dict[str, Any]) -> ConversionResult:
        if Presentation is None:
            return ConversionResult(False, error="python-pptx is not installed (pip install python-pptx)")

        extract_images = bool(options.get("extract_images", True))
        include_notes = bool(options.get("include_speaker_notes", True))
        assets_dir = assets_dir_for(output_md_path) if extract_images else None
        warnings: list[str] = []

        try:
            prs = Presentation(str(input_path))
        except Exception as exc:
            return ConversionResult(False, error=f"Cannot open PPTX: {exc}")

        slides_out: list[str] = []
        image_count = 0
        for index, slide in enumerate(prs.slides, 1):
            body, images = self._render_slide(slide, index, assets_dir, warnings)
            image_count += images
            notes = self._slide_notes(slide) if include_notes else ""
            section = body.strip()
            if notes:
                quoted = "\n".join(f"> {line}" for line in notes.splitlines() if line.strip())
                section = f"{section}\n\n**Notes:**\n\n{quoted}" if section else quoted
            if section:
                slides_out.append(section)

        if not slides_out:
            warnings.append("No slide content found in this presentation")

        markdown = "\n\n---\n\n".join(slides_out) + "\n"
        metadata = {"slides": len(prs.slides), "images": image_count}
        return ConversionResult(True, markdown, warnings, metadata=metadata)

    # -------------------------------------------------------------- slides
    def _render_slide(self, slide: Any, index: int, assets_dir: Optional[Path],
                      warnings: list[str]) -> tuple[str, int]:
        title = ""
        title_shape = None
        try:
            title_shape = slide.shapes.title
            if title_shape is not None:
                title = _clean(title_shape.text)
        except Exception:
            pass

        shapes = [s for s in slide.shapes if s.shape_type != MSO_SHAPE_TYPE.TEXT_BOX or _has_visible_text(s)]
        shapes.sort(key=lambda s: (int(getattr(s, "top", 0) or 0), int(getattr(s, "left", 0) or 0)))

        parts: list[str] = []
        images = 0
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                text, count = self._render_group(shape, assets_dir, warnings)
                images += count
                if text:
                    parts.append(text)
                continue
            if getattr(shape, "has_table", False):
                table_md = _render_shape_table(shape)
                if table_md:
                    parts.append(table_md)
                continue
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE and assets_dir is not None:
                saved = self._save_picture(shape, assets_dir, index, warnings)
                if saved:
                    images += 1
                    parts.append(f"![Slide {index} image]({saved})")
                continue
            if getattr(shape, "has_text_frame", False):
                text = _render_text_frame(shape.text_frame)
                # skip the title placeholder — it already became the heading
                if title_shape is not None and shape.shape_id == title_shape.shape_id:
                    continue
                if text and text.strip() != title:
                    parts.append(text)
                continue
            math_text = self._extract_math(shape)
            if math_text:
                parts.append(math_text)

        heading = f"## Slide {index}" + (f": {title}" if title else "")
        body = "\n\n".join(p for p in parts if p.strip())
        if body:
            return f"{heading}\n\n{body}", images
        if title:
            return heading, images
        return "", images  # completely empty slide → omitted

    def _render_group(self, group: Any, assets_dir: Optional[Path],
                      warnings: list[str]) -> tuple[str, int]:
        """Recursively render a grouped shape."""
        parts: list[str] = []
        images = 0
        for shape in group.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                text, count = self._render_group(shape, assets_dir, warnings)
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE and assets_dir is not None:
                saved = self._save_picture(shape, assets_dir, 0, warnings)
                text, count = (f"![Group image]({saved})", 1) if saved else ("", 0)
            elif getattr(shape, "has_table", False):
                text, count = _render_shape_table(shape), 0
            elif getattr(shape, "has_text_frame", False):
                text, count = _render_text_frame(shape.text_frame), 0
            else:
                text, count = self._extract_math(shape), 0
            images += count
            if text:
                parts.append(text)
        return "\n\n".join(p for p in parts if p.strip()), images

    # --------------------------------------------------------------- notes
    @staticmethod
    def _slide_notes(slide: Any) -> str:
        try:
            if slide.has_notes_slide:
                return _clean(slide.notes_slide.notes_text_frame.text)
        except Exception:
            pass
        return ""

    # -------------------------------------------------------------- images
    def _save_picture(self, shape: Any, assets_dir: Path, slide_no: int,
                      warnings: list[str]) -> str:
        """Write the picture's bytes to the assets folder; return relative path."""
        try:
            image = shape.image
            blob = image.blob
            ext = image.ext or _ext_from_content_type(image.content_type)
        except Exception as exc:
            warnings.append(f"Could not extract picture ({exc})")
            return ""
        filename = f"slide{slide_no or 'x'}_img{shape.shape_id}.{ext}"
        path = unique_path(assets_dir, filename)
        try:
            path.write_bytes(blob)
        except OSError as exc:
            warnings.append(f"Could not save picture: {exc}")
            return ""
        return f"{assets_dir.name}/{path.name}"

    # ------------------------------------------------------------- equations
    def _extract_math(self, shape: Any) -> str:
        """Best-effort Office Math (OMML) extraction: join math text nodes.

        Offline LaTeX recovery from OMML is out of scope for v1 (plan §9);
        we preserve the characters so no content is lost.
        """
        try:
            element = shape._element
        except AttributeError:
            return ""
        math_nodes = element.findall(f".//{_NS_MATH}t")
        if not math_nodes:
            return ""
        text = "".join(node.text or "" for node in math_nodes).strip()
        return f"${_clean(text)}$" if text else ""


# ---------------------------------------------------------------- helpers

def _clean(text: str) -> str:
    """Remove control characters that break markdown rendering."""
    return _RE_CLEAN.sub("", text).replace("\xa0", " ").strip()


def _has_visible_text(shape: Any) -> bool:
    try:
        return bool(_clean(shape.text))
    except Exception:
        return False


def _render_text_frame(text_frame: Any) -> str:
    """Render a text frame: level-0 lines are '- ' items, deeper levels indent."""
    lines: list[str] = []
    for paragraph in text_frame.paragraphs:
        text = _clean("".join(run.text for run in paragraph.runs))
        if not text:
            continue
        level = max(0, int(paragraph.level or 0))
        prefix = "  " * min(level, 5) + "- "
        lines.append(f"{prefix}{text}")
    return "\n".join(lines)


def _render_shape_table(shape: Any) -> str:
    """Render a pptx table shape as a GitHub-flavored markdown table."""
    try:
        table = shape.table
        rows = [[_clean(cell.text) for cell in row.cells] for row in table.rows]
    except Exception:
        return ""
    rows = [row for row in rows if any(row)]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header = [escape_table_cell(cell) or " " for cell in rows[0]]
    body = [[escape_table_cell(cell) for cell in row] for row in rows[1:]]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def _ext_from_content_type(content_type: str) -> str:
    mapping = {
        "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
        "image/bmp": "bmp", "image/tiff": "tiff", "image/x-emf": "emf",
        "image/x-wmf": "wmf", "image/svg+xml": "svg",
    }
    return mapping.get(content_type.lower().split(";")[0].strip(), "png")
