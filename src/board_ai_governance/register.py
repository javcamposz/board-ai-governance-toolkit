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
OPTIONAL_FIELDS = ("assurance", "evidence", "date_opened")
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
    date_opened: date | None = None

    def age_days(self, as_of: date) -> int | None:
        """How long the risk has been on the register, when the register says."""
        if self.date_opened is None:
            return None
        return (as_of - self.date_opened).days

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
    # date_opened is optional, so an absent value is not a problem but an unreadable one is.
    raw_opened = (row.get("date_opened") or "").strip()
    opened: date | None = None
    opened_is_unreadable = False
    if raw_opened:
        try:
            opened = date.fromisoformat(raw_opened)
        except ValueError:
            problems.append(f"row {row_number}: date_opened must be YYYY-MM-DD")
            opened_is_unreadable = True

    if opened is not None and review is not None and opened > review:
        problems.append(
            f"row {row_number}: date_opened {opened.isoformat()} is after next_review "
            f"{review.isoformat()}; a risk cannot be reviewed before it was opened"
        )
        opened_is_unreadable = True

    evidence = (row.get("evidence") or "").strip()
    if evidence.lower() in NULL_EVIDENCE:
        problems.append(
            f"row {row_number}: evidence must name the evidence or be left blank, not {evidence!r}"
        )
        evidence = None

    fields = (risk_id, system, owner, decision, impact, likelihood, control, status, review, assurance, evidence)
    if None in fields or opened_is_unreadable:
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
        date_opened=opened,
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


@dataclass(frozen=True)
class Portfolio:
    """The numbers the board is given, counted once so two reports cannot disagree."""

    as_of: date
    risks: tuple[Risk, ...]

    @property
    def active(self) -> tuple[Risk, ...]:
        return tuple(risk for risk in self.risks if risk.is_active)

    @property
    def ranked(self) -> tuple[Risk, ...]:
        return tuple(sorted(self.active, key=lambda risk: (-risk.score, risk.id)))

    @property
    def overdue(self) -> tuple[Risk, ...]:
        return tuple(sorted(
            (risk for risk in self.active if risk.next_review < self.as_of),
            key=lambda risk: (risk.next_review, risk.id),
        ))

    @property
    def elevated(self) -> tuple[Risk, ...]:
        return tuple(risk for risk in self.active if risk.level in {"high", "critical"})

    @property
    def unevidenced(self) -> tuple[Risk, ...]:
        return tuple(risk for risk in self.active if not risk.is_evidenced)

    @property
    def discounted(self) -> tuple[Risk, ...]:
        return tuple(sorted(
            (risk for risk in self.active if risk.comfort_gap > 0),
            key=lambda risk: (-risk.comfort_gap, risk.id),
        ))

    @property
    def aged(self) -> tuple[Risk, ...]:
        """Active risks open on the reporting date, oldest first."""
        return tuple(sorted(
            (risk for risk in self.active if (risk.age_days(self.as_of) or 0) >= 0 and risk.date_opened),
            key=lambda risk: (risk.date_opened, risk.id),
        ))

    @property
    def not_yet_opened(self) -> tuple[Risk, ...]:
        """Active risks the register says open after the reporting date, which needs explaining."""
        return tuple(sorted(
            (risk for risk in self.active if risk.date_opened is not None and risk.date_opened > self.as_of),
            key=lambda risk: (risk.date_opened, risk.id),
        ))

    @property
    def undated(self) -> tuple[Risk, ...]:
        return tuple(risk for risk in self.active if risk.date_opened is None)

    @property
    def records_no_assurance(self) -> bool:
        return bool(self.active) and not any(
            risk.is_evidenced or risk.assurance != NO_ASSURANCE for risk in self.active
        )

    @property
    def level_counts(self) -> dict[str, int]:
        return {
            level: sum(risk.level == level for risk in self.active)
            for level in ("critical", "high", "medium", "low")
        }


def render_dashboard(risks: list[Risk], as_of: date) -> str:
    portfolio = Portfolio(as_of=as_of, risks=tuple(risks))
    active = portfolio.active
    ranked = portfolio.ranked
    overdue = portfolio.overdue
    elevated = portfolio.elevated
    unevidenced = portfolio.unevidenced
    discounted = portfolio.discounted
    records_no_assurance = portfolio.records_no_assurance
    level_counts = portfolio.level_counts

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
        f"- Distribution: {level_counts['critical']} critical, {level_counts['high']} high, "
        f"{level_counts['medium']} medium, {level_counts['low']} low",
        "",
        "## Priority Risks",
        "",
        "| ID | System | Owner | Level | Score | Status | Next review |",
        "|---|---|---|---|---:|---|---|",
    ]
    for risk in ranked[:10]:
        lines.append(
            f"| {risk.id} | {risk.system} | {risk.owner} | {risk.level.title()} | "
            f"{risk.score:.1f} | {risk.status} | {risk.next_review.isoformat()} |"
        )
    if len(ranked) > 10:
        lines.append("")
        lines.append(f"{len(ranked) - 10} further active risks are not shown; the full register remains the record.")

    lines.extend(["", "## Decisions Required", ""])
    if elevated:
        for risk in elevated:
            lines.append(
                f"- **{risk.id} / {risk.system}:** {risk.decision.rstrip('.')}. "
                f"Accountable owner: {risk.owner}."
            )
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
        for risk in overdue:
            lines.append(f"- **{risk.id}** was due {risk.next_review.isoformat()} ({risk.owner}).")
    else:
        lines.append("- None.")

    lines.extend(["", "## Ageing", ""])
    aged = portfolio.aged
    if aged:
        lines.append("| ID | System | Opened | Days open | Status | Level |")
        lines.append("|---|---|---|---:|---|---|")
        for risk in aged[:10]:
            lines.append(
                f"| {risk.id} | {risk.system} | {risk.date_opened.isoformat()} | "
                f"{risk.age_days(as_of)} | {risk.status} | {risk.level.title()} |"
            )
        if len(aged) > 10:
            lines.append("")
            lines.append(f"{len(aged) - 10} further dated active risks are not shown.")
    caveats = []
    if portfolio.undated:
        count = len(portfolio.undated)
        subject = "1 active risk records" if count == 1 else f"{count} active risks record"
        carried = "it" if count == 1 else "them"
        caveats.append(
            f"{subject} no opening date, so how long the organization has carried "
            f"{carried} cannot be reported."
        )
    for risk in portfolio.not_yet_opened:
        caveats.append(
            f"**{risk.id}** is dated {risk.date_opened.isoformat()}, after this report, so it cannot "
            f"be aged. Confirm whether the opening date is wrong or the risk is not yet live."
        )
    if caveats:
        if aged:
            lines.append("")
        lines.extend(caveats)
    if not aged and not caveats:
        lines.append("- No active risk to age.")

    lines.extend([
        "",
        "## Board Challenge",
        "",
        "Confirm that each material AI decision has a named owner, current evidence, a reversible "
        "response where feasible, and an escalation path proportionate to its consequences.",
        "",
    ])
    return "\n".join(lines)
