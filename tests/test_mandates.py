"""Authority delegated to AI agents, and where it does not hold.

Agentic systems act on someone's behalf and spawn agents that act on theirs. The board is
accountable for the end of that chain. These tests hold the four rules docs/agent-mandates.md
states: authority does not grow through delegation, every acting agent can be stopped,
autonomy waits for the decision, and a chain is accountable only as far as someone follows it.
"""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from board_ai_governance import Policy, breached, evaluate, read_register
from board_ai_governance.cli import main
from board_ai_governance.mandates import (
    MandateError,
    escalations,
    load_mandates,
    premature_autonomy,
    render_mandates,
    stop_problems,
    too_deep,
    undeclared_principals,
    ungoverned_systems,
)

ROOT = Path(__file__).parents[1]
MANDATES = ROOT / "examples/agent-mandates.json"
REGISTER = ROOT / "examples/ai-risk-register.csv"
INVENTORY = ROOT / "examples/ai-systems.json"
AS_OF = date(2026, 9, 12)


def raw():
    return json.loads(MANDATES.read_text())


def mandates(edit=None):
    value = raw()
    if edit:
        edit(value)
    return load_mandates(value)


def agent(value, name):
    return next(item for item in value["agents"] if item["name"] == name)


def risks():
    return read_register(REGISTER)


def results(value=None, **policy):
    return {
        result.rule: result
        for result in evaluate(risks(), Policy(mandates=value or mandates(), **policy), AS_OF)
    }


# --- authority does not grow through delegation ---------------------------------------

def test_a_sub_agent_cannot_hold_what_its_parent_does_not():
    grown = {item.agent.name: item for item in escalations(mandates())}
    assert set(grown) == {"refund-worker", "release-agent"}
    assert grown["refund-worker"].extra == ("refund:up_to_100",)
    assert not grown["refund-worker"].from_principal


def test_the_principal_authorising_a_scope_does_not_let_a_child_skip_its_parent():
    """The director authorised refunds; the orchestrator never held them to pass on."""
    message = next(
        item for item in escalations(mandates()) if item.agent.name == "refund-worker"
    ).describe(mandates())
    assert "cannot grant what it does not hold" in message
    assert "has not authorised" not in message


def test_a_scope_nobody_in_the_chain_authorised_says_so():
    message = next(
        item for item in escalations(mandates()) if item.agent.name == "release-agent"
    ).describe(mandates())
    assert "Chief Technology Officer has not authorised deploy:production either" in message


def test_a_root_agent_is_held_to_its_principal():
    def edit(value):
        agent(value, "coding-planner")["scopes"].append("deploy:production")
    grown = [item for item in escalations(mandates(edit)) if item.agent.name == "coding-planner"]
    assert grown and grown[0].from_principal


def test_giving_the_parent_the_scope_resolves_it():
    def edit(value):
        agent(value, "support-orchestrator")["scopes"].append("refund:up_to_100")
    assert "refund-worker" not in {item.agent.name for item in escalations(mandates(edit))}


def test_an_undeclared_principal_is_untestable_not_unlimited():
    (name, agents), = undeclared_principals(mandates())
    assert name == "Chief Operating Officer"
    assert [item.name for item in agents] == ["meeting-notes"]
    assert "could not be tested" in results()["delegated authority"].detail


def test_principals_match_case_insensitively():
    def edit(value):
        agent(value, "coding-planner")["acts_for"] = "chief technology officer"
    assert "coding-planner" not in {item.agent.name for item in escalations(mandates(edit))}


# --- every acting agent can be stopped ------------------------------------------------

def test_a_sub_agent_that_survives_its_parents_stop_is_named():
    problems = {item.agent.name: item for item in stop_problems(mandates(), AS_OF)}
    assert "keeps running when coding-worker is stopped" in problems["release-agent"].reason


def test_a_stale_stop_test_names_the_agents_relying_on_it():
    problems = {item.agent.name: item for item in stop_problems(mandates(), AS_OF)}
    planner = problems["coding-planner"]
    assert "194 days ago" in planner.reason and "90-day limit" in planner.reason
    assert [item.name for item in planner.relying] == ["coding-worker"]
    assert planner.describe().endswith("coding-worker acts on the strength of that stop.")


def test_a_stop_tested_inside_the_window_passes():
    def edit(value):
        agent(value, "coding-planner")["stop_tested_on"] = "2026-07-01"
    names = {item.agent.name for item in stop_problems(mandates(edit), AS_OF)}
    assert "coding-planner" not in names


def test_a_stop_never_tested_is_a_problem():
    def edit(value):
        del agent(value, "support-orchestrator")["stop_tested_on"]
    problem = next(
        item for item in stop_problems(mandates(edit), AS_OF)
        if item.agent.name == "support-orchestrator"
    )
    assert "never been tested" in problem.reason
    assert [item.name for item in problem.relying] == ["refund-worker"]


def test_a_stop_test_dated_after_the_report_is_not_counted():
    def edit(value):
        agent(value, "support-orchestrator")["stop_tested_on"] = "2026-10-01"
    reasons = [item.reason for item in stop_problems(mandates(edit), AS_OF)]
    assert any("after the reporting date" in reason for reason in reasons)


def test_a_suggesting_root_with_an_acting_child_still_needs_a_stop_owner():
    def edit(value):
        root = agent(value, "support-orchestrator")
        root["autonomy"] = "suggest"
        del root["stop_owner"]
    problem = next(
        item for item in stop_problems(mandates(edit), AS_OF)
        if item.agent.name == "support-orchestrator"
    )
    assert "nobody named as owner of its stop" in problem.reason


def test_an_agent_below_a_detached_link_is_not_reached_either():
    def edit(value):
        value["agents"].append({
            "name": "release-helper", "spawned_by": "release-agent",
            "scopes": ["read:source"], "autonomy": "act", "stops_with_parent": True,
        })
    problem = next(
        item for item in stop_problems(mandates(edit), AS_OF)
        if item.agent.name == "release-helper"
    )
    assert "below release-agent" in problem.reason


def test_without_a_window_any_test_counts_and_the_result_says_so():
    def edit(value):
        del value["stop_test_within_days"]
    assert "coding-planner" not in {item.agent.name for item in stop_problems(mandates(edit), AS_OF)}
    assert "no test window declared" in results(mandates(edit))["agent stop"].detail


# --- autonomy waits for the decision --------------------------------------------------

def test_acting_on_a_system_with_its_decision_outstanding_fails():
    (early,) = premature_autonomy(mandates(), risks())
    assert early.risk.id == "AI-003"
    assert [item.name for item in early.agents] == ["coding-planner", "coding-worker", "release-agent"]
    assert "Set the permitted autonomy boundary" in early.describe()


def test_suggesting_agents_do_not_count_as_autonomy():
    def edit(value):
        for item in value["agents"]:
            if item.get("system") == "Developer coding assistant" or item.get("spawned_by", "").startswith("coding"):
                item["autonomy"] = "suggest"
        agent(value, "release-agent")["autonomy"] = "suggest"
    assert premature_autonomy(mandates(edit), risks()) == ()


def test_a_decided_system_is_clear():
    """AI-001's decision to expand beyond drafting was taken, so its agents may act."""
    systems = {item.system for item in premature_autonomy(mandates(), risks())}
    assert "Customer support assistant" not in systems


def test_acting_agents_with_no_register_entry_are_ungoverned():
    def edit(value):
        agent(value, "meeting-notes")["autonomy"] = "act"
        agent(value, "meeting-notes")["stop_owner"] = "Chief Operating Officer"
        agent(value, "meeting-notes")["stop_tested_on"] = "2026-09-01"
    value = mandates(edit)
    assert ungoverned_systems(value, risks()) == ("Meeting transcription",)
    assert not results(value)["agent autonomy"].passed


# --- depth ----------------------------------------------------------------------------

def test_depth_is_counted_in_hops_from_the_person():
    (deep, depth), = too_deep(mandates())
    assert (deep.name, depth) == ("release-agent", 3)


def test_no_declared_depth_means_no_depth_rule():
    def edit(value):
        del value["max_depth"]
    assert too_deep(mandates(edit)) == ()
    assert "delegation depth" not in results(mandates(edit))


# --- the declaration itself -----------------------------------------------------------

@pytest.mark.parametrize("edit, message", [
    (lambda v: v.update(agents=[]), "would pass every check by declaring nothing"),
    (lambda v: agent(v, "refund-worker").update(spawned_by="ghost"), "not declared"),
    (lambda v: agent(v, "refund-worker").update(acts_for="Someone"), "exactly one of"),
    (lambda v: agent(v, "coding-worker").update(autonomy="full"), "autonomy must be one of"),
    (lambda v: agent(v, "coding-planner").update(stop_tested_on="02/03/2026"), "YYYY-MM-DD"),
    (lambda v: agent(v, "coding-planner").update(stops_with_parent=True), "means nothing"),
    (lambda v: v["principals"].update({"Board": []}), "authorise nothing"),
    (lambda v: v.update(max_depth=0), "at least 1"),
    (lambda v: v["agents"].append(copy.deepcopy(agent(v, "coding-worker"))), "more than once"),
])
def test_malformed_declarations_are_refused(edit, message):
    value = raw()
    edit(value)
    with pytest.raises(MandateError, match=message):
        load_mandates(value)


def test_a_cycle_of_agents_answers_to_nobody():
    value = raw()
    agent(value, "coding-planner").pop("acts_for")
    agent(value, "coding-planner").pop("stop_owner")
    agent(value, "coding-planner").pop("stop_tested_on")
    agent(value, "coding-planner")["spawned_by"] = "coding-worker"
    with pytest.raises(MandateError, match="answers to nobody"):
        load_mandates(value)


def test_every_problem_is_reported_at_once():
    value = raw()
    agent(value, "refund-worker")["autonomy"] = "full"
    agent(value, "coding-worker")["scopes"] = "everything"
    with pytest.raises(MandateError) as raised:
        load_mandates(value)
    assert len(raised.value.problems) == 2


# --- the report and the gate ----------------------------------------------------------

def test_the_report_names_what_the_board_has_to_answer():
    report = render_mandates(mandates(), risks(), AS_OF)
    assert "5 act without per-action approval" in report
    assert "3 hops, against a declared limit of 2" in report
    assert "Autonomy granted before that decision is the decision, taken by default." in report
    assert "who would stop it tonight" in report


def test_the_table_reads_from_the_agent_up_to_the_person():
    report = render_mandates(mandates(), risks(), AS_OF)
    assert "| release-agent | Developer coding assistant | act: acts without per-action approval " \
           "| coding-worker → coding-planner → Chief Technology Officer |" in report


def test_a_clean_declaration_reports_none_everywhere():
    def edit(value):
        value["agents"] = [item for item in value["agents"] if item["name"] in {
            "support-orchestrator", "meeting-notes"}]
    value = mandates(edit)
    report = render_mandates(value, risks(), AS_OF)
    assert report.count("- None.") == 4
    assert not breached(evaluate(risks(), Policy(mandates=value), AS_OF))


def test_check_fails_on_the_example(capsys):
    code = main([
        "check", str(REGISTER), "--as-of", "2026-09-12", "--mandates", str(MANDATES),
    ])
    out = capsys.readouterr().out
    assert code == 1
    for rule in ("delegated authority", "agent stop", "agent autonomy", "delegation depth"):
        assert f"FAIL  {rule}" in out


def test_agents_command_writes_the_report(tmp_path, capsys):
    output = tmp_path / "agents.md"
    code = main([
        "agents", str(MANDATES), "--register", str(REGISTER), "--as-of", "2026-09-12",
        "--inventory", str(INVENTORY), "--output", str(output),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "Acting without per-action approval: 5" in out
    assert "Authority grown through delegation: 2" in out
    assert output.read_text().startswith("# AI Agent Mandates — 2026-09-12")
    assert "## Agents Outside The Declared Estate" in output.read_text()


def test_an_invalid_declaration_exits_two(tmp_path, capsys):
    bad = tmp_path / "mandates.json"
    bad.write_text('{"agents": []}')
    assert main(["agents", str(bad), "--register", str(REGISTER)]) == 2
    assert "declaring nothing" in capsys.readouterr().err
