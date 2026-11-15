"""Downloader tests. A fake web server (httpx.MockTransport) answers every request,
so no test touches the network and no test waits (sleep is replaced by a recorder)."""

import hashlib
from datetime import date

import httpx
import pytest

from regrag.config import Settings
from regrag.ingest.download import (
    MAX_BYTES,
    download_all,
    download_document,
    import_from_folder,
    pdf_filename,
    select_rows,
    summarize,
)
from regrag.types import ManifestRow

SETTINGS = Settings()
PDF = b"%PDF-1.7\nsynthetic test document\n%%EOF\n"
PDF_HASH = hashlib.sha256(PDF).hexdigest()
URL = "https://gstcouncil.gov.in/sites/default/files/test.pdf"


def row(doc_id="gst-231-25-2024", sha256="", pdf_url=URL) -> ManifestRow:
    return ManifestRow(
        doc_id=doc_id,
        corpus="gst",
        doc_type="circular",
        title="Test circular",
        reference_no="231/25/2024-GST",
        applies_to="",
        publish_date=date(2024, 9, 11),
        source_url="https://gstcouncil.gov.in/cgst-circulars",
        pdf_url=pdf_url,
        sha256=sha256,
    )


def client_for(*responses, requests=None):
    """A client whose fake server returns `responses` in order (the last one repeats)."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(str(request.url))
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def ok_pdf(content=PDF):
    return httpx.Response(200, content=content, headers={"content-type": "application/pdf"})


@pytest.fixture
def sleeps():
    calls: list[float] = []
    return calls


def download(r, client, tmp_path, sleeps, **kwargs):
    return download_document(r, client, tmp_path, SETTINGS, sleep=sleeps.append, **kwargs)


def test_success_writes_pdf_and_reports_hash(tmp_path, sleeps):
    result = download(row(), client_for(ok_pdf()), tmp_path, sleeps)
    assert result.status == "ok"
    assert result.sha256 == PDF_HASH and result.size_bytes == len(PDF)
    assert (tmp_path / "gst-231-25-2024.pdf").read_bytes() == PDF
    assert sleeps == []


def test_retry_then_success(tmp_path, sleeps):
    requests: list[str] = []
    client = client_for(httpx.Response(503), ok_pdf(), requests=requests)
    result = download(row(), client, tmp_path, sleeps)
    assert result.status == "ok"
    assert len(requests) == 2 and len(sleeps) == 1  # one back-off pause before the retry


def test_network_error_is_retried(tmp_path, sleeps):
    client = client_for(httpx.ConnectTimeout("slow"), ok_pdf())
    assert download(row(), client, tmp_path, sleeps).status == "ok"


def test_gives_up_after_all_retries(tmp_path, sleeps):
    requests: list[str] = []
    result = download(row(), client_for(httpx.Response(503), requests=requests), tmp_path, sleeps)
    assert result.status == "failed" and "gave up" in result.message
    assert len(requests) == SETTINGS.download_retries + 1
    assert not (tmp_path / "gst-231-25-2024.pdf").exists()


def test_404_is_not_retried(tmp_path, sleeps):
    requests: list[str] = []
    result = download(row(), client_for(httpx.Response(404), requests=requests), tmp_path, sleeps)
    assert result.status == "failed" and "HTTP 404" in result.message
    assert len(requests) == 1


def test_html_instead_of_pdf_is_a_failure(tmp_path, sleeps):
    page = httpx.Response(
        200, content=b"<html>Session expired</html>", headers={"content-type": "text/html"}
    )
    result = download(row(), client_for(page), tmp_path, sleeps)
    assert result.status == "failed" and "not a PDF" in result.message
    assert list(tmp_path.iterdir()) == []  # nothing written, not even a .part file


def test_hash_mismatch_is_reported(tmp_path, sleeps):
    result = download(row(sha256="0" * 64), client_for(ok_pdf()), tmp_path, sleeps)
    assert result.status == "ok" and result.hash_changed
    assert "may have been replaced" in result.message


def test_existing_file_with_matching_hash_is_skipped(tmp_path, sleeps):
    (tmp_path / "gst-231-25-2024.pdf").write_bytes(PDF)
    requests: list[str] = []
    result = download(
        row(sha256=PDF_HASH), client_for(ok_pdf(), requests=requests), tmp_path, sleeps
    )
    assert result.status == "skipped" and requests == []


def test_existing_pdf_is_kept_when_manifest_has_no_hash(tmp_path, sleeps):
    (tmp_path / "gst-231-25-2024.pdf").write_bytes(PDF)
    requests: list[str] = []
    result = download(row(), client_for(ok_pdf(), requests=requests), tmp_path, sleeps)
    assert result.status == "skipped" and result.sha256 == PDF_HASH and requests == []


def test_broken_existing_file_is_downloaded_again(tmp_path, sleeps):
    (tmp_path / "gst-231-25-2024.pdf").write_bytes(b"<html>half a download")
    result = download(row(), client_for(ok_pdf()), tmp_path, sleeps)
    assert result.status == "ok"
    assert (tmp_path / "gst-231-25-2024.pdf").read_bytes() == PDF


def test_force_downloads_again(tmp_path, sleeps):
    (tmp_path / "gst-231-25-2024.pdf").write_bytes(PDF)
    requests: list[str] = []
    result = download(row(), client_for(ok_pdf(), requests=requests), tmp_path, sleeps, force=True)
    assert result.status == "ok" and len(requests) == 1


def test_redirect_to_non_official_host_is_rejected(tmp_path, sleeps):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "gstcouncil.gov.in":
            return httpx.Response(302, headers={"location": "https://evil.example/x.pdf"})
        return ok_pdf()

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    result = download(row(), client, tmp_path, sleeps)
    assert result.status == "failed" and "non-official host" in result.message


def test_non_official_url_is_never_requested(tmp_path, sleeps):
    requests: list[str] = []
    r = row(pdf_url="https://example.com/x.pdf")
    result = download(r, client_for(ok_pdf(), requests=requests), tmp_path, sleeps)
    assert result.status == "failed" and requests == []


def test_oversized_file_is_rejected(tmp_path, sleeps):
    huge = ok_pdf(b"%PDF" + b"0" * (MAX_BYTES + 1))
    result = download(row(), client_for(huge), tmp_path, sleeps)
    assert result.status == "failed" and "larger than" in result.message


def test_one_failure_does_not_stop_the_run_and_delay_is_polite(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if "bad" in request.url.path else ok_pdf()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = [
        row("gst-1-1-2025"),
        row("gst-2-1-2025", pdf_url="https://gstcouncil.gov.in/bad.pdf"),
        row("gst-3-1-2025"),
    ]
    sleeps: list[float] = []
    results = download_all(rows, client, tmp_path, SETTINGS, sleep=sleeps.append)
    assert [r.status for r in results] == ["ok", "failed", "ok"]
    # A pause before every request except the first one.
    assert sleeps == [SETTINGS.download_delay_s] * 2
    assert "Failed: 1" in summarize(results)


def test_select_rows_only_and_limit():
    rows = [row("gst-1-1-2025"), row("gst-2-1-2025"), row("gst-3-1-2025")]
    assert [r.doc_id for r in select_rows(rows, ["gst-2-1-2025"], None)] == ["gst-2-1-2025"]
    assert len(select_rows(rows, None, 2)) == 2
    with pytest.raises(SystemExit):
        select_rows(rows, ["gst-9-9-2025"], None)


# --- Human checks (CAPTCHA) and hand-saved files -------------------------------------------

CAPTCHA_PAGE = httpx.Response(
    200,
    content=b"<html>This question is for testing whether you are a human visitor. "
    b"What code is in the image?</html>",
    headers={"content-type": "text/html"},
)
RBI_URL = "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/169MD.PDF"


def test_captcha_page_is_reported_as_a_human_check(tmp_path, sleeps):
    requests: list[str] = []
    result = download(
        row(pdf_url=RBI_URL), client_for(CAPTCHA_PAGE, requests=requests), tmp_path, sleeps
    )
    assert result.status == "failed" and "human check" in result.message
    assert len(requests) == 1  # not retried
    assert list(tmp_path.iterdir()) == []


def test_after_a_captcha_the_host_is_not_asked_again(tmp_path):
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        return CAPTCHA_PAGE if request.url.host == "rbidocs.rbi.org.in" else ok_pdf()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = [
        row("rbi-1", pdf_url=RBI_URL),
        row("rbi-2", pdf_url=RBI_URL.replace("169MD", "170MD")),
        row("gst-3-1-2025"),  # a different host still works
    ]
    results = download_all(rows, client, tmp_path, SETTINGS, sleep=lambda s: None)
    assert [r.status for r in results] == ["failed", "failed", "ok"]
    assert "not requested" in results[1].message
    assert requests == ["rbidocs.rbi.org.in", "gstcouncil.gov.in"]  # RBI asked only once


def test_pdf_filename_is_taken_from_the_url():
    assert pdf_filename(row(pdf_url=RBI_URL)) == "169MD.PDF"


def test_import_from_folder(tmp_path):
    downloads, raw = tmp_path / "Downloads", tmp_path / "raw"
    downloads.mkdir()
    (downloads / "169md.pdf").write_bytes(PDF)  # browsers may change the case
    (downloads / "170MD.PDF").write_bytes(b"<html>not a pdf")
    rows = [
        row("rbi-13141", pdf_url=RBI_URL),
        row("rbi-13140", pdf_url=RBI_URL.replace("169MD", "170MD")),
        row("rbi-13139", pdf_url=RBI_URL.replace("169MD", "171MD")),
    ]
    results = {r.doc_id: r for r in import_from_folder(rows, downloads, raw)}
    assert results["rbi-13141"].status == "ok" and results["rbi-13141"].sha256 == PDF_HASH
    assert (raw / "rbi-13141.pdf").read_bytes() == PDF
    assert "not a PDF" in results["rbi-13140"].message
    assert "not in folder" in results["rbi-13139"].message
    # Running it again does nothing for files already imported.
    assert "rbi-13141" not in {r.doc_id for r in import_from_folder(rows, downloads, raw)}
