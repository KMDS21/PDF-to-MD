"""Shared helpers: filename sanitizing, asset paths, markdown utilities."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Windows-forbidden filename characters + control chars
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_CONTENT_TYPE_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/webp": ".webp",
    "image/x-emf": ".emf",
    "image/x-wmf": ".wmf",
    "image/svg+xml": ".svg",
}


def sanitize_filename(name: str, replacement: str = "-", max_length: int = 150) -> str:
    """Make a string safe to use as a filename on Windows/macOS/Linux."""
    name = unicodedata.normalize("NFKC", name)
    name = _INVALID_CHARS.sub(replacement, name)
    name = re.sub(r"\s+", " ", name).strip(" .-")
    if not name:
        name = "untitled"
    return name[:max_length]


def assets_dir_for(md_path: Path) -> Path:
    """Return (creating if needed) the asset folder that sits next to an .md file."""
    directory = md_path.parent / f"{md_path.stem}_assets"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def unique_path(directory: Path, filename: str) -> Path:
    """Return a non-colliding path inside `directory` (adds _1, _2… on clash)."""
    candidate = directory / filename
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def ext_from_content_type(content_type: str) -> str:
    """Map a MIME content type to a file extension (falls back to .png)."""
    return _CONTENT_TYPE_EXT.get(content_type.lower().split(";")[0].strip(), ".png")


def ext_from_image_bytes(data: bytes, fallback: str = ".png") -> str:
    """Sniff an image's extension from its magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tiff"
    return fallback


def escape_table_cell(text: str) -> str:
    """Escape text so it is safe inside a markdown table cell."""
    return text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def build_front_matter(rel_source: Path, engine_name: str, metadata: Optional[dict] = None) -> str:
    """Build YAML front matter for a converted markdown file."""
    lines = [
        "---",
        f'source: "{rel_source.as_posix()}"',
        "converter: PDF-to-MD",
        f"engine: {engine_name}",
        f"converted: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
    ]
    for key, value in (metadata or {}).items():
        if isinstance(value, str):
            value = value.replace('"', "'")
            lines.append(f"{key}: \"{value}\"")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def human_size(num_bytes: int) -> str:
    """Format a byte count for log messages (1.4 MB)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"
