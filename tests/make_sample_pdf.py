"""Generate a sample lecture PDF for manual testing of the PDF engine.

Covers: headings, paragraphs, hyphen bullets, a unicode equation (Greek
letters), a ruled table, an embedded image, and repeated page
headers/footers over 4 pages (to exercise the recurring-text filter).

Run:  python tests/make_sample_pdf.py
Out:  tests/samples/sample_lecture.pdf
"""

from pathlib import Path

import pymupdf

SAMPLES = Path(__file__).parent / "samples"


class _Cursor:
    """Tiny helper that writes lines down a page with a moving y cursor."""

    def __init__(self, page: pymupdf.Page, x: float = 60, y: float = 60):
        self.page, self.x, self.y = page, x, y

    def write(self, text: str, size: float = 11, font: str = "helv",
              gap: float = 1.35, fontfile: Path | None = None) -> None:
        kwargs = {"fontsize": size, "fontname": font}
        if fontfile is not None:
            kwargs["fontfile"] = str(fontfile)
        self.page.insert_text((self.x, self.y), text, **kwargs)
        self.y += size * gap

    def gap(self, amount: float = 10) -> None:
        self.y += amount


def _draw_table(page: pymupdf.Page, x0: float, y0: float) -> float:
    """Draw a small ruled table; returns the y below it."""
    rows = [
        ("Activation", "Range", "Use case"),
        ("ReLU", "0 to inf", "Hidden layers"),
        ("Sigmoid", "0 to 1", "Binary output"),
        ("Softmax", "0 to 1", "Multi-class"),
    ]
    col_w, row_h = 150, 20
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            rect = pymupdf.Rect(x0 + c * col_w, y0 + r * row_h,
                                x0 + (c + 1) * col_w, y0 + (r + 1) * row_h)
            page.draw_rect(rect)
            page.insert_text((rect.x0 + 4, rect.y1 - 6), cell, fontsize=10)
    return y0 + len(rows) * row_h


def _header_footer(page: pymupdf.Page, page_no: int, total: int) -> None:
    page.insert_text((60, 30), "DL Fundamentals - Lecture 3", fontsize=9, fontname="hebo")
    page.insert_text((480, 820), f"Page {page_no} of {total}", fontsize=9, fontname="helv")


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()

    # ---------- page 1: rich content ------------------------------------
    page = doc.new_page(width=595, height=842)
    _header_footer(page, 1, 4)
    cur = _Cursor(page, y=70)
    cur.write("Lecture 3: Neural Networks", 24, "hebo")
    cur.write("Course: Deep Learning Fundamentals", 12, "heit")
    cur.gap()
    cur.write("1. Introduction", 16, "hebo")
    cur.write("A neural network is a computational model inspired by")
    cur.write("the structure of biological brains. It consists of layers")
    cur.write("of interconnected neurons that propagate signals.")
    cur.gap()
    cur.write("Key topics covered today:")
    cur.write("- Forward propagation and activations")
    cur.write("- Loss functions such as cross-entropy")
    cur.write("- Gradient descent with learning rate alpha")
    cur.gap()
    cur.write("The update rule is:")
    # insert_htmlbox embeds a proper ToUnicode map so θ/α/∇ extract cleanly
    page.insert_htmlbox(
        pymupdf.Rect(58, cur.y - 12, 535, cur.y + 6),
        "<p>θ = θ - α ∇J(θ)</p>",
    )
    cur.y += 22
    cur.gap(18)
    cur.write("2. Comparison of activation functions", 16, "hebo")
    cur.gap(8)
    below = _draw_table(page, 60, cur.y)
    cur.y = below + 24

    # embedded image
    png = SAMPLES / "_logo.png"
    logo = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 60))
    logo.clear_with(90)
    png.write_bytes(logo.tobytes("png"))
    page.insert_image(pymupdf.Rect(420, 70, 540, 130), filename=str(png))
    png.unlink()

    # ---------- pages 2-4: body text under repeated header/footer -------
    for page_no in (2, 3, 4):
        page = doc.new_page(width=595, height=842)
        _header_footer(page, page_no, 4)
        cur = _Cursor(page, y=70)
        cur.write(f"{page_no}. Section content", 16, "hebo")
        for i in range(4):
            cur.write(f"Paragraph {i + 1} on page {page_no} covers training")
            cur.write("dynamics, regularization and evaluation metrics.")
            cur.gap()

    out = SAMPLES / "sample_lecture.pdf"
    doc.save(out)
    doc.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
