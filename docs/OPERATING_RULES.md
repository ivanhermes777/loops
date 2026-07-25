# Zelvari Loop Operating Rules

These rules protect Zelvari's loop-controlled development workflow.

## Durable Sources of Truth

- Linear owns product scope and approval.
- GitHub owns code, PRs, checks, review evidence, and merge state.
- Hermes runs build, review, and merge-check automation.

## Required Human Gates

- Michael applies `agent-ready` in Linear before an issue can be built.
- Michael reacts with 🚀 on a merge-ready PR comment before Hermes may merge.

## Agent Rules

- If it is not in the Linear issue, it does not exist.
- One issue per PR.
- Acceptance criteria are binding.
- Non-goals are binding.
- Agents do not merge without rocket approval.
- Required CI checks must be green before merge.

## Review Labels

- `loop-approved` — reviewer says it is ready for Michael's merge decision.
- `loop-changes-requested` — must-fix issues remain.
- `needs-human-review` — human decision or risk review required.
