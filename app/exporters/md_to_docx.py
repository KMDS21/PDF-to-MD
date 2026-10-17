"""Markdown → DOCX exporter.

Maps the parsed block model onto python-docx:

- Heading 1..6 → Word heading styles (Title for H1)
- paragraph    → body text with bold/italic runs, links as hyperlinks
- lists        → List Bullet / List Number styles with level indent
- tables       → Table Grid with a bold header row
- code blocks  → monospace paragraphs (Consolas) with light shading
- quotes       → Quote style
- images       → embedded (resolved relative to the .md file), capped to page width
- rules        → horizontal line (bottom-bordered empty paragraph)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

try:
    import docx
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor
except ImportError:  # pragma: no cover - dependency guard
    docx = None  # type: ignore

from app import md_blocks
from app.exporters.base import ExportResult, Exporter

_MAX_IMAGE_WIDTH = Inches(6.0)


class DocxExporter(Exporter):
    """Write a parsed markdown document as a .docx file."""

    name = "docx (python-docx)"
    extension = ".docx"

    def export(self, blocks: list[Any], output_path: Path,
               options: dict[str, Any], base_dir: Path) -> ExportResult:
        if docx is None:
            return ExportResult(False, error="python-docx is not installed (pip install python-docx)")

        warnings: list[str] = []
        images = 0
        try:
            document = Document()
            for block in blocks:
                if isinstance(block, md_blocks.Heading):
                    level = min(6, max(1, block.level))
                    document.add_heading(block.text or " ", level=level)
                elif isinstance(block, md_blocks.Paragraph):
                    self._paragraph(document, block.runs, base_dir, warnings)
                elif isinstance(block, md_blocks.ListBlock):
                    for item in block.items:
                        style = "List Number" if item.ordered else "List Bullet"
                        paragraph = document.add_paragraph(style=style)
                        paragraph.paragraph_format.left_indent = Inches(0.25 * (item.level + 1))
                        self._runs(paragraph, item.runs, base_dir, warnings)
                        images += sum(1 for r in item.runs if r.image)
                elif isinstance(block, md_blocks.TableBlock):
                    self._table(document, block)
                elif isinstance(block, md_blocks.CodeBlock):
                    self._code(document, block)
                elif isinstance(block, md_blocks.QuoteBlock):
                    for quote_para in block.paragraphs:
                        try:
                            paragraph = document.add_paragraph(style="Quote")
                        except KeyError:
                            paragraph = document.add_paragraph()
                            paragraph.runs  # noqa: B018 - ensure list exists
                        paragraph.add_run(quote_para.text).italic = True
                elif isinstance(block, md_blocks.ImageBlock):
                    images += self._image(document, block, base_dir, warnings)
                elif isinstance(block, md_blocks.RuleBlock):
                    self._rule(document)
            document.save(output_path)
        except Exception as exc:
            return ExportResult(False, error=f"{type(exc).__name__}: {exc}", warnings=warnings)

        return ExportResult(True, warnings=warnings,
                            metadata={"images": images})

    # ------------------------------------------------------------ pieces
    def _paragraph(self, document: Any, runs: list[md_blocks.Run], base_dir: Path,
                   warnings: list[str]) -> None:
        if not runs:
            document.add_paragraph("")
            return
        paragraph = document.add_paragraph()
        self._runs(paragraph, runs, base_dir, warnings)

    def _runs(self, paragraph: Any, runs: list[md_blocks.Run], base_dir: Path,
              warnings: list[str]) -> None:
        for run in runs:
            if run.image and run.href:
                if self._add_picture(paragraph, run.href, base_dir, warnings,
                                     width=_MAX_IMAGE_WIDTH):
                    paragraph.add_run(" ")  # breathing room after inline image
                continue
            text = run.text
            if not text:
                continue
            if run.href and not run.image:
                self._hyperlink(paragraph, run.href, text)
                continue
            new_run = paragraph.add_run(text)
            new_run.bold = run.bold
            new_run.italic = run.italic
            if run.code:
                new_run.font.name = "Consolas"
                new_run.font.size = Pt(9.5)

    def _image(self, document: Any, block: md_blocks.ImageBlock, base_dir: Path,
               warnings: list[str]) -> int:
        """Standalone image → own paragraph, capped to page width."""
        paragraph = document.add_paragraph()
        ok = self._add_picture(paragraph, block.src, base_dir, warnings,
                               width=_MAX_IMAGE_WIDTH)
        if not ok and block.alt:
            run = paragraph.add_run(f"[{block.alt}]")
            run.italic = True
        return 1 if ok else 0

    def _add_picture(self, container: Any, src: str, base_dir: Path,
                     warnings: list[str], width: Any = None) -> bool:
        path = self.resolve_image(src, base_dir)
        if path is None:
            warnings.append(f"Image not found: {src}")
            return False
        try:
            # python-docx hangs pictures off a run, not a paragraph
            if hasattr(container, "add_run"):
                run = container.add_run()
            else:
                run = container.paragraphs[-1].add_run() if getattr(container, "paragraphs", None) else None
            if run is None:
                warnings.append(f"No place to embed image {path.name}")
                return False
            run.add_picture(str(path), width=width)
            return True
        except Exception as exc:
            warnings.append(f"Could not embed image {path.name}: {exc}")
            return False

    def _table(self, document: Any, block: md_blocks.TableBlock) -> None:
        rows, cols = len(block.rows) + 1, len(block.header)
        if cols == 0:
            return
        table = document.add_table(rows=rows, cols=cols)
        table.style = "Table Grid"
        for col, text in enumerate(block.header):
            cell = table.cell(0, col)
            cell.text = ""
            run = cell.paragraphs[0].add_run(text or " ")
            run.bold = True
        for r, row in enumerate(block.rows, start=1):
            for c in range(cols):
                table.cell(r, c).text = row[c] if c < len(row) else ""

    def _code(self, document: Any, block: md_blocks.CodeBlock) -> None:
        for line in block.text.splitlines() or [""]:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(0)
            run = paragraph.add_run(line if line else " ")
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0x1F, 0x2A, 0x44)
            shading = OxmlElement("w:shd")
            shading.set(qn("w:val"), "clear")
            shading.set(qn("w:fill"), "F4F6F8")
            run._element.get_or_add_rPr().append(shading)

    @staticmethod
    def _rule(document: Any) -> None:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(4)
        paragraph.paragraph_format.space_after = Pt(4)
        p_bdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "AAAAAA")
        p_bdr.append(bottom)
        paragraph._p.get_or_add_pPr().append(p_bdr)

    @staticmethod
    def _hyperlink(paragraph: Any, url: str, text: str) -> None:
        """Insert a real hyperlink run (python-docx has no native helper)."""
        try:
            rel_id = paragraph.part.relate_to(
                url,
                docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK,
                is_external=True,
            )
            hyperlink = OxmlElement("w:hyperlink")
            hyperlink.set(qn("r:id"), rel_id)
            new_run = OxmlElement("w:r")
            props = OxmlElement("w:rPr")
            color = OxmlElement("w:color")
            color.set(qn("w:val"), "0563C1")
            underline = OxmlElement("w:u")
            underline.set(qn("w:val"), "single")
            props.append(color)
            props.append(underline)
            new_run.append(props)
            text_el = OxmlElement("w:t")
            text_el.text = text
            new_run.append(text_el)
            hyperlink.append(new_run)
            paragraph._p.append(hyperlink)
        except Exception:
            paragraph.add_run(text)  # fallback: plain text keeps content
