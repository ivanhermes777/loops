#!/usr/bin/env python3
"""Real Hermes/Codex OAuth smoke test for the App Factory."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loops_app.app_factory import HermesCodexAgent, REQUIRED_BLUEPRINT_SECTIONS  # noqa: E402


def main() -> int:
    agent = HermesCodexAgent()
    idea = "appointment no-show recovery assistant for independent clinics"
    print("1/2 Hermes live search…", flush=True)
    findings = agent.research(idea)
    if len(findings) < 2 or not all(item.source_url.startswith(("http://", "https://")) for item in findings):
        raise RuntimeError("Hermes did not return enough valid live-search citations")
    print(f"    received {len(findings)} cited findings", flush=True)
    print("2/2 OpenAI Codex OAuth blueprint generation…", flush=True)
    blueprint = agent.generate_blueprint(idea, findings)
    missing = [section for section in REQUIRED_BLUEPRINT_SECTIONS if f"## {section}" not in blueprint]
    if missing:
        raise RuntimeError(f"Blueprint is missing sections: {', '.join(missing)}")
    print("PASS: Hermes live search and OpenAI Codex OAuth generation both work.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
