# Zelvari Loops

Hermes-native loop-controlled starter repository for Zelvari. This repository includes a stdlib-only Python cellphone buyback demo website with SQLite pricing, quote/order persistence, demo customer flows, and protected admin tools.

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

## Premium Cellphone Buyback Demo

The buyback app lets customers browse supported phones, estimate trade-in value, walk through a device-condition questionnaire, submit seller information as a guest, receive a generated quote/order number, and view polished demo account/dashboard/support screens.

The app intentionally remains a Python standard-library WSGI app. It does **not** use Next.js, React, TypeScript, Tailwind, npm, or external services.

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

3. Start the local app with realistic seeded demo pricing:

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

### Seed/demo behavior

Running with `--seed-sample` seeds editable mock SQLite pricing for Apple iPhone, Samsung Galaxy, Google Pixel, OnePlus, Motorola, Xiaomi, Nothing, and Other Brands. The pricing fields include base value, maximum payout, carrier adjustment, condition deduction, screen damage deduction, back glass deduction, water damage deduction, non-working value, promotional bonus, and a newest-sort rank.

### Demo/manual-only limitations

Customer auth, shipping labels, payments, emails, review integrations, analytics, CRM, carrier checks, identity checks, and external trust metrics are demo/manual only. The demo auth screens validate fields and show realistic messages, but customer login credentials are not stored.

### Empty and failure states

If the pricing table is empty, the public quote page shows a graceful “Pricing is not available yet” message and non-breaking catalog empty guidance. Unknown quote-status lookups return a safe not-found message without exposing customer data. Admin failures fail closed without stack traces, secrets, environment values, SQL errors, or debug metadata.

## CI

GitHub Actions runs the same test command on every push and pull request.
