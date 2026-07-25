#!/usr/bin/env python3
"""Real local-LLM smoke test for the App Factory."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loops_app.app_factory import LocalOllamaLLM, REQUIRED_BLUEPRINT_SECTIONS, ResearchFinding  # noqa: E402


def main() -> int:
    llm = LocalOllamaLLM()
    idea = "appointment no-show recovery assistant for independent clinics"
    findings = [
        ResearchFinding(
            "pain points",
            "Independent clinics lose revenue when patients miss appointments.",
            "Local smoke fixture",
            "https://example.test/local-smoke",
            "Fixture citation used to verify local generation only",
        ),
        ResearchFinding(
            "monetization opportunities",
            "Clinics can justify monthly tools that recover missed appointment revenue.",
            "Local smoke fixture",
            "https://example.test/local-smoke-pricing",
            "Fixture citation used to verify local generation only",
        ),
    ]
    print("1/1 Local LLM blueprint generation…", flush=True)
    blueprint = llm.generate_blueprint(idea, findings)
    missing = [section for section in REQUIRED_BLUEPRINT_SECTIONS if f"## {section}" not in blueprint]
    if missing:
        raise RuntimeError(f"Blueprint is missing sections: {', '.join(missing)}")
    print("PASS: configured local LLM generation works.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
