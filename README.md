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

## Contents

- `examples/ai-risk-register.csv`: fictional worked example using the required schema
- `templates/ai-risk-register.csv`: clean starting register
- `templates/decision-memo.md`: evidence and approval record for a material AI decision
- `templates/quarterly-dashboard.md`: board reporting structure
- `docs/board-questions.md`: questions that surface capability, control, and accountability gaps
- `docs/decision-rights.md`: a practical escalation model
- `src/board_ai_governance/`: dependency-free validation and reporting CLI

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

The score is a prioritization aid, not a statistical prediction. It combines ordinal impact and likelihood with a transparent control-strength factor so board discussion can challenge every input.

## Development

```bash
pip install -e '.[dev]'
pytest
python -m board_ai_governance summarize examples/ai-risk-register.csv --as-of 2026-09-12
```

## Responsible Use

This toolkit does not replace legal, regulatory, security, model-risk, or domain-specific advice. Adapt thresholds and decision rights to the organization, jurisdiction, and consequences of the system under review.
