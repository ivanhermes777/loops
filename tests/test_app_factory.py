import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from loops_app.app_factory import (
    AppFactory,
    LocalAIUnavailableError,
    ResearchFinding,
    create_app,
)


class StubResearcher:
    def __init__(self, findings=None, error=None):
        self.findings = findings or []
        self.error = error
        self.calls = []

    def research(self, idea):
        self.calls.append(idea)
        if self.error:
            raise self.error
        return self.findings


class StubLLM:
    def __init__(self, text=None, error=None):
        self.text = text or ""
        self.error = error
        self.calls = []

    def generate_blueprint(self, idea, findings, *, allow_ai_only=False):
        self.calls.append((idea, findings, allow_ai_only))
        if self.error:
            raise self.error
        return self.text


class AppFactoryTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.tmpdir.name) / "blueprints.json"
        self.good_findings = [
            ResearchFinding(
                category="pain points",
                summary="Small clinics lose hours manually reconciling appointments.",
                source_title="Clinic Operations Survey",
                source_url="https://example.test/clinic-ops",
                source_detail="Example HealthOps, 2026, appointment admin section",
            ),
            ResearchFinding(
                category="monetization opportunities",
                summary="Owners pay monthly for tools that reduce missed appointments.",
                source_title="Practice SaaS Pricing Study",
                source_url="https://example.test/pricing",
                source_detail="Pricing benchmark paragraph 3",
            ),
        ]
        self.good_blueprint = "\n".join(
            [
                "# Blueprint",
                "## Pain Points",
                "Manual appointment work wastes staff time.",
                "## Urgency",
                "Missed appointments hurt revenue this month.",
                "## Audience",
                "Independent clinic owners and office managers.",
                "## Features",
                "Reminder automation and reconciliation dashboard.",
                "## Monetization",
                "Monthly admin-only SaaS subscription.",
                "## Tech Plan",
                "Local-first Python MVP with local AI backend.",
                "## Launch Checklist",
                "Interview clinics and validate pricing.",
                "## Risks",
                "Integrations and privacy requirements.",
            ]
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_successful_idea_submission_runs_research_generates_structured_blueprint_and_saves_history(self):
        researcher = StubResearcher(self.good_findings)
        llm = StubLLM(self.good_blueprint)
        factory = AppFactory(self.storage_path, researcher=researcher, llm=llm)

        result = factory.submit_idea("AI appointment recovery for clinics")

        self.assertEqual(researcher.calls, ["AI appointment recovery for clinics"])
        self.assertEqual(len(result.research_findings), 2)
        self.assertIn("Clinic Operations Survey", result.cited_research_text)
        self.assertIn("https://example.test/clinic-ops", result.cited_research_text)
        for section in [
            "Pain Points",
            "Urgency",
            "Audience",
            "Features",
            "Monetization",
            "Tech Plan",
            "Launch Checklist",
            "Risks",
        ]:
            self.assertIn(f"## {section}", result.blueprint_markdown)
        self.assertFalse(result.used_ai_only_suggestions)
        reopened = factory.open_blueprint(result.id)
        self.assertEqual(reopened.blueprint_markdown, result.blueprint_markdown)
        self.assertEqual(factory.history()[0].title, "AI appointment recovery for clinics")

    def test_local_llm_unavailable_fails_gracefully_with_clear_admin_error(self):
        factory = AppFactory(
            self.storage_path,
            researcher=StubResearcher(self.good_findings),
            llm=StubLLM(error=LocalAIUnavailableError("connection refused")),
        )

        result = factory.submit_idea("AI quoting tool")

        self.assertEqual(result.status, "error")
        self.assertIn("local AI backend is unavailable", result.error_message)
        self.assertIn("configured local model/service", result.error_message)
        self.assertEqual(factory.history(), [])

    def test_research_failure_preserves_partial_findings_and_offers_retry_or_ai_only_continue(self):
        partial_error = URLError("timeout")
        partial_error.partial_findings = self.good_findings[:1]
        factory = AppFactory(
            self.storage_path,
            researcher=StubResearcher(error=partial_error),
            llm=StubLLM(self.good_blueprint),
        )

        result = factory.submit_idea("AI review responder")

        self.assertEqual(result.status, "research_warning")
        self.assertIn("Web research failed or returned weak results", result.warning_message)
        self.assertEqual(len(result.research_findings), 1)
        self.assertTrue(result.can_retry_research)
        self.assertTrue(result.can_continue_with_ai_only)
        self.assertEqual(factory.history(), [])

        continued = factory.continue_with_ai_only(result.pending_id)
        self.assertEqual(continued.status, "complete")
        self.assertTrue(continued.used_ai_only_suggestions)
        self.assertTrue(factory.history())

    def test_weak_research_returns_visible_warning_and_retry_can_complete(self):
        weak_researcher = StubResearcher([])
        factory = AppFactory(self.storage_path, researcher=weak_researcher, llm=StubLLM(self.good_blueprint))

        warning = factory.submit_idea("AI invoice helper")

        self.assertEqual(warning.status, "research_warning")
        self.assertIn("weak results", warning.warning_message)
        self.assertTrue(warning.can_retry_research)

        factory.researcher = StubResearcher(self.good_findings)
        completed = factory.retry_research(warning.pending_id)
        self.assertEqual(completed.status, "complete")
        self.assertEqual(len(completed.research_findings), 2)

    def test_empty_history_state_has_polished_explanation_and_primary_create_button(self):
        factory = AppFactory(self.storage_path, researcher=StubResearcher(), llm=StubLLM())

        state = factory.history_state()

        self.assertTrue(state.is_empty)
        self.assertEqual(state.primary_button_label, "Create your first app blueprint")
        self.assertIn("No blueprints yet", state.heading)
        self.assertIn("monetization-ready", state.description)

    def test_markdown_export_is_markdown_only_with_expected_content_type_and_no_pdf(self):
        factory = AppFactory(self.storage_path, researcher=StubResearcher(self.good_findings), llm=StubLLM(self.good_blueprint))
        result = factory.submit_idea("AI estimator")

        export = factory.export_markdown(result.id)

        self.assertTrue(export.filename.endswith(".md"))
        self.assertEqual(export.content_type, "text/markdown; charset=utf-8")
        self.assertIn("# Zelvari App Factory Blueprint", export.content)
        self.assertIn("AI estimator", export.content)
        self.assertIn("## Research Findings", export.content)
        self.assertFalse(hasattr(factory, "export_pdf"))

    def test_ui_html_exposes_admin_blueprint_scope_without_signup_login_pdf_or_generated_app_completion(self):
        html = create_app(self.storage_path, researcher=StubResearcher(), llm=StubLLM()).render_home()

        self.assertIn("Zelvari App Factory", html)
        self.assertIn("Create monetization-ready app blueprints", html)
        self.assertIn("blueprint, not a finished generated app", html)
        self.assertIn("No blueprints yet", html)
        self.assertIn("Create your first app blueprint", html)
        forbidden = ["Sign up", "Login", "Customer account", "PDF export", "Deploy app", "Payment setup"]
        for phrase in forbidden:
            self.assertNotIn(phrase, html)


if __name__ == "__main__":
    unittest.main()
