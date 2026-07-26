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

### Run the App Factory locally

```bash
python -m loops_app.zelvari_app_factory
```

Then open:

```text
http://127.0.0.1:8765
```

If your local shell only exposes Python as `python3`, use:

```bash
python3 -m loops_app.zelvari_app_factory
```

If port `8765` is already occupied, use the documented override:

```bash
ZELVARI_APP_FACTORY_PORT=8893 python3 -m loops_app.zelvari_app_factory
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

`ZELVARI_APP_FACTORY_HOST` must remain loopback-only (`127.0.0.1`, `localhost`, or `::1`) for this local/admin-only MVP. The app refuses non-loopback host binding unless a future issue adds a real authentication layer.

Hermes Agent must be installed and the OpenAI Codex OAuth session must already be authenticated in the local Hermes environment. The App Factory pins Hermes subprocess calls to `--provider openai-codex` so it does not silently fall back to another configured Hermes provider. If Hermes Agent or the Codex OAuth session is unavailable, the app pauses with a clear recovery message instead of crashing.

If web research fails or returns weak results, the app shows a warning, preserves partial findings when available, and lets the admin retry or continue with clearly labeled AI-only suggestions.

Run a Hermes/Codex adapter smoke test:

```bash
python3 bin/verify_hermes_runtime.py
```

## Cellphone Buyback MVP

This repository also includes the stdlib Python cellphone buyback quote site from the current `main` branch.

The buyback app lets a customer select a supported brand, model, storage size, and condition, view an estimated offer from the editable pricing table, and submit contact details for manual Zelvari follow-up. It intentionally does not include checkout, payouts, shipping labels, customer emails, or public price suggestions.

### Local setup

1. Copy the example environment file and set private admin credentials locally:

```bash
cp .env.example .env
```

2. Export the required admin values before running. Do not commit real credentials.

```bash
export BUYBACK_ADMIN_USERNAME="your-admin-username"
export BUYBACK_ADMIN_PASSWORD="your-secure-password"
export BUYBACK_DB_PATH="buyback.sqlite3"
```

3. Start the local app with sample iPhone and Samsung Galaxy pricing:

```bash
python3 -m loops_app.app_factory --host 127.0.0.1 --port 8000 --seed-sample
```

4. Open the public quote site:

```text
http://127.0.0.1:8000/
```

5. Open the protected admin area and log in with the environment-variable credentials:

```text
http://127.0.0.1:8000/admin
```

### Configuration

- `BUYBACK_ADMIN_USERNAME` — required admin username for `/admin`.
- `BUYBACK_ADMIN_PASSWORD` — required admin password for `/admin`.
- `BUYBACK_DB_PATH` — optional SQLite database path. Defaults to `buyback.sqlite3`.

### Empty pricing behavior

If the pricing table is empty, the public quote page shows a graceful “Pricing is not available yet” message and no device selectors. Seed sample data locally with `--seed-sample`, or manage existing seeded rows from `/admin`.

## CI

GitHub Actions runs the test command on every push and pull request.
