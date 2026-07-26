# Zelvari Loops

Hermes-native loop-controlled starter repository for Zelvari. This repository now includes a stdlib Python MVP cellphone buyback quote site for supported iPhone and Samsung Galaxy devices.

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
python3 -m unittest discover -s tests -v
```

## Cellphone Buyback MVP

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

GitHub Actions runs the same test command on every push and pull request.
