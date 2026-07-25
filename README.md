# Zelvari Loops

Hermes-native loop-controlled starter repository for Zelvari.

This repo is connected to:

- Linear team: `ZEL`
- GitHub repo: `ivanhermes777/loops`
- Operator: Hermes-native Finn loop repair lane
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
- Uses no-login web research for cited market evidence.
- Uses the configured local LLM backend by default for blueprint generation.
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

The app uses an Ollama-compatible local generation endpoint by default. Start
your local model service before submitting an idea:

```bash
ollama serve
ollama pull llama3.1
```

Default local AI settings:

```text
ZELVARI_LOCAL_LLM_ENDPOINT=http://127.0.0.1:11434/api/generate
ZELVARI_LOCAL_LLM_MODEL=llama3.1
ZELVARI_LOCAL_LLM_TIMEOUT=180
```

Optional web-research overrides:

```text
ZELVARI_RESEARCH_ENDPOINT=https://html.duckduckgo.com/html/
ZELVARI_RESEARCH_TIMEOUT=20
```

If the configured local model/service is unavailable, the app pauses with a
clear local-AI-backend error instead of crashing or requiring a cloud AI provider.
If web research fails or returns weak results, the app shows a warning, preserves
partial findings when available, and lets the admin retry or continue with
clearly labeled AI-only suggestions.

Run a local generation smoke test:

```bash
python3 bin/verify_hermes_runtime.py
```

## CI

GitHub Actions runs the same test command on every push and pull request.
