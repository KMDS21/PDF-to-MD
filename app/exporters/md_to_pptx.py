"""Markdown → PPTX exporter.

Slides are cut at every H1/H2 heading; deeper headings become slide body
sub-headings. Each slide carries:

- title (the heading text) in the title placeholder
- paragraphs / list items as bullets (nesting preserved)
- tables  → real PowerPoint tables
- images  → pictures (resolved relative to the .md), capped to slide width
- code    → monospace text block
- quotes  → italic text

Content before the first heading lands on an untitled intro slide.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from pathlib import Path
from typing import Any

try:
    from pptx import Presentation
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Inches, Pt
except ImportError:  # pragma: no cover - dependency guard
    Presentation = None  # type: ignore

from app import md_blocks
from app.exporters.base import ExportResult, Exporter

_SLIDE_W = Inches(13.333)   # 16:9 default of python-pptx template
_SLIDE_H = Inches(7.5)
_MARGIN = Inches(0.6)
_BODY_W = _SLIDE_W - 2 * _MARGIN
_MAX_IMG_W = Inches(7.0)


@dataclass
class _SlidePlan:
    title: str = ""
    body: list[Any] = field(default_factory=list)


class PptxExporter(Exporter):
    """Write a parsed markdown document as a .pptx presentation."""

    name = "pptx (python-pptx)"
    extension = ".pptx"

    def export(self, blocks: list[Any], output_path: Path,
               options: dict[str, Any], base_dir: Path) -> ExportResult:
        if Presentation is None:
            return ExportResult(False, error="python-pptx is not installed (pip install python-pptx)")

        warnings: list[str] = []
        plans = self._plan_slides(blocks)
        if not plans:
            return ExportResult(False, error="No content to export")

        prs = Presentation()
        prs.slide_width, prs.slide_height = _SLIDE_W, _SLIDE_H
        layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[5]

        images = tables = 0
        try:
            for plan in plans:
                slide = prs.slides.add_slide(layout)
                top = self._render_title(slide, plan.title)
                for block in plan.body:
                    if isinstance(block, md_blocks.Heading):
                        top = self._body_heading(slide, block, top)
                    elif isinstance(block, md_blocks.Paragraph):
                        top, n = self._body_paragraph(slide, block.runs, top, bullet=False,
                                                      base_dir=base_dir, warnings=warnings)
                        images += n
                    elif isinstance(block, md_blocks.ListBlock):
                        number = 0
                        for item in block.items:
                            if item.ordered:
                                number += 1
                                marker = f"{number}. "
                            else:
                                number = 0
                                marker = "• "
                            top, n = self._body_paragraph(slide, item.runs, top,
                                                          marker=marker, level=item.level,
                                                          base_dir=base_dir,
                                                          warnings=warnings)
                            images += n
                    elif isinstance(block, md_blocks.TableBlock):
                        top, ok = self._body_table(slide, block, top)
                        tables += 1 if ok else 0
                    elif isinstance(block, md_blocks.CodeBlock):
                        top = self._body_code(slide, block, top)
                    elif isinstance(block, md_blocks.QuoteBlock):
                        for qp in block.paragraphs:
                            top, n = self._body_paragraph(slide, qp.runs, top, bullet=False,
                                                          italic=True, base_dir=base_dir,
                                                          warnings=warnings)
                            images += n
                    elif isinstance(block, md_blocks.ImageBlock):
                        top, ok = self._body_image(slide, block.src, block.alt,
                                                   base_dir, top, warnings)
                        images += 1 if ok else 0
                    elif isinstance(block, md_blocks.RuleBlock):
                        continue  # slide separators already do this job
            prs.save(output_path)
        except Exception as exc:
            return ExportResult(False, error=f"{type(exc).__name__}: {exc}", warnings=warnings)

        return ExportResult(True, warnings=warnings,
                            metadata={"slides": len(plans), "images": images, "tables": tables})

    # ----------------------------------------------------------- planning
    @staticmethod
    def _plan_slides(blocks: list[Any]) -> list[_SlidePlan]:
        plans: list[_SlidePlan] = []
        current = _SlidePlan()
        for block in blocks:
            if isinstance(block, md_blocks.Heading) and block.level <= 2:
                if current.title or current.body:
                    plans.append(current)
                current = _SlidePlan(title=block.text)
            else:
                current.body.append(block)
        if current.title or current.body:
            plans.append(current)
        # drop nothing: content before first heading stays as intro slide
        return [p for p in plans if p.title or p.body]

    # ----------------------------------------------------------- rendering
    @staticmethod
    def _render_title(slide: Any, title: str) -> int:
        """Lay out the slide title; returns the next free y (EMU-like int)."""
        top = _MARGIN
        if title and slide.shapes.title is not None:
            box = slide.shapes.title
            box.left, box.top, box.width, box.height = _MARGIN, top, _BODY_W, Inches(1.0)
            box.text_frame.text = title
            for paragraph in box.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(30)
                    run.font.bold = True
            top += Inches(1.2)
        elif title:
            box = slide.shapes.add_textbox(_MARGIN, top, _BODY_W, Inches(1.0))
            box.text_frame.text = title
            for run in box.text_frame.paragraphs[0].runs:
                run.font.size = Pt(30)
                run.font.bold = True
            top += Inches(1.2)
        return int(top)

    @staticmethod
    def _body_heading(slide: Any, block: md_blocks.Heading, top: int) -> int:
        height = Inches(0.55)
        box = slide.shapes.add_textbox(_MARGIN, Emu(top), _BODY_W, height)
        box.text_frame.text = block.text
        box.text_frame.word_wrap = True
        for run in box.text_frame.paragraphs[0].runs:
            run.font.size = Pt(20 if block.level <= 3 else 17)
            run.font.bold = True
        return top + int(height) + 60000

    def _body_paragraph(self, slide: Any, runs: list[md_blocks.Run], top: int,
                        *, bullet: bool = False, marker: str | None = None,
                        level: int = 0, italic: bool = False,
                        base_dir: Path | None = None,
                        warnings: list[str] | None = None) -> tuple[int, int]:
        """Lay out one paragraph/list item; returns (next y, images placed).

        Image runs are drawn as real pictures right after the text so inline
        images are never dropped from the deck.
        """
        warnings = warnings if warnings is not None else []
        image_runs = [r for r in runs if r.image and r.href] if runs else []
        text_runs = [r for r in runs if not (r.image and r.href)] if runs else []
        text = md_blocks.runs_plain(text_runs)
        if not text.strip() and not image_runs:
            return top, 0

        if text.strip():
            if marker is None and bullet:
                marker = "• "
            if marker:
                text = marker + text
            height = Inches(0.4 + 0.3 * max(1, self._wrapped_lines(text)))
            indent = Emu(int(Inches(0.35)) * min(level, 4))
            box = slide.shapes.add_textbox(_MARGIN + indent, Emu(top),
                                           _BODY_W - indent, height)
            tf = box.text_frame
            tf.word_wrap = True
            tf.paragraphs[0].text = text
            tf.paragraphs[0].alignment = PP_ALIGN.LEFT
            self._apply_runs(tf.paragraphs[0], text_runs, italic=italic)
            top += int(height)

        placed = 0
        if base_dir is not None:
            for run in image_runs:
                top, ok = self._body_image(slide, run.href, run.text or "image",
                                           base_dir, top, warnings)
                placed += 1 if ok else 0
        return top, placed

    @staticmethod
    def _apply_runs(paragraph: Any, runs: list[md_blocks.Run], italic: bool = False) -> None:
        """Re-style paragraph runs to mirror markdown inline marks."""
        if all(not (r.bold or r.italic or r.code or r.href) for r in runs) and not italic:
            return
        for run in paragraph.runs:
            run.font.size = Pt(16)
        if not runs or len(paragraph.runs) != len(runs):
            return  # python-pptx merged/split runs differently; keep plain
        for para_run, src in zip(paragraph.runs, runs):
            para_run.font.bold = src.bold
            para_run.font.italic = src.italic or italic
            if src.code:
                para_run.font.name = "Consolas"
                para_run.font.size = Pt(14)
            if src.href and not src.image:
                try:
                    para_run.hyperlink.address = src.href
                except Exception:
                    pass

    @staticmethod
    def _wrapped_lines(text: str, chars: int = 95) -> int:
        return max(1, (len(text) + chars - 1) // chars)

    def _body_table(self, slide: Any, block: md_blocks.TableBlock, top: int) -> tuple[int, bool]:
        cols = len(block.header)
        if cols == 0:
            return top, False
        data = block.rows or [[""] * cols]
        nrows = len(data) + 1  # header row + body rows
        height = Inches(0.35 * nrows)
        frame = slide.shapes.add_table(nrows, cols, _MARGIN, Emu(top), _BODY_W, height)
        table = frame.table
        for c, text in enumerate(block.header):
            cell = table.cell(0, c)
            cell.text = text
            for run in cell.text_frame.paragraphs[0].runs:
                run.font.bold = True
                run.font.size = Pt(14)
        for r, row in enumerate(data, start=1):
            for c in range(cols):
                cell = table.cell(r, c)
                cell.text = row[c] if c < len(row) else ""
                for run in cell.text_frame.paragraphs[0].runs:
                    run.font.size = Pt(13)
        return top + int(height) + 60000, True

    def _body_code(self, slide: Any, block: md_blocks.CodeBlock, top: int) -> int:
        lines = (block.text.splitlines() or [""])[:14]
        height = Inches(0.28 * len(lines) + 0.2)
        box = slide.shapes.add_textbox(_MARGIN, Emu(top), _BODY_W, height)
        tf = box.text_frame
        tf.word_wrap = False
        for idx, line in enumerate(lines):
            paragraph = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
            paragraph.text = line if line else " "
            for run in paragraph.runs:
                run.font.name = "Consolas"
                run.font.size = Pt(13)
        return top + int(height)

    def _body_image(self, slide: Any, src: str, alt: str, base_dir: Path,
                    top: int, warnings: list[str]) -> tuple[int, bool]:
        path = self.resolve_image(src, base_dir)
        if path is None:
            warnings.append(f"Image not found: {src}")
            return top, False
        try:
            picture = slide.shapes.add_picture(str(path), _MARGIN, Emu(top), width=_MAX_IMG_W)
            # keep the whole image on the slide, preserving the aspect ratio
            max_h = int(_SLIDE_H - Inches(0.3) - picture.top)
            if max_h > 0 and picture.height > max_h:
                ratio = picture.width / picture.height
                picture.height = max_h
                picture.width = int(max_h * ratio)
            return top + picture.height + 60000, True
        except Exception as exc:
            warnings.append(f"Could not place image {path.name}: {exc}")
            return top, False
