# Board AI Governance Toolkit

[![CI](https://github.com/javcamposz/board-ai-governance-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/javcamposz/board-ai-governance-toolkit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A lightweight, inspectable toolkit for turning board-level AI oversight into explicit decisions, owners, evidence, and review dates.

It includes a risk-register schema, a deterministic dashboard generator, board questions, and decision-rights templates. The examples are fictional and designed to be adapted to an organization's existing governance.

## Generate A Board Summary

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
ai-board summarize examples/ai-risk-register.csv --as-of 2026-09-12 --output board-summary.md
```

The command validates the register, scores residual exposure, identifies overdue reviews, and produces a concise Markdown dashboard.

```text
Validated 4 AI risks
High or critical open risks: 1
Overdue reviews: 1
Dashboard written to board-summary.md
```

## Report What Changed Since The Last Meeting

A snapshot says where the portfolio is. A board also needs to know what moved, and what moved quietly.

```bash
ai-board diff examples/ai-risk-register-previous.csv examples/ai-risk-register.csv \
  --as-of 2026-09-12 --output change-report.md
```

```text
Compared 4 against 4 AI risks
New: 1  Escalated: 1  Closed: 1
Reviews moved later: 2
Removed while still active: 1
```

The change report leads with what requires explanation: risks that left the register without being closed, escalations, controls that weakened, accountable owners that changed, and review dates pushed out after they had already fallen due. Repeated slippage is visible in days, not in reassurance.

## Enforce A Policy

A register that reports a breach but never fails is a document, not a control. `ai-board check` tests a
register against thresholds an organization is willing to be held to between board meetings, and exits
non-zero when they are breached, so it can run on a schedule.

```bash
ai-board check examples/ai-risk-register.csv --as-of 2026-09-12 \
  --max-critical 0 --max-overdue 0 --require-evidence-for high,critical
```

```text
Validated 4 AI risks as of 2026-09-12
FAIL  critical risks: 1 critical (limit 0)
        AI-002 Recruitment ranking pilot
FAIL  overdue reviews: 1 overdue (limit 0)
        AI-001 was due 2026-09-01 (Customer Operations Director)
FAIL  evidence: 1 high, critical risks with no evidence recorded
        AI-002 Recruitment ranking pilot (critical, assurance asserted)
3 of 3 rules breached
```

Thresholds are opt-in, because risk appetite belongs to the organization and not to this tool. With no
threshold set, `check` validates the register and tests nothing. Closed risks are out of scope.

`--require-evidence-for` matches a risk whose reported **or** face-value level is in the set, so a risk
cannot escape the rule by being inflated past the level under test precisely because it lacks evidence.

## Exit Codes

| Code | Meaning |
|---:|---|
| `0` | The register was valid and the report was produced, or the policy was satisfied |
| `1` | The register was valid but breached a policy threshold (`ai-board check` only) |
| `2` | The register could not be read or failed validation |

Validation reports every problem in one pass, with row numbers, so a register is corrected in a single edit rather than one run per error.

```text
error: register.csv: 3 problems
  - row 2: owner is required
  - row 2: impact must be one of critical, high, low, medium
  - row 3: next_review must be YYYY-MM-DD
```

## Contents

- `examples/ai-risk-register.csv`: fictional worked example using the required schema
- `examples/ai-risk-register-previous.csv`: the prior snapshot of the same register, for `ai-board diff`
- `templates/ai-risk-register.csv`: clean starting register
- `templates/decision-memo.md`: evidence and approval record for a material AI decision
- `templates/quarterly-dashboard.md`: board reporting structure
- `docs/board-questions.md`: questions that surface capability, control, and accountability gaps
- `docs/decision-rights.md`: a practical escalation model
- `src/board_ai_governance/`: dependency-free validation, scoring, comparison, and policy CLI

## Risk Register Contract

| Field | Meaning |
|---|---|
| `id` | Stable risk identifier |
| `system` | AI system or use case |
| `owner` | Accountable named role |
| `decision` | Decision or outcome at risk |
| `impact` | `low`, `medium`, `high`, or `critical` |
| `likelihood` | `rare`, `possible`, `likely`, or `almost_certain` |
| `control_strength` | `weak`, `partial`, or `strong` |
| `status` | `open`, `mitigating`, `accepted`, or `closed` |
| `next_review` | ISO date (`YYYY-MM-DD`) |
| `assurance` | Optional. `asserted`, `tested`, or `independent`: who verified the control rating |
| `evidence` | Optional. Reference to the evidence behind the rating, such as a memo or review |
| `date_opened` | Optional. ISO date the risk joined the register |

A register without the optional columns still loads. Every risk in it is read as `asserted` with no
evidence, which is the pessimistic reading and usually the accurate one, and its age is not reported.

## How Long Has This Been Open

A risk that has sat in `mitigating` for eighteen months is not being mitigated. With `date_opened`
recorded, the dashboard ages the active register oldest first, and `check --max-open-days` fails when a
risk has been carried longer than the organization said it would tolerate. Risks with no opening date are
counted and named as untestable rather than quietly passed.

## Why A Control Rating Is Not Taken On Trust

`control_strength` is a self-report, and on its own it moves the number a long way. A critical-impact,
possible-likelihood risk reports as `medium` on the strength of one typed word:

```text
critical impact, possible likelihood, weak    control -> 8.0 critical
critical impact, possible likelihood, strong  control -> 2.8 medium
```

`docs/board-questions.md` already asks which controls have been tested independently rather than asserted
by the supplier. The score now asks the same question. A control is credited toward its stated strength
only as far as its assurance carries it, and an assurance claim with no evidence recorded is credited as
an assertion, because verification you cannot point at is an assertion.

| Assurance | Credit toward the stated control strength |
|---|---:|
| `asserted` | 40% |
| `tested` | 75% |
| `independent` | 100% |

A `weak` control gains nothing from assurance; there is no credit to earn. The dashboard reports both the
score and what the register would have reported had the control rating been taken on trust, so the board
can see how much of its comfort rests on assertion and challenge every input.

`evidence` must name the evidence or be left blank. Placeholders that mean "none" (`N/A`, `TBD`, `pending`,
`-`, and similar) are rejected in validation, because a control credited on the strength of a keystroke is
exactly the failure this is meant to catch.

The score is a prioritization aid, not a statistical prediction. Adapt the thresholds and the credit
schedule to the organization.

## Development

```bash
pip install -e '.[dev]'
pytest
python -m board_ai_governance summarize examples/ai-risk-register.csv --as-of 2026-09-12
python -m board_ai_governance diff examples/ai-risk-register-previous.csv examples/ai-risk-register.csv --as-of 2026-09-12
python -m board_ai_governance check examples/ai-risk-register.csv --as-of 2026-09-12 --max-overdue 0
ruff check .
```

## Responsible Use

This toolkit does not replace legal, regulatory, security, model-risk, or domain-specific advice. Adapt thresholds and decision rights to the organization, jurisdiction, and consequences of the system under review.
