from datetime import date
from pathlib import Path

import pytest

from board_ai_governance import RegisterError, Risk, read_register, render_dashboard

EXAMPLE = Path(__file__).parents[1] / "examples" / "ai-risk-register.csv"


def test_register_scores_and_orders_priority_risks():
    risks = read_register(EXAMPLE)
    report = render_dashboard(risks, date(2026, 9, 12))

    assert len(risks) == 4
    assert risks[1].score == 8.9
    assert risks[1].level == "critical"
    assert report.index("AI-002") < report.index("AI-003")
    assert "Overdue reviews: 1" in report


def test_closed_risk_is_not_reported_as_overdue():
    risks = read_register(EXAMPLE)
    report = render_dashboard(risks, date(2026, 9, 12))

    overdue_section = report.split("## Overdue Reviews", 1)[1]
    assert "AI-001" in overdue_section
    assert "AI-004" not in overdue_section


def test_invalid_enum_is_rejected(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text(
        "id,system,owner,decision,impact,likelihood,control_strength,status,next_review\n"
        "AI-1,Model,CTO,Approve,catastrophic,likely,weak,open,2026-12-01\n"
    )

    with pytest.raises(ValueError, match="impact"):
        read_register(path)


def test_every_problem_is_reported_in_one_pass(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text(
        "id,system,owner,decision,impact,likelihood,control_strength,status,next_review\n"
        "AI-1,Model,CTO,Approve,catastrophic,likely,weak,open,2026-12-01\n"
        "AI-1,,CTO,Approve,high,likely,weak,open,2026-12-01\n"
    )

    with pytest.raises(RegisterError) as caught:
        read_register(path)

    assert caught.value.problems == [
        "row 2: impact must be one of critical, high, low, medium",
        "row 3: duplicate id AI-1",
        "row 3: system is required",
    ]


def test_missing_columns_are_named(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text("id,system,owner\nAI-1,Model,CTO\n")

    with pytest.raises(RegisterError, match="missing required columns: decision"):
        read_register(path)


def test_evidenced_independent_assurance_keeps_the_full_control_credit():
    evidenced = Risk("AI-1", "S", "O", "D", "critical", "possible", "strong", "open", date(2027, 1, 1),
                     "independent", "evidence/review.md")

    assert evidenced.score == evidenced.face_value_score == 2.8
    assert evidenced.comfort_gap == 0.0
    assert evidenced.level == "medium"


def test_an_assertion_does_not_earn_the_control_rating():
    asserted = Risk("AI-1", "S", "O", "D", "critical", "possible", "strong", "open", date(2027, 1, 1))

    assert asserted.face_value_score == 2.8
    assert asserted.score == 5.9
    assert asserted.level == "high"
    assert asserted.face_value_level == "medium"
    assert asserted.comfort_gap == 3.1


def test_verification_you_cannot_point_at_is_an_assertion():
    unevidenced = Risk("AI-1", "S", "O", "D", "critical", "possible", "strong", "open", date(2027, 1, 1),
                       "independent", "")
    asserted = Risk("AI-1", "S", "O", "D", "critical", "possible", "strong", "open", date(2027, 1, 1))

    assert unevidenced.is_unevidenced_claim
    assert unevidenced.effective_assurance == "asserted"
    assert unevidenced.score == asserted.score


def test_a_weak_control_gains_nothing_from_assurance():
    scores = {
        Risk("AI-1", "S", "O", "D", "high", "likely", "weak", "open",
             date(2027, 1, 1), assurance, "evidence/x.md").score
        for assurance in ("asserted", "tested", "independent")
    }

    assert scores == {9.0}


def test_registers_without_the_optional_columns_still_load(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text(
        "id,system,owner,decision,impact,likelihood,control_strength,status,next_review\n"
        "AI-1,Model,CTO,Approve,high,likely,strong,open,2026-12-01\n"
    )

    risk = read_register(path)[0]

    assert risk.assurance == "asserted"
    assert risk.evidence == ""
    assert not risk.is_evidenced


def test_unknown_assurance_value_is_rejected(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text(
        "id,system,owner,decision,impact,likelihood,control_strength,status,next_review,assurance,evidence\n"
        "AI-1,Model,CTO,Approve,high,likely,strong,open,2026-12-01,vendor_says_so,\n"
    )

    with pytest.raises(RegisterError, match="assurance must be one of asserted, independent, tested"):
        read_register(path)


def test_dashboard_names_what_is_credited_on_trust():
    report = render_dashboard(read_register(EXAMPLE), date(2026, 9, 12))
    section = report.split("## Comfort Without Evidence", 1)[1].split("## Overdue Reviews", 1)[0]

    assert "AI-002" in section
    assert "asserted" in section
    assert "AI-003" not in section
    assert "Controls with no evidence recorded: 1" in report


def test_placeholder_evidence_cannot_buy_assurance_credit(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text(
        "id,system,owner,decision,impact,likelihood,control_strength,status,next_review,assurance,evidence\n"
        "AI-1,Model,CTO,Approve,critical,likely,strong,open,2027-01-01,independent,N/A\n"
        "AI-2,Model,CTO,Approve,critical,likely,strong,open,2027-01-01,independent,TBD\n"
    )

    with pytest.raises(RegisterError) as caught:
        read_register(path)

    assert caught.value.problems == [
        "row 2: evidence must name the evidence or be left blank, not 'N/A'",
        "row 3: evidence must name the evidence or be left blank, not 'TBD'",
    ]


def test_blank_evidence_remains_the_way_to_say_there_is_none(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text(
        "id,system,owner,decision,impact,likelihood,control_strength,status,next_review,assurance,evidence\n"
        "AI-1,Model,CTO,Approve,critical,likely,strong,open,2027-01-01,independent,   \n"
    )

    risk = read_register(path)[0]

    assert not risk.is_evidenced
    assert risk.effective_assurance == "asserted"


def test_a_register_recording_no_assurance_at_all_says_so(tmp_path):
    path = tmp_path / "risks.csv"
    path.write_text(
        "id,system,owner,decision,impact,likelihood,control_strength,status,next_review\n"
        "AI-1,Model,CTO,Approve,high,likely,strong,open,2027-01-01\n"
    )

    report = render_dashboard(read_register(path), date(2026, 9, 12))

    assert "This register records no assurance and no evidence" in report
    assert "most pessimistic reading available" in report
