# Zelvari Loops

Hermes-native loop-controlled starter repository for Zelvari.

This repo is connected to:

- Linear team: `ZEL`
- GitHub repo: `ivanhermes777/loops`
- Operator: Hermes Agent with authenticated OpenAI Codex OAuth
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
- Uses Hermes Agent live web search automatically for pain points, urgency angles, audience signals, and monetization opportunities.
- Uses Hermes Agent with the authenticated OpenAI Codex OAuth session by default for blueprint generation.
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

If port `8765` is already occupied, use the documented override:

```bash
ZELVARI_APP_FACTORY_PORT=8893 python3 -m loops_app.app_factory
```

Then open:

```text
http://127.0.0.1:8893
```

Optional host/port settings:

```text
ZELVARI_APP_FACTORY_HOST=127.0.0.1
ZELVARI_APP_FACTORY_PORT=8893
ZELVARI_HERMES_COMMAND=hermes
ZELVARI_HERMES_TIMEOUT=360
```

Hermes Agent must be installed and the OpenAI Codex OAuth session must already be authenticated in the local Hermes environment. If Hermes Agent or the Codex OAuth session is unavailable, the app pauses with a clear recovery message instead of crashing.

If web research fails or returns weak results, the app shows a warning, preserves partial findings when available, and lets the admin retry or continue with clearly labeled AI-only suggestions.

Run a Hermes/Codex adapter smoke test:

```bash
python3 bin/verify_hermes_runtime.py
```

## CI

GitHub Actions runs the same test command on every push and pull request.
