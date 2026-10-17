"""Common interface shared by all Markdown → X exporters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExportResult:
    """What an exporter hands back to the orchestrator."""

    success: bool
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Exporter(ABC):
    """Base class for markdown → document exporters.

    Implementations receive the parsed block model (see app.md_blocks) and
    write `output_path`. Images are resolved relative to `base_dir` (the
    directory of the source .md file) via `resolve_image`.
    """

    #: Human-readable exporter name (front matter / logs)
    name: str = "base"
    #: Target file extension including the dot, e.g. ".pdf"
    extension: str = ""

    @abstractmethod
    def export(self, blocks: list[Any], output_path: Path,
               options: dict[str, Any], base_dir: Path) -> ExportResult:
        """Convert parsed markdown blocks into `output_path`."""
        raise NotImplementedError

    @staticmethod
    def resolve_image(src: str, base_dir: Path) -> Path | None:
        """Resolve an image reference against the .md file's directory.

        Handles absolute paths, relative paths, spaces and URL encoding.
        Returns None when the file does not exist (the caller logs a warning
        and the export continues — content must never be lost silently).
        """
        if not src:
            return None
        from urllib.parse import unquote, urlparse

        if src.startswith(("http://", "https://", "data:")):
            return None  # remote/inline images are not fetched (offline app)
        parsed = urlparse(src)
        candidate = Path(unquote(parsed.path if parsed.scheme == "file" else src))
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        try:
            return candidate if candidate.is_file() else None
        except OSError:
            return None
