"""Stdlib WSGI app factory for the Zelvari cellphone buyback MVP."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import os
import subprocess
from http import HTTPStatus
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from .buyback import (
    SUPPORTED_CONDITIONS,
    BuybackStore,
    calculate_offer,
    seed_sample_pricing,
    validate_request_fields,
)

ResponseBody = str
StartResponse = Callable[[str, list[tuple[str, str]]], None]


class BuybackApp:
    def __init__(self, db_path: str):
        self.store = BuybackStore(db_path)

    def __call__(self, environ: dict, start_response: StartResponse):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        try:
            if method == "GET" and path == "/":
                return self._send(start_response, HTTPStatus.OK, self._public_quote_page())
            if method == "POST" and path == "/request":
                status, body = self._submit_request(self._form_data(environ))
                return self._send(start_response, status, body)
            if method == "GET" and path == "/prompt-builder":
                return self._send(start_response, HTTPStatus.OK, self._prompt_builder_page())
            if method == "POST" and path == "/prompt-builder":
                status, body = self._submit_prompt_builder(self._form_data(environ))
                return self._send(start_response, status, body)
            if method == "GET" and path == "/admin/login":
                return self._send(start_response, HTTPStatus.OK, self._login_page())
            if method == "POST" and path == "/admin/login":
                status, body, headers = self._login(self._form_data(environ))
                return self._send(start_response, status, body, headers=headers)
            if method == "GET" and path == "/admin":
                if not self._is_admin(environ):
                    return self._send(start_response, HTTPStatus.UNAUTHORIZED, self._login_page("Admin login required"))
                return self._send(start_response, HTTPStatus.OK, self._admin_page())
            if method == "POST" and path == "/admin/pricing/update":
                if not self._is_admin(environ):
                    return self._send(start_response, HTTPStatus.UNAUTHORIZED, self._login_page("Admin login required"))
                status, body = self._update_pricing(self._form_data(environ))
                return self._send(start_response, status, body)
            return self._send(start_response, HTTPStatus.NOT_FOUND, self._page("Not Found", "<p>Page not found.</p>"))
        except Exception as error:  # pragma: no cover - defensive WSGI boundary
            safe_error = html.escape(str(error))
            return self._send(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                self._page("Error", f"<p>Something went wrong: {safe_error}</p>"),
            )

    def _send(
        self,
        start_response: StartResponse,
        status: HTTPStatus,
        body: ResponseBody,
        *,
        headers: list[tuple[str, str]] | None = None,
    ):
        response_headers = [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body.encode("utf-8")))),
        ]
        if headers:
            response_headers.extend(headers)
        start_response(f"{status.value} {status.phrase}", response_headers)
        return [body.encode("utf-8")]

    def _form_data(self, environ: dict) -> dict[str, str]:
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
        raw_body = environ["wsgi.input"].read(content_length).decode("utf-8")
        return {key: values[0] for key, values in parse_qs(raw_body, keep_blank_values=True).items()}

    def _public_quote_page(self, errors: list[str] | None = None) -> str:
        pricing = self.store.list_pricing(active_only=True)
        if not pricing:
            return self._page(
                "Zelvari Phone Buyback",
                """
                <section class="hero">
                  <p class="eyebrow">Zelvari Buyback</p>
                  <h1>Instant cellphone buyback estimates</h1>
                  <p>Pricing is not available yet. Please check back soon so Zelvari can provide an accurate offer.</p>
                </section>
                """,
            )

        catalog_json = json.dumps(pricing)
        conditions_json = json.dumps(list(SUPPORTED_CONDITIONS.keys()))
        error_html = self._error_list(errors or [])
        body = f"""
        <section class="hero">
          <p class="eyebrow">Zelvari Buyback</p>
          <h1>Get an instant estimate for your iPhone or Samsung Galaxy.</h1>
          <p>Select your supported phone details, view the estimate, then send your contact information for manual follow-up by Zelvari.</p>
        </section>
        {error_html}
        <form class="card" method="post" action="/request" id="quote-form">
          <div class="grid">
            <label>Brand<select name="brand" id="brand" required></select></label>
            <label>Model<select name="model" id="model" required></select></label>
            <label>Storage<select name="storage" id="storage" required></select></label>
            <label>Condition<select name="condition" id="condition" required></select></label>
          </div>
          <div class="estimate" id="estimate">Choose a supported phone to see an estimate.</div>
          <div class="grid">
            <label>Name<input name="name" required autocomplete="name"></label>
            <label>Email<input type="email" name="email" required autocomplete="email"></label>
            <label>Phone<input name="phone" required autocomplete="tel"></label>
            <label>Optional notes<textarea name="notes" placeholder="Carrier, unlock status, accessories, or damage details"></textarea></label>
          </div>
          <button type="submit">Submit offer request</button>
        </form>
        <script>
        const catalog = {catalog_json};
        const conditions = {conditions_json};
        const multipliers = {json.dumps(SUPPORTED_CONDITIONS)};
        const fields = ['brand', 'model', 'storage', 'condition'].reduce((acc, id) => {{ acc[id] = document.getElementById(id); return acc; }}, {{}});
        const estimate = document.getElementById('estimate');
        function unique(values) {{ return [...new Set(values)].sort(); }}
        function options(select, values) {{
          select.innerHTML = values.map(value => `<option value="${{value}}">${{value}}</option>`).join('');
        }}
        function matching() {{
          return catalog.filter(row => (!fields.brand.value || row.brand === fields.brand.value)
            && (!fields.model.value || row.model === fields.model.value));
        }}
        function refreshModels() {{
          const models = unique(catalog.filter(row => row.brand === fields.brand.value).map(row => row.model));
          options(fields.model, models);
          refreshStorage();
        }}
        function refreshStorage() {{
          const rows = matching();
          options(fields.storage, unique(rows.map(row => row.storage)));
          refreshEstimate();
        }}
        function refreshEstimate() {{
          const row = catalog.find(item => item.brand === fields.brand.value && item.model === fields.model.value && item.storage === fields.storage.value);
          const multiplier = multipliers[fields.condition.value];
          if (!row || !multiplier) {{ estimate.textContent = 'Choose a supported phone to see an estimate.'; return; }}
          const dollars = Math.round(row.base_price_cents * multiplier) / 100;
          estimate.textContent = `Estimated offer: $${{dollars.toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}})}}`;
        }}
        options(fields.brand, unique(catalog.map(row => row.brand)));
        options(fields.condition, conditions);
        fields.brand.addEventListener('change', refreshModels);
        fields.model.addEventListener('change', refreshStorage);
        fields.storage.addEventListener('change', refreshEstimate);
        fields.condition.addEventListener('change', refreshEstimate);
        refreshModels();
        </script>
        """
        return self._page("Zelvari Phone Buyback", body)

    def _submit_request(self, data: dict[str, str]) -> tuple[HTTPStatus, str]:
        errors = validate_request_fields(data)
        if errors:
            return HTTPStatus.BAD_REQUEST, self._public_quote_page(errors)
        try:
            offer = calculate_offer(
                self.store,
                brand=data["brand"].strip(),
                model=data["model"].strip(),
                storage=data["storage"].strip(),
                condition=data["condition"].strip(),
            )
        except ValueError as error:
            return HTTPStatus.BAD_REQUEST, self._public_quote_page([str(error)])
        self.store.save_offer_request(
            {
                "name": data["name"].strip(),
                "email": data["email"].strip(),
                "phone": data["phone"].strip(),
                "brand": offer["brand"],
                "model": offer["model"],
                "storage": offer["storage"],
                "condition": offer["condition"],
                "estimate_cents": offer["offer_cents"],
                "base_price_cents": offer["base_price_cents"],
                "condition_multiplier": offer["condition_multiplier"],
                "notes": data.get("notes", "").strip(),
            }
        )
        amount = _money(offer["offer_cents"])
        return HTTPStatus.OK, self._page(
            "Request Submitted",
            f"""
            <section class="card success">
              <p class="eyebrow">Request received</p>
              <h1>Your estimated offer is {amount}.</h1>
              <p>Zelvari will follow up manually to confirm the device details and next steps. This MVP does not process checkout, payouts, or shipping labels online.</p>
              <a class="button-link" href="/">Start another quote</a>
            </section>
            """,
        )

    def _prompt_builder_page(
        self,
        *,
        validation_message: str = "",
        unavailable: bool = False,
        improved_prompt: str = "",
    ) -> str:
        validation_html = (
            f"<p class='prompt-validation' role='alert'>{html.escape(validation_message)}</p>"
            if validation_message
            else ""
        )
        unavailable_html = (
            """
            <div class="prompt-error" role="alert">
              <strong>Prompt improvement is temporarily unavailable.</strong>
              <span>Please try again shortly. Your prompt was not stored.</span>
            </div>
            """
            if unavailable
            else ""
        )
        result_html = (
            f"<pre id='improved-prompt-text' class='prompt-output-text'>{html.escape(improved_prompt)}</pre>"
            if improved_prompt
            else "<p id='improved-prompt-text' class='prompt-placeholder'>Your optimized prompt will appear here after generation.</p>"
        )
        body = f"""
        <section class="prompt-shell">
          <header class="prompt-topbar" aria-label="Zelvari prompt builder header">
            <a class="prompt-brand" href="/prompt-builder" aria-label="Zelvari prompt builder home"><span class="prompt-logo">Z</span><span>ZELVARI</span></a>
            <a class="prompt-home" href="/">Cellphone Buyback</a>
          </header>
          <section class="prompt-hero">
            <div class="prompt-orb" aria-hidden="true"><span>Z</span></div>
            <div>
              <h1>Write Better Prompts. <span>Get Better Results.</span></h1>
              <p>Enter your prompt and let AI optimize it for clarity, power, and results.</p>
              <div class="prompt-badges" aria-label="Prompt builder features">
                <span>⚡ AI-Powered</span>
                <span>📈 Smart Optimization</span>
                <span>🎯 Stronger Results</span>
              </div>
            </div>
          </section>
          <section class="prompt-flow" aria-label="Prompt improvement workflow">
            <form class="prompt-card prompt-input-card" method="post" action="/prompt-builder" novalidate>
              <div class="prompt-card-title"><span>↗</span><h2>Your Prompt</h2><button type="button" class="prompt-clear" id="prompt-clear">Clear</button></div>
              {validation_html}
              <label class="prompt-textarea-label" for="prompt-input">Rough prompt</label>
              <textarea id="prompt-input" name="prompt" maxlength="4000" placeholder="Paste or type your prompt here..." aria-describedby="prompt-counter prompt-privacy"></textarea>
              <div class="prompt-counter" id="prompt-counter">0 / 4000</div>
              <div class="prompt-select-grid">
                <label>Goal<select name="goal">{_prompt_options(['General', 'Marketing', 'Sales', 'Content', 'Coding'])}</select></label>
                <label>Tone<select name="tone">{_prompt_options(['Professional', 'Friendly', 'Bold', 'Luxury', 'Concise'])}</select></label>
                <label>Platform<select name="platform">{_prompt_options(['General (Any AI)', 'Website', 'Social Media', 'Email', 'Hermes/Codex'])}</select></label>
              </div>
              <button class="prompt-submit" type="submit">✧ Improve Prompt</button>
            </form>
            <div class="prompt-arrow" aria-hidden="true">»</div>
            <article class="prompt-card prompt-output-card" aria-live="polite">
              <div class="prompt-card-title"><span>✣</span><h2>Improved Prompt</h2><button type="button" class="prompt-copy" id="copy-prompt">Copy</button></div>
              {unavailable_html}
              <div class="prompt-output-box">{result_html}</div>
              <p class="prompt-copy-status" id="copy-status" aria-live="polite"></p>
            </article>
          </section>
          <p class="prompt-privacy" id="prompt-privacy">⌾ Your prompts are private and never stored.</p>
        </section>
        <script>
        const promptInput = document.getElementById('prompt-input');
        const promptCounter = document.getElementById('prompt-counter');
        const clearButton = document.getElementById('prompt-clear');
        const copyButton = document.getElementById('copy-prompt');
        const copyStatus = document.getElementById('copy-status');
        function updatePromptCounter() {{ promptCounter.textContent = `${{promptInput.value.length}} / 4000`; }}
        promptInput.addEventListener('input', updatePromptCounter);
        clearButton.addEventListener('click', () => {{ promptInput.value = ''; updatePromptCounter(); promptInput.focus(); }});
        copyButton.addEventListener('click', async () => {{
          const text = document.getElementById('improved-prompt-text').innerText.trim();
          if (!text || text === 'Your optimized prompt will appear here after generation.') return;
          try {{ await navigator.clipboard.writeText(text); copyStatus.textContent = 'Copied'; }}
          catch (error) {{ copyStatus.textContent = 'Select the prompt text to copy manually.'; }}
        }});
        updatePromptCounter();
        </script>
        """
        return self._page("Zelvari AI Prompt Builder", body, prompt_builder=True)

    def _submit_prompt_builder(self, data: dict[str, str]) -> tuple[HTTPStatus, str]:
        prompt = data.get("prompt", "").strip()
        if not prompt:
            return HTTPStatus.BAD_REQUEST, self._prompt_builder_page(validation_message="Please enter a prompt to improve.")
        if len(prompt) > 4000:
            prompt = prompt[:4000]
        improved_prompt = _run_prompt_builder_command(
            {
                "prompt": prompt,
                "goal": data.get("goal", "General").strip() or "General",
                "tone": data.get("tone", "Professional").strip() or "Professional",
                "platform": data.get("platform", "General (Any AI)").strip() or "General (Any AI)",
            }
        )
        if improved_prompt is None:
            return HTTPStatus.SERVICE_UNAVAILABLE, self._prompt_builder_page(unavailable=True)
        return HTTPStatus.OK, self._prompt_builder_page(improved_prompt=improved_prompt)

    def _login_page(self, message: str = "") -> str:
        notice = f"<p class='error'>{html.escape(message)}</p>" if message else ""
        return self._page(
            "Admin Login",
            f"""
            <section class="card narrow">
              <h1>Admin login</h1>
              <p>Pricing and saved requests are protected.</p>
              {notice}
              <form method="post" action="/admin/login">
                <label>Username<input name="username" required></label>
                <label>Password<input name="password" type="password" required></label>
                <button type="submit">Log in</button>
              </form>
            </section>
            """,
        )

    def _login(self, data: dict[str, str]) -> tuple[HTTPStatus, str, list[tuple[str, str]]]:
        expected_username = os.environ.get("BUYBACK_ADMIN_USERNAME", "")
        expected_password = os.environ.get("BUYBACK_ADMIN_PASSWORD", "")
        supplied_username = data.get("username", "")
        supplied_password = data.get("password", "")
        if not expected_username or not expected_password:
            return HTTPStatus.UNAUTHORIZED, self._login_page("Admin credentials are not configured."), []
        if hmac.compare_digest(supplied_username, expected_username) and hmac.compare_digest(supplied_password, expected_password):
            token = self._admin_token()
            return HTTPStatus.OK, self._admin_page(), [("Set-Cookie", f"buyback_admin={token}; HttpOnly; SameSite=Lax; Path=/")]
        return HTTPStatus.UNAUTHORIZED, self._login_page("Invalid admin username or password."), []

    def _admin_token(self) -> str | None:
        username = os.environ.get("BUYBACK_ADMIN_USERNAME", "")
        password = os.environ.get("BUYBACK_ADMIN_PASSWORD", "")
        if not username or not password:
            return None
        secret = f"{username}:{password}".encode("utf-8")
        return hmac.new(secret, b"zelvari-buyback-admin", hashlib.sha256).hexdigest()

    def _is_admin(self, environ: dict) -> bool:
        cookie_header = environ.get("HTTP_COOKIE", "")
        cookies = dict(
            item.strip().split("=", 1)
            for item in cookie_header.split(";")
            if "=" in item
        )
        token = cookies.get("buyback_admin", "")
        expected = self._admin_token()
        return bool(token and expected is not None and hmac.compare_digest(token, expected))

    def _admin_page(self, errors: list[str] | None = None) -> str:
        rows = self.store.list_pricing(active_only=False)
        requests = self.store.list_offer_requests()
        pricing_rows = "".join(
            f"""
            <tr>
              <td>{html.escape(row['brand'])}</td>
              <td>{html.escape(row['model'])}</td>
              <td>{html.escape(row['storage'])}</td>
              <td>
                <form method="post" action="/admin/pricing/update" class="inline-form">
                  <input type="hidden" name="id" value="{row['id']}">
                  <input name="base_price_cents" type="number" min="1" value="{row['base_price_cents']}" required>
                  <label class="checkbox"><input name="active" type="checkbox" value="1" {'checked' if row['active'] else ''}> Active</label>
                  <button type="submit">Save</button>
                </form>
              </td>
            </tr>
            """
            for row in rows
        ) or "<tr><td colspan='4'>No pricing records yet.</td></tr>"
        request_rows = "".join(
            f"""
            <tr>
              <td>{html.escape(row['created_at'])}</td>
              <td>{html.escape(row['name'])}<br>{html.escape(row['email'])}<br>{html.escape(row['phone'])}</td>
              <td>{html.escape(row['brand'])} {html.escape(row['model'])} {html.escape(row['storage'])}<br>{html.escape(row['condition'])}</td>
              <td>{_money(row['estimate_cents'])}</td>
              <td>{html.escape(row['notes'])}</td>
            </tr>
            """
            for row in requests
        ) or "<tr><td colspan='5'>No saved offer requests yet.</td></tr>"
        body = f"""
        <section class="card admin-card">
          <h1>Pricing Table</h1>
          {self._error_list(errors or [])}
          <table><thead><tr><th>Brand</th><th>Model</th><th>Storage</th><th>Base Price / Status</th></tr></thead><tbody>{pricing_rows}</tbody></table>
        </section>
        <section class="card admin-card">
          <h1>Saved Offer Requests</h1>
          <table><thead><tr><th>Submitted</th><th>Customer</th><th>Device</th><th>Estimate</th><th>Notes</th></tr></thead><tbody>{request_rows}</tbody></table>
        </section>
        """
        return self._page("Buyback Admin", body)

    def _update_pricing(self, data: dict[str, str]) -> tuple[HTTPStatus, str]:
        try:
            pricing_id = int(data.get("id", ""))
            base_price_cents = int(data.get("base_price_cents", ""))
            if base_price_cents <= 0:
                raise ValueError
        except ValueError:
            return HTTPStatus.BAD_REQUEST, self._admin_page(["Base price must be a positive number of cents."])
        self.store.update_pricing(pricing_id, base_price_cents, data.get("active") == "1")
        return HTTPStatus.OK, self._admin_page()

    def _error_list(self, errors: list[str]) -> str:
        if not errors:
            return ""
        items = "".join(f"<li>{html.escape(error)}</li>" for error in errors)
        return f"<ul class='error'>{items}</ul>"

    def _page(self, title: str, body: str, *, prompt_builder: bool = False) -> str:
        body_class = "prompt-builder-page" if prompt_builder else ""
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#08111f; --panel:#101c31; --line:#28415f; --accent:#38bdf8; --accent2:#7dd3fc; --text:#e5f4ff; --muted:#9fb5cc; --danger:#fca5a5; --success:#7dd3fc; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: radial-gradient(circle at top left, rgba(56,189,248,.22), transparent 32rem), linear-gradient(135deg, #07101d, #0d1728 45%, #111827); color:var(--text); min-height:100vh; padding:24px; }}
    main {{ max-width:1100px; margin:0 auto; }}
    .hero, .card {{ border:1px solid rgba(125,211,252,.22); background:rgba(16,28,49,.86); box-shadow:0 24px 80px rgba(0,0,0,.28); border-radius:28px; padding:28px; margin-bottom:22px; backdrop-filter: blur(14px); }}
    .hero h1 {{ font-size:clamp(2rem, 6vw, 4.5rem); line-height:1; margin:8px 0 16px; max-width:900px; }}
    .hero p, .card p {{ color:var(--muted); font-size:1.05rem; }}
    .eyebrow {{ color:var(--accent2); text-transform:uppercase; letter-spacing:.18em; font-weight:700; font-size:.78rem; }}
    .grid {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:16px; margin:18px 0; }}
    label {{ display:flex; flex-direction:column; gap:8px; color:#c7d7e7; font-weight:700; }}
    input, select, textarea {{ width:100%; border:1px solid var(--line); border-radius:14px; background:#07111f; color:var(--text); padding:12px 14px; font:inherit; }}
    textarea {{ min-height:92px; resize:vertical; }}
    button, .button-link {{ border:0; border-radius:999px; background:linear-gradient(135deg, var(--accent), #2563eb); color:white; padding:13px 20px; font-weight:800; cursor:pointer; text-decoration:none; display:inline-flex; justify-content:center; }}
    .estimate {{ border:1px solid rgba(56,189,248,.35); background:rgba(56,189,248,.10); color:#dff7ff; border-radius:18px; padding:18px; font-size:1.2rem; font-weight:800; }}
    .error {{ color:var(--danger); }}
    .success {{ border-color:rgba(125,211,252,.55); }}
    .narrow {{ max-width:520px; margin-inline:auto; }}
    table {{ width:100%; border-collapse:collapse; overflow:hidden; }}
    th, td {{ border-bottom:1px solid var(--line); padding:12px; text-align:left; vertical-align:top; }}
    th {{ color:var(--accent2); }}
    .inline-form {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
    .inline-form input[type='number'] {{ max-width:150px; }}
    .checkbox {{ flex-direction:row; align-items:center; font-weight:600; }}
    .checkbox input {{ width:auto; }}
    body.prompt-builder-page {{ padding:0; background:#030712; overflow-x:hidden; }}
    body.prompt-builder-page::before {{ content:""; position:fixed; inset:0; pointer-events:none; background:radial-gradient(circle at 18% 21%, rgba(68, 29, 237, .35), transparent 18rem), radial-gradient(circle at 84% 35%, rgba(14, 165, 233, .20), transparent 25rem), linear-gradient(120deg, rgba(124,58,237,.10), transparent 35%, rgba(6,182,212,.10)); }}
    .prompt-shell {{ position:relative; max-width:1480px; min-height:100vh; margin:0 auto; padding:26px clamp(16px, 4vw, 56px) 36px; }}
    .prompt-topbar {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding-bottom:24px; border-bottom:1px solid rgba(148,163,184,.12); }}
    .prompt-brand, .prompt-home {{ color:#fff; text-decoration:none; }}
    .prompt-brand {{ display:flex; align-items:center; gap:16px; font-size:1.7rem; font-weight:900; letter-spacing:.22em; }}
    .prompt-logo {{ display:grid; place-items:center; width:42px; height:42px; border-radius:12px; background:linear-gradient(135deg, #06b6d4, #7c3aed 55%, #e879f9); box-shadow:0 0 28px rgba(124,58,237,.8); letter-spacing:0; }}
    .prompt-home {{ border:1px solid rgba(99,102,241,.35); border-radius:999px; color:#c4b5fd; padding:10px 14px; background:rgba(15,23,42,.72); }}
    .prompt-hero {{ display:grid; grid-template-columns:220px minmax(0, 1fr); align-items:center; gap:44px; margin:44px auto 30px; max-width:1120px; }}
    .prompt-orb {{ width:180px; height:180px; display:grid; place-items:center; border-radius:999px; background:radial-gradient(circle, rgba(99,102,241,.55), rgba(2,6,23,.15) 52%, transparent 53%), conic-gradient(from 90deg, #22d3ee, #7c3aed, #d946ef, #22d3ee); box-shadow:0 0 54px rgba(79,70,229,.8); padding:3px; }}
    .prompt-orb span {{ display:grid; place-items:center; width:100%; height:100%; border-radius:inherit; background:#050816; color:#c4b5fd; font-size:5rem; font-weight:900; text-shadow:0 0 24px #8b5cf6; }}
    .prompt-hero h1 {{ margin:0; font-size:clamp(2.2rem, 5vw, 4.3rem); line-height:1.06; text-align:center; }}
    .prompt-hero h1 span {{ color:#b084ff; text-shadow:0 0 22px rgba(168,85,247,.48); }}
    .prompt-hero p {{ color:#dbeafe; text-align:center; font-size:1.25rem; margin:16px 0 24px; }}
    .prompt-badges {{ display:flex; justify-content:center; gap:14px; flex-wrap:wrap; }}
    .prompt-badges span {{ border:1px solid rgba(99,102,241,.32); background:linear-gradient(180deg, rgba(15,23,42,.92), rgba(15,23,42,.56)); border-radius:999px; padding:13px 24px; color:#eef2ff; box-shadow:inset 0 1px rgba(255,255,255,.08); }}
    .prompt-flow {{ position:relative; display:grid; grid-template-columns:minmax(0, 1fr) 74px minmax(0, 1fr); gap:28px; align-items:center; }}
    .prompt-card {{ border:1px solid rgba(139,92,246,.72); background:linear-gradient(180deg, rgba(15,23,42,.94), rgba(2,6,23,.90)); box-shadow:0 0 44px rgba(79,70,229,.25), inset 0 1px rgba(255,255,255,.05); border-radius:22px; padding:24px; min-height:520px; }}
    .prompt-output-card {{ border-color:rgba(168,85,247,.82); }}
    .prompt-card-title {{ display:flex; align-items:center; gap:12px; margin-bottom:14px; }}
    .prompt-card-title h2 {{ margin:0; text-transform:uppercase; font-size:1rem; letter-spacing:.04em; }}
    .prompt-card-title span {{ color:#d946ef; font-size:1.35rem; }}
    .prompt-card-title button {{ margin-left:auto; border:1px solid rgba(148,163,184,.22); background:rgba(15,23,42,.74); color:#dbeafe; border-radius:12px; padding:10px 14px; }}
    .prompt-textarea-label {{ position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); }}
    #prompt-input, .prompt-output-box {{ min-height:265px; border:1px solid rgba(71,85,105,.85); background:rgba(2,6,23,.72); border-radius:16px; color:#f8fafc; }}
    #prompt-input {{ padding:18px; font-size:1.08rem; resize:vertical; }}
    .prompt-counter {{ margin:-36px 16px 30px auto; width:max-content; color:#a5b4fc; position:relative; }}
    .prompt-select-grid {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:14px; margin:0 0 24px; }}
    .prompt-select-grid label {{ font-weight:600; color:#e2e8f0; }}
    .prompt-select-grid select {{ background:#0f172a; border-color:rgba(99,102,241,.42); }}
    .prompt-submit {{ width:100%; border-radius:12px; padding:18px 22px; font-size:1.12rem; background:linear-gradient(135deg, #6d28d9, #2563eb 65%, #0ea5e9); box-shadow:0 0 30px rgba(37,99,235,.48); }}
    .prompt-arrow {{ display:grid; place-items:center; width:72px; height:72px; margin:auto; border-radius:999px; color:#c4b5fd; font-size:3rem; background:radial-gradient(circle, rgba(91,33,182,.92), rgba(49,46,129,.75)); border:2px solid #8b5cf6; box-shadow:0 0 34px rgba(139,92,246,.86); }}
    .prompt-output-box {{ padding:20px; }}
    .prompt-output-text {{ margin:0; white-space:pre-wrap; word-break:break-word; font:inherit; line-height:1.58; color:#f8fafc; }}
    .prompt-placeholder {{ color:#94a3b8; margin:0; }}
    .prompt-error, .prompt-validation {{ border:1px solid rgba(248,113,113,.45); background:rgba(127,29,29,.30); color:#fecaca; border-radius:14px; padding:13px 15px; }}
    .prompt-error {{ display:flex; flex-direction:column; gap:4px; margin-bottom:14px; }}
    .prompt-copy-status, .prompt-privacy {{ color:#a5b4fc; text-align:center; }}
    .prompt-privacy {{ margin:28px 0 0; }}
    @media (max-width:720px) {{ body {{ padding:14px; }} .hero, .card {{ padding:20px; border-radius:22px; }} .grid {{ grid-template-columns:1fr; }} table {{ display:block; overflow-x:auto; white-space:nowrap; }} }}
    @media (max-width:900px) {{ body.prompt-builder-page {{ padding:0; }} .prompt-topbar {{ align-items:flex-start; }} .prompt-brand {{ font-size:1.25rem; }} .prompt-hero {{ grid-template-columns:1fr; text-align:center; gap:20px; }} .prompt-orb {{ margin:auto; width:132px; height:132px; }} .prompt-flow {{ grid-template-columns:1fr; }} .prompt-arrow {{ transform:rotate(90deg); }} .prompt-card {{ min-height:auto; }} .prompt-select-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body class="{body_class}"><main>{body}</main></body>
</html>"""


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _prompt_options(options: list[str]) -> str:
    return "".join(
        f"<option value=\"{html.escape(option)}\">{html.escape(option)}</option>"
        for option in options
    )


def _run_prompt_builder_command(payload: dict[str, str]) -> str | None:
    command_json = os.environ.get("PROMPT_BUILDER_COMMAND_JSON", "").strip()
    if not command_json:
        return None
    try:
        command = json.loads(command_json)
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            return None
        timeout = int(os.environ.get("PROMPT_BUILDER_TIMEOUT_SECONDS", "20"))
        completed = subprocess.run(
            command,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=max(1, min(timeout, 60)),
            check=False,
        )
    except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if completed.returncode != 0:
        return None
    improved_prompt = completed.stdout.strip()
    if not improved_prompt:
        return None
    return improved_prompt[:12000]


def create_app(db_path: str | None = None) -> BuybackApp:
    resolved_db_path = db_path or os.environ.get("BUYBACK_DB_PATH") or str(Path.cwd() / "buyback.sqlite3")
    return BuybackApp(resolved_db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Zelvari buyback MVP app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--db", default=os.environ.get("BUYBACK_DB_PATH", "buyback.sqlite3"))
    parser.add_argument("--seed-sample", action="store_true", help="Seed supported iPhone and Samsung Galaxy sample pricing.")
    args = parser.parse_args()

    app = create_app(args.db)
    if args.seed_sample:
        seed_sample_pricing(app.store)
    with make_server(args.host, args.port, app) as server:
        print(f"Serving Zelvari buyback app on http://{args.host}:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
