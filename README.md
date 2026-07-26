# Zelvari Loops

Hermes-native loop-controlled starter repository for Zelvari. This repository now includes a stdlib Python MVP cellphone buyback quote site for supported iPhone and Samsung Galaxy devices, plus a public Zelvari AI prompt builder route.

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
# Optional: required only for live /prompt-builder generation.
export PROMPT_BUILDER_COMMAND_JSON='["python3","scripts/your_prompt_builder_command.py"]'
export PROMPT_BUILDER_TIMEOUT_SECONDS="20"
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

6. Open the public prompt builder:

```text
http://127.0.0.1:8000/prompt-builder
```

### Configuration

- `BUYBACK_ADMIN_USERNAME` — required admin username for `/admin`.
- `BUYBACK_ADMIN_PASSWORD` — required admin password for `/admin`.
- `BUYBACK_DB_PATH` — optional SQLite database path. Defaults to `buyback.sqlite3`.
- `PROMPT_BUILDER_COMMAND_JSON` — optional JSON array command used server-side by `/prompt-builder` for Hermes/OpenAI Codex OAuth prompt improvement. Browser users never enter API keys or OAuth credentials. The command receives JSON on stdin with `prompt`, `goal`, `tone`, and `platform`, and should print only the improved prompt to stdout.
- `PROMPT_BUILDER_TIMEOUT_SECONDS` — optional command timeout in seconds. Defaults to `20` and is capped by the app.

## Zelvari AI Prompt Builder

`/prompt-builder` is a standalone public route with a dark futuristic Zelvari layout, centered hero, neon feature badges, left prompt input card, right improved prompt card, copy button, and mobile stacking. It is additive and does not replace `/`, `/request`, `/admin/login`, `/admin`, or `/admin/pricing/update`.

The prompt builder intentionally does not persist raw prompts, improved prompts, prompt history, browser local storage, analytics, or database rows. Prompt text is sent only to the server-side command configured in `PROMPT_BUILDER_COMMAND_JSON`; the buyback SQLite tables and admin pages remain separate.

If the command is missing, unavailable, times out, or exits unsuccessfully, users see a polished temporary-unavailable message without stack traces, secrets, command strings, stderr, or debug metadata.

### Local prompt-builder verification

For a test-safe local stub, export a command that reads stdin and prints a fixed improved prompt:

```bash
export PROMPT_BUILDER_COMMAND_JSON='["python3","-c","import sys; sys.stdin.read(); print(\"Write a clear, high-converting prompt with specific goals, audience context, constraints, and a strong CTA.\")"]'
```

Then run the app and submit a prompt at `/prompt-builder`. To verify the unavailable state, unset or break `PROMPT_BUILDER_COMMAND_JSON` and submit a valid prompt again.

### Empty pricing behavior

If the pricing table is empty, the public quote page shows a graceful “Pricing is not available yet” message and no device selectors. Seed sample data locally with `--seed-sample`, or manage existing seeded rows from `/admin`.

## CI

GitHub Actions runs the same test command on every push and pull request.
