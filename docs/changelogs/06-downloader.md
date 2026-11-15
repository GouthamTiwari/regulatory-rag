# Task 06: Downloader
Branch: task/06-downloader | Date: 2026-11-16

## What changed
- `src/regrag/ingest/download.py`:
  - **Fetching:** downloads each manifest PDF to `data/raw/<doc_id>.pdf` with `httpx`, using a generic User-Agent, TLS verification always on, a 60 s timeout, a 2 s pause between network requests and up to 3 retries with growing back-off. Only 429/5xx and network errors are retried; a 404 is not.
  - **Checks on every file:** the bytes must start with `%PDF` (the content-type header is not trusted), redirects must end on an official host, and the file must be under 50 MB.
  - **Safe writes:** files go to a `.part` name and are then renamed, so an interrupted run never leaves a half-written "PDF".
  - **Fingerprints:** a sha256 is computed for every file. An existing file is skipped when its hash matches the manifest, or when the manifest has no hash yet and the file is a valid PDF. A changed hash is reported (the regulator may have replaced the file).
  - **Keeps going:** one failure doesn't stop the run, and the exit code is 1 if any document failed. Flags: `--limit N`, `--only DOC_ID`, `--force`.
  - **Beyond the task text, needed by the real run:** RBI's PDF host (`rbidocs.rbi.org.in`) answers automated clients with a **CAPTCHA page** ("testing whether you are a human visitor"). The downloader now:
    - recognises such a page and reports "asked for a human check";
    - **stops requesting from that host for the rest of the run**. Why: repeating requests after a bot check is impolite and would look like an attempt to get through it. We never try to bypass a CAPTCHA;
    - `--list-missing` prints the PDFs still missing;
    - `--from-folder DIR` imports PDFs that a person saved in a browser, matched by the file name in `pdf_url` (case-insensitive), checked for `%PDF`, with no network use.
- `tests/ingest/test_download.py`: tests (see below).
- Not committed (gitignored): the 40 GST PDFs now in `data/raw/`.

## How to verify
- `uv run pytest tests/ingest/test_download.py` → 20 passed, no network
- `uv run python -m regrag.ingest.download` → 40 GST downloaded; the 25 RBI rows fail with "asked for a human check" (RBI requested once only), exit 1
- `uv run python -m regrag.ingest.download --list-missing` → `25 of 65 PDFs missing`
- `git status` → nothing under `data/raw/`

## Tests
- 20 tests, all using `httpx.MockTransport` with no sleeping:
  - success; retry then success; network error retried; giving up after all retries; 404 not retried;
  - HTML instead of a PDF; hash mismatch reported; existing file skipped (matching hash, or no hash yet); broken existing file downloaded again; `--force`;
  - redirect to a non-official host; non-official URL never requested; oversized file;
  - one failure doesn't stop the run and the polite delay is applied; `--only`/`--limit`;
  - CAPTCHA page reported; the host isn't asked again after a CAPTCHA; file name taken from the URL; importing from a folder (case-insensitive match, non-PDF rejected, missing reported, already-imported files skipped).
- Full suite: 117 passed (+ 9 db), 0 failed.

## Out of scope / follow-ups
- **Manual step for Goutham:** download the 25 RBI PDFs in a browser (checklist page at `C:\Users\gouth\Desktop\AI\rbi-pdf-downloads.html`), then run `uv run python -m regrag.ingest.download --from-folder C:\Users\gouth\Downloads`.
- The README (Task 29) must explain this manual step in the setup instructions.
- sha256 values are written into `data/manifest.csv` by Task 14, not here.

## Review log
- Self-review: passed. All 4 acceptance criteria met. The real run found the RBI CAPTCHA, which is handled honestly: detected, not retried, and imported by hand.
