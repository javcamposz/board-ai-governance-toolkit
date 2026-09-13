from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .register import Risk

LEVELS = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class Policy:
    """Thresholds an organization is willing to be held to between board meetings."""

    max_critical: int | None = None
    max_high: int | None = None
    max_overdue: int | None = None
    require_evidence_for: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_empty(self) -> bool:
        return not any((
            self.max_critical is not None,
            self.max_high is not None,
            self.max_overdue is not None,
            self.require_evidence_for,
        ))


@dataclass(frozen=True)
class Result:
    rule: str
    passed: bool
    detail: str
    subjects: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{'PASS' if self.passed else 'FAIL'}  {self.rule}: {self.detail}"


def _count_rule(rule: str, matched: list[Risk], limit: int, noun: str) -> Result:
    return Result(
        rule=rule,
        passed=len(matched) <= limit,
        detail=f"{len(matched)} {noun} (limit {limit})",
        subjects=tuple(f"{risk.id} {risk.system}" for risk in matched),
    )


def evaluate(risks: list[Risk], policy: Policy, as_of: date) -> list[Result]:
    """Test an active register against a policy. Closed risks are out of scope."""
    active = [risk for risk in risks if risk.is_active]
    results: list[Result] = []

    if policy.max_critical is not None:
        matched = [risk for risk in active if risk.level == "critical"]
        results.append(_count_rule("critical risks", matched, policy.max_critical, "critical"))

    if policy.max_high is not None:
        matched = [risk for risk in active if risk.level == "high"]
        results.append(_count_rule("high risks", matched, policy.max_high, "high"))

    if policy.max_overdue is not None:
        matched = sorted(
            (risk for risk in active if risk.next_review < as_of),
            key=lambda risk: (risk.next_review, risk.id),
        )
        results.append(Result(
            rule="overdue reviews",
            passed=len(matched) <= policy.max_overdue,
            detail=f"{len(matched)} overdue (limit {policy.max_overdue})",
            subjects=tuple(f"{risk.id} was due {risk.next_review.isoformat()} ({risk.owner})" for risk in matched),
        ))

    if policy.require_evidence_for:
        required = ", ".join(level for level in LEVELS if level in policy.require_evidence_for)
        matched = [risk for risk in active if risk.level in policy.require_evidence_for and not risk.is_evidenced]
        results.append(Result(
            rule="evidence",
            passed=not matched,
            detail=f"{len(matched)} {required} risks with no evidence recorded",
            subjects=tuple(f"{risk.id} {risk.system} ({risk.level}, assurance {risk.assurance})" for risk in matched),
        ))

    return results


def breached(results: list[Result]) -> list[Result]:
    return [result for result in results if not result.passed]
