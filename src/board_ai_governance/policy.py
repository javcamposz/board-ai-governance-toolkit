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
    max_open_days: int | None = None
    require_evidence_for: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_empty(self) -> bool:
        return not any((
            self.max_critical is not None,
            self.max_high is not None,
            self.max_overdue is not None,
            self.max_open_days is not None,
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


def _level_note(risk: Risk) -> str:
    """Name both readings when they differ, so a match on the face-value level is not a surprise."""
    if risk.level != risk.face_value_level:
        return f"{risk.level}, {risk.face_value_level} at face value"
    return risk.level


def _assurance_note(risk: Risk) -> str:
    """Name the claim and the fact that it was not credited, never the claim alone."""
    if risk.is_unevidenced_claim:
        return f"{risk.assurance} claimed, credited as {risk.effective_assurance}"
    return risk.effective_assurance


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

    if policy.max_open_days is not None:
        # A risk dated after the reporting date has no meaningful age, so it is untestable
        # rather than compliant. Counting it as a pass would let a wrong date clear the gate.
        ages = {risk.id: risk.age_days(as_of) for risk in active}
        testable = [risk for risk in active if (ages[risk.id] or 0) >= 0 and risk.date_opened]
        matched = sorted(
            (risk for risk in testable if ages[risk.id] > policy.max_open_days),
            key=lambda risk: (risk.date_opened, risk.id),
        )
        untestable = len(active) - len(testable)
        noun = "risk" if len(matched) == 1 else "risks"
        detail = f"{len(matched)} {noun} open longer than {policy.max_open_days} days"
        if untestable:
            detail += (
                f"; {untestable} record no usable opening date and could not be tested"
            )
        results.append(Result(
            rule="risk age",
            passed=not matched,
            detail=detail,
            subjects=tuple(
                f"{risk.id} {risk.system} open {risk.age_days(as_of)} days since "
                f"{risk.date_opened.isoformat()}, still {risk.status}"
                for risk in matched
            ),
        ))

    if policy.require_evidence_for:
        required = ", ".join(level for level in LEVELS if level in policy.require_evidence_for)
        # Match on either reading of the level. A risk whose missing evidence pushed it past the
        # level under test must not escape the very rule that missing evidence should trigger.
        matched = [
            risk for risk in active
            if not risk.is_evidenced
            and (risk.level in policy.require_evidence_for or risk.face_value_level in policy.require_evidence_for)
        ]
        noun = "risk" if len(matched) == 1 else "risks"
        results.append(Result(
            rule="evidence",
            passed=not matched,
            detail=f"{len(matched)} {noun} at {required} with no evidence recorded",
            subjects=tuple(
                f"{risk.id} {risk.system} ({_level_note(risk)}, assurance {_assurance_note(risk)})"
                for risk in matched
            ),
        ))

    return results


def breached(results: list[Result]) -> list[Result]:
    return [result for result in results if not result.passed]
