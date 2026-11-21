# Task 32: One-click start
Branch: task/32-one-click-start | Date: 2026-11-21

## What changed
- `start.bat` (new): double-click launcher. Checks that `uv` is installed and `.env` exists, starts Docker Desktop if the engine is not running (checks every 5 s, up to 3 minutes), runs `docker compose up -d`, then starts the Streamlit page. Every failure prints a plain message and pauses so the window does not vanish.
- The page is bound to `127.0.0.1`, so only this computer can open it (every question spends AWS credits). Usage statistics are switched off for this run.
- `.gitattributes` (new): `*.bat` always gets CRLF line endings; batch files with LF endings can break `goto` labels.
- `README.md`: one-click instructions, desktop-shortcut tip, `start.bat` in the project layout.
- `docs/TASKS.md`: Task 32 entry.

## How to verify
- Double-click `start.bat` → browser opens http://localhost:8501.
- Checked 2026-11-21: ran it with `cmd /c start.bat`; the database started, `/_stcore/health` returned `ok`, and the listener was `127.0.0.1:8501` only.

## Tests
- No Python code changed. Full suite: 350 passed, 36 deselected. Ruff clean.

## Out of scope / follow-ups
- Windows only; macOS/Linux users run the two commands in README "Usage".
- Assumes Docker Desktop's default install path (`%ProgramFiles%\Docker\Docker`).

## Review log
- Self-review: read the full diff. Checked the labels sit outside parenthesised blocks (a common batch bug), errors pause instead of closing, and nothing secret is printed (`.env` is only checked for existence). Passed.
