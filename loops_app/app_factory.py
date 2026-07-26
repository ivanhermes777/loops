"""Stdlib WSGI app factory for the premium Zelvari cellphone buyback demo site."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import os
from http import HTTPStatus
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from .buyback import (
    PAYOUT_METHODS,
    SUPPORTED_CONDITIONS,
    BuybackStore,
    calculate_offer,
    seed_sample_data,
    seed_sample_pricing,
    validate_seller_fields,
)

StartResponse = Callable[[str, list[tuple[str, str]]], None]

BRANDS = ["Apple iPhone", "Samsung Galaxy", "Google Pixel", "OnePlus", "Motorola", "Xiaomi", "Nothing", "Other Brands"]
TIMELINE = ["Quote Created", "Shipping Label Sent", "Device Shipped", "Device Received", "Inspection Started", "Offer Confirmed", "Payment Sent"]
QUESTIONNAIRE = [
    ("power_on", "Does the device power on?"),
    ("cracked_screen", "Is the screen cracked?"),
    ("cracked_back_glass", "Is the back glass cracked?"),
    ("deep_scratches", "Are there deep scratches?"),
    ("buttons", "Do all buttons work?"),
    ("cameras", "Do all cameras work?"),
    ("charging", "Does it charge normally?"),
    ("water_damage", "Has it had water damage?"),
    ("swollen_battery", "Is the battery swollen?"),
    ("account_lock", "Is activation/account lock enabled?"),
    ("financed", "Is the device financed?"),
    ("lost_stolen", "Is it lost or stolen?"),
    ("repair_history", "Has it had repair history?"),
    ("missing_parts", "Are any parts missing?"),
]


class BuybackApp:
    def __init__(self, db_path: str):
        self.store = BuybackStore(db_path)

    def __call__(self, environ: dict, start_response: StartResponse):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        try:
            if method == "GET" and path == "/":
                return self._send(start_response, HTTPStatus.OK, self._home_page())
            if method == "GET" and path == "/quote":
                return self._send(start_response, HTTPStatus.OK, self._quote_results_page())
            if method == "POST" and path in {"/request", "/seller"}:
                status, body = self._submit_seller(self._form_data(environ))
                return self._send(start_response, status, body)
            if method == "GET" and path == "/dashboard":
                return self._send(start_response, HTTPStatus.OK, self._dashboard_page())
            if method == "GET" and path in {"/signin", "/signup", "/forgot-password", "/verify-email", "/secure-sessions", "/signout"}:
                return self._send(start_response, HTTPStatus.OK, self._auth_page())
            if method == "POST" and path in {"/signin", "/signup", "/forgot-password"}:
                status, body = self._demo_auth_submit(self._form_data(environ))
                return self._send(start_response, status, body)
            if method == "GET" and path == "/support":
                return self._send(start_response, HTTPStatus.OK, self._support_page())
            if method == "POST" and path == "/support/lookup":
                status, body = self._lookup_quote(self._form_data(environ))
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
            if method == "POST" and path == "/admin/order/update":
                if not self._is_admin(environ):
                    return self._send(start_response, HTTPStatus.UNAUTHORIZED, self._login_page("Admin login required"))
                status, body = self._update_order(self._form_data(environ))
                return self._send(start_response, status, body)
            return self._send(start_response, HTTPStatus.NOT_FOUND, self._page("Not Found", "<section class='card'><h1>Page not found.</h1></section>"))
        except Exception:  # pragma: no cover - defensive WSGI boundary, no secret leakage
            return self._send(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, self._page("Error", "<section class='card'><h1>Something went wrong.</h1><p>Please try again safely.</p></section>"))

    def _send(self, start_response: StartResponse, status: HTTPStatus, body: str, *, headers: list[tuple[str, str]] | None = None):
        response_headers = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body.encode("utf-8"))))]
        if headers:
            response_headers.extend(headers)
        start_response(f"{status.value} {status.phrase}", response_headers)
        return [body.encode("utf-8")]

    def _form_data(self, environ: dict) -> dict[str, str]:
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
        raw_body = environ["wsgi.input"].read(content_length).decode("utf-8")
        return {key: values[0] for key, values in parse_qs(raw_body, keep_blank_values=True).items()}

    def _home_page(self, errors: list[str] | None = None) -> str:
        pricing = self.store.list_pricing(active_only=True)
        catalog_json = json.dumps(pricing)
        condition_options = "".join(f"<option>{html.escape(condition)}</option>" for condition in SUPPORTED_CONDITIONS)
        brand_cards = "".join(f"<button class='brand-card' data-brand='{html.escape(brand)}'><span>{brand.split()[0][0] if brand else 'Z'}</span>{html.escape(brand)}</button>" for brand in BRANDS)
        catalog_cards = self._catalog_cards(pricing)
        pricing_empty = "<div class='empty-state'>Pricing is not available yet. Zelvari cannot estimate this configuration right now.</div>" if not pricing else ""
        body = f"""
        <header class="site-header">
          <a class="brand" href="/"><span class="z-logo">Z</span><strong>ZELVARI</strong></a>
          <button class="mobile-menu-toggle" aria-controls="main-nav" aria-expanded="false">☰</button>
          <nav id="main-nav"><a href="#how">How It Works</a><a href="#sell">Sell Your Phone</a><a href="#top">Top Payouts</a><a href="#reviews">Reviews</a><a href="#about">About Us</a><a href="/support">Support</a></nav>
          <div class="actions"><a class="btn primary" href="#quote">Get My Quote</a><a class="btn ghost" href="/signin">Sign In</a></div>
        </header>
        <section class="hero" id="sell">
          <div class="hero-copy">
            <p class="badge">✦ AI-Powered Quotes. Human Trust.</p>
            <h1 aria-label="Sell Your Phone the Smart Way">Sell Your Phone <span>the Smart Way</span></h1>
            <p>Instant quotes, free shipping, and fast payouts. The easiest way to sell your phone online with Zelvari’s human-reviewed demo buyback experience.</p>
            <div class="hero-actions"><a class="btn primary big" href="#quote">Get My Quote →</a><a class="btn ghost big" href="#how">See How It Works</a></div>
            <div class="benefits"><span>Free Shipping</span><span>Secure and Safe</span><span>Fast Payouts</span></div>
            <p class="social-proof">Trusted by 50,000+ happy sellers in this demo experience.</p>
          </div>
          <div class="phone-stage" aria-label="Premium generic smartphone visuals on a glowing futuristic platform"><div class="phone p1"></div><div class="phone p2"></div><div class="phone p3"></div><div class="platform"></div></div>
          <form class="quote-card glass" method="post" action="/seller" id="quote">
            <h2>Get Your Instant Quote <small>AI</small></h2>
            <p>Select your device details to see your offer.</p>{self._error_list(errors or [])}{pricing_empty}
            <label>Phone Brand<select name="brand" id="brand" required></select></label>
            <label>Phone Model<select name="model" id="model" required></select></label>
            <label>Storage<select name="storage" id="storage" required></select></label>
            <label>Carrier<select name="carrier" id="carrier"><option>Unlocked</option><option>Verizon</option><option>AT&amp;T</option><option>T-Mobile</option><option>Other</option></select></label>
            <label>Condition<select name="condition" id="condition" required>{condition_options}</select></label>
            <input type="hidden" name="estimated_payout_cents" id="estimated_payout_cents" value="0">
            <div class="estimate"><span>Estimated Payout</span><strong id="estimate">Pricing unavailable</strong><small>Final value is confirmed after inspection.</small></div>
            <p class="free-note">No fees. No obligation. 100% free.</p>
          </form>
        </section>
        <section class="steps glass" id="how"><h2>How It Works</h2>{''.join(f'<article><div class="icon">{i}</div><h3>{title}</h3><p>{copy}</p></article>' for i, (title, copy) in enumerate([('Choose Your Device','Tell us your model and condition.'),('Get an Instant Offer','Receive a demo AI-powered quote in seconds.'),('Ship It for Free','A prepaid label would be sent manually.'),('Get Paid Fast','Inspection and payout are handled manually.')], 1))}</section>
        <section class="brand-grid"><h2>Popular Brands</h2>{brand_cards}</section>
        <section class="catalog glass"><h2>Phone Catalog</h2><p>Prices are estimates and may change after inspection.</p><div class="catalog-tools"><input aria-label="Search phones" placeholder="Search phones"><select aria-label="Brand filter"><option>Brand filter</option></select><select aria-label="Model filter"><option>Model filter</option></select><select aria-label="Storage filter"><option>Storage filter</option></select><select aria-label="Sort catalog"><option>Sort by highest payout</option><option>Sort by newest</option></select></div><div class="cards">{catalog_cards}</div><div class="empty-state">No catalog matches. Reset filters or choose Other Brands for manual review.</div><button class="btn ghost">Load More</button></section>
        <section class="questionnaire glass"><h2>Device Condition Questionnaire</h2><div class="progress"><span style="width:50%"></span></div>{''.join(f'<article class="question"><h3>{html.escape(text)}</h3><button>Yes</button><button>No</button></article>' for _key, text in QUESTIONNAIRE)}<div class="blocked"><h3>Zelvari cannot accept this device</h3><p>Only legally eligible devices can be sold. You can edit answers before continuing.</p></div><div class="adjustments"><h3>Value Adjustment Summary</h3><p>Condition, carrier, screen, back glass, water damage, non-working value, and promotional bonus are explained here.</p></div></section>
        <section class="results glass"><h2>Eligible Quote Results</h2><p>Phone visual, brand, model, storage, carrier, condition, estimated payout, offer expiration date, and adjustment summary appear before acceptance.</p><p>Your final payout may change after the device is inspected.</p><a class="btn primary" href="#seller">Accept Offer</a><a class="btn ghost" href="#quote">Edit Device Details</a></section>
        {self._seller_form()}
        <section class="why" id="about"><h2>Why Choose Zelvari</h2>{''.join(f'<article class="glass"><h3>{title}</h3><p>{copy}</p></article>' for title, copy in [('Fast Payment','Get paid quickly after inspection.'),('Free Shipping','Prepaid demo shipping path.'),('Trusted Quotes','AI pricing plus human review.'),('Secure Data Protection','Prepare and wipe your data safely.'),('Better for the Planet','Responsible resale keeps tech useful.')])}</section>
        <section class="top" id="top"><h2>Top Trade-In Values</h2><div class="cards"><article class="phone-card"><b>Top Pick</b><h3>Premium Ultra 1TB</h3><p>Mint Condition</p><strong>$890</strong><a href="#quote">Get Quote</a></article><article class="phone-card"><h3>Pro Max 512GB</h3><p>Excellent Condition</p><strong>$720</strong><a href="#quote">Get Quote</a></article><article class="phone-card"><h3>Galaxy S24 Ultra</h3><p>512GB · Excellent</p><strong>$650</strong><a href="#quote">Get Quote</a></article></div></section>
        <section class="reviews glass" id="reviews"><h2>What Our Sellers Say</h2><p>Average rating 4.9 ★★★★★ from original seeded mock reviews and internal trust stats only.</p><article><p>“Super fast and easy. I got my quote in seconds, shipped it for free, and was paid the next day. Zelvari is the real deal.”</p><strong>Sarah T.</strong><span>Verified Seller · Device sold: iPhone 15 Pro · Payout received: $720 · Review date: July 2026</span></article><article><p>“The estimate was clear and the inspection notes were easy to understand.”</p><strong>Marcus R.</strong><span>Verified Seller · Device sold: Galaxy S24 Ultra · Payout received: $650 · Review date: July 2026</span></article></section>
        {self._footer()}
        <script>{self._quote_script(catalog_json)}</script>
        """
        return self._page("Zelvari Phone Buyback", body)

    def _catalog_cards(self, pricing: list[dict]) -> str:
        if not pricing:
            return ""
        cards = []
        for row in pricing[:8]:
            cards.append(f"<article class='phone-card'><div class='device-visual'></div><p>{html.escape(row['brand'])}</p><h3>{html.escape(row['model'])}</h3><p>{html.escape(row['storage'])}</p><strong>{_money(row['maximum_payout_cents'])}</strong><a href='#quote'>Get Quote</a></article>")
        return "".join(cards)

    def _seller_form(self) -> str:
        payout_options = "".join(f"<option>{method}</option>" for method in PAYOUT_METHODS)
        return f"""
        <section class="seller glass" id="seller"><h2>Seller Information</h2><p>Guest checkout is allowed. Account creation is offered as a demo-only next step.</p><form method="post" action="/seller" class="form-grid">
        <input type="hidden" name="brand" value="Apple iPhone"><input type="hidden" name="model" value="iPhone 15 Pro Max"><input type="hidden" name="storage" value="256GB"><input type="hidden" name="carrier" value="Unlocked"><input type="hidden" name="condition" value="Good"><input type="hidden" name="estimated_payout_cents" value="67600">
        <label>Full Name<input name="full_name" required></label><label>Email<input type="email" name="email" required></label><label>Phone Number<input name="phone" required></label><label>Street Address<input name="street_address" required></label><label>Apartment/Unit<input name="apartment"></label><label>City<input name="city" required></label><label>State<input name="state" required></label><label>ZIP Code<input name="zip_code" required></label><label>Preferred Payout Method<select name="payout_method" required>{payout_options}</select></label><label class="check"><input type="checkbox" name="terms_agree" value="1"> I agree to the terms.</label><label class="check"><input type="checkbox" name="privacy_agree" value="1"> I agree to the privacy policy.</label><button class="btn primary" type="submit">Accept Offer</button></form></section>
        """

    def _quote_results_page(self) -> str:
        return self._page("Quote Results", "<section class='results glass'><h1>Eligible Quote Results</h1><p>Your final payout may change after the device is inspected.</p><a class='btn primary' href='/'>Edit Device Details</a></section>")

    def _submit_seller(self, data: dict[str, str]) -> tuple[HTTPStatus, str]:
        errors = validate_seller_fields(data)
        try:
            offer = calculate_offer(self.store, brand=data.get("brand", ""), model=data.get("model", ""), storage=data.get("storage", ""), carrier=data.get("carrier", "Unlocked"), condition=data.get("condition", "Good")) if not errors else None
        except ValueError as error:
            errors.append(str(error))
            offer = None
        if errors:
            return HTTPStatus.BAD_REQUEST, self._home_page(errors)
        assert offer is not None
        order = self.store.create_order({
            "brand": data["brand"].strip(), "model": data["model"].strip(), "storage": data["storage"].strip(), "carrier": data.get("carrier", "Unlocked").strip(), "condition": data["condition"].strip(),
            "estimated_payout_cents": int(data.get("estimated_payout_cents") or offer["offer_cents"]), "adjustment_summary": offer["adjustment_summary"],
            "full_name": data["full_name"].strip(), "email": data["email"].strip(), "phone": data["phone"].strip(), "street_address": data["street_address"].strip(), "apartment": data.get("apartment", "").strip(), "city": data["city"].strip(), "state": data["state"].strip(), "zip_code": data["zip_code"].strip(), "payout_method": data["payout_method"].strip(),
        })
        return HTTPStatus.OK, self._page("Confirmation", f"<section class='card success'><p class='badge'>Request received</p><h1>Quote/order number {html.escape(order['quote_number'])}</h1><p>Zelvari will follow up manually with shipping and inspection next steps.</p><p>Customer accounts are demo-only and not required for guest checkout.</p><a class='btn primary' href='/dashboard'>View Demo Dashboard</a><a class='btn ghost' href='/signup'>Create Demo Account</a></section>{self._footer()}")

    def _dashboard_page(self) -> str:
        tiles = ["Active Quotes", "Shipping Status", "Devices Received", "Inspection Results", "Payments", "Completed Sales", "Saved Devices", "Profile", "Support"]
        tile_html = "".join(f"<article class='mini'><h2>{tile}</h2><p>Demo-only customer dashboard screen.</p></article>" for tile in tiles)
        timeline_html = "".join(f"<li>{item}</li>" for item in TIMELINE)
        return self._page("Customer Dashboard", f"<section class='glass'><h1>Customer Demo Dashboard</h1><div class='cards'>{tile_html}</div><h2>Order Timeline</h2><ol class='timeline'>{timeline_html}</ol></section>{self._footer()}")

    def _auth_page(self, message: str = "") -> str:
        notice = f"<p class='success'>{html.escape(message)}</p>" if message else ""
        return self._page("Demo Auth", f"<section class='glass narrow'><h1>Demo Customer Account Flows</h1>{notice}<p>These Sign Up, Sign In, Forgot Password, Email Verification, Secure Sessions, and Sign Out screens validate fields, but customer accounts are not active yet and customer login credentials are not stored.</p><form method='post' action='/signup'><label>Email<input name='email' type='email'></label><label>Password<input name='password' type='password'></label><button class='btn primary'>Sign Up</button></form><a href='/signin'>Sign In</a> · <a href='/forgot-password'>Forgot Password</a> · <a href='/verify-email'>Email Verification</a> · <a href='/secure-sessions'>Secure Sessions</a> · <a href='/signout'>Sign Out</a></section>")

    def _demo_auth_submit(self, data: dict[str, str]) -> tuple[HTTPStatus, str]:
        errors = []
        if "@" not in data.get("email", ""):
            errors.append("Enter a valid email")
        if len(data.get("password", "")) < 8:
            errors.append("Password must be at least 8 characters")
        if errors:
            return HTTPStatus.BAD_REQUEST, self._page("Demo Auth", f"<section class='glass narrow'>{self._error_list(errors)}<p>customer accounts are not active yet</p></section>")
        return HTTPStatus.OK, self._auth_page("Demo account flow complete. Customer login credentials were not stored.")

    def _support_page(self, message: str = "") -> str:
        notice = f"<p class='error'>{html.escape(message)}</p>" if message else ""
        topics = ['value calculation','free shipping','inspection timing','value changes','payment methods','broken phones','data removal','activation lock','sale cancellation']
        topic_html = "".join(f"<article><h2>{topic}</h2><p>Helpful demo guidance for {topic.lower()}.</p></article>" for topic in topics)
        return self._page("Support Center", f"<section class='glass'><h1>Support Center</h1><p>searchable help articles, FAQs, contact form, quote-status lookup, shipping help, payment help, and device preparation instructions.</p>{notice}<input aria-label='Search help' placeholder='Search help articles'><form method='post' action='/support/lookup'><label>quote-status lookup<input name='quote_number'></label><button class='btn primary'>Look Up Quote</button></form><div class='cards'>{topic_html}</div><form><label>Contact form<textarea></textarea></label></form><h2>Shipping Help</h2><p>shipping help: package your phone safely.</p><h2>Payment Help</h2><p>payment help: PayPal, Venmo, bank transfer, digital prepaid card, mailed check.</p><h2>Device Preparation</h2><p>device preparation: back up data, remove locks, erase device.</p></section>{self._footer()}")

    def _lookup_quote(self, data: dict[str, str]) -> tuple[HTTPStatus, str]:
        quote = self.store.get_order(data.get("quote_number", ""))
        if quote is None:
            return HTTPStatus.NOT_FOUND, self._support_page("No quote was found for that number. Please check the quote number and try again.")
        return HTTPStatus.OK, self._support_page(f"Quote {quote['quote_number']} status: {quote['status']}")

    def _login_page(self, message: str = "") -> str:
        notice = f"<p class='error'>{html.escape(message)}</p>" if message else ""
        return self._page("Admin Login", f"<section class='glass narrow'><h1>Admin login</h1><p>Protected admin tools use environment-variable credentials.</p>{notice}<form method='post' action='/admin/login'><label>Username<input name='username' required></label><label>Password<input name='password' type='password' required></label><button class='btn primary'>Log in</button></form></section>")

    def _login(self, data: dict[str, str]) -> tuple[HTTPStatus, str, list[tuple[str, str]]]:
        expected_username = os.environ.get("BUYBACK_ADMIN_USERNAME", "")
        expected_password = os.environ.get("BUYBACK_ADMIN_PASSWORD", "")
        if not expected_username or not expected_password:
            return HTTPStatus.UNAUTHORIZED, self._login_page("Admin credentials are not configured."), []
        if hmac.compare_digest(data.get("username", ""), expected_username) and hmac.compare_digest(data.get("password", ""), expected_password):
            token = self._admin_token()
            return HTTPStatus.OK, self._admin_page(), [("Set-Cookie", f"buyback_admin={token}; HttpOnly; SameSite=Lax; Path=/")]
        return HTTPStatus.UNAUTHORIZED, self._login_page("Invalid admin username or password."), []

    def _admin_token(self) -> str | None:
        username = os.environ.get("BUYBACK_ADMIN_USERNAME", "")
        password = os.environ.get("BUYBACK_ADMIN_PASSWORD", "")
        if not username or not password:
            return None
        return hmac.new(f"{username}:{password}".encode(), b"zelvari-buyback-admin", hashlib.sha256).hexdigest()

    def _is_admin(self, environ: dict) -> bool:
        cookies = dict(item.strip().split("=", 1) for item in environ.get("HTTP_COOKIE", "").split(";") if "=" in item)
        expected = self._admin_token()
        token = cookies.get("buyback_admin", "")
        return bool(token and expected and hmac.compare_digest(token, expected))

    def _admin_page(self, errors: list[str] | None = None) -> str:
        stats = self.store.admin_stats()
        stat_html = "".join(f"<article><strong>{label}</strong><span>{value}</span></article>" for label, value in [
            ("Total Quotes", stats["total_quotes"]), ("Accepted Quotes", stats["accepted_quotes"]), ("Devices Received", stats["devices_received"]), ("Devices Inspected", stats["devices_inspected"]), ("Payments Sent", stats["payments_sent"]), ("Average Payout", _money(stats["average_payout_cents"])), ("Conversion Rate", f"{stats['conversion_rate']}%"), ("Total Buyback Value", _money(stats["total_buyback_value_cents"])),
        ])
        pricing_rows = "".join(f"<tr><td>{html.escape(row['brand'])}</td><td>{html.escape(row['model'])}</td><td>{html.escape(row['storage'])}</td><td>{_money(row['maximum_payout_cents'])}</td><td><form method='post' action='/admin/pricing/update'><input type='hidden' name='id' value='{row['id']}'><input name='base_value_cents' type='number' value='{row['base_value_cents']}'><input name='maximum_payout_cents' type='number' value='{row['maximum_payout_cents']}'><label><input type='checkbox' name='active' value='1' {'checked' if row['active'] else ''}> Active</label><button>Save</button></form></td></tr>" for row in self.store.list_pricing()) or "<tr><td colspan='5'>No pricing records yet.</td></tr>"
        order_rows = "".join(f"<tr><td>{html.escape(row['quote_number'])}</td><td>{html.escape(row['full_name'])}<br>{html.escape(row['email'])}</td><td>{html.escape(row['status'])}</td><td>{_money(row['estimated_payout_cents'])}</td><td><form method='post' action='/admin/order/update'><input name='quote_number' value='{html.escape(row['quote_number'])}'><select name='status'>{''.join(f'<option>{item}</option>' for item in TIMELINE)}</select><input name='inspection_result' placeholder='inspection result'><input name='internal_notes' placeholder='internal notes'><select name='decision'><option>Pending</option><option>Approved</option><option>Rejected</option></select><input name='final_payout_cents' type='number'><label><input type='checkbox' name='payment_sent' value='1'> mark payments as sent</label><button>Update</button></form></td></tr>" for row in self.store.list_orders()) or "<tr><td colspan='5'>No saved offer requests yet. Empty quote table.</td></tr>"
        return self._page("Buyback Admin", f"<section class='glass admin'><h1>Admin Dashboard</h1>{self._error_list(errors or [])}<div class='stats'>{stat_html}</div><h2>Quotes</h2><input placeholder='search customers'><input placeholder='search by quote number'><table>{order_rows}</table><h2>Editable Pricing Rows</h2><table>{pricing_rows}</table><h2>Management Areas</h2><div class='cards'><article><h3>Phone brands/models</h3><p>Seeded/admin-visible content.</p></article><article><h3>Reviews</h3><p>Seeded mock reviews.</p></article><article><h3>FAQs</h3><p>Seeded support FAQs.</p></article></div></section>")

    def _update_pricing(self, data: dict[str, str]) -> tuple[HTTPStatus, str]:
        try:
            self.store.update_pricing(int(data["id"]), base_value_cents=int(data["base_value_cents"]), maximum_payout_cents=int(data.get("maximum_payout_cents") or data["base_value_cents"]), active=data.get("active") == "1")
        except (KeyError, ValueError):
            return HTTPStatus.BAD_REQUEST, self._admin_page(["Pricing update failed. Enter valid positive cents."])
        return HTTPStatus.OK, self._admin_page()

    def _update_order(self, data: dict[str, str]) -> tuple[HTTPStatus, str]:
        try:
            final = int(data["final_payout_cents"]) if data.get("final_payout_cents") else None
            self.store.update_order(data["quote_number"].strip().upper(), status=data.get("status", "Quote Created"), inspection_result=data.get("inspection_result", ""), internal_notes=data.get("internal_notes", ""), decision=data.get("decision", "Pending"), final_payout_cents=final, payment_sent=data.get("payment_sent") == "1")
        except (KeyError, ValueError):
            return HTTPStatus.BAD_REQUEST, self._admin_page(["Order update failed. Check quote number and payout."])
        return HTTPStatus.OK, self._admin_page()

    def _quote_script(self, catalog_json: str) -> str:
        return f"""
        const catalog = {catalog_json};
        const conditions = {json.dumps(list(SUPPORTED_CONDITIONS.keys()))};
        const fields = ['brand','model','storage','condition'].reduce((acc,id)=>{{acc[id]=document.getElementById(id);return acc;}},{{}});
        function unique(values){{return [...new Set(values)].sort();}}
        function options(select, values){{ if(!select) return; select.innerHTML=values.map(v=>`<option value="${{v}}">${{v}}</option>`).join(''); }}
        function refreshModels(){{ options(fields.model, unique(catalog.filter(r=>r.brand===fields.brand.value).map(r=>r.model))); refreshStorage(); }}
        function refreshStorage(){{ options(fields.storage, unique(catalog.filter(r=>r.brand===fields.brand.value&&r.model===fields.model.value).map(r=>r.storage))); refreshEstimate(); }}
        function refreshEstimate(){{ const row=catalog.find(r=>r.brand===fields.brand.value&&r.model===fields.model.value&&r.storage===fields.storage.value); const estimate=document.getElementById('estimate'); const hidden=document.getElementById('estimated_payout_cents'); if(!row){{estimate.textContent='Pricing unavailable'; return;}} let cents=row.maximum_payout_cents; if(fields.condition.value==='Good') cents=Math.max(0,row.base_value_cents-row.condition_deduction_cents); if(fields.condition.value==='Fair') cents=Math.max(0,row.base_value_cents-16000); if(fields.condition.value==='Damaged') cents=Math.max(0,row.base_value_cents-30000); if(fields.condition.value==='Not Working') cents=row.non_working_value_cents; hidden.value=cents; estimate.textContent='$'+(cents/100).toLocaleString(undefined,{{maximumFractionDigits:0}}); }}
        options(fields.brand, unique(catalog.map(r=>r.brand))); options(fields.condition, conditions); ['brand','model','storage','condition'].forEach(id=>fields[id]&&fields[id].addEventListener('change', id==='brand'?refreshModels:id==='model'?refreshStorage:refreshEstimate)); refreshModels();
        document.querySelector('.mobile-menu-toggle')?.addEventListener('click',()=>document.body.classList.toggle('nav-open'));
        """

    def _footer(self) -> str:
        return """<footer><div class='brand'><span class='z-logo'>Z</span><strong>ZELVARI</strong></div><p>The smarter way to sell your phone.</p><div class='footer-grid'><div><h3>Sell</h3><a>Sell Your Phone</a><a>How It Works</a><a>Top Payouts</a></div><div><h3>Company</h3><a>About Us</a><a>Careers</a><a>Press</a></div><div><h3>Support</h3><a>Help Center</a><a>Shipping</a><a>Contact Us</a></div><div><h3>Legal</h3><a>Terms of Service</a><a>Privacy Policy</a><a>Data Deletion</a></div><div><h3>Stay in the loop</h3><input placeholder='Enter your email'><p class='social'>𝕏 ◎ ▶ ♪ f</p></div></div><aside>Good for your wallet. Better for the planet.</aside></footer>"""

    def _error_list(self, errors: list[str]) -> str:
        if not errors:
            return ""
        return "<ul class='error'>" + "".join(f"<li>{html.escape(error)}</li>" for error in errors) + "</ul>"

    def _page(self, title: str, body: str) -> str:
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>"""


CSS = """
:root{color-scheme:dark;--bg:#030712;--panel:rgba(13,18,38,.76);--line:rgba(139,92,246,.34);--purple:#a855f7;--blue:#0ea5e9;--teal:#2dd4bf;--text:#f8fbff;--muted:#aab6ce;--danger:#fda4af}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:radial-gradient(circle at 18% 10%,rgba(168,85,247,.28),transparent 30rem),radial-gradient(circle at 78% 6%,rgba(14,165,233,.28),transparent 28rem),linear-gradient(180deg,#020617,#050816 55%,#030712);color:var(--text)}main{max-width:1580px;margin:auto;padding:0 28px}.site-header{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:24px;padding:18px 4px;border-bottom:1px solid rgba(255,255,255,.08);backdrop-filter:blur(18px)}.brand{display:flex;align-items:center;gap:14px;color:white;text-decoration:none;letter-spacing:.22em}.z-logo{display:grid;place-items:center;width:50px;height:50px;border-radius:14px;font-size:34px;font-weight:900;color:#d8b4fe;text-shadow:0 0 18px var(--purple),0 0 24px var(--blue);border:1px solid var(--line);box-shadow:0 0 28px rgba(168,85,247,.5)}nav{display:flex;gap:28px}nav a,footer a{color:#f3f7ff;text-decoration:none;font-weight:700}.actions,.hero-actions,.benefits,.cards,.catalog-tools{display:flex;gap:14px;flex-wrap:wrap}.btn,button{border:0;border-radius:14px;padding:13px 22px;font-weight:900;color:white;text-decoration:none;cursor:pointer}.primary{background:linear-gradient(135deg,var(--purple),var(--blue));box-shadow:0 0 26px rgba(14,165,233,.38)}.ghost{background:rgba(255,255,255,.04);border:1px solid rgba(139,92,246,.35)}.big{padding:17px 28px}.mobile-menu-toggle{display:none}.hero{display:grid;grid-template-columns:1.15fr 1fr .78fr;gap:38px;align-items:center;padding:40px 0 18px}.badge{display:inline-flex;border:1px solid rgba(168,85,247,.42);border-radius:999px;padding:10px 16px;background:rgba(168,85,247,.11);color:#e9d5ff;text-transform:uppercase;letter-spacing:.08em;font-weight:900}.hero h1{font-size:clamp(3rem,6.5vw,6.4rem);line-height:.95;margin:20px 0}.hero h1 span{display:block;background:linear-gradient(90deg,var(--purple),var(--blue),var(--teal));-webkit-background-clip:text;color:transparent}.hero p{color:var(--muted);font-size:1.2rem}.benefits span{color:#dbeafe}.glass,.quote-card,.steps,.card{border:1px solid var(--line);background:linear-gradient(180deg,rgba(15,23,42,.78),rgba(8,13,30,.68));box-shadow:0 28px 90px rgba(0,0,0,.38),inset 0 0 28px rgba(14,165,233,.07);backdrop-filter:blur(18px);border-radius:28px;padding:26px;margin:22px 0}.quote-card{box-shadow:0 0 40px rgba(14,165,233,.24),0 0 44px rgba(168,85,247,.16)}label{display:flex;flex-direction:column;gap:8px;margin:12px 0;color:#dbeafe;font-weight:800}input,select,textarea{width:100%;border:1px solid rgba(148,163,184,.22);border-radius:13px;background:rgba(15,23,42,.9);color:white;padding:13px 14px;font:inherit}input:focus,select:focus,textarea:focus,button:focus,a:focus{outline:3px solid rgba(45,212,191,.55);outline-offset:3px}.estimate{margin:18px 0;padding:16px;border-radius:18px;background:rgba(14,165,233,.08);border:1px solid rgba(14,165,233,.26);display:flex;flex-direction:column}.estimate strong{font-size:2.1rem;color:var(--teal)}.phone-stage{position:relative;min-height:360px}.phone{position:absolute;bottom:50px;width:145px;height:285px;border-radius:32px;background:linear-gradient(160deg,#e0f2fe,#111827 55%,#a855f7);border:4px solid #090e1d;box-shadow:0 0 34px rgba(168,85,247,.7)}.p1{left:18%;transform:rotate(-8deg)}.p2{left:40%;height:330px;width:165px}.p3{left:66%;transform:rotate(8deg);background:linear-gradient(160deg,#111827,#7c3aed,#22d3ee)}.platform{position:absolute;bottom:30px;left:8%;right:8%;height:38px;border-radius:50%;border:2px solid var(--purple);box-shadow:0 0 40px var(--purple),0 0 80px var(--blue)}.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}.steps h2,.brand-grid h2,.catalog h2,.why h2,.top h2,.reviews h2{grid-column:1/-1}.icon,.brand-card span{display:grid;place-items:center;width:70px;height:70px;border-radius:18px;background:rgba(168,85,247,.14);border:1px solid var(--line);box-shadow:inset 0 0 24px rgba(14,165,233,.13);font-weight:900;color:#c4b5fd}.brand-grid,.why{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.brand-card,.phone-card,.mini,.question{background:rgba(15,23,42,.72);border:1px solid rgba(148,163,184,.18);border-radius:20px;padding:18px;color:white}.phone-card{min-width:210px}.phone-card a{display:inline-block;margin-left:.25rem}.device-visual{height:130px;border-radius:22px;background:linear-gradient(145deg,#172554,#a855f7,#22d3ee);box-shadow:0 0 24px rgba(14,165,233,.25)}.progress{height:12px;border-radius:99px;background:#111827;overflow:hidden}.progress span{display:block;height:100%;background:linear-gradient(90deg,var(--purple),var(--blue))}.form-grid,.footer-grid,.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.seller .check{flex-direction:row}.error{color:var(--danger)}.success{color:#86efac}table{width:100%;border-collapse:collapse;display:block;overflow:auto}td,th{border-bottom:1px solid rgba(148,163,184,.18);padding:12px;text-align:left;vertical-align:top}footer{margin:30px 0 0;padding:30px 0;border-top:1px solid rgba(255,255,255,.1)}footer a{display:block;margin:.4rem 0;color:#cbd5e1}footer aside{float:right;border:1px solid var(--line);border-radius:18px;padding:18px;color:#d8b4fe}@media(max-width:1100px){.hero{grid-template-columns:1fr}.phone-stage{min-height:320px}.steps,.brand-grid,.why,.form-grid,.footer-grid,.stats{grid-template-columns:repeat(2,1fr)}}@media(max-width:760px){main{padding:0 14px}.mobile-menu-toggle{display:inline-flex}nav,.actions{display:none}.nav-open nav{display:flex;position:absolute;top:72px;left:0;right:0;flex-direction:column;padding:20px;background:#050816;border:1px solid var(--line)}.hero h1{font-size:3.3rem}.steps,.brand-grid,.why,.form-grid,.footer-grid,.stats{grid-template-columns:1fr}.glass,.quote-card{padding:20px;border-radius:22px}.phone{width:105px;height:220px}.p2{width:120px;height:250px}}
"""


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def create_app(db_path: str | None = None) -> BuybackApp:
    resolved_db_path = db_path or os.environ.get("BUYBACK_DB_PATH") or str(Path.cwd() / "buyback.sqlite3")
    return BuybackApp(resolved_db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Zelvari premium buyback app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--db", default=os.environ.get("BUYBACK_DB_PATH", "buyback.sqlite3"))
    parser.add_argument("--seed-sample", action="store_true", help="Seed realistic demo pricing, reviews, brands, and FAQs.")
    args = parser.parse_args()
    app = create_app(args.db)
    if args.seed_sample:
        seed_sample_data(app.store)
    with make_server(args.host, args.port, app) as server:
        print(f"Serving Zelvari buyback app on http://{args.host}:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
