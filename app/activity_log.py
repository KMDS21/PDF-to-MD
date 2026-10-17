"""Persistent activity log in **Markdown format** — one `.md` file per day.

Every conversion session is appended as a section with a heading, the full
options used, per-file results as a table (with sizes, durations, warnings),
and a summary line. The file stays valid Markdown at all times, so it can be
read in any editor or rendered by any MD viewer.

Location: <project>/logs/conversion_YYYY-MM-DD.md
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def today_log_path() -> Path:
    """Path of today's markdown log file (also shown in the UI)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"conversion_{datetime.now():%Y-%m-%d}.md"


def _ensure_header(path: Path, now: datetime) -> None:
    """Create the file with a document header if it doesn't exist yet."""
    if path.exists() and path.stat().st_size > 0:
        return
    path.write_text(
        f"# Conversion Log — {now:%Y-%m-%d}\n\n"
        f"*All conversion activity of {now:%Y-%m-%d}, newest session last.*\n",
        encoding="utf-8",
    )


def write(message: str = "", *, header: bool = False) -> None:
    """Append a timestamped line; `header=True` starts a new session section."""
    now = datetime.now()
    try:
        path = today_log_path()
        _ensure_header(path, now)
        with path.open("a", encoding="utf-8") as fh:
            if header:
                fh.write(f"\n## Session — {now:%H:%M:%S}\n\n")
                fh.write(f"> started {now:%Y-%m-%d %H:%M:%S}\n\n")
            if message:
                fh.write(f"- `{now:%H:%M:%S}` {message}\n")
    except OSError:
        pass  # logging must never break a conversion


def write_table_header() -> None:
    """Write the markdown table header for per-file result rows."""
    try:
        path = today_log_path()
        _ensure_header(path, datetime.now())
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n| File | Size | Duration | Result | Details |\n")
            fh.write("|---|---:|---:|:-:|---|\n")
    except OSError:
        pass


def write_row(file: str, size: str, duration: str, mark: str, details: str) -> None:
    """Append one per-file result row to the session table."""
    try:
        with today_log_path().open("a", encoding="utf-8") as fh:
            fh.write(f"| {file} | {size} | {duration} | {mark} | {details} |\n")
    except OSError:
        pass


def write_summary(succeeded: int, total: int, failed: int, warnings: int,
                  duration_s: float) -> None:
    """Append the session summary block after the results table."""
    try:
        path = today_log_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n**Summary:** ✅ {succeeded}/{total} succeeded · "
                     f"❌ {failed} failed · ⚠️ {warnings} warning(s) · "
                     f"⏱️ {duration_s:.1f}s total\n")
    except OSError:
        pass


def format_options(options: object) -> str:
    """One-line, human-readable dump of the conversion options (markdown-safe)."""
    pairs = []
    for name in ("direction", "recursive", "extract_images", "include_speaker_notes",
                 "ocr_enabled", "ai_enabled", "merge_all"):
        value = getattr(options, name, None)
        if value is not None:
            pairs.append(f"`{name}={value}`")
    targets = getattr(options, "target_formats", None)
    if targets:
        pairs.append(f"`targets={','.join(targets)}`")
    provider = getattr(options, "ai_provider", "") or ""
    if provider:
        pairs.append(f"`ai_provider={provider}`")
    return " ".join(pairs)
