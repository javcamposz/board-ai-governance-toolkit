from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .register import read_register, render_dashboard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a board AI risk dashboard")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("summarize", help="validate a CSV register and render Markdown")
    command.add_argument("input", type=Path)
    command.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    command.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    risks = read_register(args.input)
    report = render_dashboard(risks, args.as_of)
    elevated = sum(risk.status != "closed" and risk.level in {"high", "critical"} for risk in risks)
    overdue = sum(risk.status != "closed" and risk.next_review < args.as_of for risk in risks)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)
    print(f"Validated {len(risks)} AI risks")
    print(f"High or critical open risks: {elevated}")
    print(f"Overdue reviews: {overdue}")
    if args.output:
        print(f"Dashboard written to {args.output}")
    return 0
