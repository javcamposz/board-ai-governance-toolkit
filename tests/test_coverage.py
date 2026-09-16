"""Which material AI systems are missing from this view.

docs/board-questions.md asks that first under portfolio governance, and the dashboard told
the board to challenge whether the register was complete while giving them nothing to
challenge it with. A register cannot report what it is missing: absence is the one thing it
has no row for, so the estate is declared where the anchors and the rights are.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from board_ai_governance import (
    Inventory,
    Policy,
    Portfolio,
    System,
    breached,
    evaluate,
    read_register,
    render_dashboard,
)
from board_ai_governance.cli import main

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/ai-risk-register.csv"
SYSTEMS_FILE = ROOT / "examples/ai-systems.json"
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


def shipped_inventory():
    return Inventory.from_records(json.loads(SYSTEMS_FILE.read_text())["systems"])


def coverage(risks=None, inventory=None):
    return Portfolio(
        as_of=AS_OF, risks=tuple(risks if risks is not None else read_register(EXAMPLE))
    ).coverage(inventory or shipped_inventory())


# --- the estate ---

def test_only_material_systems_are_expected_in_the_register():
    inventory = shipped_inventory()

    assert len(inventory.systems) == 6
    assert len(inventory.material) == 5
    assert inventory.find("Meeting transcription").tier == "routine"


def test_a_system_is_found_regardless_of_case_and_padding():
    inventory = Inventory((System("Customer support assistant", "material"),))

    assert inventory.find("  CUSTOMER SUPPORT ASSISTANT ") is not None
    assert inventory.find("something else") is None


# --- what the register is silent on ---

def test_a_material_system_with_no_entry_is_named():
    result = coverage()

    assert [system.name for system in result.unregistered] == ["Marketing copy assistant"]


def test_a_material_system_whose_only_entry_is_closed_is_named_separately():
    """Worse than absence: the register looks considered and reports nothing current."""
    result = coverage()

    assert [system.name for system in result.only_closed] == ["Fraud triage model"]
    assert result.material_count == 5
    assert len(result.blind_spots) == 2
    assert not result.is_complete


def test_a_material_system_with_an_active_entry_is_covered():
    result = coverage()

    assert {system.name for system in result.covered} == {
        "Customer support assistant", "Recruitment ranking pilot", "Developer coding assistant",
    }


def test_a_routine_system_is_not_expected_in_the_register():
    result = coverage()

    assert "Meeting transcription" not in {system.name for system in result.blind_spots}


def test_a_risk_about_a_system_not_on_the_estate_is_reported(tmp_path):
    path = write(
        tmp_path,
        "AI-1,Shadow tool,O,Decide,high,likely,strong,open,2027-01-01,asserted,,,,,\n",
    )
    result = coverage(read_register(path))

    assert result.unlisted == ("Shadow tool",)


def test_a_closed_entry_for_an_unlisted_system_is_not_reported(tmp_path):
    """The concern is something running unlisted, not something retired and unlisted."""
    path = write(
        tmp_path,
        "AI-1,Shadow tool,O,Decide,high,likely,strong,closed,2027-01-01,asserted,,,,,\n",
    )

    assert coverage(read_register(path)).unlisted == ()


def test_a_complete_register_is_complete():
    inventory = Inventory((
        System("Customer support assistant", "material"),
        System("Recruitment ranking pilot", "material"),
    ))
    result = coverage(inventory=inventory)

    assert result.is_complete
    assert result.blind_spots == ()


# --- the dashboard ---

def test_the_dashboard_says_nothing_about_the_estate_without_one():
    assert "Systems Missing From This View" not in render_dashboard(read_register(EXAMPLE), AS_OF)


def test_the_dashboard_tables_what_is_missing_and_why():
    report = render_dashboard(read_register(EXAMPLE), AS_OF, shipped_inventory())
    section = report.split("## Systems Missing From This View", 1)[1].split("## Board", 1)[0]

    assert "| Marketing copy assistant | material | Chief Marketing Officer | No entry" in section
    assert "| Fraud triage model | material | Chief Risk Officer | Its only entries are closed" in section
    assert "2 of 5 material systems are running without a current entry" in section
    assert "A closed entry is the worse of the two" in section


def test_a_complete_register_is_told_to_challenge_the_estate_instead():
    inventory = Inventory((System("Customer support assistant", "material"),))
    report = render_dashboard(read_register(EXAMPLE), AS_OF, inventory)

    assert "Challenge the estate rather than the register" in report
    assert "not that the list of systems is right" in report


def test_the_dashboard_reports_something_running_unlisted(tmp_path):
    path = write(tmp_path, "AI-1,Shadow tool,O,Decide,high,likely,strong,open,2027-01-01,asserted,,,,,\n")
    report = render_dashboard(read_register(path), AS_OF, shipped_inventory())

    assert "**Shadow tool** carries an active risk and is not on the estate" in report
    assert "Either the estate is out of date or something is running unlisted" in report


# --- the gate ---

def test_a_material_system_without_a_current_entry_breaches():
    results = evaluate(read_register(EXAMPLE), Policy(inventory=shipped_inventory()), AS_OF)

    assert breached(results) == results
    assert results[0].detail == "2 material systems of 5 running without a current entry"
    assert results[0].subjects == (
        "Marketing copy assistant (Chief Marketing Officer) has no entry in the register",
        "Fraud triage model (Chief Risk Officer) has only closed entries, so nothing current "
        "is reported",
    )


def test_an_unlisted_system_is_noted_but_does_not_breach_on_its_own(tmp_path):
    path = write(
        tmp_path,
        "AI-1,Customer support assistant,O,Decide,high,likely,strong,open,2027-01-01,asserted,,,,,\n",
        "AI-2,Shadow tool,O,Decide,low,rare,strong,open,2027-01-01,asserted,,,,,\n",
    )
    inventory = Inventory((System("Customer support assistant", "material"),))
    results = evaluate(read_register(path), Policy(inventory=inventory), AS_OF)

    assert breached(results) == []
    assert "1 recorded and not on the declared estate" in results[0].detail


def test_an_inventory_is_part_of_a_policy():
    assert not Policy(inventory=shipped_inventory()).is_empty


# --- the file ---

def test_the_shipped_estate_fails_the_shipped_register(capsys):
    assert main([
        "check", str(EXAMPLE), "--as-of", "2026-09-12", "--inventory", str(SYSTEMS_FILE),
    ]) == 1
    assert "has only closed entries" in capsys.readouterr().out


def test_summarize_reports_coverage_when_given_an_estate(capsys, tmp_path):
    assert main([
        "summarize", str(EXAMPLE), "--as-of", "2026-09-12",
        "--inventory", str(SYSTEMS_FILE), "--output", str(tmp_path / "board.md"),
    ]) == 0
    assert "Material systems with no current entry: 2 of 5" in capsys.readouterr().out


@pytest.mark.parametrize("payload,expected", [
    ({"systems": [{"name": "A"}]}, "system 0 missing: tier"),
    ({"systems": [{"name": "A", "tier": "vital"}]}, "A tier is 'vital'"),
    ({"systems": [{"name": "", "tier": "material"}]}, "system 0 name must not be empty"),
    ({"systems": [{"name": "A", "tier": "material"}, {"name": "a", "tier": "routine"}]},
     "a is listed more than once"),
    ({"systems": "not a list"}, 'must be a JSON object with a "systems" array'),
])
def test_a_malformed_estate_is_refused(tmp_path, capsys, payload, expected):
    path = tmp_path / "systems.json"
    path.write_text(json.dumps(payload))

    assert main(["check", str(EXAMPLE), "--inventory", str(path)]) == 2
    assert expected in capsys.readouterr().err


def test_a_non_json_estate_is_reported_cleanly(tmp_path, capsys):
    path = tmp_path / "systems.json"
    path.write_text("{not json")

    assert main(["check", str(EXAMPLE), "--inventory", str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_an_estate_with_no_material_systems_fails_rather_than_passes():
    """A check an empty declaration satisfies produces a green result for no claim."""
    inventory = Inventory((System("Meeting transcription", "routine"),))
    results = evaluate(read_register(EXAMPLE), Policy(inventory=inventory), AS_OF)

    assert breached(results) == results
    assert results[0].detail.startswith(
        "the declared estate lists no material systems, so nothing was checked"
    )
    # The evidence that the estate is wrong belongs on the same line as the failure.
    assert "3 recorded and not on the declared estate" in results[0].detail


def test_an_entirely_empty_estate_fails_too():
    results = evaluate(read_register(EXAMPLE), Policy(inventory=Inventory(())), AS_OF)

    assert breached(results) == results


# --- what the review found ---

def test_the_cli_refuses_an_estate_that_declares_nothing_material(tmp_path, capsys):
    """The gate must not be satisfiable by emptying the file it checks."""
    path = tmp_path / "systems.json"
    path.write_text(json.dumps({"systems": []}))

    assert main(["check", str(EXAMPLE), "--inventory", str(path)]) == 2
    err = capsys.readouterr().err
    assert "declares no material systems" in err
    assert "would pass by declaring nothing" in err


def test_the_cli_refuses_an_all_routine_estate(tmp_path, capsys):
    path = tmp_path / "systems.json"
    path.write_text(json.dumps({"systems": [{"name": "Transcription", "tier": "routine"}]}))

    assert main(["summarize", str(EXAMPLE), "--inventory", str(path)]) == 2
    assert "declares no material systems" in capsys.readouterr().err


def test_the_dashboard_does_not_call_an_empty_estate_complete():
    report = render_dashboard(read_register(EXAMPLE), AS_OF, Inventory(()))

    assert "Every one of the 0" not in report
    assert "lists no material systems, so nothing here says the register is complete" in report
    assert "It says only that nothing was claimed." in report


def test_a_tier_the_cli_would_reject_is_rejected_by_the_constructor_too():
    """A tier the rule does not recognise silently removes a system from the check."""
    from board_ai_governance.inventory import InventoryError

    with pytest.raises(InventoryError, match="tier is 'materail'"):
        Inventory.from_records([{"name": "Payments model", "tier": "materail"}])

    with pytest.raises(InventoryError, match="tier is 'vital'"):
        System("Payments model", "vital")


def test_a_valid_tier_is_still_accepted_in_any_case():
    inventory = Inventory.from_records([{"name": "A", "tier": " Material "}])

    assert inventory.material[0].name == "A"
    assert inventory.declares_material_systems


def test_declares_material_systems_reads_the_tier_not_the_count():
    assert not Inventory((System("A", "routine"),)).declares_material_systems
    assert Inventory((System("A", "material"),)).declares_material_systems
