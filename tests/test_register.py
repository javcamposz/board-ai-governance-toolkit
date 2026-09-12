from datetime import date
from pathlib import Path

import pytest

from board_ai_governance import read_register, render_dashboard


EXAMPLE = Path(__file__).parents[1] / "examples" / "ai-risk-register.csv"


def test_register_scores_and_orders_priority_risks():
    risks = read_register(EXAMPLE)
    report = render_dashboard(risks, date(2026, 9, 12))

    assert len(risks) == 4
    assert risks[1].score == 4.2
    assert risks[1].level == "high"
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
