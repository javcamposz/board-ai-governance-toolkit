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
RIGHTS = DecisionRights.from_mapping({
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
        "AI-002 Recruitment ranking pilot was decided by Chief People Officer, and is critical, "
        "where the decision rests with Board or Chief Executive. It is critical only because the "
        "control rating is unevidenced; evidenced it would be high, which is still above that "
        "decider.",
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
    assert "was decided by Chief Risk Officer, and is critical" in results[0].subjects[0]


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
    assert ("evidenced it would be high, where that decider is authorised."
            in capsys.readouterr().out)


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


def test_a_breach_says_when_evidence_alone_would_resolve_it():
    """The adjusted level can fail a decider who is authorised at face value."""
    risk = next(r for r in read_register(EXAMPLE) if r.id == "AI-002")
    assert risk.level == "critical" and risk.face_value_level == "high"

    shipped = DecisionRights.from_mapping(json.loads(RIGHTS_FILE.read_text()))
    assert shipped.permits("high", risk.decided_by)

    subject = evaluate([risk], Policy(rights=shipped), AS_OF)[0].subjects[0]

    assert "It is critical only because the control rating is unevidenced" in subject
    assert "evidenced it would be high, where that decider is authorised." in subject


def test_a_breach_says_when_evidence_would_not_be_enough(tmp_path):
    path = write(
        tmp_path,
        "AI-1,Pilot,O,Approve,critical,likely,strong,open,2027-01-01,asserted,,"
        "2026-01-01,,2026-02-01,Someone Unlisted\n",
    )
    subject = evaluate(read_register(path), Policy(rights=RIGHTS), AS_OF)[0].subjects[0]

    assert "which is still above that decider." in subject


def test_a_breach_at_face_value_makes_no_evidence_claim(tmp_path):
    path = write(
        tmp_path,
        "AI-1,Pilot,O,Approve,critical,almost_certain,weak,open,2027-01-01,independent,e.md,"
        "2026-01-01,,2026-02-01,Chief Risk Officer\n",
    )
    risk = read_register(path)[0]
    assert risk.level == risk.face_value_level == "critical"

    subject = evaluate([risk], Policy(rights=RIGHTS), AS_OF)[0].subjects[0]

    assert "unevidenced" not in subject
    assert subject.endswith("where the decision rests with Board or Chief Executive.")


def test_unconstrained_levels_are_listed_by_severity(tmp_path):
    path = write(
        tmp_path,
        "AI-1,A,O,Approve,low,rare,strong,open,2027-01-01,independent,e.md,"
        "2026-01-01,,2026-02-01,Anyone\n",
        "AI-2,B,O,Approve,medium,likely,strong,open,2027-01-01,independent,e.md,"
        "2026-01-01,,2026-02-01,Customer Operations Director\n",
    )
    rights = DecisionRights.from_mapping({"critical": ["Board"]})
    results = evaluate(read_register(path), Policy(rights=rights), AS_OF)

    assert results[0].detail.endswith("; no rights declared for low, medium")


def test_declared_rights_cannot_be_edited_after_the_fact():
    """The argument for this type is that the rights come from outside the register."""
    source = {"critical": ["Board"]}
    rights = DecisionRights.from_mapping(source)
    source["critical"].append("Anyone")

    assert rights.deciders("critical") == ("Board",)
    assert not rights.permits("critical", "Anyone")
    assert hash(Policy(rights=rights))
