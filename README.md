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

If your local shell only exposes Python as `python3`, use:

```bash
python3 -m unittest discover -s tests -v
```

## Zelvari App Factory MVP

This repository includes the local/admin-only **Zelvari App Factory** blueprint MVP for `ZEL-9`.

Version 1 scope:

- Creates monetization-ready app blueprints from a submitted idea.
- Runs web research automatically for pain points, urgency angles, audience signals, and monetization opportunities.
- Uses the configured local LLM by default through an Ollama-compatible local endpoint.
- Saves completed blueprints locally so they can be reopened from project history.
- Exports completed blueprints as Markdown only.
- Does **not** provide public signup/login, customer accounts, payment setup, deployment, PDF export, or generated app code.

### Run the app locally

```bash
python -m loops_app.app_factory
```

Then open:

```text
http://127.0.0.1:8765
```

If your local shell only exposes Python as `python3`, use:

```bash
python3 -m loops_app.app_factory
```

### Local LLM configuration

By default, the app calls an Ollama-compatible local generation endpoint:

```text
ZELVARI_LOCAL_LLM_URL=http://127.0.0.1:11434/api/generate
ZELVARI_LOCAL_LLM_MODEL=gemma4
```

If that local AI backend is stopped or misconfigured, the app fails gracefully with a clear admin-facing error asking you to check the configured local model/service.

## CI

GitHub Actions runs the same test command on every push and pull request.
