"""Generate a sample lecture PPTX for manual testing of the PPTX engine.

Covers: title slide, nested bullets, a table, a picture, speaker notes.

Run:  python tests/make_sample_pptx.py
Out:  tests/samples/sample_lecture.pptx
"""

from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from PIL import Image, ImageDraw

SAMPLES = Path(__file__).parent / "samples"


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    prs = Presentation()

    # ---------- slide 1: title + nested bullets + notes -----------------
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Week 5: Database Indexing"
    slide.placeholders[1].text = "Databases II — Lecture Slides"

    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Why Indexes Matter"
    body = slide.placeholders[1].text_frame
    body.text = "Full table scan costs O(n)"
    for level, text in ((1, "B-tree indexes give O(log n) lookups"),
                        (1, "Hash indexes give O(1) equality lookup"),
                        (2, "but no range support")):
        paragraph = body.add_paragraph()
        paragraph.text = text
        paragraph.level = level
    body.add_paragraph().text = "Composite indexes follow leftmost-prefix rule"
    slide.notes_slide.notes_text_frame.text = (
        "Emphasize the exam question from 2023: why not always hash indexes?"
    )

    # ---------- slide 2: table ------------------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # title only
    slide.shapes.title.text = "Index type comparison"
    table_shape = slide.shapes.add_table(3, 3, Inches(0.5), Inches(1.3), Inches(8), Inches(1.5))
    data = [
        ("Type", "Lookup", "Range"),
        ("B-tree", "O(log n)", "Yes"),
        ("Hash", "O(1)", "No"),
    ]
    for r, row in enumerate(data):
        for c, value in enumerate(row):
            table_shape.table.cell(r, c).text = value

    # ---------- slide 3: picture + notes --------------------------------
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # title only
    slide.shapes.title.text = "Query plan example"
    img_path = SAMPLES / "_plan.png"
    image = Image.new("RGB", (400, 200), color=(235, 240, 250))
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, 390, 190], outline=(60, 90, 160), width=3)
    draw.text((20, 20), "Seq Scan -> Sort -> Index Scan", fill=(30, 30, 30))
    image.save(img_path)
    slide.shapes.add_picture(str(img_path), Inches(1), Inches(1.5), Inches(5))
    img_path.unlink()
    slide.notes_slide.notes_text_frame.text = "Show EXPLAIN output live in demo."

    out = SAMPLES / "sample_lecture.pptx"
    prs.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
