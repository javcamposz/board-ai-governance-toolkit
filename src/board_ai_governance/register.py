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


def _choice(row_number: int, field: str, value: str, allowed: set[str] | dict[str, object]) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed:
        options = ", ".join(sorted(allowed))
        raise ValueError(f"row {row_number}: {field} must be one of {options}")
    return normalized


def read_register(path: Path) -> list[Risk]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in REQUIRED_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"missing required columns: {', '.join(missing)}")

        risks: list[Risk] = []
        seen: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            risk_id = row["id"].strip()
            if not risk_id:
                raise ValueError(f"row {row_number}: id is required")
            if risk_id in seen:
                raise ValueError(f"row {row_number}: duplicate id {risk_id}")
            seen.add(risk_id)
            owner = row["owner"].strip()
            if not owner:
                raise ValueError(f"row {row_number}: owner is required")
            try:
                review = date.fromisoformat(row["next_review"].strip())
            except ValueError as exc:
                raise ValueError(f"row {row_number}: next_review must be YYYY-MM-DD") from exc

            risks.append(Risk(
                id=risk_id,
                system=row["system"].strip(),
                owner=owner,
                decision=row["decision"].strip(),
                impact=_choice(row_number, "impact", row["impact"], IMPACT),
                likelihood=_choice(row_number, "likelihood", row["likelihood"], LIKELIHOOD),
                control_strength=_choice(row_number, "control_strength", row["control_strength"], CONTROL_FACTOR),
                status=_choice(row_number, "status", row["status"], STATUSES),
                next_review=review,
            ))
    if not risks:
        raise ValueError("risk register is empty")
    return risks


def render_dashboard(risks: list[Risk], as_of: date) -> str:
    active = [risk for risk in risks if risk.status != "closed"]
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
