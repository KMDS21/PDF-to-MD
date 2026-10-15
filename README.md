# PDF-to-MD Converter

Desktop app that batch-converts lecture materials into clean, high-fidelity Markdown —
**without losing content**.

**Supported formats:** PDF · PPTX · DOCX · XLSX · Images (png/jpg/tiff/bmp/webp)

> Status: under active development. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the roadmap.

## Features (in progress)

- 📁 Select a folder → converts every supported file inside (recursively)
- 📄 PDF: layout-aware text, real Markdown tables, extracted images, equation preservation, OCR for scanned pages
- 📊 PPTX: slide titles → headings, bullet levels preserved, tables, images, speaker notes
- 📝 DOCX / 📈 XLSX / 🖼 Images: same pipeline, same quality
- 🔌 Offline-first; optional AI enhancement (OpenAI/Gemini) for scanned pages, equations and captions
- 🗂 Output mirrors your folder structure: `output/<same folders>/<same name>.md`

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

## Usage

_Will be documented here after the GUI milestone._

## License

MIT
