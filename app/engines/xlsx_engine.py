"""XLSX → Markdown engine.

Each worksheet becomes a section of the markdown document (plan §6):

- sheet name     → `## SheetName`
- first non-empty row is treated as the header row
- remaining rows → markdown table cells (numbers keep their formatting,
                   dates render as ISO strings)
- merged/empty trailing rows and columns are trimmed
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Optional

try:
    import openpyxl
except ImportError:  # pragma: no cover - dependency guard
    openpyxl = None  # type: ignore

from app.engines.base import ConversionEngine, ConversionResult
from app.utils import escape_table_cell

_MAX_ROWS = 5000  # sanity cap per sheet keeps output files manageable
_MAX_COLS = 100


class XlsxEngine(ConversionEngine):
    """Convert a .xlsx (or .xls via openpyxl) file to Markdown."""

    name = "xlsx (openpyxl)"
    extensions = (".xlsx", ".xlsm")

    # ------------------------------------------------------------------ API
    def convert(self, input_path: Path, output_md_path: Path, options: dict[str, Any]) -> ConversionResult:
        if openpyxl is None:
            return ConversionResult(False, error="openpyxl is not installed (pip install openpyxl)")

        warnings: list[str] = []
        try:
            # data_only=True → formulas resolve to their cached values
            workbook = openpyxl.load_workbook(input_path, read_only=True, data_only=True)
        except Exception as exc:
            return ConversionResult(False, error=f"Cannot open workbook: {exc}")

        sections: list[str] = []
        sheet_count = len(workbook.sheetnames)
        try:
            for sheet in workbook.worksheets:
                if sheet.max_row is None or sheet.max_column is None:
                    continue
                rows = self._sheet_rows(sheet)
                table_md = _rows_to_table(rows)
                title = f"## {sheet.title}"
                sections.append(f"{title}\n\n{table_md}" if table_md else title)
                skipped = max(0, (sheet.max_row or 0) - _MAX_ROWS)
                if skipped:
                    warnings.append(f"Sheet '{sheet.title}': {skipped} row(s) beyond {_MAX_ROWS} not converted")
        finally:
            workbook.close()

        if not sections:
            warnings.append("No sheets found in this workbook")

        markdown = "\n\n".join(sections) + "\n"
        metadata = {"sheets": sheet_count}
        return ConversionResult(True, markdown, warnings, metadata=metadata)

    # ---------------------------------------------------------------- rows
    @staticmethod
    def _sheet_rows(sheet: Any) -> list[list[str]]:
        """Read up to _MAX_ROWS × _MAX_COLS cells, formatted for markdown."""
        rows: list[list[str]] = []
        for r_index, row in enumerate(sheet.iter_rows(max_col=_MAX_COLS)):
            if r_index >= _MAX_ROWS:
                break
            values = [_format_cell(cell.value) for cell in row]
            # trim trailing empties
            while values and not values[-1]:
                values.pop()
            rows.append(values)
        # drop trailing empty rows
        while rows and not any(rows[-1]):
            rows.pop()
        return rows


def _format_cell(value: Any) -> str:
    """Format an openpyxl cell value as a markdown-safe string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat(sep=" ") if isinstance(value, _dt.datetime) else value.isoformat()
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.10g}"
    return str(value).strip()


def _rows_to_table(rows: list[list[str]]) -> str:
    """Trim fully-empty leading rows, then build a markdown table."""
    rows = [row for row in rows if any(row)]
    if not rows:
        return ""
    if len(rows) == 1:  # only a header → pad an empty body row
        rows.append([""] * len(rows[0]))
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header = [escape_table_cell(cell) or " " for cell in rows[0]]
    body = [[escape_table_cell(cell) for cell in row] for row in rows[1:]]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)
