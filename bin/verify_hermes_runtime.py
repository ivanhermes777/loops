#!/usr/bin/env python3
"""Hermes/Codex adapter smoke test for the App Factory.

This check verifies the repository's default ZEL-9 adapter contract without
performing a paid or networked generation run. Unit and browser checks exercise
the same AppFactory path with mocked Hermes output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loops_app.zelvari_app_factory import HermesCodexAgent, REQUIRED_BLUEPRINT_SECTIONS, ResearchFinding  # noqa: E402


def main() -> int:
    findings = [
        ResearchFinding(
            "pain points",
            "Independent clinics lose revenue when patients miss appointments.",
            "Hermes smoke fixture",
            "https://example.test/hermes-smoke",
            "Fixture citation used to verify Hermes adapter wiring only",
        ),
        ResearchFinding(
            "monetization opportunities",
            "Clinics can justify monthly tools that recover missed appointment revenue.",
            "Hermes smoke fixture",
            "https://example.test/hermes-smoke-pricing",
            "Fixture citation used to verify Hermes adapter wiring only",
        ),
    ]
    research_json = json.dumps([finding.__dict__ for finding in findings])
    blueprint = "\n".join([f"## {section}\nSmoke fixture content." for section in REQUIRED_BLUEPRINT_SECTIONS])
    agent = HermesCodexAgent(command="hermes", timeout_seconds=30)

    print("1/1 Hermes Agent + OpenAI Codex OAuth adapter command contract…", flush=True)
    with patch("subprocess.run") as run:
        run.side_effect = [
            type("Result", (), {"returncode": 0, "stdout": research_json, "stderr": ""})(),
            type("Result", (), {"returncode": 0, "stdout": blueprint, "stderr": ""})(),
        ]
        parsed_findings = agent.research("appointment no-show recovery assistant for independent clinics")
        generated = agent.generate_blueprint("appointment no-show recovery assistant for independent clinics", parsed_findings)

    research_command = run.call_args_list[0].args[0]
    generation_command = run.call_args_list[1].args[0]
    if "--ignore-rules" in research_command or "--ignore-rules" in generation_command:
        raise RuntimeError("Hermes adapter must not disable Hermes rules")
    if "web" not in research_command or "none" not in generation_command:
        raise RuntimeError("Hermes adapter toolsets are not constrained as expected")
    missing = [section for section in REQUIRED_BLUEPRINT_SECTIONS if f"## {section}" not in generated]
    if missing:
        raise RuntimeError(f"Blueprint is missing sections: {', '.join(missing)}")
    print("PASS: Hermes Agent/Codex OAuth adapter wiring is correct.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
