from datetime import date
from pathlib import Path

from board_ai_governance import Policy, breached, evaluate, read_register


EXAMPLE = Path(__file__).parents[1] / "examples" / "ai-risk-register.csv"
AS_OF = date(2026, 9, 12)


def risks():
    return read_register(EXAMPLE)


def test_an_empty_policy_tests_nothing():
    policy = Policy()

    assert policy.is_empty
    assert evaluate(risks(), policy, AS_OF) == []


def test_thresholds_that_are_met_pass():
    results = evaluate(risks(), Policy(max_critical=1, max_high=0, max_overdue=1), AS_OF)

    assert breached(results) == []
    assert [result.rule for result in results] == ["critical risks", "high risks", "overdue reviews"]


def test_breaches_name_the_risks_responsible():
    results = evaluate(risks(), Policy(max_critical=0, max_overdue=0), AS_OF)
    failures = breached(results)

    assert [result.rule for result in failures] == ["critical risks", "overdue reviews"]
    assert failures[0].detail == "1 critical (limit 0)"
    assert failures[0].subjects == ("AI-002 Recruitment ranking pilot",)
    assert "AI-001 was due 2026-09-01" in failures[1].subjects[0]


def test_evidence_requirement_catches_unevidenced_elevated_risks():
    results = evaluate(risks(), Policy(require_evidence_for=frozenset({"high", "critical"})), AS_OF)

    assert breached(results) == results
    assert results[0].detail == "1 high, critical risks with no evidence recorded"
    assert results[0].subjects == ("AI-002 Recruitment ranking pilot (critical, assurance asserted)",)


def test_evidence_requirement_ignores_levels_it_was_not_asked_about():
    results = evaluate(risks(), Policy(require_evidence_for=frozenset({"low"})), AS_OF)

    assert breached(results) == []


def test_closed_risks_are_out_of_policy_scope():
    closed = [risk for risk in risks() if not risk.is_active]
    results = evaluate(closed, Policy(max_critical=0, max_high=0, max_overdue=0), AS_OF)

    assert breached(results) == []
