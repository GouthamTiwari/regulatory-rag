# Task 08: Section-aware chunker
Branch: task/08-chunker | Date: 2026-11-16

## What changed
- `src/regrag/ingest/chunk.py`:
  - `chunk_document(parsed, manifest_row, settings) -> list[Chunk]` and `embedding_text(chunk, title)`.
  - **Structure it recognises,** with patterns calibrated on the real parsed RBI and GST text:
    - top-level headings: `Chapter I – Preliminary`, `Part B`, `Annex II`, `Appendix`, `Schedule`;
    - titled sub-headings: `A. Short Title and Commencement.` (new RBI style), `1. Introduction` and `1.4 Purpose` (older Master Direction style);
    - numbered paragraphs: `16.`, `2.1`.
  - **Look-alikes deliberately rejected:**
    - `Chapter VI.` (a wrapped sentence ending);
    - `15 percent of …` (a whole number needs its dot to be a paragraph number);
    - footnotes such as `1 Earlier, …`.
  - **Headings in context:** `Part I` inside an active Chapter becomes a sub-heading, giving SPEC's example path `Chapter VI > … > Part I`.
  - **Sections:** a heading starts a new section, and chunks never cross a section, so they never mix chapters.
  - **Packing:** inside a section, whole paragraphs are packed up to 400 tokens (hard max 500). Consecutive chunks overlap by about 60 tokens; the overlap is dropped if it would push the next chunk over 500. A paragraph over 500 tokens is split into overlapping windows.
  - **Tables:** each table is its own chunk and is only split above 1,000 tokens, into row groups that each repeat the header rows.
  - **Labels:** `section_no` names the paragraphs that start in the chunk, e.g. `Chapter VI, para 23`, `Chapter I, paras 1–2`, `Paras 2–3` (no chapter), or `Preamble`. `section_path` is the heading trail. `page_start` / `page_end` come from the pages of the chunk's own words, so a paragraph running from page 2 to 3 gives 2–3.
  - **Tokens:** estimated as characters / 4. Scanned pages are skipped.
  - **Two fixes beyond the task text, found on the real corpus** (they halved tiny chunks, 104 → 52):
    1. A bare heading such as `Chapter IV` or `Annex-1` takes its title from the next short line (`KYC and Due Diligence`).
    2. A short text (under 40 tokens) right before a table, such as `Table 1: List of Circulars consolidated in the MD`, becomes the table's caption instead of a tiny chunk on its own. `Table N` lines are never treated as section titles.
  - `embedding_text()` puts the document title and section path in front of the chunk text.
- `tests/ingest/test_chunk.py`: tests (see below).

## How to verify
- `uv run pytest tests/ingest/test_chunk.py` → 21 passed
- Whole corpus (manual check): 65 documents → **2,265 chunks** (2,014 text, 251 table). Text chunks have a median of 302 tokens and a max of 499, none over 500. Table chunks max 849 tokens, none over 1,000. About 597K tokens including overlap. Example: `rbi-13141` → `Chapter VI, para 23`, path `Chapter VI – Customer Due Diligence (CDD) Procedure > A. CDD Procedure in case of Individuals`, page 25.

## Tests
- 21 tests on hand-built `ParsedDocument`s:
  - Task criteria: no chunk over the max; never mixes two chapters; a paragraph across pages 2–3 gives 2–3; adjacent chunks share 40–80 tokens; `chunk_index` is 0..n-1 and output is identical on a second run.
  - Sizing: labels and paths; a long paragraph becomes windows; a table is its own chunk in place; a table under 1,000 tokens is never split; a big table is split with its header repeated and every row exactly once.
  - Structure: 4 heading look-alikes; Part inside a Chapter; a GST-style circular; scanned pages skipped; a caption joins its table; a bare chapter takes its title from the next line.
  - Embedding text has the title and path in front.
- Full suite: 150 passed (+ 9 db), 0 failed.

## Out of scope / follow-ups
- GST circulars have no headings, so their first chunk is labelled `Preamble`. It includes the address block and the "Subject:" line, which is useful for keyword search but noisy for embeddings. Revisit if retrieval suffers (Task 28).
- A wrapped line that begins with a decimal number (e.g. `2.5 crore …`) would be read as paragraph 2.5. It's rare, and the only effect is a wrong paragraph label.
- Tables that continue across pages stay as one chunk per page.

## Review log
- Self-review: passed. All 5 acceptance criteria met. Two quality issues from the real corpus were fixed with tests (bare headings, table captions). A footnote look-alike caught by a test was fixed (heading numbers now need a dot).
