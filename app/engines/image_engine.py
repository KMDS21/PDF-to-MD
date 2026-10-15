"""Image → Markdown engine (scans, photos, screenshots).

Images have no text layer, so conversion is OCR-based (plan §6):

- OCR enabled  → pytesseract extracts text (requires Tesseract-OCR installed)
- AI enabled   → a vision model captions/transcribes the image instead
- neither      → the image is still copied to assets and referenced, with a
                 warning, so nothing is silently lost
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover - optional OCR dependency
    pytesseract = None  # type: ignore
    Image = None  # type: ignore

from app.engines.base import ConversionEngine, ConversionResult
from app.utils import assets_dir_for, unique_path


class ImageEngine(ConversionEngine):
    """Convert a raster image (png/jpg/tiff/bmp/webp) to Markdown via OCR."""

    name = "image (OCR)"
    extensions = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")

    # ------------------------------------------------------------------ API
    def convert(self, input_path: Path, output_md_path: Path, options: dict[str, Any]) -> ConversionResult:
        ocr_enabled = bool(options.get("ocr_enabled", True))
        ai_enabled = bool(options.get("ai_enabled", False))
        warnings: list[str] = []
        assets_dir = assets_dir_for(output_md_path)

        # always keep the original image in assets (content preservation)
        saved = unique_path(assets_dir, input_path.name)
        try:
            saved.write_bytes(Path(input_path).read_bytes())
            image_ref = f"![{input_path.stem}]({assets_dir.name}/{saved.name})"
        except OSError as exc:
            image_ref = ""
            warnings.append(f"Could not copy image to assets: {exc}")

        text = ""
        # 1st choice: AI vision (available from milestone M7)
        if ai_enabled:
            helper = self._get_ai_helper()
            if helper is not None:
                try:
                    text = helper.page_image_to_markdown(
                        Path(input_path).read_bytes(),
                        context=f"image file {input_path.name}",
                    ).strip()
                except Exception as exc:
                    warnings.append(f"AI transcription failed ({exc}); trying OCR")

        # 2nd choice: local OCR
        if not text and ocr_enabled:
            if pytesseract is None:
                warnings.append(
                    "OCR unavailable (install: pip install pytesseract + Tesseract-OCR)")
            else:
                try:
                    with Image.open(input_path) as image:
                        text = pytesseract.image_to_string(image).strip()
                except Exception as exc:
                    warnings.append(f"OCR failed: {exc}")

        if not text and not ai_enabled and not ocr_enabled:
            warnings.append("OCR disabled — image kept without transcription")

        parts = [p.strip() for p in text.split("\n\n") if p.strip()] if text else []
        if image_ref:
            parts.append(image_ref)
        if not parts:
            return ConversionResult(False, warnings=warnings, error="Nothing could be extracted")

        metadata: dict[str, Any] = {}
        if text:
            metadata["ocr"] = True
        return ConversionResult(True, "\n\n".join(parts) + "\n", warnings, metadata=metadata)

    # ------------------------------------------------------------- ai hook
    @staticmethod
    def _get_ai_helper() -> Any:
        try:
            from app import ai_helper  # type: ignore
        except ImportError:
            return None
        return getattr(ai_helper, "AiHelper", None) and ai_helper.AiHelper()
