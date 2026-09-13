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

EXAMPLE = Path(__file__).parents[1] / "examples" / "ai-risk-register.csv"
AS_OF = date(2026, 9, 12)
HEADER = (
    "id,system,owner,decision,impact,likelihood,control_strength,status,"
    "next_review,assurance,evidence,date_opened\n"
)


def write(tmp_path, *rows):
    path = tmp_path / "risks.csv"
    path.write_text(HEADER + "".join(rows))
    return path


def test_age_is_measured_from_the_opening_date():
    risk = read_register(EXAMPLE)[0]

    assert risk.date_opened == date(2025, 11, 10)
    assert risk.age_days(AS_OF) == 306


def test_a_risk_without_an_opening_date_has_no_age(tmp_path):
    path = write(tmp_path, "AI-1,M,CTO,A,high,likely,strong,open,2027-01-01,asserted,,\n")
    risk = read_register(path)[0]

    assert risk.date_opened is None
    assert risk.age_days(AS_OF) is None


def test_an_unreadable_opening_date_is_a_problem_but_an_absent_one_is_not(tmp_path):
    path = write(tmp_path, "AI-1,M,CTO,A,high,likely,strong,open,2027-01-01,asserted,,15-03-2025\n")

    with pytest.raises(RegisterError, match="row 2: date_opened must be YYYY-MM-DD"):
        read_register(path)


def test_ageing_orders_oldest_first_and_ignores_closed_risks():
    portfolio = Portfolio(as_of=AS_OF, risks=tuple(read_register(EXAMPLE)))

    assert [risk.id for risk in portfolio.aged] == ["AI-001", "AI-002", "AI-003"]
    assert portfolio.undated == ()


def test_dashboard_reports_ageing():
    report = render_dashboard(read_register(EXAMPLE), AS_OF)
    section = report.split("## Ageing", 1)[1].split("## Board Challenge", 1)[0]

    assert "| AI-001 | Customer support assistant | 2025-11-10 | 306 |" in section
    assert "AI-004" not in section


def test_dashboard_says_when_opening_dates_are_missing(tmp_path):
    path = write(tmp_path, "AI-1,M,CTO,A,high,likely,strong,open,2027-01-01,asserted,,\n")
    section = render_dashboard(read_register(path), AS_OF).split("## Ageing", 1)[1]

    assert "1 active risk records no opening date" in section
    assert "carried it cannot be reported" in section


def test_age_rule_names_what_it_could_not_test(tmp_path):
    path = write(
        tmp_path,
        "AI-1,Legacy,CRO,A,medium,possible,partial,mitigating,2027-01-01,asserted,,2024-01-15\n",
        "AI-2,Undated,CRO,A,low,rare,strong,open,2027-01-01,asserted,,\n",
    )
    results = evaluate(read_register(path), Policy(max_open_days=365), AS_OF)

    assert breached(results) == results
    assert results[0].detail == (
        "1 risk open longer than 365 days; 1 record no usable opening date and could not be tested"
    )
    assert "AI-1 Legacy open 971 days since 2024-01-15, still mitigating" in results[0].subjects[0]


def test_age_rule_passes_when_every_dated_risk_is_within_the_limit(tmp_path):
    path = write(tmp_path, "AI-1,M,CTO,A,low,rare,strong,open,2027-01-01,asserted,,2026-09-01\n")

    assert breached(evaluate(read_register(path), Policy(max_open_days=365), AS_OF)) == []


def test_a_risk_cannot_escape_the_evidence_rule_by_being_inflated_past_it(tmp_path):
    path = write(tmp_path, "AI-2,Recruitment,CPO,A,critical,likely,strong,open,2027-01-01,asserted,,\n")
    risk = read_register(path)[0]

    assert risk.face_value_level == "high"
    assert risk.level == "critical"

    for levels in ({"high"}, {"critical"}, {"high", "critical"}):
        results = evaluate([risk], Policy(require_evidence_for=frozenset(levels)), AS_OF)
        assert breached(results) == results, f"missed by --require-evidence-for {levels}"


def test_a_rewritten_opening_date_shows_up_as_a_change(tmp_path):
    """Moving when a risk supposedly started is rewriting the record, and the board should see it."""
    before = tmp_path / "before.csv"
    after = tmp_path / "after.csv"
    before.write_text(HEADER + "AI-1,M,CTO,A,high,likely,strong,open,2027-01-01,asserted,,2024-01-01\n")
    after.write_text(HEADER + "AI-1,M,CTO,A,high,likely,strong,open,2027-01-01,asserted,,2026-01-01\n")

    diff = diff_registers(read_register(before), read_register(after), AS_OF)

    assert "date opened: 2024-01-01 to 2026-01-01" in render_diff(diff)


def test_a_risk_dated_after_the_report_is_surfaced_not_aged(tmp_path):
    """A negative age is nonsense in a board pack; say the date is wrong instead."""
    path = write(tmp_path, "AI-1,Planned,CTO,A,high,likely,strong,open,2027-06-01,asserted,,2027-01-15\n")
    portfolio = Portfolio(as_of=AS_OF, risks=tuple(read_register(path)))

    assert portfolio.aged == ()
    assert [risk.id for risk in portfolio.not_yet_opened] == ["AI-1"]

    section = render_dashboard(read_register(path), AS_OF).split("## Ageing", 1)[1]
    assert "-125" not in section
    assert "**AI-1** is dated 2027-01-15, after this report" in section


def test_a_risk_dated_after_the_report_cannot_quietly_clear_the_age_gate(tmp_path):
    path = write(tmp_path, "AI-1,Planned,CTO,A,high,likely,strong,open,2027-06-01,asserted,,2027-01-15\n")
    results = evaluate(read_register(path), Policy(max_open_days=0), AS_OF)

    assert results[0].detail == (
        "0 risks open longer than 0 days; 1 record no usable opening date and could not be tested"
    )


def test_an_opening_date_after_the_review_date_is_rejected(tmp_path):
    path = write(tmp_path, "AI-1,S,CTO,A,high,likely,strong,open,2026-01-01,asserted,,2026-08-01\n")

    with pytest.raises(RegisterError) as caught:
        read_register(path)

    assert caught.value.problems == [
        "row 2: date_opened 2026-08-01 is after next_review 2026-01-01; "
        "a risk cannot be reviewed before it was opened"
    ]


def test_one_undated_risk_reads_in_the_singular(tmp_path):
    path = write(tmp_path, "AI-1,M,CTO,A,high,likely,strong,open,2027-01-01,asserted,,\n")
    section = render_dashboard(read_register(path), AS_OF).split("## Ageing", 1)[1]

    assert "1 active risk records no opening date" in section
    assert "carried it cannot be reported" in section
