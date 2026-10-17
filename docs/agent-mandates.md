# Agent Mandates: Governing AI That Acts

The register was built for systems that recommend and people that act. Agentic systems act. A
support orchestrator replies to customers and spawns a worker that issues refunds; a coding planner
spawns workers that write code, and one of them spawns a release agent. Swarms of agents like these
are now ordinary, and each spawn is a **delegation of authority**. The board is accountable for the
end of that chain, not the first link, and none of it appears in a risk register.

`ai-board agents` reads a declaration of the agents and the authority delegated to them, held outside
the register for the reason the estate and the decision rights are: a register that declared what its
own agents were allowed to do would declare what they already do.

## What Is Declared

```json
{
  "principals": {
    "Customer Operations Director": ["read:customer_record", "reply:customer", "refund:up_to_100"]
  },
  "max_depth": 2,
  "stop_test_within_days": 90,
  "agents": [
    {"name": "support-orchestrator", "system": "Customer support assistant",
     "acts_for": "Customer Operations Director", "scopes": ["read:customer_record", "reply:customer"],
     "autonomy": "act", "stop_owner": "Customer Operations Director", "stop_tested_on": "2026-08-20"},
    {"name": "refund-worker", "spawned_by": "support-orchestrator",
     "scopes": ["read:customer_record", "refund:up_to_100"], "autonomy": "act", "stops_with_parent": true}
  ]
}
```

| Field | Meaning |
|---|---|
| `principals` | What each accountable owner has authorised agents to do on their behalf |
| `max_depth` | Optional. How many hops from a person the board will follow; a choice, not a fact |
| `stop_test_within_days` | Optional. How recent a stop test must be to count |
| `acts_for` / `spawned_by` | Exactly one: the person a root agent answers to, or the agent that created this one |
| `scopes` | What the agent may do, in whatever vocabulary the organization's access control uses |
| `autonomy` | `suggest` (a person carries out), `approve` (acts after per-action approval), `act` (no per-action approval) |
| `stop_owner`, `stop_tested_on` | Who can stop a root agent, and when they last proved it |
| `stops_with_parent` | Whether stopping the parent stops this agent |

A declaration with no agents is refused: a check an empty declaration satisfies is a green result
for the absence of a claim. A cycle of agents spawning each other is refused, because every agent in
it answers to nobody.

## The Four Rules

### Authority does not grow through delegation

An agent cannot hold a scope its parent does not hold, and a root agent cannot hold one its
principal has not authorised. This is the decision-rights rule read downwards: a decision's
authority does not carry up to a higher risk level, and an agent's authority does not carry down to
a child that holds more.

The principal authorising a scope does **not** let a child skip its parent. The Customer Operations
Director authorised refunds; the orchestrator never held them, so it had nothing to pass on. A
worker holding refunds anyway is authority that appeared somewhere in the chain nobody approved.

A principal who has declared nothing is reported as **untestable**, not passed: unstated is not the
same as unlimited, and should not read as either.

### Every acting agent can be stopped

An agent with autonomy `act` needs a stop that reaches it. For a root agent that means a named owner
and a test inside the declared window. For a sub-agent it means stopping with its parent, all the way
up; an agent that keeps running when its parent is stopped has a stop that does not reach it, and so
does every agent below it. A stale test on the root is reported once, naming the acting agents that
rely on it, rather than once per agent.

### Autonomy waits for the decision

An agent acting without per-action approval on a system whose register entry still has a decision
outstanding has been given, in practice, the answer the board has not given. In the example, AI-003
asks the board to *set the permitted autonomy boundary* for the developer coding assistant, and three
agents are already acting autonomously on it:

> coding-planner, coding-worker, release-agent act without per-action approval on Developer coding
> assistant, where AI-003 still asks the board to decide: Set the permitted autonomy boundary.
> Autonomy granted before that decision is the decision, taken by default.

A system with acting agents and no active register entry at all fails the same rule: there is no
risk, owner or decision recorded for what those agents do.

### A chain is accountable only as far as someone follows it

When `max_depth` is declared, an agent more hops from its person than that is reported with its
whole chain, so the board sees what it would have to trace.

## Running It

```bash
ai-board agents examples/agent-mandates.json --register examples/ai-risk-register.csv \
  --as-of 2026-09-12 --inventory examples/ai-systems.json --output agent-mandates.md
ai-board check examples/ai-risk-register.csv --as-of 2026-09-12 --mandates examples/agent-mandates.json
```

`agents` writes the board report and exits `0`; `check --mandates` adds the rules to the policy gate
and exits `1` when any is breached, so it can run on the same schedule as the rest of the register.

## What This Does Not Claim

- The declaration is only as true as whoever wrote it. It should be generated from the access-control
  system the agents actually run under, not typed; a mandate that differs from the real permissions
  is a finding this tool cannot see.
- Scopes are compared as strings. `refund:up_to_100` and `refund:up_to_500` are different scopes, and
  this tool does not know one contains the other.
- A tested stop proves the stop worked on the day it was tested, on the agents that existed then.
  Agents spawned since inherit it only if they stop with their parent.
