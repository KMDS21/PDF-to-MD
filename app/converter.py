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
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable, Optional

from app import activity_log
from app.engines.base import ConversionEngine
from app.utils import build_front_matter, sanitize_filename

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


def _is_skippable(relative_parts: tuple[str, ...]) -> bool:
    """Skip hidden/system dirs, virtualenvs and our own extracted-asset folders."""
    for part in relative_parts:
        if part in _SKIP_DIRS or part.startswith("."):
            return True
        if part.endswith("_assets"):  # folders created by earlier conversions
            return True
    return False

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
    merge_all: bool = False      # combine every file into ONE markdown book


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
        and not _is_skippable(p.relative_to(root).parts)
    ]
    return sorted(files)


def _convert_one(source: Path, input_root: Path, output_root: Path,
                 options: ConversionOptions,
                 forced_output_md: Optional[Path] = None,
                 output_stem: Optional[str] = None) -> tuple[FileResult, str, str]:
    """Convert one file without writing the final .md.

    Returns (FileResult, front_matter, markdown_body). Assets are written next
    to `forced_output_md` when given (merge mode: one shared asset folder),
    otherwise next to the file's own .md path. `output_stem` overrides the
    default <source stem> used for the .md name (collision handling).
    """
    source = Path(source)
    engine = get_engine(source.suffix)
    if engine is None:
        return FileResult(source, None, False,
                          f"Engine for '{source.suffix}' is unavailable (not installed)"), "", ""

    try:
        rel_source = source.relative_to(input_root)
    except ValueError:
        rel_source = Path(source.name)

    if forced_output_md is not None:
        out_path = Path(forced_output_md)
    else:
        out_path = Path(output_root) / rel_source.parent / f"{output_stem or source.stem}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = engine.convert(source, out_path, asdict(options))
    except Exception as exc:  # engines should catch internally; this is the safety net
        return FileResult(source, None, False, f"{type(exc).__name__}: {exc}"), "", ""

    if not result.success:
        return (FileResult(source, None, False, result.error or "Conversion failed",
                           result.warnings), "", "")

    front_matter = build_front_matter(rel_source, engine.name, result.metadata)
    return FileResult(source, out_path, True, "OK", result.warnings), front_matter, result.markdown


def convert_file(source: Path, input_root: Path, output_root: Path,
                 options: ConversionOptions,
                 output_stem: Optional[str] = None) -> FileResult:
    """Convert a single file, writing the .md (and assets) under `output_root`."""
    result, front_matter, markdown = _convert_one(source, input_root, output_root, options,
                                                  output_stem=output_stem)
    if not result.success or result.output is None:
        return result
    try:
        result.output.write_text(front_matter + markdown, encoding="utf-8")
    except OSError as exc:
        return FileResult(source, None, False, f"Could not write output: {exc}", result.warnings)
    return result


def _section_header(rel_source: Path, engine_name: str) -> str:
    """Divider + source banner used between files in merged (book) mode."""
    return (f"\n\n---\n\n**📄 Source: `{rel_source.as_posix()}`**  \n"
            f"*Converted by {engine_name}*\n\n")


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
    :param options.merge_all: combine ALL files into one `<folder>.md` book,
                              each source separated by a divider + source banner
    """
    input_root = Path(input_root).resolve()
    output_root = Path(output_root).resolve()
    options = options or ConversionOptions()

    files = find_files(input_root, recursive=options.recursive)
    # never re-convert our own output (e.g. when output lives inside input)
    try:
        files = [f for f in files if output_root not in f.resolve().parents]
    except OSError:
        pass
    total = len(files)
    results: list[FileResult] = []
    session_started = datetime.now(timezone.utc)
    activity_log.write(header=True)
    activity_log.write(f"**Input:** `{input_root}`")
    activity_log.write(f"**Output:** `{output_root}`")
    activity_log.write(f"**Files found:** {total} — {activity_log.format_options(options)}")
    activity_log.write_table_header()
    if log_cb:
        mode = "merged book" if options.merge_all else "separate files"
        log_cb(f"Found {total} convertible file(s) in {input_root} → mode: {mode}")

    # collision handling: same stem in the same folder (e.g. notes.pdf + notes.pptx)
    # → later files keep their extension in the output name (notes.pptx.md)
    stem_owners: dict[tuple[str, str], Path] = {}
    output_stems: dict[Path, str] = {}
    for source in files:
        try:
            rel_parent = source.relative_to(input_root).parent.as_posix().lower()
        except ValueError:
            rel_parent = ""
        key = (rel_parent, source.stem.lower())
        if key in stem_owners:
            output_stems[source] = f"{source.stem}.{source.suffix.lstrip('.').lower()}"
        else:
            stem_owners[key] = source
            output_stems[source] = source.stem

    # merge mode: every engine writes assets into the book's shared asset folder
    book_path: Optional[Path] = None
    book_sections: list[str] = []
    if options.merge_all and total:
        book_name = sanitize_filename(input_root.name if input_root.is_dir()
                                      else input_root.stem) + ".md"
        book_path = output_root / book_name
        book_path.parent.mkdir(parents=True, exist_ok=True)

    for index, source in enumerate(files, 1):
        if cancel_event is not None and cancel_event.is_set():
            if log_cb:
                log_cb("Conversion cancelled by user.")
            activity_log.write(f"⛔ **Cancelled** by user after {len(results)} file(s)")
            break
        if progress_cb:
            progress_cb(index, total, source)

        file_started = time.perf_counter()
        if options.merge_all and book_path is not None:
            # all engines derive their asset folder from the output md path,
            # so passing the book path gives every file one shared assets folder
            try:
                rel = source.relative_to(input_root)
            except ValueError:
                rel = Path(source.name)
            result, _front, body = _convert_one(source, input_root, book_path.parent, options,
                                                forced_output_md=book_path)
            if result.success:
                engine = get_engine(source.suffix)
                book_sections.append(_section_header(rel, engine.name if engine else "?") + body.strip())
                result = FileResult(source, book_path, True, "OK (merged)", result.warnings)
            results.append(result)
        else:
            result = convert_file(source, input_root, output_root, options,
                                  output_stem=output_stems.get(source))
            results.append(result)

        elapsed = time.perf_counter() - file_started
        last = results[-1]
        mark = "✅" if last.success else "❌"
        try:
            size_kb = source.stat().st_size / 1024
        except OSError:
            size_kb = 0.0
        details = last.message
        if last.warnings:
            details += " · " + " · ".join(w.replace("|", "\\|") for w in last.warnings)
        activity_log.write_row(f"`{source.name}`", f"{size_kb:.0f} KB",
                               f"{elapsed:.2f}s", mark, details.replace("|", "\\|"))
        if log_cb:
            log_cb(f"[{index}/{total}] {'✓' if last.success else '✗'} "
                  f"{source.name} — {last.message}")
            for warning in last.warnings:
                log_cb(f"    ⚠ {warning}")

    # assemble the merged book
    if options.merge_all and book_path is not None and book_sections:
        ok_sources = [r.source for r in results if r.success]
        front = "---\n"
        front += f'title: "{sanitize_filename(input_root.name if input_root.is_dir() else input_root.stem)}"\n'
        front += "converter: PDF-to-MD\n"
        front += f"sources: {len(ok_sources)}\n"
        front += f"converted: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        front += "---\n"
        heading = f"# 📚 {sanitize_filename(input_root.name if input_root.is_dir() else input_root.stem)}\n\n"
        heading += (f"*Combined conversion of {len(ok_sources)} file(s). "
                    f"Each source starts after a horizontal rule.*\n")
        try:
            book_path.write_text(front + "\n" + heading + "".join(book_sections) + "\n",
                                 encoding="utf-8")
            if log_cb:
                log_cb(f"📖 Merged book written → {book_path}")
            activity_log.write(f"📖 **Merged book:** `{book_path}` "
                               f"({book_path.stat().st_size / 1024:.0f} KB)")
        except OSError as exc:
            for r in results:
                if r.output == book_path:
                    r.success = False
                    r.message = f"Could not write merged book: {exc}"
            activity_log.write(f"❌ **Merged book failed:** {exc}")

    # session summary in the persistent log
    ok_count = sum(1 for r in results if r.success)
    warn_count = sum(len(r.warnings) for r in results)
    duration = (datetime.now(timezone.utc) - session_started).total_seconds()
    activity_log.write_summary(ok_count, len(results), len(results) - ok_count,
                               warn_count, duration)

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
    parser.add_argument("--merge", action="store_true",
                        help="combine ALL files into one <folder>.md book")
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
        merge_all=args.merge,
    )
    results = convert_folder(input_path, output_path, options, log_cb=print)
    ok = sum(1 for r in results if r.success)
    print(f"\nDone: {ok}/{len(results)} file(s) converted → {output_path}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
