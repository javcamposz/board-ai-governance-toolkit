from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .diff import diff_registers, render_diff
from .policy import LEVELS, Policy, breached, evaluate
from .register import Portfolio, RegisterError, read_register, render_dashboard

EXIT_OK = 0
EXIT_POLICY_BREACH = 1
EXIT_INPUT_ERROR = 2


def _emit(report: str, output: Path | None) -> None:
    if output:
        output.write_text(report, encoding="utf-8")
    else:
        print(report)


def _summarize(args: argparse.Namespace) -> int:
    risks = read_register(args.input)
    _emit(render_dashboard(risks, args.as_of), args.output)
    portfolio = Portfolio(as_of=args.as_of, risks=tuple(risks))

    print(f"Validated {len(risks)} AI risks")
    print(f"High or critical open risks: {len(portfolio.elevated)}")
    print(f"Overdue reviews: {len(portfolio.overdue)}")
    print(f"Controls with no evidence recorded: {len(portfolio.unevidenced)}")
    if portfolio.undated:
        print(f"Active risks with no opening date: {len(portfolio.undated)}")
    print(f"Decisions outstanding: {len(portfolio.undecided)}"
          + (f", {len(portfolio.decisions_overdue)} past their due date"
             if portfolio.decisions_overdue else ""))
    if args.output:
        print(f"Dashboard written to {args.output}")
    return EXIT_OK


def _levels(value: str) -> frozenset[str]:
    chosen = {level.strip().lower() for level in value.split(",") if level.strip()}
    if not chosen:
        raise argparse.ArgumentTypeError(f"no levels given; choose from {', '.join(LEVELS)}")
    unknown = sorted(chosen - set(LEVELS))
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown level(s): {', '.join(unknown)}; choose from {', '.join(LEVELS)}")
    return frozenset(chosen)


def _check(args: argparse.Namespace) -> int:
    risks = read_register(args.input)
    policy = Policy(
        max_critical=args.max_critical,
        max_high=args.max_high,
        max_overdue=args.max_overdue,
        max_open_days=args.max_open_days,
        max_undecided_days=args.max_undecided_days,
        max_overdue_decisions=args.max_overdue_decisions,
        require_evidence_for=args.require_evidence_for or frozenset(),
    )
    results = evaluate(risks, policy, args.as_of)

    print(f"Validated {len(risks)} AI risks as of {args.as_of.isoformat()}")
    if policy.is_empty:
        print("No thresholds were set, so nothing was tested. Pass --max-critical, --max-high, "
              "--max-overdue, --max-open-days, --max-undecided-days, "
              "--max-overdue-decisions, or --require-evidence-for to enforce a policy.")
        return EXIT_OK

    for result in results:
        print(result)
        if not result.passed:
            for subject in result.subjects:
                print(f"        {subject}")

    failures = breached(results)
    if failures:
        print(f"{len(failures)} of {len(results)} rules breached")
        return EXIT_POLICY_BREACH
    print(f"All {len(results)} rules satisfied")
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

    check = subparsers.add_parser("check", help="test a register against governance thresholds")
    check.add_argument("input", type=Path)
    check.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    check.add_argument("--max-critical", type=int, help="maximum active critical risks")
    check.add_argument("--max-high", type=int, help="maximum active high risks")
    check.add_argument("--max-overdue", type=int, help="maximum active risks past their review date")
    check.add_argument("--max-open-days", type=int, help="maximum days an active risk may have been open")
    check.add_argument(
        "--max-undecided-days",
        type=int,
        help="maximum days a decision may remain outstanding on an active risk",
    )
    check.add_argument(
        "--max-overdue-decisions",
        type=int,
        help="maximum active decisions past the date they were required by",
    )
    check.add_argument(
        "--require-evidence-for",
        type=_levels,
        metavar="LEVELS",
        help="comma-separated levels that must record evidence, for example high,critical",
    )
    check.set_defaults(handler=_check)

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
