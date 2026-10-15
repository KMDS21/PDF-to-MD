"""Generate sample DOCX + XLSX lecture files for engine testing.

Run:  python tests/make_sample_docs.py
Out:  tests/samples/sample_notes.docx
      tests/samples/sample_grades.xlsx
"""

from pathlib import Path

import docx
import openpyxl
from PIL import Image, ImageDraw
from docx.shared import Pt

SAMPLES = Path(__file__).parent / "samples"


def make_docx() -> None:
    document = docx.Document()
    document.add_heading("Operating Systems — Week 2 Notes", level=0)
    document.add_heading("1. Process Scheduling", level=1)

    para = document.add_paragraph("The scheduler decides which process runs next. ")
    para.add_run("Critical concept: ").bold = True
    para.add_run("context switching has a cost.").italic = True

    document.add_paragraph("Common algorithms:", style="Intense Quote")
    for item in ("Round Robin", "Shortest Job First", "Multi-level Feedback Queue"):
        document.add_paragraph(item, style="List Bullet")

    document.add_heading("1.1 Comparison", level=2)
    table = document.add_table(rows=3, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).text = "Algorithm"
    table.cell(0, 1).text = "Preemptive"
    table.cell(1, 0).text = "Round Robin"
    table.cell(1, 1).text = "Yes"
    table.cell(2, 0).text = "SJF"
    table.cell(2, 1).text = "Sometimes"

    # embedded image
    img_path = SAMPLES / "_diagram.png"
    image = Image.new("RGB", (300, 120), color=(250, 245, 235))
    draw = ImageDraw.Draw(image)
    draw.rectangle([5, 5, 295, 115], outline=(150, 60, 60), width=2)
    draw.text((12, 15), "Ready Queue -> CPU -> Waiting", fill=(60, 30, 30))
    image.save(img_path)
    document.add_picture(str(img_path), width=Pt(240))
    img_path.unlink()

    document.add_page_break()
    document.add_heading("2. Deadlocks", level=1)
    document.add_paragraph("Four necessary conditions must hold simultaneously.")
    out = SAMPLES / "sample_notes.docx"
    document.save(out)
    print(f"wrote {out}")


def make_xlsx() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Midterm Results"
    rows = [
        ("Student ID", "Name", "Midterm", "Final", "Passed"),
        (1001, "Amal", 78.5, 82, True),
        (1002, "Nimal", 55, 61.25, True),
        (1003, "Kasun", 41.75, 49, False),
        (1004, "Ishara", 88, None, True),
    ]
    for row in rows:
        sheet.append(row)

    notes = workbook.create_sheet("Grading Notes")
    notes.append(("Grade", "Range"))
    notes.append(("A", "75-100"))
    notes.append(("B", "65-74"))
    notes.append(("C", "50-64"))
    notes.append(("F", "0-49"))

    out = SAMPLES / "sample_grades.xlsx"
    workbook.save(out)
    print(f"wrote {out}")


def make_image() -> None:
    """A screenshot-like image with clear text for OCR testing."""
    out = SAMPLES / "whiteboard.png"
    image = Image.new("RGB", (700, 220), color="white")
    draw = ImageDraw.Draw(image)
    draw.text((25, 30), "Reminder: Lab submission deadline is Friday 5 PM", fill="black")
    draw.text((25, 80), "Bring your student ID for verification.", fill="black")
    draw.text((25, 130), "Late penalty: 10% per day.", fill="black")
    image.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    SAMPLES.mkdir(parents=True, exist_ok=True)
    make_docx()
    make_xlsx()
    make_image()
