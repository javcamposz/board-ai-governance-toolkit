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
OPTIONAL_FIELDS = ("assurance", "evidence")
# Spreadsheet habits that mean "no evidence". Accepting them as a reference would let one
# keystroke buy the full assurance credit, so the register is asked to leave the cell blank.
NULL_EVIDENCE = {"n/a", "n.a.", "na", "none", "nil", "tbd", "tbc", "pending", "unknown", "-", "--", "?"}
IMPACT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
LIKELIHOOD = {"rare": 1, "possible": 2, "likely": 3, "almost_certain": 4}
CONTROL_FACTOR = {"weak": 1.0, "partial": 0.65, "strong": 0.35}
STATUSES = {"open", "mitigating", "accepted", "closed"}

# How much of a control rating the board is entitled to credit, by who verified it.
# An assertion is not nothing, but it is not a tested control either.
ASSURANCE_CREDIT = {"asserted": 0.4, "tested": 0.75, "independent": 1.0}
NO_ASSURANCE = "asserted"


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
    assurance: str = NO_ASSURANCE
    evidence: str = ""

    @property
    def is_evidenced(self) -> bool:
        return bool(self.evidence)

    @property
    def effective_assurance(self) -> str:
        """Verification you cannot point at is an assertion."""
        if self.assurance != NO_ASSURANCE and not self.is_evidenced:
            return NO_ASSURANCE
        return self.assurance

    @property
    def is_unevidenced_claim(self) -> bool:
        return self.assurance != NO_ASSURANCE and not self.is_evidenced

    @property
    def control_factor(self) -> float:
        """Credit the control rating only as far as its assurance carries it."""
        credited = CONTROL_FACTOR[self.control_strength]
        return 1.0 - (1.0 - credited) * ASSURANCE_CREDIT[self.effective_assurance]

    @property
    def score(self) -> float:
        return round(IMPACT[self.impact] * LIKELIHOOD[self.likelihood] * self.control_factor, 1)

    @property
    def face_value_score(self) -> float:
        """What the register would report if the control rating were taken on trust."""
        return round(IMPACT[self.impact] * LIKELIHOOD[self.likelihood] * CONTROL_FACTOR[self.control_strength], 1)

    @staticmethod
    def level_of(score: float) -> str:
        if score >= 8:
            return "critical"
        if score >= 4:
            return "high"
        if score >= 2:
            return "medium"
        return "low"

    @property
    def level(self) -> str:
        return self.level_of(self.score)

    @property
    def face_value_level(self) -> str:
        return self.level_of(self.face_value_score)

    @property
    def comfort_gap(self) -> float:
        """Exposure that a face-value reading of the controls would have hidden."""
        return round(self.score - self.face_value_score, 1)

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

    # Absent or blank assurance is read as an assertion, never as verification.
    raw_assurance = (row.get("assurance") or "").strip()
    assurance: str | None = NO_ASSURANCE
    if raw_assurance:
        assurance = _choice(row_number, "assurance", raw_assurance, ASSURANCE_CREDIT, problems)
    evidence = (row.get("evidence") or "").strip()
    if evidence.lower() in NULL_EVIDENCE:
        problems.append(
            f"row {row_number}: evidence must name the evidence or be left blank, not {evidence!r}"
        )
        evidence = None

    if None in (risk_id, system, owner, decision, impact, likelihood, control, status, review, assurance, evidence):
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
        assurance=assurance,
        evidence=evidence,
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
    unevidenced = [risk for risk in active if not risk.is_evidenced]
    discounted = sorted(
        (risk for risk in active if risk.comfort_gap > 0),
        key=lambda risk: (-risk.comfort_gap, risk.id),
    )
    records_no_assurance = bool(active) and not any(
        risk.is_evidenced or risk.assurance != NO_ASSURANCE for risk in active
    )
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
        f"- Controls with no evidence recorded: {len(unevidenced)}",
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

    lines.extend(["", "## Comfort Without Evidence", ""])
    if records_no_assurance:
        lines.append(
            "This register records no assurance and no evidence, so every control is credited as "
            "asserted. The scores below are the most pessimistic reading available; recording who "
            "verified each control, and where the evidence sits, is what makes them sharper."
        )
        lines.append("")
    if discounted:
        lines.append(
            "These controls are credited below their stated strength because the verification behind "
            "them is asserted rather than evidenced. The face-value column is what the register would "
            "have reported on trust."
        )
        lines.append("")
        lines.append("| ID | System | Control | Assurance | Evidence | Reported | On trust |")
        lines.append("|---|---|---|---|---|---|---|")
        for risk in discounted:
            claim = risk.assurance
            if risk.is_unevidenced_claim:
                claim = f"{risk.assurance} (unevidenced)"
            lines.append(
                f"| {risk.id} | {risk.system} | {risk.control_strength} | {claim} | "
                f"{risk.evidence or 'None'} | {risk.level.title()} {risk.score:.1f} | "
                f"{risk.face_value_level.title()} {risk.face_value_score:.1f} |"
            )
    elif not records_no_assurance:
        lines.append("- Every active control is credited in full; its assurance is evidenced.")

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
