# Project Plan: PDF-to-MD Converter

> Desktop app that batch-converts lecture materials (PDF, PPTX, DOCX, XLSX, images)
> into clean, high-fidelity Markdown — without losing content.
> Repository: https://github.com/KMDS21/PDF-to-MD.git

---

## 1. Overview

**Goal.** A single desktop tool where a user selects a folder of lecture files and gets back
a mirrored folder of `.md` files with text, headings, tables, images and equations preserved.

**Primary user.** A student/lecturer whose course materials live as PDF slides, PowerPoint
presentations, Word docs, Excel sheets and scanned images.

**Design principles.**
- Offline-first: everything works with no API keys and no internet.
- Optional AI: a toggle upgrades hard pages (scans, equations, image captions) via OpenAI/Gemini.
- No content loss: images are extracted to asset folders, tables become real Markdown tables,
  math is preserved (LaTeX where possible, Unicode otherwise).
- One engine per format, sharing a common interface, so any file type can be added later.

---

## 2. Requirements

| # | Requirement | Source |
|---|-------------|--------|
| R1 | Desktop GUI with folder selection (recursive batch conversion) | User |
| R2 | Convert PDF → MD accurately | User |
| R3 | Convert PPTX → MD accurately | User |
| R4 | Also support DOCX, XLSX, and image files | User |
| R5 | Preserve text + images + tables + equations | User |
| R6 | Offline conversion engine with optional AI enhancement | Plan review |
| R7 | Progress display, per-file status, cancel, open-output button | Plan review |
| R8 | Output mirrors input folder structure | Plan review |
| R9 | Option to merge ALL files into one book .md, each source separated (user request) | User |
| R10 | Creative, easy-to-understand UI (cards, mode switch, live status) | User |
| R11 | "New Conversion" button — reset UI for the next batch without restarting the app | User |
| R12 | Persistent dated activity log file with all conversion details | User |

---

## 3. Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python 3.10+ | Best document-parsing ecosystem |
| GUI | CustomTkinter | Modern look, pure Python, easy to run (`python main.py`) |
| PDF | PyMuPDF + pdfplumber | Layout-aware text & images (PyMuPDF), robust table extraction (pdfplumber) |
| PPTX | python-pptx | Slides, bullets, tables, images, speaker notes |
| DOCX | python-docx | Paragraphs, headings, tables, images |
| XLSX | openpyxl | Sheets → Markdown tables |
| Images/OCR | Pillow + pytesseract | Scanned pages & standalone images (needs Tesseract binary) |
| AI (optional) | OpenAI / Gemini vision API | Scanned-page OCR upgrade, equation LaTeX, image captions |
| HTTP | requests | AI API calls |

---

## 4. Architecture

```
PDF-to-MD/
├── main.py                  # entry point → launches GUI
├── requirements.txt
├── README.md
├── PROJECT_PLAN.md          # this file
├── app/
│   ├── gui.py               # folder picker, options, progress, log
│   ├── converter.py         # orchestrator: picks engine per extension, batch jobs
│   ├── ai_helper.py         # optional AI enhancement (OpenAI/Gemini)
│   ├── utils.py             # asset saving, filename sanitizing, markdown cleanup
│   └── engines/
│       ├── base.py          # ConversionEngine interface + ConversionResult
│       ├── pdf_engine.py    # text/tables/images/equations + OCR fallback
│       ├── pptx_engine.py   # slides → headings/lists, notes, tables, images
│       ├── docx_engine.py   # Word documents
│       ├── xlsx_engine.py   # each sheet → markdown table
│       └── image_engine.py  # scans/photos → OCR text or AI caption
└── tests/
    └── samples/             # sample files for manual verification
```

**Pipeline.** GUI → Converter (scans folder, builds job list) → Engine per file →
Markdown string + assets on disk → written to `output/<mirrored path>/<name>.md`.

---

## 5. Milestones (one git commit each)

| # | Milestone | Commit content | Status |
|---|-----------|----------------|--------|
| M1 | Scaffold | git init, requirements, .gitignore, README skeleton, main.py stub, this plan | ✅ |
| M2 | Core orchestrator | `converter.py`, `utils.py`, `engines/base.py` | ✅ |
| M3 | PDF engine | `pdf_engine.py` — text, tables, images, equations, OCR fallback | ✅ |
| M4 | PPTX engine | `pptx_engine.py` — slides, notes, tables, images, equations | ✅ |
| M5 | DOCX/XLSX/image engines | `docx_engine.py`, `xlsx_engine.py`, `image_engine.py` | ✅ |
| M6 | GUI | `gui.py` — card-based creative UI, folder picker, merge-mode switch, progress, log | ✅ |
| M6+ | Merge mode | all files → one book .md with per-source dividers + shared assets (user request) | ✅ |
| M6++ | Session reset + activity log | 🔄 New Conversion reset button; dated `logs/conversion_YYYY-MM-DD.log` with per-file timing/warnings/session summaries (user request) | ✅ |
| M7 | AI enhancement | `ai_helper.py` — optional OpenAI/Gemini upgrades | ⏳ |
| M8 | Docs & release | Full README, sample tests, push to GitHub | ⏳ |

---

## 6. Conversion Rules per Format

### PDF
1. Per page, measure text density → classify as **text-based** or **scanned**.
2. Text pages → layout-aware extraction with heading heuristics (font size/weight).
3. Tables → pdfplumber → proper Markdown pipe tables.
4. Images → extracted to `<name>_assets/`, embedded at their page position.
5. Math zones (symbol-density heuristic) → wrapped in `$$…$$` (LaTeX when recoverable).
6. Scanned pages → OCR (Tesseract); with AI toggle, the vision model converts them instead.

### PPTX
- Slide title → `# Heading` (slide number in heading)
- Body placeholders → bullet lists with nesting preserved (`-`, `  -`, …)
- Tables → Markdown tables; images → extracted assets; equations → math preserved
- Speaker notes → blockquote section at the end of each slide (toggleable)

### DOCX
- Headings → `#`…`######`; body → paragraphs; lists → bullets/numbers; tables → MD tables; images → assets.

### XLSX
- Each worksheet → Markdown table section (`## SheetName`), header row detected from first non-empty row.

### Images (png/jpg/tiff/bmp/webp)
- OCR → text file, or AI caption when enabled; original image copied to assets.

---

## 7. GUI Specification

| Control | Behavior |
|---------|----------|
| **Select Folder…** | Opens folder dialog; lists found convertible files + count badge |
| Recursive scan toggle | Include subfolders (default: on) |
| Output folder picker | Defaults to `<input>/output` |
| **Output mode switch** | 📄 Separate files (one .md each, mirrored structure) **or** 📚 Merge into one book (`<folder>.md` with `---` dividers + shared assets folder) |
| Options | Extract images · Speaker notes · OCR scanned pages · AI enhancement |
| AI settings | Provider (OpenAI/Gemini), API key field (stored in memory only) |
| **Convert** button | Starts batch; **Cancel** stops after current file |
| Progress bar + % + status | Per-file ✓ / ✗ / ⚠ in live log pane; final "Done: n/m" |
| **Open Output** | Windows Explorer at output dir |

---

## 8. Testing Strategy

1. **Smoke test:** every module imports; `python main.py` launches GUI.
2. **Sample files** in `tests/samples/`: text PDF, scanned PDF, lecture PPTX with
   images/tables/notes, DOCX, XLSX, image scan.
3. **Manual verification checklist** per file: headings present, tables render,
   images referenced and present in assets folder, no missing paragraphs.
4. **Batch test:** run folder conversion over all samples at once, verify mirrored output.

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Offline LaTeX recovery from PDF/PPTX is imperfect | Equations may be Unicode instead of LaTeX | Best-effort detection + `$$…$$` wrapping; AI toggle fixes hard cases |
| Tesseract not installed | OCR unavailable | Graceful degradation + clear README install guide (`winget install`) |
| Python 3.14 is very new; some libs lag | Install errors | Pin minimum versions with wheels for 3.14; test install in venv |
| Huge PDFs / 100+ file batches | Slow, memory spikes | Convert file-by-file in a worker thread; cancel support |
| API key handling | Security | Key kept in memory only, never written to disk or logs |

---

## 10. Future Work (out of scope for v1)

- Drag-and-drop files onto the window
- Watch-folder mode (auto-convert new files)
- Multi-language OCR (EasyOCR/PaddleOCR)
- EPUB / HTML output formats
- Resume interrupted batches
- Per-file setting overrides

---

*Plan is a living document — milestones are checked off as commits land.*
