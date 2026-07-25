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
- Uses Hermes with the operator's authenticated OpenAI Codex OAuth session.
- Uses Hermes' built-in live web search for cited market evidence.
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

### Hermes + OpenAI Codex OAuth configuration

The app does not require Ollama or a separate model API key. It calls the local
Hermes CLI, which must be authenticated to OpenAI Codex:

```bash
hermes doctor
```

`OpenAI Codex auth` and the `web` tool should both show as available. For the
free built-in DuckDuckGo search provider:

```bash
hermes tools post-setup ddgs
hermes config set web.search_backend ddgs
```

Optional overrides:

```text
ZELVARI_HERMES_COMMAND=/home/hermes/.local/bin/hermes
ZELVARI_HERMES_TIMEOUT=360
```

If Hermes, Codex OAuth, or live search is unavailable, the app pauses with a
clear operator-facing error instead of silently inventing research.

Run a real authenticated smoke test (this performs live search and one Codex
generation):

```bash
python3 bin/verify_hermes_runtime.py
```

## CI

GitHub Actions runs the same test command on every push and pull request.
