"""One place answers "is this date usable as of the report?".

A date the register places after the report has no meaningful elapsed time. Returning a
signed integer made that every caller's problem, and it was forgotten three times: in the
age gate, in the decision gate, and in two tables that printed a negative day count to a
board. Elapsed removes the thing to remember by removing the negative.
"""

from datetime import date

import pytest

from board_ai_governance import Elapsed, Risk

AS_OF = date(2026, 9, 12)


def risk(opened=None, due=None, decided=None, by=""):
    return Risk(
        id="AI-1", system="S", owner="O", decision="Decide",
        impact="high", likelihood="likely", control_strength="strong",
        status="open", next_review=date(2027, 1, 1),
        date_opened=opened, decision_due=due, decided_on=decided, decided_by=by,
    )


def test_a_past_date_measures_in_whole_days():
    elapsed = Elapsed(since=date(2026, 9, 2), as_of=AS_OF)

    assert elapsed.days == 10
    assert elapsed.is_measurable and elapsed.is_recorded and not elapsed.is_future
    assert elapsed.describe() == "10 days"


def test_the_reporting_date_itself_measures_as_zero():
    elapsed = Elapsed(since=AS_OF, as_of=AS_OF)

    assert elapsed.days == 0
    assert elapsed.is_measurable and not elapsed.is_future


def test_a_future_date_has_no_elapsed_time_rather_than_a_negative_one():
    elapsed = Elapsed(since=date(2027, 1, 15), as_of=AS_OF)

    assert elapsed.days is None
    assert elapsed.is_future and elapsed.is_recorded and not elapsed.is_measurable
    assert elapsed.describe() == "dated 2027-01-15, after this report"


def test_an_absent_date_is_distinguished_from_a_future_one():
    elapsed = Elapsed(since=None, as_of=AS_OF)

    assert elapsed.days is None
    assert not elapsed.is_recorded and not elapsed.is_future
    assert elapsed.describe() == "not recorded"
    assert elapsed.describe(absent="never asked") == "never asked"


@pytest.mark.parametrize("accessor", ["age_days", "days_undecided"])
def test_no_day_count_a_risk_reports_can_be_negative(accessor):
    for opened in (date(2025, 1, 1), AS_OF, date(2027, 6, 1), None):
        value = getattr(risk(opened=opened), accessor)(AS_OF)
        assert value is None or value >= 0, (accessor, opened)


def test_a_decided_risk_has_no_outstanding_wait():
    decided = risk(opened=date(2026, 1, 1), decided=date(2026, 2, 1), by="CTO")

    assert decided.opened_for(AS_OF).days == 254
    assert not decided.undecided_for(AS_OF).is_recorded
    assert decided.days_undecided(AS_OF) is None


def test_a_decision_due_in_the_future_is_not_overdue():
    assert risk(opened=date(2026, 1, 1), due=date(2027, 1, 1)).decision_overdue_days(AS_OF) is None


def test_a_decision_due_today_is_not_yet_overdue():
    assert risk(opened=date(2026, 1, 1), due=AS_OF).decision_overdue_days(AS_OF) is None


def test_a_decision_due_in_the_past_is_overdue_by_whole_days():
    assert risk(opened=date(2026, 1, 1), due=date(2026, 8, 31)).decision_overdue_days(AS_OF) == 12
