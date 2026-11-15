"""Download the manifest's PDFs into data/raw/ (gitignored). SPEC section 5, "Download".

Run:  uv run python -m regrag.ingest.download [--limit N] [--only DOC_ID] [--force]
      uv run python -m regrag.ingest.download --list-missing
      uv run python -m regrag.ingest.download --from-folder C:\\Users\\<you>\\Downloads

Rules: be polite to government servers (one request every 2 s), verify TLS, accept only
real PDFs from official hosts, never leave a half-written file, and keep going when one
document fails (then exit non-zero so the failure is noticed). If a site answers with a
CAPTCHA, we stop asking that site: a person saves those PDFs in a browser and imports them
with --from-folder. (rbidocs.rbi.org.in does this for automated clients.)
"""

import argparse
import hashlib
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

import httpx

from regrag.config import Settings, get_settings
from regrag.ingest.manifest import REPO_ROOT, is_allowed_host, load_manifest
from regrag.types import ManifestRow

RAW_DIR = REPO_ROOT / "data" / "raw"
# A plain, generic client name: identifies the tool, says nothing about the person running it.
USER_AGENT = "Mozilla/5.0 (compatible; regrag/0.1; +public-document-research)"
# Our largest documents are a few MB; anything far bigger is not what we expect.
MAX_BYTES = 50 * 1024 * 1024
# Worth retrying: rate limiting and temporary server errors. A 404 will not fix itself.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

Status = Literal["ok", "skipped", "failed"]


@dataclass
class DownloadResult:
    doc_id: str
    status: Status
    sha256: str = ""
    size_bytes: int = 0
    message: str = ""
    # True when the manifest already had a hash and the downloaded file differs: the
    # regulator may have silently replaced the PDF, which a human should look at.
    hash_changed: bool = False


class _Retryable(Exception):
    """A failure that may succeed on the next attempt."""


class HumanCheckRequired(ValueError):
    """The site answered with a CAPTCHA / "are you human" page instead of the file.

    We never try to get around such a check (that is the site's decision to make). The
    PDF must be saved by a person in a browser and imported with --from-folder.
    """


# Phrases that mark a bot-check page rather than an ordinary error page.
_HUMAN_CHECK_MARKERS = (b"human visitor", b"captcha", b"what code is in the image")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_pdf_file(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(4) == b"%PDF"


def make_client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        timeout=settings.download_timeout_s,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        verify=True,  # TLS verification always on (SPEC 5): never download over a forged connection
    )


def _fetch(client: httpx.Client, row: ManifestRow, settings: Settings) -> bytes:
    """One attempt. Returns the PDF bytes or raises (_Retryable for temporary problems)."""
    try:
        with client.stream("GET", row.pdf_url) as response:
            # Check where redirects ended up: an official link must not lead off-site.
            if not is_allowed_host(str(response.url), settings.allowed_download_hosts):
                raise ValueError(f"redirected to a non-official host: {response.url.host}")
            if response.status_code in RETRYABLE_STATUS:
                raise _Retryable(f"HTTP {response.status_code}")
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code}")
            chunks, total = [], 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError(f"larger than {MAX_BYTES // (1024 * 1024)} MB")
                chunks.append(chunk)
            content_type = response.headers.get("content-type", "?")
    except httpx.TransportError as exc:  # timeouts, refused or dropped connections
        raise _Retryable(type(exc).__name__) from exc
    content = b"".join(chunks)
    # Check the bytes, not the content-type header: servers sometimes return an HTML
    # error page with status 200, and the header can lie in either direction.
    if not content.startswith(b"%PDF"):
        if any(marker in content[:100_000].lower() for marker in _HUMAN_CHECK_MARKERS):
            raise HumanCheckRequired(
                f"{response.url.host} asked for a human check (CAPTCHA): save this PDF by "
                "hand in a browser, then import it with --from-folder"
            )
        raise ValueError(f"not a PDF (content-type {content_type})")
    return content


def download_document(
    row: ManifestRow,
    client: httpx.Client,
    raw_dir: Path,
    settings: Settings,
    *,
    force: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> DownloadResult:
    target = raw_dir / f"{row.doc_id}.pdf"

    if target.exists() and not force:
        existing = sha256_of(target)
        if row.sha256 and existing == row.sha256:
            return DownloadResult(
                row.doc_id,
                "skipped",
                existing,
                target.stat().st_size,
                "already downloaded, hash matches",
            )
        if not row.sha256 and _is_pdf_file(target):
            # The manifest has no hash yet (Task 14 adds them), so a valid existing PDF is
            # kept rather than downloaded again on every run.
            return DownloadResult(
                row.doc_id,
                "skipped",
                existing,
                target.stat().st_size,
                "already downloaded (manifest has no hash yet)",
            )
        # Otherwise the local file is broken or outdated: download it again.

    if not is_allowed_host(row.pdf_url, settings.allowed_download_hosts):
        return DownloadResult(row.doc_id, "failed", message="pdf_url is not an official host")

    attempts = settings.download_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            content = _fetch(client, row, settings)
            break
        except _Retryable as exc:
            if attempt == attempts:
                return DownloadResult(
                    row.doc_id, "failed", message=f"gave up after {attempts} attempts: {exc}"
                )
            sleep(2.0 * attempt)  # back off a little more each time
        except ValueError as exc:
            return DownloadResult(row.doc_id, "failed", message=str(exc))

    raw_dir.mkdir(parents=True, exist_ok=True)
    # Write to a temporary name, then rename. Why: if the run is interrupted mid-write,
    # no half-written file is left behind looking like a real PDF.
    partial = target.with_suffix(".pdf.part")
    partial.write_bytes(content)
    partial.replace(target)

    new_hash = hashlib.sha256(content).hexdigest()
    hash_changed = bool(row.sha256) and new_hash != row.sha256
    message = (
        "hash differs from the manifest: the file may have been replaced" if hash_changed else ""
    )
    return DownloadResult(row.doc_id, "ok", new_hash, len(content), message, hash_changed)


def download_all(
    rows: list[ManifestRow],
    client: httpx.Client,
    raw_dir: Path,
    settings: Settings,
    *,
    force: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[DownloadResult], None] | None = None,
) -> list[DownloadResult]:
    results: list[DownloadResult] = []
    went_to_network = False
    blocked_hosts: set[str] = set()  # hosts that showed a CAPTCHA during this run
    for row in rows:
        host = (urlsplit(row.pdf_url).hostname or "").lower()
        will_download = force or not (raw_dir / f"{row.doc_id}.pdf").exists()
        if will_download and host in blocked_hosts:
            # Why stop asking: repeating requests after a bot check is impolite and would
            # look like an attempt to get through it. A person saves these files instead.
            result = DownloadResult(
                row.doc_id,
                "failed",
                message=f"not requested: {host} asked for a human check earlier in this run",
            )
        else:
            # The polite delay goes between network requests; skipped files cost nothing.
            if went_to_network and will_download:
                sleep(settings.download_delay_s)
            result = download_document(row, client, raw_dir, settings, force=force, sleep=sleep)
            went_to_network = went_to_network or result.status != "skipped"
            if "human check" in result.message:
                blocked_hosts.add(host)
        results.append(result)
        if progress:
            progress(result)
    return results


def pdf_filename(row: ManifestRow) -> str:
    """The file name a browser gives the download, e.g. 169MD.PDF."""
    return unquote(urlsplit(row.pdf_url).path.rsplit("/", 1)[-1])


def missing_rows(rows: list[ManifestRow], raw_dir: Path) -> list[ManifestRow]:
    return [r for r in rows if not (raw_dir / f"{r.doc_id}.pdf").exists()]


def import_from_folder(
    rows: list[ManifestRow], folder: Path, raw_dir: Path
) -> list[DownloadResult]:
    """Copy PDFs a person saved by hand (e.g. into Downloads) into data/raw/<doc_id>.pdf.

    Files are matched by the name in the manifest's pdf_url, ignoring upper/lower case,
    and must really be PDFs. Nothing is fetched from the network.
    """
    by_name = {p.name.lower(): p for p in folder.iterdir() if p.is_file()}
    results = []
    for row in missing_rows(rows, raw_dir):
        source = by_name.get(pdf_filename(row).lower())
        if source is None:
            results.append(
                DownloadResult(row.doc_id, "failed", message=f"{pdf_filename(row)} not in folder")
            )
            continue
        if not _is_pdf_file(source):
            results.append(
                DownloadResult(row.doc_id, "failed", message=f"{source.name} is not a PDF")
            )
            continue
        raw_dir.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        partial = raw_dir / f"{row.doc_id}.pdf.part"
        partial.write_bytes(content)
        partial.replace(raw_dir / f"{row.doc_id}.pdf")
        results.append(
            DownloadResult(
                row.doc_id,
                "ok",
                hashlib.sha256(content).hexdigest(),
                len(content),
                f"imported from {source.name}",
            )
        )
    return results


def select_rows(
    rows: list[ManifestRow], only: list[str] | None, limit: int | None
) -> list[ManifestRow]:
    if only:
        unknown = set(only) - {r.doc_id for r in rows}
        if unknown:
            raise SystemExit(f"Unknown doc_id(s): {', '.join(sorted(unknown))}")
        rows = [r for r in rows if r.doc_id in set(only)]
    return rows[:limit] if limit is not None else rows


def summarize(results: list[DownloadResult]) -> str:
    counts = {s: sum(r.status == s for r in results) for s in ("ok", "skipped", "failed")}
    lines = [
        f"Downloaded: {counts['ok']}  Skipped: {counts['skipped']}  Failed: {counts['failed']}",
        f"Total size: {sum(r.size_bytes for r in results) / 1_048_576:.1f} MB",
    ]
    for r in results:
        if r.status == "failed" or r.hash_changed:
            lines.append(f"  {r.status.upper():7} {r.doc_id}: {r.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download manifest PDFs into data/raw/")
    parser.add_argument("--limit", type=int, help="only the first N documents")
    parser.add_argument("--only", action="append", help="only this doc_id (repeatable)")
    parser.add_argument("--force", action="store_true", help="download again even if present")
    parser.add_argument(
        "--list-missing", action="store_true", help="print the PDFs not yet in data/raw and exit"
    )
    parser.add_argument(
        "--from-folder",
        type=Path,
        help="import hand-saved PDFs from this folder (no network), e.g. your Downloads folder",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    rows = select_rows(load_manifest(settings=settings).rows, args.only, args.limit)

    if args.list_missing:
        missing = missing_rows(rows, RAW_DIR)
        for r in missing:
            print(f"{r.doc_id:24} {pdf_filename(r):45} {r.pdf_url}")
        print(f"{len(missing)} of {len(rows)} PDFs missing from {RAW_DIR}")
        return 0

    def show(r: DownloadResult) -> None:
        print(f"{r.status:7} {r.doc_id:24} {r.size_bytes / 1024:8.0f} KB  {r.message}", flush=True)

    if args.from_folder:
        results = import_from_folder(rows, args.from_folder, RAW_DIR)
        for r in results:
            show(r)
    else:
        with make_client(settings) as client:
            results = download_all(rows, client, RAW_DIR, settings, force=args.force, progress=show)
    print(summarize(results))
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
