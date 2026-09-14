"""Decisions required are tracked; decisions made were not.

Every risk carries the decision it puts at risk, and the dashboard listed the same ask
every quarter with no record that it had been asked before, when an answer was due, or
whether one was ever given. docs/decision-rights.md defines who must approve what, and
templates/decision-memo.md asks for exactly these fields.
"""

from datetime import date
from pathlib import Path

import pytest

from board_ai_governance import (
    Policy,
    Portfolio,
    RegisterError,
    breached,
    diff_registers,
    evaluate,
    read_register,
    render_dashboard,
    render_diff,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/ai-risk-register.csv"
PREVIOUS = ROOT / "examples/ai-risk-register-previous.csv"
AS_OF = date(2026, 9, 12)
HEADER = (
    "id,system,owner,decision,impact,likelihood,control_strength,status,next_review,"
    "assurance,evidence,date_opened,decision_due,decided_on,decided_by\n"
)


def write(tmp_path, *rows, name="risks.csv"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    path.write_text(HEADER + "".join(rows))
    return path


def portfolio():
    return Portfolio(as_of=AS_OF, risks=tuple(read_register(EXAMPLE)))


def by_id(risks, risk_id):
    return next(risk for risk in risks if risk.id == risk_id)


# --- the record itself ---

def test_a_decision_records_when_it_was_taken_and_by_whom():
    risk = by_id(read_register(EXAMPLE), "AI-001")

    assert risk.is_decided
    assert risk.decided_on == date(2026, 8, 15)
    assert risk.decided_by == "Customer Operations Director"
    assert risk.days_undecided(AS_OF) is None


def test_an_outstanding_decision_is_timed_from_when_the_risk_opened():
    risk = by_id(read_register(EXAMPLE), "AI-003")

    assert not risk.is_decided
    assert risk.days_undecided(AS_OF) == 54
    assert risk.decision_overdue_days(AS_OF) == 12


def test_a_decision_not_yet_due_is_not_overdue(tmp_path):
    path = write(tmp_path, "AI-1,S,O,Decide,high,likely,strong,open,2027-01-01,asserted,,2026-09-01,2027-01-01,,\n")

    assert read_register(path)[0].decision_overdue_days(AS_OF) is None


def test_a_decision_without_a_named_decider_is_refused(tmp_path):
    path = write(tmp_path, "AI-1,S,O,Decide,high,likely,strong,open,2027-01-01,asserted,,2026-01-01,,2026-02-01,\n")

    with pytest.raises(RegisterError, match="a decision without a named decider is not accountable"):
        read_register(path)


def test_a_decision_cannot_predate_the_risk(tmp_path):
    path = write(tmp_path, "AI-1,S,O,Decide,high,likely,strong,open,2027-01-01,asserted,,2026-06-01,,2026-01-01,CTO\n")

    with pytest.raises(RegisterError, match="a decision cannot precede the risk"):
        read_register(path)


def test_a_register_without_the_decision_columns_still_loads(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text(
        "id,system,owner,decision,impact,likelihood,control_strength,status,next_review\n"
        "AI-1,Model,CTO,Decide,high,likely,strong,open,2026-12-01\n"
    )
    risk = read_register(path)[0]

    assert not risk.is_decided
    assert risk.decision_due is None and risk.decided_by == ""


# --- the dashboard ---

def test_the_dashboard_says_where_each_required_decision_stands():
    report = render_dashboard(read_register(EXAMPLE), AS_OF)
    section = report.split("## Decisions Required", 1)[1].split("## Decisions Outstanding", 1)[0]

    assert "Decided 2026-05-20 by Chief People Officer." in section


def test_an_outstanding_decision_is_tabled_with_how_long_it_has_waited():
    report = render_dashboard(read_register(EXAMPLE), AS_OF)
    section = report.split("## Decisions Outstanding", 1)[1].split("## Decisions Taken", 1)[0]

    assert "| AI-003 | Developer coding assistant |" in section
    assert "| 54 days | 2026-08-31 | 12 |" in section
    assert "a decision the board has declined to take" in section


def test_decisions_taken_are_listed_with_their_decider():
    section = render_dashboard(read_register(EXAMPLE), AS_OF).split("## Decisions Taken", 1)[1]

    assert "decided 2026-08-15 by Customer Operations Director." in section
    assert "decided 2026-05-20 by Chief People Officer." in section


def test_a_register_where_every_decision_is_taken_says_so(tmp_path):
    path = write(tmp_path, "AI-1,S,O,Decide,high,likely,strong,open,2027-01-01,asserted,,2026-01-01,,2026-02-01,CTO\n")
    section = render_dashboard(read_register(path), AS_OF).split("## Decisions Outstanding", 1)[1]

    assert "Every active risk records a decision and who took it." in section


def test_closed_risks_are_out_of_the_decision_view():
    assert "AI-004" not in {risk.id for risk in portfolio().undecided}
    assert "AI-004" not in {risk.id for risk in portfolio().decided}


# --- the gate ---

def test_a_decision_outstanding_too_long_breaches():
    results = evaluate(read_register(EXAMPLE), Policy(max_undecided_days=30), AS_OF)

    assert breached(results) == results
    assert results[0].detail == "1 decision outstanding longer than 30 days"
    assert "AI-003 Developer coding assistant: Set the permitted autonomy boundary (54 days" in results[0].subjects[0]


def test_an_undecided_risk_with_no_opening_date_is_named_as_untimed(tmp_path):
    path = write(
        tmp_path,
        "AI-1,Timed,O,Decide,high,likely,strong,open,2027-01-01,asserted,,2024-01-01,,,\n",
        "AI-2,Untimed,O,Decide,low,rare,strong,open,2027-01-01,asserted,,,,,\n",
    )
    results = evaluate(read_register(path), Policy(max_undecided_days=30), AS_OF)

    assert "1 undecided with no opening date and could not be timed" in results[0].detail


def test_a_decision_past_its_due_date_breaches():
    results = evaluate(read_register(EXAMPLE), Policy(max_overdue_decisions=0), AS_OF)

    assert breached(results) == results
    assert results[0].detail == "1 past their due date (limit 0)"
    assert "AI-003 Developer coding assistant was due 2026-08-31, 12 days ago" in results[0].subjects[0]


def test_a_taken_decision_never_counts_as_overdue(tmp_path):
    path = write(
        tmp_path,
        "AI-1,S,O,Decide,high,likely,strong,open,2027-01-01,asserted,,"
        "2026-01-01,2026-02-01,2026-03-01,CTO\n",
    )

    assert breached(evaluate(read_register(path), Policy(max_overdue_decisions=0), AS_OF)) == []


# --- the change report ---

def test_an_approval_overtaken_by_escalation_is_reported():
    """An approval given for a high risk does not automatically cover a critical one."""
    diff = diff_registers(read_register(PREVIOUS), read_register(EXAMPLE), AS_OF)

    assert [change.id for change in diff.stale_approvals] == ["AI-002"]
    explanation = render_diff(diff).split("## Requires Explanation", 1)[1].split("## Movement", 1)[0]
    assert "was decided on 2026-05-20 by Chief People Officer, when it was high" in explanation
    assert "An approval given for a smaller risk does not cover this one." in explanation


def test_a_decision_taken_since_the_last_snapshot_is_counted():
    diff = diff_registers(read_register(PREVIOUS), read_register(EXAMPLE), AS_OF)

    assert [change.id for change in diff.decisions_taken] == ["AI-001"]
    assert "Decisions taken: 1" in render_diff(diff)


def test_a_withdrawn_decision_is_reported(tmp_path):
    before = write(
        tmp_path / "a",
        "AI-1,S,O,Decide,high,likely,strong,open,2027-01-01,asserted,,2026-01-01,,2026-02-01,CTO\n",
    )
    after = write(
        tmp_path / "b",
        "AI-1,S,O,Decide,high,likely,strong,open,2027-01-01,asserted,,2026-01-01,,,\n",
    )

    diff = diff_registers(read_register(before), read_register(after), AS_OF)

    assert [change.id for change in diff.withdrawn_decisions] == ["AI-1"]
    assert "no longer records a decision; 2026-02-01 by CTO was removed" in render_diff(diff)


def test_an_escalation_with_a_fresh_decision_is_not_a_stale_approval(tmp_path):
    before = write(
        tmp_path / "a",
        "AI-1,S,O,Decide,high,possible,strong,open,2027-01-01,independent,e.md,"
        "2026-01-01,,2026-02-01,CTO\n",
    )
    after = write(
        tmp_path / "b",
        "AI-1,S,O,Decide,critical,likely,strong,open,2027-01-01,independent,e.md,"
        "2026-01-01,,2026-08-01,CTO\n",
    )

    diff = diff_registers(read_register(before), read_register(after), AS_OF)

    assert diff.escalated and diff.stale_approvals == ()


def test_an_opening_date_after_the_review_date_still_rejects_the_row(tmp_path):
    """The guard for this predates the decision columns; a rename had silently dropped it."""
    path = write(
        tmp_path,
        "AI-1,S,O,Decide,high,likely,strong,open,2026-01-01,asserted,,2026-08-01,,,\n",
    )

    with pytest.raises(RegisterError) as caught:
        read_register(path)

    assert caught.value.problems == [
        "row 2: date_opened 2026-08-01 is after next_review 2026-01-01; "
        "a risk cannot be reviewed before it was opened"
    ]


@pytest.mark.parametrize("field,value", [
    ("next_review", "20261001"),
    ("date_opened", "2026-W03-4"),
    ("decision_due", "01/03/2026"),
    ("decided_on", "20260301"),
])
def test_every_date_is_read_as_the_one_documented_shape(tmp_path, field, value):
    """date.fromisoformat widened in 3.11; both supported versions must agree."""
    columns = {
        "next_review": "2027-01-01", "date_opened": "2026-01-01",
        "decision_due": "", "decided_on": "", "decided_by": "",
    }
    columns[field] = value
    if field == "decided_on":
        columns["decided_by"] = "CTO"
    path = write(
        tmp_path,
        f"AI-1,S,O,Decide,high,likely,strong,open,{columns['next_review']},asserted,,"
        f"{columns['date_opened']},{columns['decision_due']},{columns['decided_on']},"
        f"{columns['decided_by']}\n",
    )

    with pytest.raises(RegisterError, match=f"{field} must be YYYY-MM-DD"):
        read_register(path)


def test_a_well_shaped_but_impossible_date_is_named_as_such(tmp_path):
    path = write(tmp_path, "AI-1,S,O,Decide,high,likely,strong,open,2026-02-30,asserted,,,,,\n")

    with pytest.raises(RegisterError, match="next_review is 2026-02-30, which is not a real date"):
        read_register(path)
