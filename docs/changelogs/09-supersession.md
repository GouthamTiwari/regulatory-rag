# Task 09: Supersession extraction
Branch: task/09-supersession | Date: 2026-11-16

## What changed
- `src/regrag/ingest/supersession.py`:
  - **API:** `extract_relations(doc_id, chunks, reference_no="") -> list[Relation]`, plus `normalise_ref()`, `find_refs()` and `sentences()`.
  - **Calibrated on the real corpus first.** A survey of all 2,265 chunks showed the naive keywords are mostly false alarms: "amended" (134 hits, almost all "as amended from time to time") and "repeal" (108, mostly "Notwithstanding such repeal…" boilerplate). So the patterns only accept **operative** forms:
    - *supersedes*: "in supersession of", "supersede(s)", "stand(s)/is/are … superseded/repealed", "hereby repeals";
    - *withdraws*: "… withdrawn", "withdrawn ab initio", "rescinded";
    - *amends*: "in partial modification of", "… modified/amended/substituted", "amended as under", "amendment to (the) circular/direction";
    - *corrects*: "corrigendum";
    - *clarifies*: "in furtherance of/to".
  - **Rejected:** known boilerplate, and a negation word just before the phrase ("does not supersede").
  - **References recognised:**
    - GST circulars (`195/07/2023-GST`, with spacing, dash and zero-padding variants);
    - RBI references (`RBI/2025-26/79`, `RBI/FIDD/2020-21/72`);
    - department references (`DPSS.CO.PD.No.1810/02.14.008 /2019-20`).
  - `normalise_ref` gives each one a single spelling.
  - **History is not a target:** references after "vide …", "as amended by …" or "modified vide Para N of …" record history, not the target.
  - **Self-references** are skipped, except in a corrigendum, whose named circular *is* its target.
  - **Earliest phrase wins:** when a sentence has several phrases, the first one decides the relation.
  - **Generic repeals:** "the existing Directions … stand repealed" with no number becomes a *supersedes* link to the generic target `earlier instructions (not named; see evidence)`. This is SPEC 3.4's RBI case.
  - **Repeal and consolidation tables:** tables titled "List of circulars repealed…" or "…consolidated" turn every listed reference into a *supersedes* link, with the table row as evidence.
  - **Every relation** keeps its sentence (up to 500 characters) as evidence, with `source="extracted"` and `reviewed=False`. Relations are de-duplicated per document.
  - **Sentence splitting** doesn't break after "No.", "Rs.", "i.e." and similar abbreviations.
- `tests/ingest/test_supersession.py`: tests (see below).

## How to verify
- `uv run pytest tests/ingest/test_supersession.py` → 38 passed
- Whole corpus (manual check): **61 relations** (54 supersedes, 5 amends, 1 corrects, 1 clarifies). 33 come from repeal/consolidation tables in 6 RBI directions, and 15 are the generic "existing directions stand repealed" links of the 2025–26 RBI directions.
- **Recovers 5 of the 7** hand-curated links in `data/relations.csv`. The two not recovered are by design:
  - `rbi-12799 → rbi-11959`: 12799 names the 2020 direction by *title*, so it is recorded as a generic link;
  - `225 → 204`: 225 only *describes* 204 ("was also issued … to provide clarity"), with no operative phrase.
- Spot-checked against the source text: 227 *supersedes* 60/34/2018-GST ("in supersession of"), 197 *amends* 125/44/2019 and 139/09/2020 ("stands modified").

## Tests
- 38 tests:
  - 14 positive sentences covering all five relation types, including two targets in one sentence;
  - 8 negative sentences: negations, a bare mention, and the 4 boilerplate forms found in the corpus;
  - self-reference ignored; "vide" reference ignored but a generic repeal recorded;
  - repeal-list table extraction; an ordinary table ignored; evidence, flags and de-duplication;
  - 5 GST spelling variants plus RBI and department normalisation; `find_refs` order and de-duplication; the sentence splitter;
  - 3 regressions from the corpus run: the corrigendum target, "(as amended by …)" history, and "earlier modified vide Para 5 of …".
- Full suite: 188 passed (+ 9 db), 0 failed.

## Out of scope / follow-ups
- Resolving `to_doc_ref` to `to_doc_id` (when the target is in our corpus) is Task 13.
- Extracted relations never change a document's status (SPEC 3.4). Task 14 prints them for Goutham to review before anything is appended to `relations.csv`.
- References by *title* ("the Reserve Bank of India (Priority Sector Lending …) Directions, 2020") aren't matched to documents. The manual file covers the one case in v1.

## Review log
- Self-review: passed. All 3 acceptance criteria met. The corpus run found 3 real bugs, all fixed with regression tests: the corrigendum was treated as a self-reference, "as amended by / vide Para N of" history was taken as a target, and a later "corrigendum" in a quote overrode "is substituted".
