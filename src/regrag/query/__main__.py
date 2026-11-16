"""Ask a question from the command line.

uv run python -m regrag.query "Can a car dealer claim ITC on demo vehicles?"
uv run python -m regrag.query "..." --config hybrid --json
"""

import argparse
import json
import logging
import sys

from regrag.query.pipeline import DISCLAIMER, answer_question
from regrag.types import CONFIG_NAMES, PipelineConfig


def render(result) -> str:
    lines = [result.answer, ""]
    if result.citations:
        lines.append("Sources:")
        for c in result.citations:
            pages = (
                f"p. {c.page_start}"
                if c.page_start == c.page_end
                else f"pp. {c.page_start}-{c.page_end}"
            )
            lines.append(
                f"  [{c.marker}] {c.title} | {c.section_no} | {pages}\n       {c.source_url}"
            )
        lines.append("")
    if result.supersession_notes:
        lines.append("Supersession notes:")
        lines += [f"  - {n}" for n in result.supersession_notes]
        lines.append("")
    lines.append(
        f"route={result.route}  config={result.config_name}  "
        f"time={result.latency_ms.get('total', 0) / 1000:.1f}s  cost=${result.cost_usd:.5f}"
    )
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask the RBI/GST regulatory assistant")
    parser.add_argument("question")
    parser.add_argument("--config", default="hybrid_rerank", choices=CONFIG_NAMES)
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--verbose", action="store_true", help="show the JSON log line")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, stream=sys.stderr)
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a narrower encoding
    result = answer_question(args.question, config=PipelineConfig(name=args.config))
    print(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) if args.json else render(result)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
