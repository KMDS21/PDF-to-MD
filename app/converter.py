"""Batch conversion orchestrator.

Scans a folder for supported files, dispatches each one to the right engine,
mirrors the folder structure into the output directory, and can be driven by
the GUI (thread + callbacks) or used directly from the command line:

    python -m app.converter <input_folder> [output_folder]
"""

from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable, Optional

from app.engines.base import ConversionEngine
from app.utils import build_front_matter

# extension -> (module, class) — imported lazily so a missing optional
# dependency never breaks the whole app
_ENGINE_MAP: dict[str, tuple[str, str]] = {
    ".pdf": ("app.engines.pdf_engine", "PdfEngine"),
    ".pptx": ("app.engines.pptx_engine", "PptxEngine"),
    ".docx": ("app.engines.docx_engine", "DocxEngine"),
    ".xlsx": ("app.engines.xlsx_engine", "XlsxEngine"),
    ".xls": ("app.engines.xlsx_engine", "XlsxEngine"),
    ".png": ("app.engines.image_engine", "ImageEngine"),
    ".jpg": ("app.engines.image_engine", "ImageEngine"),
    ".jpeg": ("app.engines.image_engine", "ImageEngine"),
    ".tif": ("app.engines.image_engine", "ImageEngine"),
    ".tiff": ("app.engines.image_engine", "ImageEngine"),
    ".bmp": ("app.engines.image_engine", "ImageEngine"),
    ".webp": ("app.engines.image_engine", "ImageEngine"),
}

SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(_ENGINE_MAP)

#: Directories never worth scanning
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "env", "node_modules"}

_engine_cache: dict[str, ConversionEngine] = {}


@dataclass
class ConversionOptions:
    """Everything the engines need to know about how to convert."""

    recursive: bool = True
    extract_images: bool = True
    include_speaker_notes: bool = True
    ocr_enabled: bool = True
    ai_enabled: bool = False
    ai_provider: str = ""        # "openai" or "gemini"
    ai_api_key: str = ""
    ai_model: str = ""           # empty → provider default


@dataclass
class FileResult:
    """Outcome of converting one file."""

    source: Path
    output: Optional[Path]
    success: bool
    message: str
    warnings: list[str] = field(default_factory=list)


def get_engine(extension: str) -> Optional[ConversionEngine]:
    """Return a cached engine instance for the extension, or None if unavailable."""
    ext = extension.lower()
    if ext in _engine_cache:
        return _engine_cache[ext]
    spec = _ENGINE_MAP.get(ext)
    if spec is None:
        return None
    module_name, class_name = spec
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None  # engine module or one of its dependencies is not installed
    engine: ConversionEngine = getattr(module, class_name)()
    _engine_cache[ext] = engine
    return engine


def find_files(root: Path, recursive: bool = True) -> list[Path]:
    """Find every supported file under `root`, sorted for stable ordering."""
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix.lower() in SUPPORTED_EXTENSIONS else []
    pattern = root.rglob("*") if recursive else root.glob("*")
    files = [
        p for p in pattern
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and not any(part in _SKIP_DIRS or part.startswith(".") for part in p.relative_to(root).parts)
    ]
    return sorted(files)


def convert_file(source: Path, input_root: Path, output_root: Path,
                 options: ConversionOptions) -> FileResult:
    """Convert a single file, writing the .md (and assets) under `output_root`."""
    source = Path(source)
    engine = get_engine(source.suffix)
    if engine is None:
        return FileResult(source, None, False,
                          f"Engine for '{source.suffix}' is unavailable (not installed)")

    try:
        rel_source = source.relative_to(input_root)
    except ValueError:
        rel_source = Path(source.name)

    out_path = Path(output_root) / rel_source.parent / f"{source.stem}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = engine.convert(source, out_path, asdict(options))
    except Exception as exc:  # engines should catch internally; this is the safety net
        return FileResult(source, None, False, f"{type(exc).__name__}: {exc}")

    if not result.success:
        return FileResult(source, None, False, result.error or "Conversion failed", result.warnings)

    try:
        front_matter = build_front_matter(rel_source, engine.name, result.metadata)
        out_path.write_text(front_matter + result.markdown, encoding="utf-8")
    except OSError as exc:
        return FileResult(source, None, False, f"Could not write output: {exc}", result.warnings)

    return FileResult(source, out_path, True, "OK", result.warnings)


def convert_folder(
    input_root: Path,
    output_root: Path,
    options: Optional[ConversionOptions] = None,
    progress_cb: Optional[Callable[[int, int, Path], None]] = None,
    cancel_event: Optional[Event] = None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> list[FileResult]:
    """Convert every supported file in `input_root`.

    :param progress_cb: called as (done, total, current_file) before each file
    :param cancel_event: set this Event to stop after the current file
    :param log_cb:      receives human-readable status lines
    """
    input_root = Path(input_root).resolve()
    output_root = Path(output_root).resolve()
    options = options or ConversionOptions()

    files = find_files(input_root, recursive=options.recursive)
    total = len(files)
    results: list[FileResult] = []
    if log_cb:
        log_cb(f"Found {total} convertible file(s) in {input_root}")

    for index, source in enumerate(files, 1):
        if cancel_event is not None and cancel_event.is_set():
            if log_cb:
                log_cb("Conversion cancelled by user.")
            break
        if progress_cb:
            progress_cb(index, total, source)
        result = convert_file(source, input_root, output_root, options)
        results.append(result)
        if log_cb:
            mark = "✓" if result.success else "✗"
            log_cb(f"[{index}/{total}] {mark} {source.name} — {result.message}")
            for warning in result.warnings:
                log_cb(f"    ⚠ {warning}")

    if progress_cb:
        progress_cb(len(results), total, Path(""))
    return results


def _configure_console() -> None:
    """Make sure ✓/✗ and other unicode log marks print on Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _cli(argv: Optional[list[str]] = None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(
        prog="python -m app.converter",
        description="Convert a folder of PDF/PPTX/DOCX/XLSX/image files to Markdown.",
    )
    parser.add_argument("input", help="input folder (or single file)")
    parser.add_argument("output", nargs="?", default=None,
                        help="output folder (default: <input>/output)")
    parser.add_argument("--no-recursive", action="store_true", help="do not scan subfolders")
    parser.add_argument("--no-images", action="store_true", help="skip image extraction")
    parser.add_argument("--no-notes", action="store_true", help="skip PPTX speaker notes")
    parser.add_argument("--no-ocr", action="store_true", help="disable OCR for scanned pages")
    args = parser.parse_args(argv)

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        parser.error(f"input path does not exist: {input_path}")
    output_path = (Path(args.output).expanduser().resolve() if args.output
                   else input_path.parent / f"{input_path.name}_md" if input_path.is_dir()
                   else input_path.parent / "output")

    options = ConversionOptions(
        recursive=not args.no_recursive,
        extract_images=not args.no_images,
        include_speaker_notes=not args.no_notes,
        ocr_enabled=not args.no_ocr,
    )
    results = convert_folder(input_path, output_path, options, log_cb=print)
    ok = sum(1 for r in results if r.success)
    print(f"\nDone: {ok}/{len(results)} file(s) converted → {output_path}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
