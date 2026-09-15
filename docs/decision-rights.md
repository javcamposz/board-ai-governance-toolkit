# AI Decision Rights

Use impact, uncertainty, and reversibility together. High uncertainty does not become low risk merely because a deployment is called a pilot.

| Decision | Product team | Risk and assurance | Executive owner | Board |
|---|---|---|---|---|
| Low-impact, reversible experiment | Approve and record | Consult as required | Informed through portfolio reporting | Aggregate oversight |
| Material workflow change | Recommend | Challenge evidence and controls | Approve conditions and owner | Review material exposure |
| High-impact or hard-to-reverse use | Build evidence only | Independent assessment | Recommend | Approve risk appetite and conditions |
| Incident containment | Act within playbook | Verify containment and evidence | Accountable for response | Notified by severity threshold |
| Restart after material incident | Recommend remediation | Independently challenge | Recommend | Approve when consequences warrant |

Every organization should map this template to its legal duties, regulated functions, and existing delegations of authority.

## The Machine-Readable Form

`ai-board check --rights` reads the same model as JSON, mapping each exposure level to the roles that
may decide at it, and fails a register where a decision was taken without that authority.

```json
{
  "critical": ["Board", "Chief Executive"],
  "high": ["Chief Risk Officer", "Chief Technology Officer", "Chief People Officer"]
}
```

The file is held outside the register, because a register that named its own acceptable deciders
would name the ones who had already decided. Matching is on the `decided_by` text, trimmed and
case-insensitive, so the roles here and the roles in the register must be written the same way.
A level left out of the file is unconstrained and the check says so.
