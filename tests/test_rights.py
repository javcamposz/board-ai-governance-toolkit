"""Whether the right authority took the decision.

docs/decision-rights.md maps decisions to who may approve them and was prose the toolkit
could not read. The register records decided_by as free text, so a critical risk signed
off by a delegate looked exactly like one the board approved.
"""

import json
from datetime import date
from pathlib import Path

from board_ai_governance import (
    DecisionRights,
    Policy,
    breached,
    evaluate,
    read_register,
)
from board_ai_governance.cli import main

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/ai-risk-register.csv"
RIGHTS_FILE = ROOT / "examples/decision-rights.json"
AS_OF = date(2026, 9, 12)
RIGHTS = DecisionRights({
    "critical": ("Board", "Chief Executive"),
    "high": ("Chief Risk Officer",),
    "medium": ("Customer Operations Director",),
})
HEADER = (
    "id,system,owner,decision,impact,likelihood,control_strength,status,next_review,"
    "assurance,evidence,date_opened,decision_due,decided_on,decided_by\n"
)


def write(tmp_path, *rows, name="risks.csv"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    path.write_text(HEADER + "".join(rows))
    return path


# --- the rights themselves ---

def test_an_authorised_decider_is_permitted():
    assert RIGHTS.permits("critical", "Board")
    assert RIGHTS.permits("critical", "  chief executive  ")


def test_an_unauthorised_decider_is_refused():
    assert not RIGHTS.permits("critical", "Chief People Officer")


def test_a_level_with_no_declared_rights_is_unconstrained():
    assert not RIGHTS.constrains("low")
    assert RIGHTS.permits("low", "Anyone At All")


def test_authority_does_not_carry_upward():
    """A role that may decide a high risk does not thereby decide a critical one."""
    assert RIGHTS.permits("high", "Chief Risk Officer")
    assert not RIGHTS.permits("critical", "Chief Risk Officer")


# --- the gate ---

def test_a_decision_taken_without_the_authority_breaches():
    results = evaluate(read_register(EXAMPLE), Policy(rights=RIGHTS), AS_OF)

    assert breached(results) == results
    assert results[0].detail.startswith("1 decision taken without the authority")
    assert results[0].subjects == (
        "AI-002 Recruitment ranking pilot is critical and was decided by Chief People Officer; "
        "at that level the decision rests with Board or Chief Executive",
    )


def test_a_risk_that_escalated_past_its_approver_fails_from_one_register(tmp_path):
    """The change report needs two snapshots for this; declared rights need only one."""
    path = write(
        tmp_path,
        "AI-1,Pilot,CPO,Approve,critical,likely,strong,open,2027-01-01,asserted,,"
        "2026-01-01,,2026-02-01,Chief Risk Officer\n",
    )

    results = evaluate(read_register(path), Policy(rights=RIGHTS), AS_OF)

    assert breached(results) == results
    assert "is critical and was decided by Chief Risk Officer" in results[0].subjects[0]


def test_an_undecided_risk_is_not_a_rights_breach(tmp_path):
    path = write(
        tmp_path,
        "AI-1,Pilot,CPO,Approve,critical,likely,strong,open,2027-01-01,asserted,,2026-01-01,,,\n",
    )

    assert breached(evaluate(read_register(path), Policy(rights=RIGHTS), AS_OF)) == []


def test_a_closed_risk_is_out_of_scope(tmp_path):
    path = write(
        tmp_path,
        "AI-1,Pilot,CPO,Approve,critical,likely,strong,closed,2027-01-01,asserted,,"
        "2026-01-01,,2026-02-01,Chief People Officer\n",
    )

    assert breached(evaluate(read_register(path), Policy(rights=RIGHTS), AS_OF)) == []


def test_levels_with_no_declared_rights_are_named_rather_than_assumed_safe(tmp_path):
    path = write(
        tmp_path,
        "AI-1,Small,O,Approve,low,rare,strong,open,2027-01-01,independent,e.md,"
        "2026-01-01,,2026-02-01,Anyone\n",
    )
    results = evaluate(read_register(path), Policy(rights=RIGHTS), AS_OF)

    assert results[0].passed
    assert results[0].detail.endswith("; no rights declared for low")


def test_rights_are_part_of_a_policy():
    assert not Policy(rights=RIGHTS).is_empty
    assert Policy().is_empty


# --- the file ---

def test_the_shipped_rights_file_fails_the_shipped_register(capsys):
    assert main([
        "check", str(EXAMPLE), "--as-of", "2026-09-12", "--rights", str(RIGHTS_FILE),
    ]) == 1
    assert "at that level the decision rests with Board or Chief Executive" in capsys.readouterr().out


def test_an_unknown_level_in_the_rights_file_is_refused(tmp_path, capsys):
    path = tmp_path / "rights.json"
    path.write_text(json.dumps({"catastrophic": ["Board"]}))

    assert main(["check", str(EXAMPLE), "--rights", str(path)]) == 2
    assert "catastrophic is not a level" in capsys.readouterr().err


def test_a_level_declaring_no_decider_is_refused(tmp_path, capsys):
    path = tmp_path / "rights.json"
    path.write_text(json.dumps({"critical": []}))

    assert main(["check", str(EXAMPLE), "--rights", str(path)]) == 2
    assert "remove the level to leave it unconstrained" in capsys.readouterr().err


def test_malformed_rights_are_reported_cleanly(tmp_path, capsys):
    path = tmp_path / "rights.json"
    path.write_text("{not json")

    assert main(["check", str(EXAMPLE), "--rights", str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_non_string_deciders_are_refused(tmp_path, capsys):
    path = tmp_path / "rights.json"
    path.write_text(json.dumps({"critical": [1, 2]}))

    assert main(["check", str(EXAMPLE), "--rights", str(path)]) == 2
    assert "critical must list deciders as strings" in capsys.readouterr().err
