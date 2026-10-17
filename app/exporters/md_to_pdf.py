"""Markdown → PDF exporter.

Renders the block model to HTML (app.md_blocks.blocks_to_html) and lays it
out with PyMuPDF's Story API — a real HTML layout engine with automatic
pagination, flowing tables, nested lists and images:

- A4 pages, 2 cm margins
- styled headings, tables with grid, blockquotes, code blocks
- images resolved against the .md file's directory (Story archive)
- page numbers in the footer
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    import pymupdf
except ImportError:  # pragma: no cover - dependency guard
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        pymupdf = None  # type: ignore

from app import md_blocks
from app.exporters.base import ExportResult, Exporter

_CSS = """
* { font-family: sans-serif; }
body { font-size: 10.5pt; line-height: 1.45; color: #1c1c1c; }
h1 { font-size: 24pt; color: #1a4f8b; margin-top: 0; margin-bottom: 8pt; }
h2 { font-size: 18pt; color: #1a4f8b; margin-top: 14pt; margin-bottom: 6pt; }
h3 { font-size: 14pt; color: #2c3e50; margin-top: 12pt; margin-bottom: 4pt; }
h4, h5, h6 { font-size: 12pt; color: #2c3e50; margin-top: 10pt; margin-bottom: 4pt; }
p { margin-top: 0; margin-bottom: 7pt; }
strong { font-weight: bold; }
em { font-style: italic; }
code { font-family: monospace; font-size: 9.5pt; background-color: #f0f2f5; }
pre { background-color: #f0f2f5; padding: 6pt; margin-top: 4pt; margin-bottom: 8pt; }
pre code { background-color: #f0f2f5; font-size: 9pt; }
blockquote { margin-left: 12pt; margin-right: 6pt; padding-left: 8pt;
             border-left: 2pt solid #8aa4c4; color: #444444; }
table { border-collapse: collapse; margin-top: 4pt; margin-bottom: 8pt; }
th { background-color: #e4ebf3; font-weight: bold; }
th, td { border: 0.6pt solid #9aa7b5; padding: 3pt 5pt; font-size: 9.5pt; }
hr { color: #b9c2cc; margin-top: 8pt; margin-bottom: 8pt; }
img { margin-top: 4pt; margin-bottom: 4pt; }
ul, ol { margin-top: 2pt; margin-bottom: 7pt; }
li { margin-bottom: 2pt; }
"""

_PAGE = pymupdf.paper_rect("a4") if pymupdf else None  # type: ignore[union-attr]


class PdfExporter(Exporter):
    """Write a parsed markdown document as a paginated .pdf file."""

    name = "pdf (PyMuPDF Story)"
    extension = ".pdf"

    def export(self, blocks: list[Any], output_path: Path,
               options: dict[str, Any], base_dir: Path) -> ExportResult:
        if pymupdf is None:
            return ExportResult(False, error="PyMuPDF is not installed (pip install PyMuPDF)")

        warnings: list[str] = []
        if not blocks:
            return ExportResult(False, error="No content to export")

        # HTML first — resolving it also reports which extra folders the
        # archive must cover (Story only draws images relative to an archive)
        html, image_dirs = self._build_html(blocks, base_dir, warnings)
        if not html.strip():
            return ExportResult(False, error="No content to export")

        archive = None
        locations = [str(base_dir), *(str(p) for p in image_dirs)]
        try:
            archive = pymupdf.Archive(locations)  # <img src> resolve here
        except Exception:
            try:
                archive = pymupdf.Archive(str(base_dir))
            except Exception:
                archive = None

        margin = 50  # ~1.8 cm
        where = _PAGE + (margin, margin, -margin, -margin + 20)  # room for footer

        page_no = 0
        try:
            story = pymupdf.Story(html=html, user_css=_CSS, archive=archive)
            writer = pymupdf.DocumentWriter(str(output_path))
            more = 1
            while more:
                device = writer.begin_page(_PAGE)
                more, _ = story.place(where)
                story.draw(device)
                page_no += 1
                writer.end_page()
            writer.close()
            # PyMuPDF keeps the output file locked until the writer object is
            # released (Windows sharing violation otherwise) — drop it now
            del writer
        except Exception as exc:
            return ExportResult(False, error=f"{type(exc).__name__}: {exc}", warnings=warnings)

        if not output_path.exists() or output_path.stat().st_size == 0:
            return ExportResult(False, error="PDF writer produced an empty file")

        # page numbers need real page objects (the DocumentWriter device has
        # none) — reopen, stamp the footers and save incrementally in place
        try:
            doc = pymupdf.open(output_path)
            for index in range(doc.page_count):
                self._add_page_number(doc[index], index + 1)
            doc.saveIncr()
            doc.close()
        except Exception:
            pass  # footer is cosmetic — never fail the export for it

        return ExportResult(True, warnings=warnings, metadata={"pages": page_no})

    # ------------------------------------------------------------ html
    def _build_html(self, blocks: list[Any], base_dir: Path,
                    warnings: list[str]) -> tuple[str, list[Path]]:
        """Render blocks to HTML.

        Returns the document plus the folders of images living outside
        `base_dir` — Story can only draw paths relative to an archive, so
        those folders are handed back for inclusion in the archive and the
        images are referenced by their file name.
        """
        resolved_base = base_dir.resolve()
        extra_dirs: list[Path] = []
        claimed: dict[str, Path] = {}

        def resolver(src: str) -> str:
            path = self.resolve_image(src, base_dir)
            if path is None:
                warnings.append(f"Image not found: {src}")
                return ""
            try:
                key = path.resolve().relative_to(resolved_base).as_posix()
            except ValueError:
                # outside the .md's folder → archive its directory instead
                key = path.name
                owner = claimed.get(key)
                if owner is not None and owner != path:
                    warnings.append(f"Duplicate image name skipped: {key}")
                    return ""
                claimed.setdefault(key, path)
                if path.parent not in extra_dirs:
                    extra_dirs.append(path.parent)
            else:
                claimed.setdefault(key, path)
            return key

        body = md_blocks.blocks_to_html(blocks, image_resolver=resolver)
        # drop <img> tags whose resolver failed (empty src would break layout)
        body = re.sub(r"<p>\s*<img src=\"\"[^>]*/>\s*</p>", "<p><em>[image missing]</em></p>", body)
        body = re.sub(r"<img src=\"\" alt=\"([^\"]*)\"/>", r"<em>[\1]</em>", body)
        return f"<html><body>{body}</body></html>", extra_dirs

    # ----------------------------------------------------------- footer
    @staticmethod
    def _add_page_number(page: Any, page_no: int) -> None:
        """Centered page number in the bottom margin (cosmetic by design)."""
        text = f"— {page_no} —"
        try:
            font = pymupdf.Font("helv")  # type: ignore[union-attr]
            x = (page.rect.width - font.text_length(text, fontsize=8)) / 2
            writer = pymupdf.TextWriter(page.rect)  # type: ignore[union-attr]
            writer.append((x, page.rect.height - 14), text, font=font)
            writer.write_text(page, color=(0.45, 0.45, 0.45))
        except Exception:
            pass  # footer is cosmetic — never fail the export for it
