from datetime import date
from pathlib import Path

from board_ai_governance import diff_registers, read_register, render_diff


EXAMPLES = Path(__file__).parents[1] / "examples"
PREVIOUS = EXAMPLES / "ai-risk-register-previous.csv"
CURRENT = EXAMPLES / "ai-risk-register.csv"
AS_OF = date(2026, 9, 12)


def build_diff():
    return diff_registers(read_register(PREVIOUS), read_register(CURRENT), AS_OF)


def test_diff_classifies_each_risk_once():
    diff = build_diff()

    assert [risk.id for risk in diff.added] == ["AI-003"]
    assert [risk.id for risk in diff.dropped] == ["AI-005"]
    assert [change.id for change in diff.closed] == ["AI-004"]
    assert [change.id for change in diff.changed] == ["AI-001", "AI-002"]
    assert diff.reopened == ()
    assert diff.retired == ()
    assert diff.unchanged == ()


def test_level_movement_is_directional():
    diff = build_diff()

    assert [change.id for change in diff.escalated] == ["AI-002"]
    assert [change.id for change in diff.de_escalated] == ["AI-001"]


def test_slipped_reviews_are_ordered_by_days_and_flag_overdue_moves():
    diff = build_diff()
    slipped = diff.slipped

    assert [change.id for change in slipped] == ["AI-002", "AI-001"]
    assert slipped[0].slip_days == 92
    assert all(change.was_due(AS_OF) for change in slipped)


def test_pulling_a_review_forward_is_not_slippage():
    previous = read_register(PREVIOUS)
    current = read_register(CURRENT)
    diff = diff_registers(current, previous, AS_OF)

    assert diff.slipped == ()


def test_owner_change_and_control_direction_are_tracked():
    diff = build_diff()

    owner_change = next(change for change in diff.owner_changes)
    assert owner_change.id == "AI-001"
    assert owner_change.control_direction == "strengthened"
    assert diff.weakened_controls == ()


def test_report_leads_with_what_requires_explanation():
    report = render_diff(build_diff())
    explanation = report.split("## Requires Explanation", 1)[1].split("## Movement", 1)[0]

    assert "AI-005" in explanation
    assert "left the register while still open" in explanation
    assert "escalated from medium to high" in explanation
    assert report.index("## Requires Explanation") < report.index("## Movement")


def test_identical_snapshots_report_no_change():
    risks = read_register(CURRENT)
    diff = diff_registers(risks, risks, AS_OF)
    report = render_diff(diff)

    assert len(diff.unchanged) == len(risks)
    assert diff.changed == ()
    assert "Nothing in this comparison requires explanation" in report
    assert "No review date moved later." in report


def test_reopened_risk_is_separated_from_ordinary_change(tmp_path):
    header = "id,system,owner,decision,impact,likelihood,control_strength,status,next_review\n"
    before = tmp_path / "before.csv"
    after = tmp_path / "after.csv"
    before.write_text(header + "AI-1,Model,CTO,Approve,high,likely,strong,closed,2026-06-01\n")
    after.write_text(header + "AI-1,Model,CTO,Approve,high,likely,strong,open,2026-06-01\n")

    diff = diff_registers(read_register(before), read_register(after), AS_OF)

    assert [change.id for change in diff.reopened] == ["AI-1"]
    assert diff.changed == ()
    assert "is active again as open" in render_diff(diff)
