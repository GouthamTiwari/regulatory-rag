"""Generate tests/fixtures/sample_direction.pdf: a small, made-up 3-page "direction".

It imitates the layout features the parser must handle (a running header, numbered
headings, paragraphs, one ruled table and a "Page N of 3" footer) but contains no real
regulatory text. The PDF is committed, so tests don't need to regenerate it.

Regenerate with:  uv run python tests/ingest/make_fixture_pdf.py
"""

from pathlib import Path

from fpdf import FPDF

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_direction.pdf"

RUNNING_HEADER = "SYNTHETIC REGULATOR OF TEST MATTERS"
TABLE_HEADER = ("Instrument type", "Maximum limit (Rs.)", "Verification level")
TABLE_ROWS = (
    ("Small test wallet", "10,000", "Minimum details"),
    ("Full test wallet", "2,00,000", "Full verification"),
    ("Test gift card", "10,000", "Minimum details"),
)
PARAGRAPH = (
    "This synthetic paragraph exists only to test the parser. It describes an imaginary "
    "rule about imaginary instruments, so that the text has a realistic length and wraps "
    "across several lines of the page without quoting any real document."
)


class _TestDirection(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 6, RUNNING_HEADER, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Test Directions, 2099 - Page {self.page_no()} of 3", align="C")


def _heading(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")


def _paragraph(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def build(path: Path = FIXTURE) -> Path:
    pdf = _TestDirection()
    pdf.set_auto_page_break(auto=True, margin=20)

    pdf.add_page()
    _heading(pdf, "Chapter I - Preliminary")
    _paragraph(pdf, "1. Short title. These are the Test Directions, 2099. " + PARAGRAPH)
    _paragraph(
        pdf,
        "2. Definitions. In these directions a test wallet means a pretend "
        "instrument. " + PARAGRAPH,
    )

    pdf.add_page()
    _heading(pdf, "Chapter II - Limits")
    _paragraph(pdf, "3. Limits on test wallets. The limits in the table below apply.")
    pdf.set_font("Helvetica", "", 10)
    with pdf.table(col_widths=(60, 50, 60), text_align="LEFT") as table:
        for values in (TABLE_HEADER, *TABLE_ROWS):
            row = table.row()
            for value in values:
                row.cell(value)
    pdf.ln(4)
    _paragraph(pdf, "4. Review. The limits above are reviewed every imaginary year.")

    pdf.add_page()
    _heading(pdf, "Annex - Test glossary")
    _paragraph(pdf, "5. Glossary. " + PARAGRAPH)

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


if __name__ == "__main__":
    out = build()
    print(f"wrote {out} ({out.stat().st_size} bytes)")
