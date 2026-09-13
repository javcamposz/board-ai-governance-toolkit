from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .register import Risk

LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
CONTROL_ORDER = {"weak": 0, "partial": 1, "strong": 2}
ASSURANCE_ORDER = {"asserted": 0, "tested": 1, "independent": 2}
TRACKED_FIELDS = (
    "system",
    "owner",
    "decision",
    "impact",
    "likelihood",
    "control_strength",
    "status",
    "next_review",
    "assurance",
    "evidence",
    "date_opened",
)


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: str
    after: str

    def __str__(self) -> str:
        return f"{self.field.replace('_', ' ')}: {self.before} to {self.after}"


@dataclass(frozen=True)
class RiskChange:
    before: Risk
    after: Risk
    fields: tuple[FieldChange, ...]

    @property
    def id(self) -> str:
        return self.after.id

    @property
    def level_direction(self) -> str:
        moved = LEVEL_ORDER[self.after.level] - LEVEL_ORDER[self.before.level]
        if moved > 0:
            return "escalated"
        if moved < 0:
            return "de-escalated"
        return "unchanged"

    @property
    def control_direction(self) -> str:
        moved = CONTROL_ORDER[self.after.control_strength] - CONTROL_ORDER[self.before.control_strength]
        if moved > 0:
            return "strengthened"
        if moved < 0:
            return "weakened"
        return "unchanged"

    @property
    def assurance_direction(self) -> str:
        """Movement in assurance actually credited, not merely claimed."""
        moved = ASSURANCE_ORDER[self.after.effective_assurance] - ASSURANCE_ORDER[self.before.effective_assurance]
        if moved > 0:
            return "strengthened"
        if moved < 0:
            return "weakened"
        return "unchanged"

    @property
    def lost_evidence(self) -> bool:
        return self.before.is_evidenced and not self.after.is_evidenced

    @property
    def slip_days(self) -> int:
        """Days the next review moved later; negative when it was pulled forward."""
        return (self.after.next_review - self.before.next_review).days

    def was_due(self, as_of: date) -> bool:
        """True when the review being moved had already fallen due."""
        return self.before.next_review < as_of


@dataclass(frozen=True)
class RegisterDiff:
    as_of: date
    added: tuple[Risk, ...]
    dropped: tuple[Risk, ...]
    retired: tuple[Risk, ...]
    closed: tuple[RiskChange, ...]
    reopened: tuple[RiskChange, ...]
    changed: tuple[RiskChange, ...]
    unchanged: tuple[Risk, ...]

    @property
    def escalated(self) -> tuple[RiskChange, ...]:
        return tuple(change for change in self.changed if change.level_direction == "escalated")

    @property
    def de_escalated(self) -> tuple[RiskChange, ...]:
        return tuple(change for change in self.changed if change.level_direction == "de-escalated")

    @property
    def slipped(self) -> tuple[RiskChange, ...]:
        moved = [change for change in self.changed + self.reopened if change.slip_days > 0]
        return tuple(sorted(moved, key=lambda change: (-change.slip_days, change.id)))

    @property
    def owner_changes(self) -> tuple[RiskChange, ...]:
        return tuple(change for change in self.changed + self.reopened if change.before.owner != change.after.owner)

    @property
    def weakened_controls(self) -> tuple[RiskChange, ...]:
        return tuple(change for change in self.changed if change.control_direction == "weakened")

    @property
    def weakened_assurance(self) -> tuple[RiskChange, ...]:
        return tuple(
            change for change in self.changed + self.reopened
            if change.assurance_direction == "weakened" or change.lost_evidence
        )


def _field_value(risk: Risk, field: str) -> str:
    value = getattr(risk, field)
    if value is None:
        return "not recorded"
    return value.isoformat() if isinstance(value, date) else str(value)


def _field_changes(before: Risk, after: Risk) -> tuple[FieldChange, ...]:
    return tuple(
        FieldChange(field, _field_value(before, field), _field_value(after, field))
        for field in TRACKED_FIELDS
        if _field_value(before, field) != _field_value(after, field)
    )


def diff_registers(previous: list[Risk], current: list[Risk], as_of: date) -> RegisterDiff:
    """Compare two snapshots of the same register, keyed on risk id."""
    before_by_id = {risk.id: risk for risk in previous}
    after_by_id = {risk.id: risk for risk in current}

    added = tuple(risk for risk in current if risk.id not in before_by_id)
    gone = [risk for risk in previous if risk.id not in after_by_id]
    dropped = tuple(risk for risk in gone if risk.is_active)
    retired = tuple(risk for risk in gone if not risk.is_active)

    closed: list[RiskChange] = []
    reopened: list[RiskChange] = []
    changed: list[RiskChange] = []
    unchanged: list[Risk] = []

    for risk in current:
        before = before_by_id.get(risk.id)
        if before is None:
            continue
        fields = _field_changes(before, risk)
        if not fields:
            unchanged.append(risk)
            continue
        change = RiskChange(before=before, after=risk, fields=fields)
        if before.is_active and not risk.is_active:
            closed.append(change)
        elif not before.is_active and risk.is_active:
            reopened.append(change)
        else:
            changed.append(change)

    return RegisterDiff(
        as_of=as_of,
        added=added,
        dropped=dropped,
        retired=retired,
        closed=tuple(closed),
        reopened=tuple(reopened),
        changed=tuple(changed),
        unchanged=tuple(unchanged),
    )


def _describe(change: RiskChange) -> str:
    return "; ".join(str(field) for field in change.fields)


def render_diff(diff: RegisterDiff) -> str:
    """Render the change report a board reads alongside the dashboard."""
    as_of = diff.as_of
    lines = [
        "# Board AI Risk Register Change Report",
        "",
        f"**As of:** {as_of.isoformat()}",
        "",
        "## What Changed",
        "",
        f"- New risks: {len(diff.added)}",
        f"- Escalated: {len(diff.escalated)}",
        f"- De-escalated: {len(diff.de_escalated)}",
        f"- Closed: {len(diff.closed)}",
        f"- Reopened: {len(diff.reopened)}",
        f"- Removed while still active: {len(diff.dropped)}",
        f"- Reviews moved later: {len(diff.slipped)}",
        f"- Assurance weakened or evidence withdrawn: {len(diff.weakened_assurance)}",
        f"- Accountable owner changed: {len(diff.owner_changes)}",
        f"- Unchanged: {len(diff.unchanged)}",
        "",
        "## Requires Explanation",
        "",
    ]

    challenges: list[str] = []
    for risk in diff.dropped:
        challenges.append(
            f"- **{risk.id} / {risk.system}** left the register while still {risk.status}. "
            f"Ask {risk.owner} who decided to remove it and on what evidence."
        )
    for change in diff.escalated:
        challenges.append(
            f"- **{change.id} / {change.after.system}** escalated from {change.before.level} to "
            f"{change.after.level} ({change.before.score:.1f} to {change.after.score:.1f}). "
            f"Accountable owner: {change.after.owner}."
        )
    for change in diff.weakened_controls:
        challenges.append(
            f"- **{change.id} / {change.after.system}** control strength fell from "
            f"{change.before.control_strength} to {change.after.control_strength}."
        )
    for change in diff.weakened_assurance:
        if change.lost_evidence:
            challenges.append(
                f"- **{change.id} / {change.after.system}** no longer records evidence for its control "
                f"rating; {change.before.evidence} was removed."
            )
        else:
            challenges.append(
                f"- **{change.id} / {change.after.system}** assurance fell from "
                f"{change.before.effective_assurance} to {change.after.effective_assurance}."
            )
    for change in diff.slipped:
        if change.was_due(as_of):
            challenges.append(
                f"- **{change.id} / {change.after.system}** was already due on "
                f"{change.before.next_review.isoformat()} when the review moved "
                f"{change.slip_days} days to {change.after.next_review.isoformat()}."
            )
    for change in diff.owner_changes:
        challenges.append(
            f"- **{change.id} / {change.after.system}** changed accountable owner from "
            f"{change.before.owner} to {change.after.owner}. Confirm the handover included open conditions."
        )
    for change in diff.reopened:
        challenges.append(
            f"- **{change.id} / {change.after.system}** was closed and is active again as {change.after.status}."
        )
    lines.extend(challenges or [
        "- Nothing in this comparison requires explanation; challenge whether the register is current."
    ])

    lines.extend(["", "## Movement", ""])
    movement = sorted(
        diff.changed + diff.closed + diff.reopened,
        key=lambda change: (-abs(change.after.score - change.before.score), change.id),
    )
    if movement:
        lines.append("| ID | System | Level | Score | Change |")
        lines.append("|---|---|---|---:|---|")
        for change in movement:
            if change.level_direction == "unchanged":
                level = change.after.level.title()
            else:
                level = f"{change.before.level.title()} to {change.after.level.title()}"
            lines.append(
                f"| {change.id} | {change.after.system} | {level} | "
                f"{change.before.score:.1f} to {change.after.score:.1f} | {_describe(change)} |"
            )
    else:
        lines.append("- No risk carried across both snapshots changed.")

    lines.extend(["", "## Review Dates Moved", ""])
    if diff.slipped:
        lines.append("| ID | Was due | Now due | Days later | Already due when moved |")
        lines.append("|---|---|---|---:|---|")
        for change in diff.slipped:
            lines.append(
                f"| {change.id} | {change.before.next_review.isoformat()} | "
                f"{change.after.next_review.isoformat()} | {change.slip_days} | "
                f"{'Yes' if change.was_due(as_of) else 'No'} |"
            )
    else:
        lines.append("- No review date moved later.")

    lines.extend(["", "## New Risks", ""])
    if diff.added:
        for risk in sorted(diff.added, key=lambda item: (-item.score, item.id)):
            lines.append(
                f"- **{risk.id} / {risk.system}** ({risk.level}, score {risk.score:.1f}, {risk.status}). "
                f"Owner: {risk.owner}. Next review {risk.next_review.isoformat()}."
            )
    else:
        lines.append("- None. A register that never gains a risk is rarely complete.")

    lines.extend(["", "## Closed And Removed", ""])
    if diff.closed or diff.retired:
        for change in diff.closed:
            lines.append(f"- **{change.id} / {change.after.system}** closed by {change.after.owner}.")
        for risk in diff.retired:
            lines.append(f"- **{risk.id} / {risk.system}** was already closed and has left the register.")
    else:
        lines.append("- None.")

    lines.extend([
        "",
        "## Board Challenge",
        "",
        "Ask management to account for every escalation, every review date that moved, and every risk that "
        "left the register without being closed. Movement without evidence is not progress.",
        "",
    ])
    return "\n".join(lines)
