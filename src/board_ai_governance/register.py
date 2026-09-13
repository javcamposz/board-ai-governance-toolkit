from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REQUIRED_FIELDS = (
    "id",
    "system",
    "owner",
    "decision",
    "impact",
    "likelihood",
    "control_strength",
    "status",
    "next_review",
)
IMPACT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
LIKELIHOOD = {"rare": 1, "possible": 2, "likely": 3, "almost_certain": 4}
CONTROL_FACTOR = {"weak": 1.0, "partial": 0.65, "strong": 0.35}
STATUSES = {"open", "mitigating", "accepted", "closed"}


class RegisterError(ValueError):
    """Every problem found while reading a register, reported together."""

    def __init__(self, path: Path, problems: list[str]) -> None:
        self.path = path
        self.problems = list(problems)
        detail = "\n".join(f"  - {problem}" for problem in self.problems)
        noun = "problem" if len(self.problems) == 1 else "problems"
        super().__init__(f"{path}: {len(self.problems)} {noun}\n{detail}")


@dataclass(frozen=True)
class Risk:
    id: str
    system: str
    owner: str
    decision: str
    impact: str
    likelihood: str
    control_strength: str
    status: str
    next_review: date

    @property
    def score(self) -> float:
        return round(IMPACT[self.impact] * LIKELIHOOD[self.likelihood] * CONTROL_FACTOR[self.control_strength], 1)

    @property
    def level(self) -> str:
        if self.score >= 8:
            return "critical"
        if self.score >= 4:
            return "high"
        if self.score >= 2:
            return "medium"
        return "low"

    @property
    def is_active(self) -> bool:
        return self.status != "closed"


def _choice(
    row_number: int,
    field: str,
    value: str,
    allowed: set[str] | dict[str, object],
    problems: list[str],
) -> str | None:
    normalized = value.strip().lower()
    if normalized not in allowed:
        options = ", ".join(sorted(allowed))
        problems.append(f"row {row_number}: {field} must be one of {options}")
        return None
    return normalized


def _required(row_number: int, field: str, value: str, problems: list[str]) -> str | None:
    text = value.strip()
    if not text:
        problems.append(f"row {row_number}: {field} is required")
        return None
    return text


def _read_row(row_number: int, row: dict[str, str], seen: set[str], problems: list[str]) -> Risk | None:
    """Collect every problem in one row; return the Risk only when the row is clean."""
    risk_id = _required(row_number, "id", row["id"] or "", problems)
    if risk_id is not None and risk_id in seen:
        problems.append(f"row {row_number}: duplicate id {risk_id}")
        risk_id = None
    if risk_id is not None:
        seen.add(risk_id)

    system = _required(row_number, "system", row["system"] or "", problems)
    owner = _required(row_number, "owner", row["owner"] or "", problems)
    decision = _required(row_number, "decision", row["decision"] or "", problems)
    impact = _choice(row_number, "impact", row["impact"] or "", IMPACT, problems)
    likelihood = _choice(row_number, "likelihood", row["likelihood"] or "", LIKELIHOOD, problems)
    control = _choice(row_number, "control_strength", row["control_strength"] or "", CONTROL_FACTOR, problems)
    status = _choice(row_number, "status", row["status"] or "", STATUSES, problems)

    review: date | None = None
    try:
        review = date.fromisoformat((row["next_review"] or "").strip())
    except ValueError:
        problems.append(f"row {row_number}: next_review must be YYYY-MM-DD")

    if None in (risk_id, system, owner, decision, impact, likelihood, control, status, review):
        return None
    return Risk(
        id=risk_id,
        system=system,
        owner=owner,
        decision=decision,
        impact=impact,
        likelihood=likelihood,
        control_strength=control,
        status=status,
        next_review=review,
    )


def read_register(path: Path) -> list[Risk]:
    """Read and validate a register, reporting every problem in one pass."""
    path = Path(path)
    problems: list[str] = []
    risks: list[Risk] = []

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in REQUIRED_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise RegisterError(path, [f"missing required columns: {', '.join(missing)}"])

        seen: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            risk = _read_row(row_number, row, seen, problems)
            if risk is not None:
                risks.append(risk)

    if not risks and not problems:
        problems.append("risk register is empty")
    if problems:
        raise RegisterError(path, problems)
    return risks


def render_dashboard(risks: list[Risk], as_of: date) -> str:
    active = [risk for risk in risks if risk.is_active]
    ranked = sorted(active, key=lambda risk: (-risk.score, risk.id))
    overdue = [risk for risk in active if risk.next_review < as_of]
    elevated = [risk for risk in active if risk.level in {"high", "critical"}]
    level_counts = {level: sum(risk.level == level for risk in active) for level in ("critical", "high", "medium", "low")}

    lines = [
        "# Board AI Risk Dashboard",
        "",
        f"**As of:** {as_of.isoformat()}",
        "",
        "## Portfolio Read",
        "",
        f"- Risks in register: {len(risks)}",
        f"- Active risks: {len(active)}",
        f"- High or critical active risks: {len(elevated)}",
        f"- Overdue reviews: {len(overdue)}",
        f"- Distribution: {level_counts['critical']} critical, {level_counts['high']} high, {level_counts['medium']} medium, {level_counts['low']} low",
        "",
        "## Priority Risks",
        "",
        "| ID | System | Owner | Level | Score | Status | Next review |",
        "|---|---|---|---|---:|---|---|",
    ]
    for risk in ranked[:10]:
        lines.append(f"| {risk.id} | {risk.system} | {risk.owner} | {risk.level.title()} | {risk.score:.1f} | {risk.status} | {risk.next_review.isoformat()} |")
    if len(ranked) > 10:
        lines.append("")
        lines.append(f"{len(ranked) - 10} further active risks are not shown; the full register remains the record.")

    lines.extend(["", "## Decisions Required", ""])
    if elevated:
        for risk in elevated:
            lines.append(f"- **{risk.id} / {risk.system}:** {risk.decision.rstrip('.')}. Accountable owner: {risk.owner}.")
    else:
        lines.append("- No high or critical active risk is recorded; challenge whether the register is complete.")

    lines.extend(["", "## Overdue Reviews", ""])
    if overdue:
        for risk in sorted(overdue, key=lambda item: (item.next_review, item.id)):
            lines.append(f"- **{risk.id}** was due {risk.next_review.isoformat()} ({risk.owner}).")
    else:
        lines.append("- None.")

    lines.extend([
        "",
        "## Board Challenge",
        "",
        "Confirm that each material AI decision has a named owner, current evidence, a reversible response where feasible, and an escalation path proportionate to its consequences.",
        "",
    ])
    return "\n".join(lines)
