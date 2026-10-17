"""AI agents acting on someone's behalf, and the authority they act with.

The register holds risks and the decisions they need. It was written for systems that
recommend and people that act. Agentic systems act: a support orchestrator replies to
customers, spawns a worker that issues refunds, and the worker spawns another to chase the
payment provider. Each of those is a delegation of authority, and the board is accountable
for the end of the chain, not the first link.

So the agents are declared beside the estate and the decision rights, outside the
register, with what each accountable owner has authorised agents to do on their behalf.
Four things are then checkable that the register cannot see:

* **Authority does not grow through delegation.** An agent cannot hold a scope its parent
  does not hold, and a root agent cannot hold one its principal never authorised. The
  register already refuses to let a decision's authority carry upward to a higher risk
  level; this is the same rule, read down a chain of agents.
* **Every acting agent can be stopped.** An agent that acts without per-action approval
  needs a named owner of its stop and a recent test of it, and a sub-agent that keeps
  running when its parent is stopped has a stop that does not reach it.
* **Autonomy waits for the decision.** An agent acting autonomously on a system whose
  register entry still has a decision outstanding has been given, in practice, the answer
  the board has not yet given.
* **A chain is only accountable as far as someone can follow it.** Depth is declared,
  because how many hops a board will trace is a choice and not a fact.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from .inventory import Inventory
from .register import Risk

AUTONOMY = ("suggest", "approve", "act")
AUTONOMY_MEANING = {
    "suggest": "proposes; a person carries out",
    "approve": "acts after a person approves each action",
    "act": "acts without per-action approval",
}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MandateError(ValueError):
    """Every problem found in a declaration of agent mandates, reported together."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class Agent:
    name: str
    scopes: tuple[str, ...]
    autonomy: str
    system: str = ""
    acts_for: str = ""
    spawned_by: str = ""
    stop_owner: str = ""
    stop_tested_on: date | None = None
    stops_with_parent: bool = False

    @property
    def is_root(self) -> bool:
        return not self.spawned_by

    @property
    def acts(self) -> bool:
        return self.autonomy == "act"


@dataclass(frozen=True)
class Mandates:
    """What each accountable owner has authorised agents to do, and the agents doing it."""

    principals: tuple[tuple[str, tuple[str, ...]], ...]
    agents: tuple[Agent, ...]
    max_depth: int | None = None
    stop_test_within_days: int | None = None

    def agent(self, name: str) -> Agent:
        for agent in self.agents:
            if agent.name == name:
                return agent
        raise KeyError(name)

    def chain(self, agent: Agent) -> tuple[Agent, ...]:
        """The agent and every agent above it, root first."""
        links = [agent]
        while not links[0].is_root:
            links.insert(0, self.agent(links[0].spawned_by))
        return tuple(links)

    def root(self, agent: Agent) -> Agent:
        return self.chain(agent)[0]

    def depth(self, agent: Agent) -> int:
        """Hops from the accountable person: a root agent is one."""
        return len(self.chain(agent))

    def principal(self, agent: Agent) -> str:
        return self.root(agent).acts_for

    def system(self, agent: Agent) -> str:
        """A sub-agent works on its parent's system unless it says otherwise."""
        for link in reversed(self.chain(agent)):
            if link.system:
                return link.system
        return ""

    def principal_scopes(self, name: str) -> tuple[str, ...] | None:
        wanted = name.strip().casefold()
        for principal, scopes in self.principals:
            if principal.strip().casefold() == wanted:
                return scopes
        return None

    def descendants(self, agent: Agent) -> tuple[Agent, ...]:
        return tuple(
            other for other in self.agents
            if other is not agent and agent in self.chain(other)
        )

    def answers_to(self, agent: Agent, include_self: bool = True) -> str:
        """The chain as a board would read it, from the agent up to the person."""
        names = [link.name for link in reversed(self.chain(agent))]
        if not include_self:
            names = names[1:]
        return " → ".join([*names, self.principal(agent) or "nobody"])


# --- reading the declaration -------------------------------------------------------------

def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def load_mandates(value: object) -> Mandates:
    """Validate a declaration, reporting every problem in one pass."""
    if not isinstance(value, dict):
        raise MandateError(['agent mandates must be a JSON object with "principals" and "agents"'])
    problems: list[str] = []

    principals: list[tuple[str, tuple[str, ...]]] = []
    raw_principals = value.get("principals", {})
    if not isinstance(raw_principals, dict):
        problems.append("principals must map each accountable owner to the scopes they have "
                        "authorised agents to use")
        raw_principals = {}
    for name, scopes in raw_principals.items():
        if not _strings(scopes) or not scopes:
            problems.append(
                f"principal {name} must list the scopes they authorise as non-empty strings; "
                "leave a principal out rather than declare that they authorise nothing"
            )
            continue
        principals.append((name.strip(), tuple(scope.strip() for scope in scopes)))

    settings: dict[str, int | None] = {}
    for setting in ("max_depth", "stop_test_within_days"):
        raw = value.get(setting)
        if raw is not None and (not isinstance(raw, int) or isinstance(raw, bool) or raw < 1):
            problems.append(f"{setting} must be a whole number of at least 1")
            raw = None
        settings[setting] = raw

    raw_agents = value.get("agents")
    if not isinstance(raw_agents, list) or not raw_agents:
        problems.append(
            "agents must be a non-empty list; a declaration with no agents would pass every "
            "check by declaring nothing"
        )
        raise MandateError(problems)

    agents: list[Agent] = []
    seen: set[str] = set()
    for index, record in enumerate(raw_agents):
        if not isinstance(record, dict):
            problems.append(f"agent {index} must be a JSON object")
            continue
        name = str(record.get("name", "")).strip()
        label = name or f"agent {index}"
        if not name:
            problems.append(f"agent {index} needs a name")
        elif name in seen:
            problems.append(f"{name} is declared more than once")
        seen.add(name)

        scopes = record.get("scopes")
        if not _strings(scopes):
            problems.append(f"{label} scopes must be a list of non-empty strings")
            scopes = []
        autonomy = str(record.get("autonomy", "")).strip().lower()
        if autonomy not in AUTONOMY:
            problems.append(f"{label} autonomy must be one of {', '.join(AUTONOMY)}")

        acts_for = str(record.get("acts_for", "") or "").strip()
        spawned_by = str(record.get("spawned_by", "") or "").strip()
        if bool(acts_for) == bool(spawned_by):
            problems.append(
                f"{label} must name exactly one of acts_for (the person it answers to) or "
                "spawned_by (the agent that created it)"
            )
        system = str(record.get("system", "") or "").strip()
        if acts_for and not system:
            problems.append(f"{label} acts for {acts_for} and must name the system it runs in")

        tested = record.get("stop_tested_on")
        tested_on: date | None = None
        if tested not in (None, ""):
            if not isinstance(tested, str) or not ISO_DATE.match(tested):
                problems.append(f"{label} stop_tested_on must be YYYY-MM-DD")
            else:
                try:
                    tested_on = date.fromisoformat(tested)
                except ValueError:
                    problems.append(f"{label} stop_tested_on is not a real date")
        stops_with_parent = record.get("stops_with_parent", False)
        if not isinstance(stops_with_parent, bool):
            problems.append(f"{label} stops_with_parent must be true or false")
            stops_with_parent = False
        if acts_for and record.get("stops_with_parent") is not None:
            problems.append(f"{label} has no parent agent, so stops_with_parent means nothing")

        agents.append(Agent(
            name=name,
            scopes=tuple(scope.strip() for scope in scopes),
            autonomy=autonomy,
            system=system,
            acts_for=acts_for,
            spawned_by=spawned_by,
            stop_owner=str(record.get("stop_owner", "") or "").strip(),
            stop_tested_on=tested_on,
            stops_with_parent=stops_with_parent,
        ))

    names = {agent.name for agent in agents}
    for agent in agents:
        if agent.spawned_by and agent.spawned_by not in names:
            problems.append(f"{agent.name} is spawned by {agent.spawned_by}, which is not declared")
    if not problems:
        by_name = {agent.name: agent for agent in agents}
        for agent in agents:
            path = [agent.name]
            current = agent
            while current.spawned_by:
                current = by_name[current.spawned_by]
                if current.name in path:
                    problems.append(
                        f"{agent.name} is in a cycle of agents spawning each other "
                        f"({' → '.join([*path, current.name])}), so it answers to nobody"
                    )
                    break
                path.append(current.name)

    if problems:
        raise MandateError(problems)
    return Mandates(
        principals=tuple(principals),
        agents=tuple(agents),
        max_depth=settings["max_depth"],
        stop_test_within_days=settings["stop_test_within_days"],
    )


# --- what the declaration says ------------------------------------------------------------

@dataclass(frozen=True)
class Escalation:
    """Scopes an agent holds that whoever granted its authority did not."""

    agent: Agent
    extra: tuple[str, ...]
    granted_by: str
    from_principal: bool

    def describe(self, mandates: Mandates) -> str:
        if self.from_principal:
            return (
                f"{self.agent.name} holds {', '.join(self.extra)}, which {self.granted_by} has "
                "not authorised agents to use on their behalf."
            )
        principal = mandates.principal(self.agent)
        held = mandates.principal_scopes(principal) or ()
        above = [scope for scope in self.extra if scope not in held]
        note = (
            f" {principal} has not authorised {', '.join(above)} either."
            if above and mandates.principal_scopes(principal) is not None else ""
        )
        return (
            f"{self.agent.name} holds {', '.join(self.extra)}, which {self.granted_by}, the "
            f"agent that spawned it, does not. Authority does not grow through delegation: "
            f"an agent cannot grant what it does not hold.{note}"
        )


def escalations(mandates: Mandates) -> tuple[Escalation, ...]:
    found: list[Escalation] = []
    for agent in mandates.agents:
        if agent.is_root:
            held = mandates.principal_scopes(agent.acts_for)
            if held is None:
                continue
            extra = tuple(scope for scope in agent.scopes if scope not in held)
            if extra:
                found.append(Escalation(agent, extra, agent.acts_for, True))
        else:
            parent = mandates.agent(agent.spawned_by)
            extra = tuple(scope for scope in agent.scopes if scope not in parent.scopes)
            if extra:
                found.append(Escalation(agent, extra, parent.name, False))
    return tuple(found)


def undeclared_principals(mandates: Mandates) -> tuple[tuple[str, tuple[Agent, ...]], ...]:
    """Principals whose agents' authority cannot be tested, because nobody said what it is."""
    found: dict[str, list[Agent]] = {}
    for agent in mandates.agents:
        if agent.is_root and mandates.principal_scopes(agent.acts_for) is None:
            found.setdefault(agent.acts_for, []).append(agent)
    return tuple((name, tuple(agents)) for name, agents in found.items())


@dataclass(frozen=True)
class StopProblem:
    agent: Agent
    reason: str
    relying: tuple[Agent, ...] = ()

    def describe(self) -> str:
        if not self.relying:
            return f"{self.agent.name}: {self.reason}."
        names = ", ".join(agent.name for agent in self.relying)
        verb = "acts" if len(self.relying) == 1 else "act"
        return f"{self.agent.name}: {self.reason}, and {names} {verb} on the strength of that stop."


def stop_problems(mandates: Mandates, as_of: date) -> tuple[StopProblem, ...]:
    """Which acting agents a declared stop does not reliably reach.

    An acting sub-agent's stop is its root's stop, reached through every link that stops
    with its parent. A link that does not is the problem, wherever it is; past it, the
    root's stop is reported once with the acting agents relying on it.
    """
    problems: list[StopProblem] = []
    relying: dict[str, list[Agent]] = {}
    for agent in mandates.agents:
        if not agent.acts:
            continue
        chain = mandates.chain(agent)
        detached = next((link for link in reversed(chain[1:]) if not link.stops_with_parent), None)
        if detached is not None:
            problems.append(StopProblem(
                agent,
                f"keeps running when {detached.spawned_by} is stopped"
                if detached is agent else
                f"is below {detached.name}, which keeps running when {detached.spawned_by} is "
                "stopped, so stopping the chain does not reach it",
            ))
            continue
        relying.setdefault(chain[0].name, []).append(agent)

    window = mandates.stop_test_within_days
    for root_name, acting in relying.items():
        root = mandates.agent(root_name)
        others = tuple(agent for agent in acting if agent is not root)
        if not root.stop_owner:
            reason = "acts without per-action approval and nobody owns its stop" if root.acts \
                else "has nobody named as owner of its stop"
        elif root.stop_tested_on is None:
            reason = f"its stop, owned by {root.stop_owner}, has never been tested"
        elif root.stop_tested_on > as_of:
            reason = (
                f"its stop test is dated {root.stop_tested_on.isoformat()}, after the reporting "
                "date, and cannot be counted"
            )
        elif window is not None and (as_of - root.stop_tested_on).days > window:
            reason = (
                f"its stop, owned by {root.stop_owner}, was last tested "
                f"{(as_of - root.stop_tested_on).days} days ago, against a declared "
                f"{window}-day limit"
            )
        else:
            continue
        problems.append(StopProblem(root, reason, others))
    return tuple(problems)


@dataclass(frozen=True)
class PrematureAutonomy:
    system: str
    risk: Risk
    agents: tuple[Agent, ...]

    def describe(self) -> str:
        names = ", ".join(agent.name for agent in self.agents)
        return (
            f"{names} act without per-action approval on {self.system}, where {self.risk.id} "
            f"still asks the board to decide: {self.risk.decision.rstrip('.')}. "
            f"Autonomy granted before that decision is the decision, taken by default."
        )


def premature_autonomy(mandates: Mandates, risks: Sequence[Risk]) -> tuple[PrematureAutonomy, ...]:
    found: list[PrematureAutonomy] = []
    acting: dict[str, list[Agent]] = {}
    for agent in mandates.agents:
        if agent.acts:
            acting.setdefault(mandates.system(agent).casefold(), []).append(agent)
    for risk in risks:
        if not risk.is_active or risk.is_decided:
            continue
        agents = acting.get(risk.system.strip().casefold())
        if agents:
            found.append(PrematureAutonomy(risk.system, risk, tuple(agents)))
    return tuple(found)


def too_deep(mandates: Mandates) -> tuple[tuple[Agent, int], ...]:
    if mandates.max_depth is None:
        return ()
    return tuple(
        (agent, mandates.depth(agent)) for agent in mandates.agents
        if mandates.depth(agent) > mandates.max_depth
    )


def off_estate(mandates: Mandates, inventory: Inventory) -> tuple[tuple[str, tuple[Agent, ...]], ...]:
    found: dict[str, list[Agent]] = {}
    for agent in mandates.agents:
        system = mandates.system(agent)
        if inventory.find(system) is None:
            found.setdefault(system, []).append(agent)
    return tuple((system, tuple(agents)) for system, agents in found.items())


def ungoverned_systems(mandates: Mandates, risks: Sequence[Risk]) -> tuple[str, ...]:
    """Systems with acting agents and no active entry in the register at all."""
    registered = {risk.system.strip().casefold() for risk in risks if risk.is_active}
    systems: list[str] = []
    for agent in mandates.agents:
        system = mandates.system(agent)
        if agent.acts and system.casefold() not in registered and system not in systems:
            systems.append(system)
    return tuple(systems)


# --- the board report --------------------------------------------------------------------

def render_mandates(
    mandates: Mandates,
    risks: Sequence[Risk],
    as_of: date,
    inventory: Inventory | None = None,
) -> str:
    acting = [agent for agent in mandates.agents if agent.acts]
    systems = sorted({mandates.system(agent) for agent in mandates.agents})
    deepest = max(mandates.depth(agent) for agent in mandates.agents)
    lines = [
        f"# AI Agent Mandates — {as_of.isoformat()}",
        "",
        f"{len(mandates.agents)} agents across {len(systems)} systems. {len(acting)} act without "
        f"per-action approval. The longest chain from an agent to the person it answers to is "
        f"{deepest} {'hop' if deepest == 1 else 'hops'}"
        + (f", against a declared limit of {mandates.max_depth}." if mandates.max_depth else "."),
        "",
        "## Who Each Agent Answers To",
        "",
        "| Agent | System | Autonomy | Answers to | Scopes |",
        "|---|---|---|---|---|",
    ]
    for agent in sorted(mandates.agents, key=lambda item: (mandates.system(item), mandates.depth(item), item.name)):
        lines.append(
            f"| {agent.name} | {mandates.system(agent)} | {agent.autonomy}: "
            f"{AUTONOMY_MEANING[agent.autonomy]} | {mandates.answers_to(agent, include_self=False)} | "
            f"{', '.join(agent.scopes)} |"
        )

    def section(title: str, items: list[str], empty: str) -> None:
        lines.extend(["", f"## {title}", ""])
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append(f"- {empty}")

    section(
        "Authority That Grew Through Delegation",
        [item.describe(mandates) for item in escalations(mandates)],
        "None. Every agent holds only scopes its parent or principal holds.",
    )
    undeclared = undeclared_principals(mandates)
    if undeclared:
        lines.append("")
        for name, agents in undeclared:
            lines.append(
                f"- **Untestable:** {name} has not declared what agents may do on their behalf, "
                f"so the authority of {', '.join(agent.name for agent in agents)} cannot be "
                "checked. Unstated is not the same as unlimited, and it should not read as either."
            )

    window = (
        f"within {mandates.stop_test_within_days} days" if mandates.stop_test_within_days
        else "at some point; no window is declared, so any test counts however old"
    )
    section(
        "Agents The Declared Stop Does Not Reach",
        [item.describe() for item in stop_problems(mandates, as_of)],
        f"None. Every acting agent stops with a root whose stop is owned and was tested {window}.",
    )
    section(
        "Autonomy Granted Before The Decision",
        [item.describe() for item in premature_autonomy(mandates, risks)],
        "None. No agent acts autonomously on a system with a decision outstanding.",
    )
    ungoverned = ungoverned_systems(mandates, risks)
    if ungoverned:
        lines.append("")
        for system in ungoverned:
            lines.append(
                f"- **{system}** has agents acting autonomously and no active entry in the "
                "register, so there is no risk, owner or decision recorded for what they do."
            )
    if mandates.max_depth is not None:
        section(
            "Chains Longer Than The Board Will Follow",
            [
                f"{agent.name} is {depth} hops from {mandates.principal(agent)}: "
                f"{mandates.answers_to(agent)}."
                for agent, depth in too_deep(mandates)
            ],
            f"None. Every agent is within {mandates.max_depth} hops of the person it answers to.",
        )
    if inventory is not None:
        section(
            "Agents Outside The Declared Estate",
            [
                f"{', '.join(agent.name for agent in agents)} run in {system}, which is not on the "
                "declared estate: either the estate is out of date or something is running unlisted."
                for system, agents in off_estate(mandates, inventory)
            ],
            "None. Every agent runs in a system on the declared estate.",
        )

    lines.extend([
        "",
        "## Questions For The Board",
        "",
        "- For each acting agent, who would stop it tonight, and when did they last prove they could?",
        "- Which decisions has an agent's autonomy already answered for us?",
        "- Has every owner said what agents may do on their behalf, and is that what the agents hold?",
        "",
    ])
    return "\n".join(lines)
