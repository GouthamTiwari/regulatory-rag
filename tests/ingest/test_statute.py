"""Bare-law ingestion (task 33): HTML to text, clause splitting, chunking, fetching.

No network: the portal is replaced by an httpx.MockTransport.
"""

import json
from datetime import date

import httpx
import pytest

from regrag.config import Settings
from regrag.ingest import statute
from regrag.ingest.statute import (
    StatuteError,
    chunk_statute,
    fetch_statute,
    html_to_text,
    parse_statute,
    tidy_markers,
)
from regrag.types import ManifestRow

SETTINGS = Settings()
LIST_URL = "https://taxinformation.cbic.gov.in/api/cbic-act-section-msts/findByActId/1000006"

S16_HTML = """<html><body><script>var x = 1;</script>
<p>Section 16</p><p>16. Eligibility and conditions for taking input tax credit.-</p>
<p>(1)</p><p>Every registered person shall, subject to such conditions and restrictions as may be
prescribed, be entitled to take credit of input tax charged on any supply.</p>
<p>(2) Notwithstanding anything contained in this section, no registered person shall be
entitled to the credit of any input tax in respect of any supply unless,-</p>
<p>(a) he is in possession of a tax invoice or debit note issued by a supplier;</p>
<p>1[(aa) the details of the invoice or debit note referred to in clause (a) has been furnished
by the supplier in the statement of outward supplies and such details have been communicated
to the recipient of such invoice or debit note in the manner specified under section 37;]</p>
<p>(b) he has received the goods or services or both.</p>
<p>( 4 ) A registered person shall not be entitled to take input tax credit after the thirtieth
day of November following the end of financial year.</p>
<p>1. Inserted by s. 2 of the Central Goods and Services Tax (Amendment) Act, 2018.</p>
</body></html>"""

S20_HTML = """<p>Section 20. Application of provisions of Central Goods and Services Tax Act.-</p>
<p>( i ) scope of supply;</p><p>(ii) composite supply and mixed supply;</p>
<p>(iii) time and value of supply;</p><p>(iv) input tax credit;</p>"""


def statute_row(doc_id="gst-cgst-act-2017", pdf_url=LIST_URL) -> ManifestRow:
    return ManifestRow(
        doc_id=doc_id, corpus="gst", doc_type="act", title="CGST Act", reference_no="12/2017",
        applies_to="", publish_date=date(2017, 4, 12),
        source_url="https://taxinformation.cbic.gov.in/x", pdf_url=pdf_url,
    )  # fmt: skip


def write_statute(tmp_path, sections) -> object:
    path = tmp_path / "gst-cgst-act-2017.json"
    path.write_text(json.dumps({"doc_id": "gst-cgst-act-2017", "sections": sections}), "utf-8")
    return path


def section(number, title, html):
    return {"number": number, "title": title, "url": f"https://x/{number}",
            "text": html_to_text(html)}  # fmt: skip


# --- text -------------------------------------------------------------------------------------


def test_html_to_text_keeps_one_paragraph_per_clause():
    text = html_to_text(S16_HTML)
    paras = text.split("\n\n")
    assert "var x" not in text  # scripts dropped
    assert paras[2].startswith("(1) Every registered person")  # lone marker joined to its text
    assert any(p.startswith("1[(aa) the details") for p in paras)
    assert any(p.startswith("(4) A registered person") for p in paras)  # "( 4 )" tidied


def test_tidy_markers():
    assert tidy_markers("( 1 ) x ( iv ) y (aa) z") == "(1) x (iv) y (aa) z"


# --- clause splitting and chunks --------------------------------------------------------------


def test_chunks_follow_the_laws_numbering(tmp_path):
    path = write_statute(tmp_path, [section("16", "Eligibility and conditions", S16_HTML)])
    chunks = chunk_statute(path, statute_row(), SETTINGS)
    cites = [c.section_no for c in chunks]
    assert "16(1)" in cites and "16(4)" in cites
    aa = next(c for c in chunks if "16(2)(aa)" in c.section_path)
    assert "statement of outward supplies" in aa.content
    assert aa.content.startswith("CGST Act s.16")
    notes = [c for c in chunks if c.section_path.endswith("16 amendment notes")]
    assert len(notes) == 1 and "Inserted by" in notes[0].content
    assert notes[0].section_no == "16 (amendment history)"
    assert "NOT in force" in notes[0].content  # quoted old wording is never mistaken for law
    assert all(c.page_start == c.page_end == 1 for c in chunks)  # page = position of section
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_heading_joins_the_first_clause(tmp_path):
    path = write_statute(tmp_path, [section("16", "Eligibility", S16_HTML)])
    first = chunk_statute(path, statute_row(), SETTINGS)[0]
    assert first.section_no == "16(1)" and "16. Eligibility" in first.content


def test_top_level_roman_list_is_a_list_of_clauses(tmp_path):
    path = write_statute(tmp_path, [section("20", "Application of CGST Act", S20_HTML)])
    chunks = chunk_statute(path, statute_row(), SETTINGS)
    covered = " ".join(c.section_path for c in chunks)
    assert "20(i)" in covered and "20(ii)" in covered and "20(iv)" in covered


@pytest.mark.parametrize(
    ("token", "last", "roman"),
    [
        ("i", "h", False),
        ("i", "a", True),
        ("v", "u", False),
        ("v", "b", True),
        ("xiv", "", True),
        ("aa", "a", False),
        ("iia", "", True),
    ],
)
def test_roman_or_letter(token, last, roman):
    assert statute._is_roman(token, last) is roman


def test_long_clauses_are_split_with_overlap(tmp_path):
    long = "<p>(1) " + " ".join(f"word{i}" for i in range(2000)) + "</p>"
    path = write_statute(tmp_path, [section("99", "Long", long)])
    chunks = chunk_statute(path, statute_row(), SETTINGS)
    assert len(chunks) > 1
    assert all(c.token_count <= SETTINGS.chunk_max_tokens for c in chunks)
    tail = chunks[0].content.split()[-5:]
    assert all(w in chunks[1].content for w in tail)  # overlap: nothing lost at the boundary


def test_parse_makes_one_page_per_section(tmp_path):
    path = write_statute(tmp_path, [section("16", "A", S16_HTML), section("20", "B", S20_HTML)])
    parsed = parse_statute(path, "gst-cgst-act-2017")
    assert [p.page_no for p in parsed.pages] == [1, 2]


def test_empty_file_is_an_error(tmp_path):
    path = write_statute(tmp_path, [])
    with pytest.raises(StatuteError):
        parse_statute(path, "gst-cgst-act-2017")


# --- fetching ---------------------------------------------------------------------------------


def portal(handler_calls):
    listing = [
        {"sectionNo": "Section 16", "sectionName": "Eligibility", "isActive": "Y",
         "contentFilePath": "tax_repository\\gst\\acts\\2017_CGST_act\\active\\chapter5\\"
                            "section16_v1.00.html"},
        {"sectionNo": "Introduction", "sectionName": "x", "isActive": "Y",
         "contentFilePath": "tax_repository\\gst\\intro.html"},
        {"sectionNo": "Section 17", "sectionName": "Old", "isActive": "N",
         "contentFilePath": "tax_repository\\gst\\old.html"},
        {"sectionNo": "Schedule I", "sectionName": "Supply", "isActive": "Y",
         "contentFilePath": "tax_repository\\gst\\acts\\2017_CGST_act\\active\\chapter21\\"
                            "schedulei_v1.00.html"},
    ]  # fmt: skip

    def handler(request: httpx.Request) -> httpx.Response:
        handler_calls.append(str(request.url))
        if request.url.path.startswith("/api/"):
            return httpx.Response(200, json=listing)
        if "section16" in request.url.path:
            return httpx.Response(200, text=S16_HTML)
        return httpx.Response(200, text="<p>Schedule I</p><p>1. Permanent transfer of assets.</p>")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_writes_active_sections_only(tmp_path):
    calls = []
    path = fetch_statute(statute_row(), portal(calls), SETTINGS, tmp_path, sleep=lambda s: None)
    data = json.loads(path.read_text("utf-8"))
    assert [s["number"] for s in data["sections"]] == ["16", "Schedule I"]
    assert data["sections"][0]["url"].startswith(
        "https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/"
    )
    assert len(calls) == 3  # the list + two active section pages; inactive/intro skipped
    assert not path.with_suffix(".json.part").exists()


def test_fetch_is_deterministic(tmp_path):
    a = fetch_statute(statute_row(), portal([]), SETTINGS, tmp_path / "a", sleep=lambda s: None)
    b = fetch_statute(statute_row(), portal([]), SETTINGS, tmp_path / "b", sleep=lambda s: None)
    assert a.read_bytes() == b.read_bytes()  # same law, same hash: nothing re-embedded


def test_fetch_refuses_unofficial_hosts(tmp_path):
    with pytest.raises(StatuteError, match="official host"):
        fetch_statute(statute_row(pdf_url="https://evil.example/list"), portal([]), SETTINGS,
                      tmp_path, sleep=lambda s: None)  # fmt: skip


def test_statute_rows_are_recognised():
    assert statute.is_statute(statute_row())
    rules = statute_row("gst-cgst-rules-2017")
    rules.doc_type = "rules"
    assert statute.is_statute(rules)
    circular = statute_row("gst-250-07-2025")
    circular.doc_type = "circular"
    assert not statute.is_statute(circular)


R36_TEXT = (
    "Rule 36. Documentary requirements.-\n\n(3) No input tax credit shall be availed in respect "
    "of tax paid in pursuance of an order.\n\n3 [(4) No input tax credit shall be availed in "
    "respect of invoices unless,-\n\n(a) the details have been furnished by the supplier;\n\n(b) "
    "the details have been communicated in FORM GSTR-2B.]\n\n3. Substituted (w.e.f. 01.01.2022) "
    'for\n\n"(4) Input tax credit to be availed shall not exceed 5 per cent.\n\nProvided that the '
    "said condition shall apply cumulatively."
)


def test_spaced_amendment_marker_starts_a_new_sub_section():
    labels = [u.label for u in statute._units(R36_TEXT)]
    assert "(4)" in labels and "(4)(a)" in labels and "(4)(b)" in labels


def test_quoted_old_wording_in_notes_is_not_law_text():
    units = statute._units(R36_TEXT)
    notes = [u for u in units if u.footnotes]
    assert len(notes) == 1 and "5 per cent" in notes[0].text
    assert all("5 per cent" not in u.text for u in units if not u.footnotes)


def test_section_url_points_at_the_sections_own_page(tmp_path):
    (tmp_path / "gst-cgst-rules-2017.json").write_text(
        json.dumps(
            {
                "sections": [
                    {"number": "36", "url": "https://x/rule36.html", "text": "x", "title": "t"}
                ]
            }
        ),  # fmt: skip
        "utf-8",
    )
    statute._URL_CACHE.clear()
    path = "CGST Rules > r.36 Documentary requirements > 36(4)"
    assert (
        statute.section_url("gst-cgst-rules-2017", path, "d", tmp_path) == "https://x/rule36.html"
    )
    assert (
        statute.section_url("gst-cgst-rules-2017", "CGST Rules > r.99 X > 99", "d", tmp_path) == "d"
    )
    assert statute.section_url("gst-231-25-2024", path, "d", tmp_path) == "d"
    statute._URL_CACHE.clear()
