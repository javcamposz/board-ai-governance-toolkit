from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from .register import Risk

LEVELS = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class DecisionRights:
    """Who may take a decision at each level of exposure.

    Declared outside the register, because a register that named its own acceptable
    deciders would name the ones who had already decided.
    """

    # A tuple of pairs rather than a dict, so frozen means what it says. The argument for
    # this type is that the rights come from outside the register; a mapping a caller can
    # still edit in place would not be that.
    levels: tuple[tuple[str, tuple[str, ...]], ...]

    @classmethod
    def from_mapping(cls, by_level: Mapping[str, Sequence[str]]) -> DecisionRights:
        return cls(tuple(
            (level, tuple(by_level[level])) for level in LEVELS if level in by_level
        ))

    @property
    def by_level(self) -> dict[str, tuple[str, ...]]:
        return dict(self.levels)

    def deciders(self, level: str) -> tuple[str, ...]:
        return self.by_level.get(level, ())

    def constrains(self, level: str) -> bool:
        return any(declared == level for declared, _ in self.levels)

    def permits(self, level: str, decided_by: str) -> bool:
        if not self.constrains(level):
            return True
        authorised = {name.strip().casefold() for name in self.deciders(level)}
        return decided_by.strip().casefold() in authorised


@dataclass(frozen=True)
class Policy:
    """Thresholds an organization is willing to be held to between board meetings."""

    max_critical: int | None = None
    max_high: int | None = None
    max_overdue: int | None = None
    max_open_days: int | None = None
    max_undecided_days: int | None = None
    max_overdue_decisions: int | None = None
    require_evidence_for: frozenset[str] = field(default_factory=frozenset)
    rights: DecisionRights | None = None

    @property
    def is_empty(self) -> bool:
        return not any((
            self.max_critical is not None,
            self.max_high is not None,
            self.max_overdue is not None,
            self.max_open_days is not None,
            self.max_undecided_days is not None,
            self.max_overdue_decisions is not None,
            self.require_evidence_for,
            self.rights is not None,
        ))


@dataclass(frozen=True)
class Result:
    rule: str
    passed: bool
    detail: str
    subjects: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{'PASS' if self.passed else 'FAIL'}  {self.rule}: {self.detail}"


def _rights_breach(risk: Risk, rights: DecisionRights) -> str:
    """Name who decided, at what level, and whether evidence alone would resolve it.

    The level read here is the assurance-adjusted one, so a risk can breach because its
    control rating is unevidenced rather than because the decider overstepped. Those are
    different remedies for different people, and the line has to say which applies.
    """
    line = (
        f"{risk.id} {risk.system} was decided by {risk.decided_by}, and is {risk.level}, "
        f"where the decision rests with {' or '.join(rights.deciders(risk.level))}."
    )
    if risk.level == risk.face_value_level:
        return line
    line += (
        f" It is {risk.level} only because the control rating is unevidenced; "
        f"evidenced it would be {risk.face_value_level}"
    )
    if rights.permits(risk.face_value_level, risk.decided_by):
        return line + ", where that decider is authorised."
    return line + ", which is still above that decider."


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
        testable = [risk for risk in active if risk.opened_for(as_of).is_measurable]
        matched = sorted(
            (risk for risk in testable if risk.age_days(as_of) > policy.max_open_days),
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

    if policy.max_undecided_days is not None:
        # A decision the board has been asked for across several cycles and not given is a
        # decision by default. Risks with no opening date cannot be timed, so they are named.
        # A risk the register dates after the reporting date has no meaningful wait, so it
        # is untestable rather than compliant, exactly as the age rule treats it.
        outstanding = [risk for risk in active if not risk.is_decided]
        timed = [risk for risk in outstanding if risk.undecided_for(as_of).is_measurable]
        matched = sorted(
            (risk for risk in timed if risk.days_undecided(as_of) > policy.max_undecided_days),
            key=lambda risk: (risk.date_opened, risk.id),
        )
        untimed = len(outstanding) - len(timed)
        noun = "decision" if len(matched) == 1 else "decisions"
        detail = f"{len(matched)} {noun} outstanding longer than {policy.max_undecided_days} days"
        if untimed:
            detail += f"; {untimed} undecided with no usable opening date and could not be timed"
        results.append(Result(
            rule="undecided",
            passed=not matched,
            detail=detail,
            subjects=tuple(
                f"{risk.id} {risk.system}: {risk.decision.rstrip('.')} "
                f"({risk.days_undecided(as_of)} days, owner {risk.owner})"
                for risk in matched
            ),
        ))

    if policy.max_overdue_decisions is not None:
        matched = sorted(
            (risk for risk in active if not risk.is_decided and risk.decision_overdue_days(as_of)),
            key=lambda risk: (risk.decision_due, risk.id),
        )
        results.append(Result(
            rule="overdue decisions",
            passed=len(matched) <= policy.max_overdue_decisions,
            detail=f"{len(matched)} past their due date (limit {policy.max_overdue_decisions})",
            subjects=tuple(
                f"{risk.id} {risk.system} was due {risk.decision_due.isoformat()}, "
                f"{risk.decision_overdue_days(as_of)} days ago ({risk.owner})"
                for risk in matched
            ),
        ))

    if policy.rights is not None:
        # A decision taken at one level does not carry to a higher one. Because the level
        # is read now rather than when the decision was taken, a risk that escalated past
        # the authority that approved it fails here from a single register.
        matched = [
            risk for risk in active
            if risk.is_decided and not policy.rights.permits(risk.level, risk.decided_by)
        ]
        seen = {
            risk.level for risk in active
            if risk.is_decided and not policy.rights.constrains(risk.level)
        }
        unconstrained = [level for level in LEVELS if level in seen]
        noun = "decision" if len(matched) == 1 else "decisions"
        detail = f"{len(matched)} {noun} taken without the authority the level requires"
        if unconstrained:
            detail += f"; no rights declared for {', '.join(unconstrained)}"
        results.append(Result(
            rule="decision rights",
            passed=not matched,
            detail=detail,
            subjects=tuple(
                _rights_breach(risk, policy.rights)
                for risk in sorted(matched, key=lambda item: (-item.score, item.id))
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
