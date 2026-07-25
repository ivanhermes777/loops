import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from unittest.mock import patch

from loops_app.app_factory import (
    AppFactory,
    BlueprintResult,
    HermesCodexAgent,
    HermesUnavailableError,
    ResearchFinding,
    _parse_hermes_findings,
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
                "Local-first Python MVP with Hermes and OpenAI Codex OAuth.",
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

    def test_hermes_unavailable_fails_gracefully_with_clear_admin_error(self):
        factory = AppFactory(
            self.storage_path,
            researcher=StubResearcher(self.good_findings),
            llm=StubLLM(error=HermesUnavailableError("connection refused")),
        )

        result = factory.submit_idea("AI quoting tool")

        self.assertEqual(result.status, "error")
        self.assertIn("Hermes with OpenAI Codex OAuth is unavailable", result.error_message)
        self.assertIn("live search is enabled", result.error_message)
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

    def test_hermes_live_search_parser_accepts_real_citations_and_rejects_placeholders(self):
        raw = """```json
        [
          {"category":"pain points","summary":"Manual work is expensive.","source_title":"Operations Study","source_url":"https://research.test/ops","source_detail":"2026 survey"},
          {"category":"urgency","summary":"Costs are rising.","source_title":"Market Report","source_url":"https://market.test/report","source_detail":"Current market data"},
          {"category":"audience","summary":"Ignore me.","source_title":"Placeholder","source_url":"https://example.com/fake","source_detail":"Not real"}
        ]
        ```"""

        findings = _parse_hermes_findings(raw)

        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0].source_title, "Operations Study")
        self.assertEqual(findings[1].source_url, "https://market.test/report")

    def test_hermes_agent_uses_web_tool_for_research_and_constrained_codex_session_for_generation(self):
        agent = HermesCodexAgent(command="/opt/hermes", timeout_seconds=45)
        research_json = json.dumps(
            [
                {
                    "category": finding.category,
                    "summary": finding.summary,
                    "source_title": finding.source_title,
                    "source_url": finding.source_url,
                    "source_detail": finding.source_detail,
                }
                for finding in self.good_findings
            ]
        )

        with patch("subprocess.run") as run:
            run.side_effect = [
                type("Result", (), {"returncode": 0, "stdout": research_json, "stderr": ""})(),
                type("Result", (), {"returncode": 0, "stdout": self.good_blueprint, "stderr": ""})(),
            ]
            findings = agent.research("AI appointment recovery")
            blueprint = agent.generate_blueprint("AI appointment recovery", findings)

        research_command = run.call_args_list[0].args[0]
        generation_command = run.call_args_list[1].args[0]
        self.assertEqual(research_command[:3], ["/opt/hermes", "chat", "--quiet"])
        self.assertIn("--ignore-rules", research_command)
        self.assertIn("--toolsets", research_command)
        self.assertIn("web", research_command)
        self.assertNotIn("-z", research_command)
        self.assertEqual(generation_command[:3], ["/opt/hermes", "chat", "--quiet"])
        self.assertIn("--ignore-rules", generation_command)
        self.assertIn("--toolsets", generation_command)
        self.assertIn("none", generation_command)
        self.assertNotIn("-z", generation_command)
        self.assertIn("## Monetization", blueprint)

    def test_cross_origin_or_missing_csrf_post_is_forbidden_before_research_or_generation(self):
        researcher = StubResearcher(self.good_findings)
        llm = StubLLM(self.good_blueprint)
        app = create_app(self.storage_path, researcher=researcher, llm=llm)

        blocked_requests = [
            ("/blueprints", {"idea": "malicious cross-origin idea"}, {"HTTP_ORIGIN": "https://attacker.example"}),
            ("/blueprints", {"idea": "missing token idea"}, {}),
            ("/research/retry", {"pending_id": "attacker-pending"}, {"HTTP_ORIGIN": "https://attacker.example"}),
            ("/research/continue-ai-only", {"pending_id": "attacker-pending"}, {"HTTP_ORIGIN": "https://attacker.example"}),
        ]
        for path, form, headers_in in blocked_requests:
            with self.subTest(path=path, headers=headers_in):
                body, status, headers = call_wsgi(app, "POST", path, form=form, headers=headers_in)
                self.assertEqual(status, "403 Forbidden")
                self.assertIn("Local admin request rejected", body)
                self.assertEqual(headers["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(researcher.calls, [])
        self.assertEqual(llm.calls, [])

    def test_rendered_csrf_token_allows_intentional_admin_submit_retry_and_ai_only_continue(self):
        weak_researcher = StubResearcher([])
        llm = StubLLM(self.good_blueprint)
        app = create_app(self.storage_path, researcher=weak_researcher, llm=llm)
        token = app.admin_token

        warning_body, warning_status, _ = call_wsgi(
            app,
            "POST",
            "/blueprints",
            form={"idea": "AI clinic assistant", "admin_token": token},
        )

        self.assertEqual(warning_status, "303 See Other")
        self.assertEqual(weak_researcher.calls, ["AI clinic assistant"])
        self.assertEqual(llm.calls, [])
        self.assertEqual(warning_body, "")
        self.assertIn(f'name="admin_token" value="{token}"', app.render_home())

        pending_id = app.latest_result.pending_id
        app.factory.researcher = StubResearcher(self.good_findings)
        retry_body, retry_status, _ = call_wsgi(
            app,
            "POST",
            "/research/retry",
            form={"pending_id": pending_id, "admin_token": token},
        )

        self.assertEqual(retry_status, "303 See Other")
        self.assertEqual(retry_body, "")
        self.assertEqual(app.latest_result.status, "complete")

        app.factory.researcher = StubResearcher([])
        call_wsgi(app, "POST", "/blueprints", form={"idea": "AI invoice helper", "admin_token": token})
        pending_id = app.latest_result.pending_id
        continue_body, continue_status, _ = call_wsgi(
            app,
            "POST",
            "/research/continue-ai-only",
            form={"pending_id": pending_id, "admin_token": token},
        )

        self.assertEqual(continue_status, "303 See Other")
        self.assertEqual(continue_body, "")
        self.assertTrue(app.latest_result.used_ai_only_suggestions)

    def test_invalid_hermes_live_search_contract_is_rejected(self):
        with self.assertRaises(HermesUnavailableError):
            _parse_hermes_findings('[{"source_url":"https://example.com/fake"}]')

    def test_source_evidence_links_allow_only_http_and_https_urls(self):
        valid = ResearchFinding(
            category="pain points",
            summary="Valid cited source should remain clickable.",
            source_title="Valid web source",
            source_url="https://example.test/source",
            source_detail="Safe URL fixture",
        )
        unsafe_findings = [
            ResearchFinding("urgency", "Unsafe JavaScript URL", "Unsafe JS", "javascript:alert(1)", "Rejected URL fixture"),
            ResearchFinding("audience signals", "Unsafe data URL", "Unsafe data", "data:text/html,alert(1)", "Rejected URL fixture"),
            ResearchFinding("monetization opportunities", "Unsafe file URL", "Unsafe file", "file:///etc/passwd", "Rejected URL fixture"),
            ResearchFinding("pain points", "Unsafe vbscript URL", "Unsafe vbscript", "vbscript:msgbox(1)", "Rejected URL fixture"),
            ResearchFinding("urgency", "Unsafe relative URL", "Unsafe relative", "/relative-source", "Rejected URL fixture"),
            ResearchFinding("audience signals", "Empty URL", "Unsafe empty", "", "Rejected URL fixture"),
        ]
        result = BlueprintResult(
            id="safe-link-check",
            idea="AI appointment recovery for clinics",
            status="complete",
            research_findings=[valid, *unsafe_findings],
            blueprint_markdown=self.good_blueprint,
        )
        app = create_app(self.storage_path, researcher=StubResearcher(), llm=StubLLM())
        app.latest_result = result

        html = app.render_home()

        self.assertIn('href="https://example.test/source"', html)
        for rejected in ["javascript:", "data:", "file:", "vbscript:", 'href="/relative-source"', 'href=""']:
            self.assertNotIn(rejected, html)
        self.assertIn("Source URL unavailable or rejected for safety", html)

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

    def test_history_ui_can_reopen_saved_blueprint_through_in_app_route(self):
        app = create_app(self.storage_path, researcher=StubResearcher(self.good_findings), llm=StubLLM(self.good_blueprint))
        result = app.factory.submit_idea("AI estimate follow-up assistant")

        history_html = app.render_home()
        self.assertIn(f'href="/blueprints/{result.id}"', history_html)
        self.assertIn("Reopen blueprint", history_html)

        body, status, headers = call_wsgi(app, "GET", f"/blueprints/{result.id}")

        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("AI estimate follow-up assistant", body)
        self.assertIn("Manual appointment work wastes staff time.", body)
        self.assertIn("Completed Blueprint", body)

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

    def test_ui_html_presents_premium_command_center_layout_with_accessible_motion_and_evidence_cards(self):
        app = create_app(self.storage_path, researcher=StubResearcher(self.good_findings), llm=StubLLM(self.good_blueprint))
        app.latest_result = app.factory.submit_idea("AI estimate follow-up assistant")

        html = app.render_home()

        self.assertIn('class="app-shell command-center"', html)
        self.assertIn('class="history-sidebar glass-panel"', html)
        self.assertIn('class="workspace-hero glass-panel"', html)
        self.assertIn('class="research-pipeline" aria-label="Research pipeline progress"', html)
        for stage in ["Idea intake", "Market scan", "Source review", "Blueprint generation", "Export readiness"]:
            self.assertIn(stage, html)
        self.assertIn('class="evidence-card"', html)
        self.assertIn("Credibility cue", html)
        self.assertIn("Source type", html)
        self.assertIn('class="blueprint-deliverable"', html)
        self.assertIn("@media (prefers-reduced-motion: reduce)", html)
        self.assertIn(":focus-visible", html)
        self.assertIn("grid-template-columns:1fr", html)

def call_wsgi(app, method, path, *, form=None, headers=None):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    encoded = urlencode(form or {}).encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(encoded)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "HTTP_HOST": "127.0.0.1:8765",
        "wsgi.input": BytesIO(encoded),
    }
    environ.update(headers or {})
    body = b"".join(app(environ, start_response)).decode("utf-8")
    return body, captured["status"], captured["headers"]


if __name__ == "__main__":
    unittest.main()
