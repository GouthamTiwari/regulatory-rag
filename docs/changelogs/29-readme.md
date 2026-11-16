# Task 29: README (v1)
Branch: task/29-readme | Date: 2026-11-16

## What changed
- `README.md`: the full README, replacing the Task 01 skeleton.
  - **What it is:** a pitch and a real CLI example (the PSL 2020 question answered from the 2025 directions, with the supersession note).
  - **Architecture:** a Mermaid diagram of the ingest and query flows.
  - **Evaluation results:** the sample 4-way table from Task 26, clearly labelled, with a short honest reading.
  - **Setup:** Windows PowerShell steps, including the RBI CAPTCHA step (`--list-missing`, `--from-folder`).
  - **Usage, design decisions, cost and project layout.**
  - **Design decisions covered:** Amazon models (AISPL Marketplace restriction), Mumbai + Tokyo, hybrid + RRF, Postgres for both searches, rerank via InvokeModel, precision-first supersession, the calibrated abstain threshold, pacing for small quotas, section-aware chunking.
  - **Known limitations and disclaimer.**

## How to verify
- Read the README on GitHub: the Mermaid block renders, and every command in Setup/Usage exists in the code.
- The numbers in the results table match `docs/eval/results.md`.
- No secret, account ID, employer name or personal detail appears: the only identity shown is the public GitHub path `GouthamTiwari/regulatory-rag`.

## Tests
- Docs only; the full suite is unchanged: 326 passed.

## Out of scope / follow-ups
- **v1, not final:** Task 28 replaces the sample table with the final run (≈60 reviewed questions, section-level gold, Nova Pro judge), and the README is updated then. A screenshot or GIF follows once the web UI exists.

## Review log
- Self-review: passed for v1. Each command was checked against the code, the numbers against `docs/eval/results.md`, and the file was checked for personal or secret data.
