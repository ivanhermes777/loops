# Zelvari Loops

Hermes-native loop-controlled starter repository for Zelvari.

This repo is connected to:

- Linear team: `ZEL`
- GitHub repo: `ivanhermes777/loops`
- Operator: Hermes with OpenAI Codex OAuth
- Final merge gate: Michael approves by reacting with 🚀 on a merge-ready PR comment

## Loop Workflow

1. **Spec** — turn an idea into Linear issues with acceptance criteria and non-goals.
2. **Build** — Hermes claims approved `agent-ready` issues and opens PRs.
3. **Review** — Hermes reviews PRs against the Linear contract and required checks.
4. **Rocket Merge** — Michael reacts with 🚀, then Hermes re-checks and merges.

## Local Test

```bash
python -m unittest discover -s tests -v
```

## CI

GitHub Actions runs the same test command on every push and pull request.
