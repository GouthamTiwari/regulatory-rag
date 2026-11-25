# Task 34: Section-aware lookup
Branch: task/34-section-lookup | Date: 2026-11-26

## What changed
- `src/regrag/query/references.py` (new):
  - **`parse_references(question)`** finds the provisions a question names:
    - "rule 36(4)" and "r. 37A" → CGST Rules;
    - "section 16(2)(aa)", "s.16(4)" and "sec. 17(5)(d)" → CGST Act;
    - "IGST section 19" and "section 19 of the IGST Act" → IGST Act;
    - "Schedule II" → CGST Act.

    It also handles spaced markers like "( 3 )". A section of another Act ("section 35A of the Banking Regulation Act", "… of the Reserve Bank of India Act", "… of FEMA, 1999") is ignored, so RBI questions are never pinned to GST law.
  - **`lookup(conn, references)`** reads the matching statute chunks in the law's order, at most 3 per reference, and uses the amendment history only when nothing else matches. A chunk matches when it covers the provision or one of its parts: '16(2)' covers '16(2)(aa)', but not '16(20)'.
- `src/regrag/query/pipeline.py`: after reranking, the chunks of a named provision go first and count as the strongest evidence (rerank score 1.0), so the system does not refuse a question about a provision it holds. Never for RBI-routed questions. `Parts.reference_lookup` lets tests use a fake. Citations of statute chunks link to the section's own portal page.
- `src/regrag/query/prompts.py`, `src/regrag/ui/view.py`, `src/regrag/query/__main__.py`: a statute chunk is shown with its section (`36(4)`), not a "page", which for the bare law would only be a section's position.

## How to verify (live, about $0.003 per question)
- `uv run python -m regrag.query "What does rule 36(4) say?"` → cites CGST Rules 36(4) and 36(4)(b), quotes the current rule (no ITC unless the invoice is in GSTR-1/IFF and communicated in GSTR-2B), and describes the old 20/10/5% limits only as history.
- `"What is the time limit to take input tax credit under section 16(4)?"` → cites CGST Act 16(4) (and 16(5)), with circulars 211 and 237.
- `"If IGST was paid on a supply later held to be intra-State, can it be refunded under IGST section 19?"` → cites IGST Act 19(1), linked to `.../chapterviii/section19_v1.00.html`.
- `"What does section 16(2) of the CGST Act require before ITC can be taken?"` → cites 16(2), 16(2)(aa), 16(2)(b) and 16(2)(ba).

## Tests
- `tests/query/test_references.py` (23): the parser on twelve phrasings, other Acts ignored, labels, chunk matching (including '16(2)' not covering '16(20)').
- `tests/query/test_pipeline.py` (4 new):
  - a named provision is pinned first and stops a refusal that the weak search score alone would have caused;
  - no reference means no lookup;
  - RBI-routed questions are never pinned;
  - statute sources in the prompt show sections, not pages.

## Out of scope / follow-ups
- "sections 16 and 17" names only s.16 (one number per keyword).
- The plain question "Can I claim ITC on an invoice that does not appear in my GSTR-2B?" answers correctly from circulars 193 and 197, but does not cite r.36(4) itself. Ranking, not lookup: measured in task 36's evaluation.

## Review log
- Self-review: read the diff line by line. No secrets, no network in unit tests, Bedrock mocked. Found and fixed during review: the "Reserve Bank of India Act" guard (a lowercase "of" inside an Act's name); the CLI still printing "p. 17" for statute sections.
