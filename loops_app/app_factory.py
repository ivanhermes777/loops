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
            '<section class="panel history empty"><p class="eyebrow">Project History</p>'
            f"<h2>{html.escape(state.heading)}</h2>"
            f"<p>{html.escape(state.description)}</p>"
            f'<a class="primary secondary" href="#idea">{html.escape(state.primary_button_label)}</a></section>'
        )
    items = "".join(
        f'<li><strong>{html.escape(item.title)}</strong><span>{html.escape(item.created_at)}</span>'
        f'<a href="/blueprints/{html.escape(item.id)}.md">Export Markdown</a></li>'
        for item in state.items
    )
    return f'<section class="panel history"><p class="eyebrow">Project History</p><h2>{html.escape(state.heading)}</h2><ul>{items}</ul></section>'


def _latest_result_html(result: BlueprintResult | None) -> str:
    if result is None:
        return ""
    if result.status == "error":
        return f'<section class="panel alert"><h2>Generation paused</h2><p>{html.escape(result.error_message)}</p></section>'
    if result.status == "research_warning":
        findings = _research_list_html(result.research_findings)
        return (
            '<section class="panel warning"><h2>Research needs attention</h2>'
            f"<p>{html.escape(result.warning_message)}</p>{findings}"
            '<div class="actions">'
            f'<form method="post" action="/research/retry"><input type="hidden" name="pending_id" value="{html.escape(result.pending_id)}"><button>Retry research</button></form>'
            f'<form method="post" action="/research/continue-ai-only"><input type="hidden" name="pending_id" value="{html.escape(result.pending_id)}"><button>Continue with AI-only suggestions</button></form>'
            "</div></section>"
        )
    findings = _research_list_html(result.research_findings)
    return (
        '<section class="panel result"><p class="eyebrow">Completed Blueprint</p>'
        f"<h2>{html.escape(result.idea)}</h2>{findings}"
        f'<a class="primary" href="/blueprints/{html.escape(result.id)}.md">Export Markdown</a>'
        f"<pre>{html.escape(result.blueprint_markdown)}</pre></section>"
    )


def _research_list_html(findings: list[ResearchFinding]) -> str:
    if not findings:
        return '<p class="muted">No useful cited findings were collected yet.</p>'
    items = "".join(
        "<li>"
        f"<strong>{html.escape(finding.category.title())}</strong>: {html.escape(finding.summary)}"
        f'<br><a href="{html.escape(finding.source_url)}">{html.escape(finding.source_title)}</a>'
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
    :root {{ color-scheme: dark; --bg:#08111f; --panel:#101c30; --line:#243755; --text:#eef6ff; --muted:#a9b9cc; --cyan:#31d7ff; --blue:#3b82f6; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif; background: radial-gradient(circle at top left, #12345e, var(--bg) 42%); color:var(--text); }}
    main {{ max-width:1120px; margin:0 auto; padding:48px 20px; }}
    .hero {{ display:grid; gap:24px; grid-template-columns: minmax(0, 1.4fr) minmax(280px, .8fr); align-items:stretch; }}
    .panel {{ border:1px solid var(--line); background:rgba(16,28,48,.9); border-radius:24px; padding:28px; box-shadow:0 24px 80px rgba(0,0,0,.28); }}
    .eyebrow {{ color:var(--cyan); text-transform:uppercase; letter-spacing:.16em; font-size:.76rem; font-weight:800; }}
    h1 {{ font-size:clamp(2.4rem, 6vw, 5.4rem); line-height:.9; margin:8px 0 16px; }}
    h2 {{ margin-top:0; }}
    p {{ color:var(--muted); line-height:1.65; }}
    label {{ display:block; margin:18px 0 8px; font-weight:800; }}
    textarea {{ width:100%; min-height:150px; border-radius:18px; border:1px solid var(--line); background:#07111f; color:var(--text); padding:18px; font:inherit; }}
    button, .primary {{ display:inline-flex; align-items:center; justify-content:center; border:0; border-radius:999px; padding:13px 18px; margin-top:14px; color:#04111f; background:linear-gradient(135deg,var(--cyan),var(--blue)); font-weight:900; text-decoration:none; cursor:pointer; }}
    .secondary {{ background:#e8f7ff; }}
    .scope {{ margin-top:18px; padding:14px 16px; border-radius:18px; background:#07111f; border:1px solid var(--line); color:#d9e9ff; }}
    .grid {{ display:grid; grid-template-columns: .9fr 1.1fr; gap:22px; margin-top:22px; }}
    ul {{ padding-left:20px; }}
    li {{ margin:0 0 12px; color:var(--muted); }}
    .findings a {{ color:#9be9ff; }}
    .findings span {{ display:block; color:#88a0bb; margin-top:4px; }}
    .warning {{ border-color:#fbbf24; }} .alert {{ border-color:#fb7185; }}
    .actions {{ display:flex; gap:12px; flex-wrap:wrap; }}
    pre {{ white-space:pre-wrap; background:#050b14; border:1px solid var(--line); border-radius:18px; padding:18px; overflow:auto; }}
    .muted {{ color:#8da1b8; }}
    @media (max-width: 820px) {{ .hero, .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <section class="hero">
    <div class="panel">
      <p class="eyebrow">Local/Admin Blueprint Studio</p>
      <h1>Zelvari App Factory</h1>
      <p>Create monetization-ready app blueprints from a raw idea using automatic web research and the configured local LLM by default.</p>
      <p class="scope"><strong>Version 1 scope:</strong> this creates a monetization-ready blueprint, not a finished generated app. Markdown export only.</p>
    </div>
    <form id="idea" class="panel" method="post" action="/blueprints">
      <p class="eyebrow">Primary Idea Flow</p>
      <label for="idea-input">App idea</label>
      <textarea id="idea-input" name="idea" placeholder="Example: AI appointment recovery assistant for small clinics"></textarea>
      <button type="submit">Research and create blueprint</button>
      <p>Web research runs automatically for each submission. No public accounts, hosting setup, payments, or customer login are required.</p>
    </form>
  </section>
  <section class="grid">
    {history_html}
    <div>{latest_html or '<section class="panel"><h2>Blueprint structure</h2><p>Each completed blueprint includes pain points, urgency, audience, features, monetization, tech plan, launch checklist, and risks.</p></section>'}</div>
  </section>
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
