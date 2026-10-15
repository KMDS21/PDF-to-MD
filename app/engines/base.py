"""Common interface shared by every conversion engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ConversionResult:
    """What an engine hands back to the orchestrator."""

    success: bool
    markdown: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversionEngine(ABC):
    """Base class for format-specific converters.

    Implementations extract content from `input_path` and return markdown text.
    Binary assets (images etc.) must be written to `assets_dir_for(output_md_path)`
    and referenced from the markdown with relative paths so the .md file stays
    portable next to its assets folder.
    """

    #: Human-readable engine name, shown in front matter and logs
    name: str = "base"
    #: Lower-case file extensions this engine handles, e.g. (".pdf",)
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def convert(self, input_path: Path, output_md_path: Path, options: dict[str, Any]) -> ConversionResult:
        """Convert `input_path` into markdown.

        :param input_path:      source document (pdf/pptx/docx/xlsx/image)
        :param output_md_path:  where the .md will be written — engines use its
                                sibling `<stem>_assets/` folder for extracted images
        :param options:         dict of ConversionOptions fields (extract_images,
                                include_speaker_notes, ocr_enabled, ai_enabled, ...)
        :return: ConversionResult with the markdown body (front matter is added
                 by the orchestrator) and any warnings
        """
        raise NotImplementedError
