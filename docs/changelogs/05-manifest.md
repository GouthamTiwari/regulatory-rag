# Task 05: Manifest and relations files
Branch: task/05-manifest | Date: 2026-11-16

## What changed
- `data/manifest.csv`: **65 documents (25 RBI, 40 GST)**. Every value was copied from an official page on 2026-11-16; nothing was typed from memory.
  - **RBI:** each `https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=<ID>` page was downloaded (2 s apart). The exact title, reference number (e.g. `RBI/DOR/2025-26/169`), issue date, "Updated as on" date and the PDF link on `rbidocs.rbi.org.in` were parsed from it. The "(Updated as on …)" suffix is stored in `updated_as_on`, not in the title.
  - **GST:** the six list pages of `https://gstcouncil.gov.in/cgst-circulars` were parsed for each circular's number, date and official subject line. All 40 picks matched the list by PDF path. All 40 dates matched SPEC section 3.3. **All 40 PDF links were checked:** each returned HTTP 200 and a body starting with `%PDF`.
  - The title is `Circular No. <number>: <official subject>`. The list page shows a typo ("239/33/2024--GST"); the clean number is used.
  - `doc_id`: `rbi-<page id>`, `gst-<no>-<serial>-<year>`, and `gst-237-31-2024-corr` for the corrigendum.
  - `status`: `superseded` for `rbi-11959` (2020 PSL Directions), all others `active`. `sha256` is left empty for Task 14.
- `data/relations.csv`: **7 hand-curated links**, each with evidence quoted from an official page or PDF:
  - `rbi-12799` supersedes `rbi-11959`: the RBI page for 11959 says "[superseded by … PSL … Directions, 2025]".
  - `gst-216-10-2024` clarifies `gst-195-07-2023`: the official subject says "in furtherance to Circular No. 195/07/2023-GST". Recorded as *clarifies*, not *amends* as SPEC 3.4 suggested, because the wording only supports that.
  - `gst-225-19-2024` clarifies `gst-204-16-2023`: quoted from para 1 of the PDF.
  - `gst-239-33-2024` amends `31/05/2018-GST` (not in the corpus): from the official subject.
  - `gst-249-06-2025` amends **both** `122/41/2019-GST` and `128/47/2019-GST` (not in the corpus), "to the above extent", only for portal communications that carry an RFN. Quoted from para 6. SPEC 3.4 named only one earlier DIN circular; the PDF shows two.
  - `gst-237-31-2024-corr` corrects `gst-237-31-2024`.
- `src/regrag/ingest/manifest.py`:
  - `load_manifest()` checks required columns, the `doc_id` format and its corpus prefix, unique IDs, corpus and status values, ISO dates (`updated_as_on` not before `publish_date`), the sha256 format, and **https URLs on an official host or its subdomain** (look-alikes such as `rbi.org.in.evil.example` are rejected).
  - It reports all problems at once, with CSV line numbers. `to_verify` rows are skipped with a warning.
  - `load_relations()` checks relation types and that evidence is non-empty, and that doc IDs exist in the manifest when given. Manual links load as `source="manual"`, `reviewed=True`.
  - The CSV reader tolerates an Excel BOM. `python -m regrag.ingest.manifest --check` prints the counts.
- `tests/ingest/test_manifest.py`: tests (see below).

## How to verify
- `uv run python -m regrag.ingest.manifest --check` → `Documents: 65 by corpus: {'gst': 40, 'rbi': 25} by status: {'active': 64, 'superseded': 1, 'withdrawn': 0}`, `Skipped (to_verify): 0 Relations: 7`, exit 0
- `uv run pytest tests/ingest/test_manifest.py` → 32 passed

## Tests
- 32 tests: host check (8 cases including http and look-alike hosts); valid row; non-official host; duplicate `doc_id`; `to_verify` skipped with a warning; 8 bad-value cases; all problems reported together with line numbers; missing column; Excel BOM; relations (valid, target outside the corpus, 4 bad cases); the committed files themselves (25 + 40 documents, PSL supersession present); the `--check` command.
- Full suite: 97 passed (db: 9 passed), 0 failed.

## Out of scope / follow-ups
- No row is `to_verify`: every URL was confirmed.
- GST circulars 251 and above remain out of v1 (SPEC decision 2).
- The scraping scripts were one-off helpers kept outside the repo. Re-running them is not needed, because the manifest *is* the record and its URLs are re-checked by the downloader (Task 06).
- RBI's new Directions repeal older instructions through a separate repeal circular (SPEC 3.4). Those links come from text extraction (Task 09), not this file.

## Review log
- Self-review: passed. All 4 acceptance criteria met. Two spec statements were corrected from primary sources (216 → 195 is *clarifies*; 249 amends two circulars, not one).
