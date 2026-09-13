from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .diff import diff_registers, render_diff
from .register import RegisterError, read_register, render_dashboard

EXIT_OK = 0
EXIT_INPUT_ERROR = 2


def _emit(report: str, output: Path | None) -> None:
    if output:
        output.write_text(report, encoding="utf-8")
    else:
        print(report)


def _summarize(args: argparse.Namespace) -> int:
    risks = read_register(args.input)
    _emit(render_dashboard(risks, args.as_of), args.output)
    active = [risk for risk in risks if risk.is_active]
    elevated = sum(risk.level in {"high", "critical"} for risk in active)
    overdue = sum(risk.next_review < args.as_of for risk in active)

    print(f"Validated {len(risks)} AI risks")
    print(f"High or critical open risks: {elevated}")
    print(f"Overdue reviews: {overdue}")
    if args.output:
        print(f"Dashboard written to {args.output}")
    return EXIT_OK


def _diff(args: argparse.Namespace) -> int:
    previous = read_register(args.previous)
    current = read_register(args.current)
    diff = diff_registers(previous, current, args.as_of)
    _emit(render_diff(diff), args.output)

    print(f"Compared {len(previous)} against {len(current)} AI risks")
    print(f"New: {len(diff.added)}  Escalated: {len(diff.escalated)}  Closed: {len(diff.closed)}")
    print(f"Reviews moved later: {len(diff.slipped)}")
    print(f"Removed while still active: {len(diff.dropped)}")
    if args.output:
        print(f"Change report written to {args.output}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate AI risk registers and report to the board")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize = subparsers.add_parser("summarize", help="validate a CSV register and render Markdown")
    summarize.add_argument("input", type=Path)
    summarize.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    summarize.add_argument("--output", type=Path)
    summarize.set_defaults(handler=_summarize)

    compare = subparsers.add_parser("diff", help="compare two register snapshots and report what changed")
    compare.add_argument("previous", type=Path, help="the earlier snapshot, for example last quarter")
    compare.add_argument("current", type=Path, help="the snapshot going to the board")
    compare.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    compare.add_argument("--output", type=Path)
    compare.set_defaults(handler=_diff)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except RegisterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
