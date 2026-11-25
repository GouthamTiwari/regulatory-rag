# Task 33: Bare GST law: CGST Act, CGST Rules, IGST Act
Branch: task/33-statute-ingest | Date: 2026-11-25

## What changed
- `src/regrag/ingest/statute.py` (new): the bare law from the CBIC tax portal.
  - **Section list:** read from the portal's own public JSON endpoints, the ones its pages use: `findByActId/1000006` (CGST Act), `findSectionByRuleId/1000006` (CGST Rules), `findByActId/1000015` (IGST Act). Only active sections are kept; headers and chapter introductions are skipped.
  - **Fetching:** each section page once, with the usual 2-second delay and retries. Saved as `data/raw/<doc_id>.json` (gitignored), holding each section's number, title, official URL and plain text. The file's sha256 is the document hash, so unchanged law is never re-embedded.
  - **HTML to text:** one paragraph per clause; a lone marker such as `(1)` joins its text; spaced markers `( 1 )` become `(1)`.
  - **Parsing:** one page per section (the "page" is the section's position, not a printed page).
  - **Chunking:** section-aware, following the law's own numbering. Sub-sections `(2)` and clauses `(aa)` become citable labels (`16(2)(aa)`). Roman items inside a lettered clause stay with it; a roman list at the top level (IGST s.20) is a list of clauses itself; clause `(i)` after `(h)` is a letter, not a numeral. The section heading joins the first clause. Short clauses merge within a sub-section; long ones split with overlap. Amendment footnotes are a separate chunk per section.
  - **Labels:** `section_no` is the first provision in the chunk; `section_path` lists every provision it covers (`CGST Act > s.16 Eligibility... > 16(2)(a), 16(2)(aa)`), which the full-text index also sees.
  - **TLS:** certificates are verified against the operating system's trust store (`truststore`). The portal's chain is incomplete for Python's bundled list, which is the TLS error noted in SPEC section 2.4. Verification is never turned off.
- `src/regrag/db/connection.py`: TCP keepalives. The first live run lost its connection while it embedded the CGST Act for 20 minutes: Docker Desktop's port forwarding drops idle connections, and the PC may have slept. Nothing was stored, because each document is one transaction.
- `src/regrag/db/repository.py`: `stored_embeddings()`, which returns a document's stored vectors keyed by (section path, content), only while its title and embedding model are unchanged.
- `src/regrag/ingest/pipeline.py`:
  - **Reconnect before writing** if the connection died during a long embedding.
  - **Vector reuse:** a chunk whose embedded text (title + section path + content) is unchanged keeps its stored vector, so a re-ingest pays only for changed chunks.
  - **`--force`:** re-chunks and stores a document whose source file is unchanged (after a chunker fix).
- `src/regrag/ingest/pipeline.py`: law documents (`doc_type` `act` or `rules`) read their saved JSON instead of a PDF, fetch it if missing (with their own trust-store client), and skip relation extraction (amendments live in the law text). Everything after that is unchanged: embed, store, skip-if-unchanged.
- `data/manifest.csv`: three rows: `gst-cgst-act-2017`, `gst-cgst-rules-2017`, `gst-igst-act-2017`. Each has an official source URL, the portal's section-list endpoint as `pdf_url`, the enactment or notification date, and "updated as on" 2026-11-25.
- `pyproject.toml`, `uv.lock`: `truststore`.
- `tests/ingest/test_manifest.py`: the GST count is now 43 (40 circulars plus 3 statutes).
- `docs/SPEC.md` (decision 9), `docs/TASKS.md` (tasks 33 to 36).

## Found by the live check (fixed before merging)
- **Rule 36(4) had no chunk of its own.** The portal writes an amendment marker with a space (`3 [(4)`), which the marker pattern did not allow, so the current r.36(4) text was glued onto 36(3)(b).
- **Quoted old wording was read as law.** Amendment notes quote the earlier text of a provision ('Substituted ... for "(4) ... shall not exceed 5 per cent"'), and the splitter turned that quote back into a clause. Now every paragraph after the first amendment note belongs to the notes.
- **Repealed wording presented as current.** After that fix, one answer still quoted the old 5% limit from the notes chunk as if it were in force. Note chunks are now cited as "36 (amendment history)" and their text says "HISTORY ONLY: any wording quoted below is earlier text, NOT in force". The same question then described the 20/10/5% limits as history.
- Final numbers: 2,501 chunks (CGST Act 1,171; CGST Rules 1,172; IGST Act 158). Embedding cost over all runs: $0.0096 (first full run), plus $0.0021 and $0.0018 for the two re-ingests with vector reuse (2,097 and 2,211 vectors reused), plus about $0.004 lost in the interrupted first attempt.

## Why not the consolidated Act and Rules
The portal's consolidated pages were last updated on 28 September 2022 (Act) and 26 December 2022 (Rules), so they miss later amendments, for example s.16(5) and (6) added in 2024. The per-section "active" pages are current.

## How to verify
- `uv run python -m regrag.ingest.statute` → fetches the three statutes (about 435 pages; skips any already saved).
- `uv run python -m regrag.ingest.pipeline --only gst-cgst-act-2017 --dry-run` → chunk count and embedding estimate, no AWS.
- Cross-check done on 2026-11-25: the fetched text of CGST Act s.16, s.38 and s.77 equals, word for word, the official snapshots saved by the agent-orchestrator project. s.34 differs by one token ("st", a superscript in a footnote date).

## Tests
- `tests/ingest/test_pipeline.py`: a dead connection is replaced before writing; unchanged chunks reuse stored vectors (only the changed chunk is embedded); `--force` re-ingests an unchanged file.
- `tests/ingest/test_statute.py` (22 new):
  - HTML to text: scripts dropped, lone markers joined, spaced markers tidied;
  - chunk labels and covers, the heading joining the first clause, amendment notes, the top-level roman list, letter-or-numeral cases;
  - long clauses split with overlap;
  - one page per section, and an empty file is an error;
  - fetching through a mock portal: only active sections, deterministic bytes, unofficial hosts refused;
  - the spaced amendment marker; quoted old wording kept inside the notes; note chunks labelled as history;
  - section links to each section's own page.
- Full suite: 410+ passed, no network, AWS or database needed.

## Out of scope / follow-ups
- Section-aware lookup for questions that name a provision: task 34.
- "sections 16 and 17" names only s.16 (the reference parser reads one number per keyword): task 34 notes.

## Review log
- Self-review: read the diff line by line. Secrets: none (the .env is untouched and no key appears in code or logs). `data/raw/` stays gitignored, and only the manifest rows are committed. Bedrock is mocked in every unit test. Found and fixed before merging: the two splitter bugs, the history label, the idle-connection loss, and pgvector's `Vector` type in `stored_embeddings` (converted to a list).
