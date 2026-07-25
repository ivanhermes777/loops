"""Local/admin-only Zelvari App Factory blueprint MVP.

The first version intentionally creates monetization-ready Markdown blueprints only.
It does not generate app code, deploy apps, configure payments, or expose public
account flows.
"""

from __future__ import annotations

import html
import json
import os
import re
import socket
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol
from wsgiref.simple_server import make_server


REQUIRED_BLUEPRINT_SECTIONS = (
    "Pain Points",
    "Urgency",
    "Audience",
    "Features",
    "Monetization",
    "Tech Plan",
    "Launch Checklist",
    "Risks",
)

LOCAL_AI_UNAVAILABLE_MESSAGE = (
    "The local AI backend is unavailable. Please check the configured local "
    "model/service and make sure it is running before generating a blueprint."
)


class LocalAIUnavailableError(RuntimeError):
    """Raised when the configured local LLM service cannot generate text."""


@dataclass(frozen=True)
class ResearchFinding:
    category: str
    summary: str
    source_title: str
    source_url: str
    source_detail: str


@dataclass(frozen=True)
class HistoryItem:
    id: str
    title: str
    created_at: str


@dataclass(frozen=True)
class HistoryState:
    is_empty: bool
    heading: str
    description: str
    primary_button_label: str
    items: list[HistoryItem]


@dataclass(frozen=True)
class MarkdownExport:
    filename: str
    content_type: str
    content: str


@dataclass
class BlueprintResult:
    id: str = ""
    pending_id: str = ""
    idea: str = ""
    status: str = "complete"
    created_at: str = ""
    research_findings: list[ResearchFinding] = field(default_factory=list)
    blueprint_markdown: str = ""
    warning_message: str = ""
    error_message: str = ""
    can_retry_research: bool = False
    can_continue_with_ai_only: bool = False
    used_ai_only_suggestions: bool = False

    @property
    def title(self) -> str:
        return self.idea

    @property
    def cited_research_text(self) -> str:
        if not self.research_findings:
            return "No cited web research findings are available."
        lines = []
        for index, finding in enumerate(self.research_findings, start=1):
            lines.append(
                f"{index}. [{finding.category}] {finding.summary} "
                f"— {finding.source_title} ({finding.source_url}); {finding.source_detail}"
            )
        return "\n".join(lines)


class Researcher(Protocol):
    def research(self, idea: str) -> list[ResearchFinding]:
        """Return cited market research findings for the app idea."""
        ...


class LocalLLM(Protocol):
    def generate_blueprint(
        self,
        idea: str,
        findings: list[ResearchFinding],
        *,
        allow_ai_only: bool = False,
    ) -> str:
        """Generate a professional Markdown blueprint."""
        ...


class DuckDuckGoResearcher:
    """Small stdlib web researcher for local/admin MVP use.

    The implementation intentionally keeps dependencies at zero for CI and local
    setup. It fetches DuckDuckGo HTML results automatically and turns source
    snippets into cited findings. Network failures are surfaced to the UI instead
    of being hidden behind AI-only content.
    """

    SEARCH_CATEGORIES = (
        ("pain points", "pain points problems complaints"),
        ("urgency", "urgent need trend deadline cost of delay"),
        ("audience signals", "target audience small business buyers forum"),
        ("monetization opportunities", "pricing willingness to pay SaaS market"),
    )

    def __init__(self, timeout_seconds: float = 8.0, max_findings: int = 8):
        self.timeout_seconds = timeout_seconds
        self.max_findings = max_findings

    def research(self, idea: str) -> list[ResearchFinding]:
        findings: list[ResearchFinding] = []
        for category, suffix in self.SEARCH_CATEGORIES:
            if len(findings) >= self.max_findings:
                break
            findings.extend(self._search_category(idea, category, suffix))
        return findings[: self.max_findings]

    def _search_category(self, idea: str, category: str, suffix: str) -> list[ResearchFinding]:
        query = urllib.parse.urlencode({"q": f"{idea} {suffix}"})
        url = f"https://duckduckgo.com/html/?{query}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ZelvariAppFactory/1.0 (+local-admin-blueprint-research)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            page = response.read().decode("utf-8", errors="replace")
        return self._parse_results(page, category)

    def _parse_results(self, page: str, category: str) -> list[ResearchFinding]:
        results: list[ResearchFinding] = []
        blocks = re.findall(
            r'<a rel="nofollow" class="result__a" href="(?P<url>[^"]+)">(?P<title>.*?)</a>.*?'
            r'<a class="result__snippet".*?>(?P<snippet>.*?)</a>',
            page,
            flags=re.DOTALL,
        )
        for raw_url, raw_title, raw_snippet in blocks[:2]:
            title = _clean_html(raw_title)
            snippet = _clean_html(raw_snippet)
            source_url = _decode_duckduckgo_url(raw_url)
            if title and snippet and source_url:
                results.append(
                    ResearchFinding(
                        category=category,
                        summary=snippet,
                        source_title=title,
                        source_url=source_url,
                        source_detail="DuckDuckGo result snippet from web research",
                    )
                )
        return results


class OllamaLocalLLM:
    """Default local LLM client for the configured local model/service."""

    def __init__(self, endpoint: str | None = None, model: str | None = None, timeout_seconds: float = 60.0):
        self.endpoint = endpoint or os.getenv("ZELVARI_LOCAL_LLM_URL", "http://127.0.0.1:11434/api/generate")
        self.model = model or os.getenv("ZELVARI_LOCAL_LLM_MODEL", "gemma4")
        self.timeout_seconds = timeout_seconds

    def generate_blueprint(
        self,
        idea: str,
        findings: list[ResearchFinding],
        *,
        allow_ai_only: bool = False,
    ) -> str:
        prompt = _blueprint_prompt(idea, findings, allow_ai_only=allow_ai_only)
        payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
            raise LocalAIUnavailableError(str(exc)) from exc
        text = str(data.get("response", "")).strip()
        if not text:
            raise LocalAIUnavailableError("local model returned an empty response")
        return _ensure_blueprint_structure(text, idea, findings, allow_ai_only=allow_ai_only)


class AppFactory:
    """Core application service used by tests and the local HTTP UI."""

    def __init__(
        self,
        storage_path: str | Path = "data/app_factory_blueprints.json",
        *,
        researcher: Researcher | None = None,
        llm: LocalLLM | None = None,
    ):
        self.storage_path = Path(storage_path)
        self.researcher = researcher or DuckDuckGoResearcher()
        self.llm = llm or OllamaLocalLLM()
        self._pending: dict[str, BlueprintResult] = {}

    def submit_idea(self, idea: str) -> BlueprintResult:
        idea = idea.strip()
        if not idea:
            return BlueprintResult(status="error", error_message="Please enter an app idea first.")
        try:
            findings = self.researcher.research(idea)
        except Exception as exc:  # surfaced as research warning by design
            partial_findings = list(getattr(exc, "partial_findings", []) or [])
            return self._research_warning(idea, partial_findings)
        if self._research_is_weak(findings):
            return self._research_warning(idea, findings)
        return self._generate_and_save(idea, findings, allow_ai_only=False)

    def retry_research(self, pending_id: str) -> BlueprintResult:
        pending = self._pending[pending_id]
        return self.submit_idea(pending.idea)

    def continue_with_ai_only(self, pending_id: str) -> BlueprintResult:
        pending = self._pending[pending_id]
        return self._generate_and_save(pending.idea, pending.research_findings, allow_ai_only=True)

    def history(self) -> list[HistoryItem]:
        return [
            HistoryItem(id=item.id, title=item.idea, created_at=item.created_at)
            for item in sorted(self._load_all(), key=lambda saved: saved.created_at, reverse=True)
        ]

    def history_state(self) -> HistoryState:
        items = self.history()
        return HistoryState(
            is_empty=not items,
            heading="No blueprints yet" if not items else "Project history",
            description=(
                "Create your first monetization-ready app blueprint. Your saved local projects "
                "will appear here so you can reopen them later."
                if not items
                else "Reopen previous local/admin-only blueprints saved on this machine."
            ),
            primary_button_label="Create your first app blueprint" if not items else "Create another blueprint",
            items=items,
        )

    def open_blueprint(self, blueprint_id: str) -> BlueprintResult:
        for item in self._load_all():
            if item.id == blueprint_id:
                return item
        raise KeyError(f"Blueprint not found: {blueprint_id}")

    def export_markdown(self, blueprint_id: str) -> MarkdownExport:
        blueprint = self.open_blueprint(blueprint_id)
        slug = _slugify(blueprint.idea) or "app-blueprint"
        content = _markdown_document(blueprint)
        return MarkdownExport(
            filename=f"{slug}.md",
            content_type="text/markdown; charset=utf-8",
            content=content,
        )

    def _research_warning(self, idea: str, findings: Iterable[ResearchFinding]) -> BlueprintResult:
        pending_id = uuid.uuid4().hex
        result = BlueprintResult(
            pending_id=pending_id,
            idea=idea,
            status="research_warning",
            research_findings=list(findings),
            warning_message=(
                "Web research failed or returned weak results. Partial findings are preserved when available. "
                "Retry research, or continue with clearly labeled AI-only suggestions."
            ),
            can_retry_research=True,
            can_continue_with_ai_only=True,
        )
        self._pending[pending_id] = result
        return result

    def _research_is_weak(self, findings: list[ResearchFinding]) -> bool:
        return len(findings) < 2

    def _generate_and_save(
        self,
        idea: str,
        findings: list[ResearchFinding],
        *,
        allow_ai_only: bool,
    ) -> BlueprintResult:
        try:
            blueprint = self.llm.generate_blueprint(idea, findings, allow_ai_only=allow_ai_only)
        except LocalAIUnavailableError:
            return BlueprintResult(status="error", idea=idea, research_findings=findings, error_message=LOCAL_AI_UNAVAILABLE_MESSAGE)
        blueprint = _ensure_blueprint_structure(blueprint, idea, findings, allow_ai_only=allow_ai_only)
        result = BlueprintResult(
            id=uuid.uuid4().hex,
            idea=idea,
            status="complete",
            created_at=datetime.now(timezone.utc).isoformat(),
            research_findings=findings,
            blueprint_markdown=blueprint,
            used_ai_only_suggestions=allow_ai_only,
        )
        self._save(result)
        return result

    def _load_all(self) -> list[BlueprintResult]:
        if not self.storage_path.exists():
            return []
        with self.storage_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return [_result_from_dict(item) for item in data]

    def _save(self, result: BlueprintResult) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._load_all()
        existing.append(result)
        with self.storage_path.open("w", encoding="utf-8") as handle:
            json.dump([_result_to_dict(item) for item in existing], handle, indent=2)


class LocalApp:
    """Minimal stdlib web UI for local/admin use."""

    def __init__(self, factory: AppFactory):
        self.factory = factory
        self.latest_result: BlueprintResult | None = None

    def render_home(self) -> str:
        history_state = self.factory.history_state()
        latest = self.latest_result
        return _page_template(
            history_html=_history_html(history_state),
            latest_html=_latest_result_html(latest),
        )

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        if method == "POST" and path == "/blueprints":
            form = _read_form(environ)
            self.latest_result = self.factory.submit_idea(form.get("idea", ""))
            return _response(start_response, "303 See Other", b"", headers=[("Location", "/")])
        if method == "POST" and path == "/research/retry":
            form = _read_form(environ)
            self.latest_result = self.factory.retry_research(form["pending_id"])
            return _response(start_response, "303 See Other", b"", headers=[("Location", "/")])
        if method == "POST" and path == "/research/continue-ai-only":
            form = _read_form(environ)
            self.latest_result = self.factory.continue_with_ai_only(form["pending_id"])
            return _response(start_response, "303 See Other", b"", headers=[("Location", "/")])
        if method == "GET" and path.startswith("/blueprints/") and path.endswith(".md"):
            blueprint_id = path.split("/")[2].removesuffix(".md")
            export = self.factory.export_markdown(blueprint_id)
            return _response(
                start_response,
                "200 OK",
                export.content.encode("utf-8"),
                headers=[
                    ("Content-Type", export.content_type),
                    ("Content-Disposition", f'attachment; filename="{export.filename}"'),
                ],
            )
        if method == "GET" and path.startswith("/blueprints/"):
            blueprint_id = path.split("/")[2]
            self.latest_result = self.factory.open_blueprint(blueprint_id)
            body = self.render_home().encode("utf-8")
            return _response(start_response, "200 OK", body, headers=[("Content-Type", "text/html; charset=utf-8")])
        body = self.render_home().encode("utf-8")
        return _response(start_response, "200 OK", body, headers=[("Content-Type", "text/html; charset=utf-8")])


def create_app(
    storage_path: str | Path = "data/app_factory_blueprints.json",
    *,
    researcher: Researcher | None = None,
    llm: LocalLLM | None = None,
) -> LocalApp:
    return LocalApp(AppFactory(storage_path, researcher=researcher, llm=llm))


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    app = create_app()
    with make_server(host, port, app) as server:
        print(f"Zelvari App Factory running at http://{host}:{port}")
        server.serve_forever()


def _blueprint_prompt(idea: str, findings: list[ResearchFinding], *, allow_ai_only: bool) -> str:
    research_block = "\n".join(f"- {finding.category}: {finding.summary} ({finding.source_url})" for finding in findings)
    if allow_ai_only:
        research_block = (research_block or "No strong cited sources available.") + "\nLabel any unsupported suggestions as AI-only."
    sections = ", ".join(REQUIRED_BLUEPRINT_SECTIONS)
    return (
        "You are Zelvari App Factory, a local/admin-only blueprint generator. "
        "Generate a professional monetization-ready app blueprint, not finished app code.\n"
        f"Idea: {idea}\n"
        f"Cited research findings:\n{research_block}\n"
        f"Use Markdown and include exactly these section headings: {sections}."
    )


def _ensure_blueprint_structure(
    text: str,
    idea: str,
    findings: list[ResearchFinding],
    *,
    allow_ai_only: bool,
) -> str:
    body = text.strip()
    missing = [section for section in REQUIRED_BLUEPRINT_SECTIONS if f"## {section}" not in body]
    if missing:
        additions = []
        for section in missing:
            additions.append(f"## {section}\n{_fallback_section(section, idea, findings, allow_ai_only)}")
        body = body + "\n\n" + "\n\n".join(additions)
    return body


def _fallback_section(section: str, idea: str, findings: list[ResearchFinding], allow_ai_only: bool) -> str:
    qualifier = "AI-only suggestion: " if allow_ai_only else ""
    research_hint = findings[0].summary if findings else "Validate this with stronger market research before launch."
    return f"{qualifier}For {idea}, use the research signal: {research_hint}"


def _markdown_document(result: BlueprintResult) -> str:
    warning = "\n\n> AI-only suggestions were used because web research was weak or unavailable.\n" if result.used_ai_only_suggestions else ""
    return (
        "# Zelvari App Factory Blueprint\n\n"
        f"**Idea:** {result.idea}\n\n"
        "**First-version scope:** This is a monetization-ready blueprint, not a finished generated app.\n"
        f"{warning}\n"
        "## Research Findings\n\n"
        f"{result.cited_research_text}\n\n"
        f"{result.blueprint_markdown}\n"
    )


def _history_html(state: HistoryState) -> str:
    if state.is_empty:
        return (
            '<aside class="history-sidebar glass-panel empty" aria-label="Project history"><p class="eyebrow">Project History</p>'
            f"<h2>{html.escape(state.heading)}</h2>"
            f"<p>{html.escape(state.description)}</p>"
            f'<a class="primary secondary" href="#idea">{html.escape(state.primary_button_label)}</a></aside>'
        )
    items = "".join(
        f'<li class="history-item"><span class="status-dot" aria-hidden="true"></span><div><strong>{html.escape(item.title)}</strong>'
        f'<span>{html.escape(item.created_at)}</span><div class="history-actions">'
        f'<a href="/blueprints/{html.escape(item.id)}">Reopen blueprint</a>'
        f'<a href="/blueprints/{html.escape(item.id)}.md">Export Markdown</a></div></div></li>'
        for item in state.items
    )
    return f'<aside class="history-sidebar glass-panel" aria-label="Project history"><p class="eyebrow">Project History</p><h2>{html.escape(state.heading)}</h2><p>{html.escape(state.description)}</p><ul>{items}</ul></aside>'


def _latest_result_html(result: BlueprintResult | None) -> str:
    if result is None:
        return ""
    if result.status == "error":
        return f'<section class="glass-panel alert"><h2>Generation paused</h2><p>{html.escape(result.error_message)}</p></section>'
    if result.status == "research_warning":
        findings = _research_list_html(result.research_findings)
        return (
            '<section class="glass-panel warning"><h2>Research needs attention</h2>'
            f"<p>{html.escape(result.warning_message)}</p>{findings}"
            '<div class="actions">'
            f'<form method="post" action="/research/retry"><input type="hidden" name="pending_id" value="{html.escape(result.pending_id)}"><button>Retry research</button></form>'
            f'<form method="post" action="/research/continue-ai-only"><input type="hidden" name="pending_id" value="{html.escape(result.pending_id)}"><button>Continue with AI-only suggestions</button></form>'
            "</div></section>"
        )
    findings = _research_list_html(result.research_findings)
    return (
        '<section class="glass-panel result"><div class="blueprint-deliverable"><p class="eyebrow">Completed Blueprint</p>'
        f"<h2>{html.escape(result.idea)}</h2>{findings}"
        f'<a class="primary" href="/blueprints/{html.escape(result.id)}.md">Export Markdown</a>'
        f"<pre aria-label=\"Generated blueprint Markdown\">{html.escape(result.blueprint_markdown)}</pre></div></section>"
    )


def _research_list_html(findings: list[ResearchFinding]) -> str:
    if not findings:
        return '<p class="muted">No useful cited findings were collected yet.</p>'
    items = "".join(
        '<li class="evidence-card">'
        f'<div><p class="eyebrow">Source type: {html.escape(finding.category.title())}</p>'
        f"<strong>{html.escape(finding.source_title)}</strong>"
        f'<span class="credibility">Credibility cue: cited web source reviewed by admin</span></div>'
        f"<p>{html.escape(finding.summary)}</p>"
        f'<a href="{html.escape(finding.source_url)}">Open source</a>'
        f'<span>{html.escape(finding.source_detail)}</span></li>'
        for finding in findings
    )
    return f"<h3>Cited research findings</h3><ul class=\"findings\">{items}</ul>"


def _page_template(*, history_html: str, latest_html: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Zelvari App Factory</title>
  <style>
    :root {{ color-scheme: dark; --bg:#030712; --panel:rgba(10,22,42,.76); --panel-strong:rgba(16,30,56,.92); --line:rgba(129,199,255,.24); --text:#f3f8ff; --muted:#adc0d8; --cyan:#2ee8ff; --violet:#9d6bff; --blue:#4b8dff; --gold:#ffd166; }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; min-height:100vh; font-family: Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif; background:radial-gradient(circle at 18% 10%, rgba(46,232,255,.2), transparent 28%), radial-gradient(circle at 84% 2%, rgba(157,107,255,.24), transparent 32%), linear-gradient(135deg,#020617 0%,#081426 52%,#020617 100%); color:var(--text); }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; background:linear-gradient(120deg, transparent, rgba(46,232,255,.08), transparent); animation:aurora 10s ease-in-out infinite alternate; }}
    main {{ width:min(1480px, 100%); margin:0 auto; padding:28px; position:relative; }}
    .app-shell.command-center {{ display:grid; grid-template-columns:310px minmax(0,1fr); gap:24px; align-items:start; }}
    .command-main {{ display:grid; gap:22px; }}
    .workspace-hero {{ display:grid; grid-template-columns:minmax(0,1.05fr) minmax(340px,.95fr); gap:22px; align-items:stretch; }}
    .glass-panel {{ border:1px solid var(--line); background:linear-gradient(145deg, rgba(9,20,39,.86), rgba(15,29,55,.68)); border-radius:28px; padding:28px; box-shadow:0 28px 90px rgba(0,0,0,.36), inset 0 1px 0 rgba(255,255,255,.08); backdrop-filter:blur(18px); transition:transform .22s ease, border-color .22s ease, box-shadow .22s ease; }}
    .glass-panel:hover {{ transform:translateY(-2px); border-color:rgba(46,232,255,.48); box-shadow:0 32px 105px rgba(0,0,0,.44), 0 0 38px rgba(46,232,255,.1); }}
    .panel {{ border:1px solid var(--line); background:var(--panel); border-radius:24px; padding:24px; }}
    .eyebrow {{ color:var(--cyan); text-transform:uppercase; letter-spacing:.16em; font-size:.76rem; font-weight:800; }}
    h1 {{ font-size:clamp(2.55rem, 6vw, 5.8rem); line-height:.88; margin:8px 0 16px; letter-spacing:-.07em; }}
    h2 {{ margin-top:0; letter-spacing:-.03em; }}
    h3 {{ letter-spacing:-.02em; }}
    p {{ color:var(--muted); line-height:1.7; font-size:1rem; }}
    label {{ display:block; margin:18px 0 8px; font-weight:800; }}
    textarea {{ width:100%; min-height:190px; border-radius:22px; border:1px solid var(--line); background:rgba(3,9,20,.82); color:var(--text); padding:18px; font:inherit; box-shadow:inset 0 0 28px rgba(46,232,255,.05); }}
    button, .primary {{ display:inline-flex; align-items:center; justify-content:center; border:0; border-radius:999px; padding:13px 19px; margin-top:14px; color:#03101d; background:linear-gradient(135deg,var(--cyan),var(--blue) 58%,var(--violet)); font-weight:900; text-decoration:none; cursor:pointer; box-shadow:0 14px 34px rgba(46,232,255,.2); transition:transform .2s ease, box-shadow .2s ease; }}
    button:hover, .primary:hover {{ transform:translateY(-1px); box-shadow:0 18px 42px rgba(46,232,255,.3); }}
    :focus-visible {{ outline:3px solid var(--gold); outline-offset:4px; }}
    .secondary {{ background:linear-gradient(135deg,#effaff,#b9e8ff); }}
    .scope {{ margin-top:18px; padding:16px 18px; border-radius:20px; background:rgba(3,9,20,.68); border:1px solid var(--line); color:#e5f4ff; }}
    .research-pipeline {{ display:grid; grid-template-columns:repeat(5, minmax(110px,1fr)); gap:12px; margin-top:22px; }}
    .pipeline-stage {{ position:relative; min-height:94px; border:1px solid rgba(46,232,255,.22); border-radius:18px; padding:14px; background:rgba(8,18,34,.72); color:#dfeeff; }}
    .pipeline-stage::before {{ content:""; display:block; width:10px; height:10px; border-radius:999px; margin-bottom:10px; background:var(--cyan); box-shadow:0 0 18px var(--cyan); animation:pulse 1.9s ease-in-out infinite; }}
    .pipeline-stage span {{ display:block; color:var(--muted); font-size:.84rem; margin-top:4px; }}
    .support-grid {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(300px,.65fr); gap:22px; }}
    ul {{ padding-left:0; list-style:none; }}
    li {{ margin:0 0 12px; color:var(--muted); }}
    .history-sidebar {{ position:sticky; top:24px; min-height:calc(100vh - 56px); }}
    .history-item {{ display:flex; gap:12px; padding:14px; border:1px solid rgba(255,255,255,.08); border-radius:18px; background:rgba(255,255,255,.035); }}
    .history-item strong, .evidence-card strong {{ display:block; color:var(--text); }}
    .history-item span, .history-actions {{ display:block; color:#91a8c4; font-size:.88rem; margin-top:4px; }}
    .history-actions {{ display:flex; gap:12px; flex-wrap:wrap; }}
    .history-actions a, .findings a {{ color:#9be9ff; }}
    .status-dot {{ width:10px; height:10px; flex:0 0 10px; margin-top:5px; border-radius:999px; background:var(--cyan); box-shadow:0 0 16px rgba(46,232,255,.8); }}
    .findings {{ display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:14px; }}
    .evidence-card {{ padding:18px; border:1px solid rgba(129,199,255,.22); border-radius:20px; background:linear-gradient(160deg, rgba(5,14,29,.92), rgba(20,31,58,.72)); }}
    .evidence-card .eyebrow {{ margin:0 0 6px; }}
    .evidence-card .credibility, .findings span {{ display:block; color:#9fb3cc; margin-top:6px; font-size:.9rem; }}
    .warning {{ border-color:#fbbf24; }} .alert {{ border-color:#fb7185; }}
    .actions {{ display:flex; gap:12px; flex-wrap:wrap; }}
    .blueprint-deliverable pre {{ white-space:pre-wrap; background:linear-gradient(180deg, rgba(2,8,18,.96), rgba(5,14,28,.92)); border:1px solid rgba(46,232,255,.2); border-radius:22px; padding:22px; overflow:auto; line-height:1.68; box-shadow:inset 0 0 26px rgba(46,232,255,.04); }}
    .muted {{ color:#8da1b8; }}
    @keyframes aurora {{ from {{ opacity:.55; transform:translateX(-4%); }} to {{ opacity:.95; transform:translateX(4%); }} }}
    @keyframes pulse {{ 0%,100% {{ transform:scale(.9); opacity:.75; }} 50% {{ transform:scale(1.12); opacity:1; }} }}
    @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation:none !important; transition:none !important; scroll-behavior:auto !important; }} }}
    @media (max-width: 1040px) {{ .app-shell.command-center, .workspace-hero, .support-grid {{ grid-template-columns:1fr; }} .history-sidebar {{ position:static; min-height:auto; order:3; }} .research-pipeline {{ grid-template-columns:1fr; }} }}
    @media (max-width: 720px) {{ main {{ padding:16px; }} .glass-panel {{ padding:20px; border-radius:22px; }} .findings {{ grid-template-columns:1fr; }} h1 {{ font-size:clamp(2.25rem, 14vw, 3.8rem); }} }}
  </style>
</head>
<body>
<main>
  <div class="app-shell command-center">
    {history_html}
    <div class="command-main">
      <section class="workspace-hero glass-panel">
        <div>
      <p class="eyebrow">Local/Admin Blueprint Studio</p>
      <h1>Zelvari App Factory</h1>
      <p>Create monetization-ready app blueprints from a raw idea using automatic web research and the configured local LLM by default.</p>
      <p class="scope"><strong>Version 1 scope:</strong> this creates a monetization-ready blueprint, not a finished generated app. Markdown export only.</p>
      <div class="research-pipeline" aria-label="Research pipeline progress">
        <div class="pipeline-stage"><strong>Idea intake</strong><span>Capture the raw app opportunity.</span></div>
        <div class="pipeline-stage"><strong>Market scan</strong><span>Find pain and urgency signals.</span></div>
        <div class="pipeline-stage"><strong>Source review</strong><span>Surface cited evidence cards.</span></div>
        <div class="pipeline-stage"><strong>Blueprint generation</strong><span>Use the configured local AI model.</span></div>
        <div class="pipeline-stage"><strong>Export readiness</strong><span>Save locally and export Markdown only.</span></div>
      </div>
    </div>
    <form id="idea" class="panel idea-console" method="post" action="/blueprints">
      <p class="eyebrow">Primary Idea Flow</p>
      <label for="idea-input">App idea</label>
      <textarea id="idea-input" name="idea" placeholder="Example: AI appointment recovery assistant for small clinics"></textarea>
      <button type="submit">Research and create blueprint</button>
      <p>Web research runs automatically for each submission. No public accounts, hosting setup, payments, or customer login are required.</p>
    </form>
  </section>
  <section class="support-grid">
    <div>{latest_html or '<section class="glass-panel"><h2>Blueprint structure</h2><p>Each completed blueprint includes pain points, urgency, audience, features, monetization, tech plan, launch checklist, and risks.</p></section>'}</div>
    <aside class="glass-panel" aria-label="Command center guidance"><p class="eyebrow">Operator Guidance</p><h2>Blueprint-only first version</h2><p>The workspace researches the market, cites sources, saves local history, and prepares a professional Markdown deliverable while avoiding account flows, billing setup, hosting deployment, PDF output, and completed app-code generation.</p></aside>
  </section>
    </div>
  </div>
</main>
</body>
</html>"""


def _response(start_response, status: str, body: bytes, headers: list[tuple[str, str]] | None = None):
    start_response(status, headers or [("Content-Type", "text/plain; charset=utf-8")])
    return [body]


def _read_form(environ) -> dict[str, str]:
    size = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(size).decode("utf-8")
    parsed = urllib.parse.parse_qs(body)
    return {key: values[0] for key, values in parsed.items()}


def _clean_html(value: str) -> str:
    without_tags = re.sub(r"<.*?>", " ", value)
    return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()


def _decode_duckduckgo_url(url: str) -> str:
    decoded = html.unescape(url)
    parsed = urllib.parse.urlparse(decoded)
    query_url = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
    return urllib.parse.unquote(query_url or decoded)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80]


def _result_to_dict(result: BlueprintResult) -> dict[str, object]:
    data = asdict(result)
    data["research_findings"] = [asdict(finding) for finding in result.research_findings]
    return data


def _result_from_dict(data: dict[str, object]) -> BlueprintResult:
    raw_findings = data.get("research_findings", [])
    findings = [ResearchFinding(**finding) for finding in raw_findings]  # type: ignore[arg-type]
    copied = dict(data)
    copied["research_findings"] = findings
    return BlueprintResult(**copied)  # type: ignore[arg-type]


if __name__ == "__main__":
    run()
