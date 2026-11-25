# Task 35: Newer GST documents
Branch: task/35-newer-docs | Date: 2026-11-26

## What changed
- `data/manifest.csv`: 20 new GST documents.
  - **16 CGST circulars after 250/07/2025**, from 251/08/2025-GST (12 Sep 2025) to 266/12/2026-GST (28 Oct 2026), taken from the CBIC tax portal's own circular list (`/api/cbic-circular-msts/fetchAllCircularsByTaxId/1000001`), which is more current than the GST Council page used for v1. The PDF links are the portal's `content/pdf/...` addresses.
  - **4 GSTN advisories** from the official help site:
    - the revised IMS advisory (3 Sep 2024);
    - the GSTR-2B advisory (12 Oct 2021);
    - the GSTR-2B "Advisory tab" note (22 Apr 2024);
    - the Bill of Entry in IMS advisory (30 Oct 2025).

    These dates come from the PDFs' creation dates and file names where none is printed. Their `source_url` is the PDF itself.
  - **Circular 212/06/2024-GST is now `withdrawn`.**
- `data/relations.csv`, both from the circulars' official subjects:
  - 253/10/2025 *withdraws* 212/06/2024;
  - 262/08/2026 *clarifies* 231/25/2024.
- `src/regrag/config.py`: `tutorial.gst.gov.in` (GSTN's official help site) added to the allowed download hosts.
- `src/regrag/ingest/download.py`:
  - **JSON-wrapped PDFs:** the CBIC portal serves PDFs as `{"data": "<base64>"}`, the same response its own viewer reads. The downloader unwraps that, and the "must start with %PDF" check still decides.
  - **TLS:** certificates are verified against the operating system's trust store (`truststore`), as for the statutes in task 33. Verification stays on.
- `tests/ingest/test_manifest.py`: the GST count is now 63.

## How to verify
- `uv run python -m regrag.ingest.manifest --check` → 88 documents (gst 63, rbi 25), 1 withdrawn, 9 relations.
- Live (about $0.0025 each):
  - "Under the Invoice Management System, what happens to an invoice on which the recipient takes no action?" → deemed accepted at GSTR-2B generation, citing the revised IMS advisory.
  - "Does the section 17(4) restriction on input tax credit apply to non-banking financial companies?" → CGST Act 17(4) and Circular 261/07/2026.
  - "Is Circular No. 212/06/2024-GST still in force?" → withdrawn by 253/10/2025, with the automatic supersession note.

## Ingest
- 21 documents (20 new, plus 212 for its status), 255 chunks, 42 tables, $0.0017.
- 7 scanned pages were skipped (OCR is a non-goal): circular 260 pages 11–12, circular 262 page 4, and **circular 266 pages 2–5**. Circular 266 is therefore only partly searchable; this is noted as a known limitation.

## Tests
- `tests/ingest/test_download.py` (4 new): the portal's JSON wrapper is unwrapped and hashed as the PDF; an error JSON and a wrapper around non-PDF bytes are refused; `tutorial.gst.gov.in` is an official host and a look-alike is not.

## Out of scope / follow-ups
- OCR for scanned pages (circular 266) remains a non-goal.
- GST notifications (rates, due dates) are still not in the corpus; questions about them should be refused.

## Review log
- Self-review: read the diff line by line. No secrets. `data/raw/` is not committed. The manifest diff is exactly 20 new rows, 212's status and 4 advisory source URLs. Bedrock is mocked in unit tests.
