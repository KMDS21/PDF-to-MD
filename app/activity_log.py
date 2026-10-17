"""Persistent activity log — one file per day, every line timestamped.

Records the full story of each conversion session so nothing is lost when
the GUI log pane is cleared: session start (with all options), per-file
results and durations, warnings, and the final summary.

Location: <project>/logs/conversion_YYYY-MM-DD.log
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def today_log_path() -> Path:
    """Path of today's log file (also used to show it in the UI)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"conversion_{datetime.now():%Y-%m-%d}.log"


def write(message: str, *, header: bool = False) -> None:
    """Append a timestamped line to today's log file.

    Logging must never break a conversion, so any I/O error is swallowed.
    """
    now = datetime.now()
    try:
        with today_log_path().open("a", encoding="utf-8") as fh:
            if header:
                fh.write("\n" + "=" * 76 + "\n")
            fh.write(f"[{now:%Y-%m-%d %H:%M:%S}] {message}\n")
    except OSError:
        pass


def format_options(options: object) -> str:
    """One-line, human-readable dump of the conversion options."""
    pairs = []
    for name in ("recursive", "extract_images", "include_speaker_notes",
                 "ocr_enabled", "ai_enabled", "merge_all"):
        pairs.append(f"{name}={getattr(options, name, '?')}")
    provider = getattr(options, "ai_provider", "") or "-"
    pairs.append(f"ai_provider={provider}")
    return ", ".join(pairs)
