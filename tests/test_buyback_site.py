import io
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock
from urllib.parse import urlencode

from loops_app.app_factory import create_app
from loops_app.buyback import (
    BuybackStore,
    calculate_condition_offer,
    calculate_offer,
    seed_sample_data,
    seed_sample_pricing,
)


class WsgiTestClient:
    def __init__(self, app):
        self.app = app
        self.cookies = {}

    def get(self, path, query=""):
        return self._request("GET", path, query=query)

    def post(self, path, data):
        body = urlencode(data).encode("utf-8")
        return self._request(
            "POST",
            path,
            body=body,
            headers={
                "CONTENT_TYPE": "application/x-www-form-urlencoded",
                "CONTENT_LENGTH": str(len(body)),
            },
        )

    def _request(self, method, path, query="", body=b"", headers=None):
        headers = headers or {}
        status_headers = {}
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "80",
            "wsgi.version": (1, 0),
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
            "wsgi.url_scheme": "http",
        }
        environ.update(headers)
        if self.cookies:
            environ["HTTP_COOKIE"] = "; ".join(
                f"{name}={value}" for name, value in self.cookies.items()
            )

        def start_response(status, response_headers):
            status_headers["status"] = status
            status_headers["headers"] = dict(response_headers)
            for key, value in response_headers:
                if key.lower() == "set-cookie":
                    cookie = value.split(";", 1)[0]
                    name, cookie_value = cookie.split("=", 1)
                    self.cookies[name] = cookie_value

        payload = b"".join(self.app(environ, start_response)).decode("utf-8")
        return status_headers["status"], status_headers["headers"], payload


class BuybackSiteTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "buyback.sqlite3")
        self.store = BuybackStore(self.db_path)
        seed_sample_data(self.store)
        self.addCleanup(self.tempdir.cleanup)
        os.environ.pop("BUYBACK_ADMIN_USERNAME", None)
        os.environ.pop("BUYBACK_ADMIN_PASSWORD", None)

    def test_quote_calculation_uses_editable_pricing_carrier_condition_damage_bonus_fields(self):
        offer = calculate_offer(
            self.store,
            brand="Apple iPhone",
            model="iPhone 15 Pro Max",
            storage="256GB",
            carrier="Unlocked",
            condition="Good",
            cracked_screen="yes",
            cracked_back_glass="yes",
            water_damage="no",
        )

        self.assertEqual(offer["offer_cents"], 53000)
        self.assertEqual(offer["maximum_payout_cents"], 89000)
        self.assertIn("Good condition", offer["adjustments"])
        self.assertTrue(any("Unlocked carrier bonus" in item for item in offer["adjustments"]))
        self.assertTrue(any("Cracked screen" in item for item in offer["adjustments"]))
        self.assertTrue(any("Cracked back glass" in item for item in offer["adjustments"]))

    def test_condition_questionnaire_blocks_legally_ineligible_devices(self):
        result = calculate_condition_offer(
            self.store,
            brand="Samsung Galaxy",
            model="Galaxy S24 Ultra",
            storage="512GB",
            carrier="Verizon",
            condition="Like New",
            answers={"lost_stolen": "yes", "financed": "no", "account_lock": "no"},
        )

        self.assertFalse(result["eligible"])
        self.assertEqual(result["block_message"], "Zelvari cannot accept this device")
        self.assertIn("legally eligible", result["block_explanation"])

    def test_seller_submission_validates_required_fields_terms_privacy_and_saves_quote_number(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        bad_status, _headers, bad_body = client.post("/seller", {"full_name": ""})
        self.assertTrue(bad_status.startswith("400"))
        self.assertIn("Full name is required", bad_body)
        self.assertIn("Terms agreement is required", bad_body)
        self.assertEqual(self.store.list_orders(), [])

        status, _headers, body = client.post(
            "/seller",
            {
                "brand": "Apple iPhone",
                "model": "iPhone 15 Pro Max",
                "storage": "256GB",
                "carrier": "Unlocked",
                "condition": "Good",
                "estimated_payout_cents": "67600",
                "full_name": "Michael Rod",
                "email": "michael@example.com",
                "phone": "555-100-2000",
                "street_address": "123 Main St",
                "apartment": "Unit 7",
                "city": "Denver",
                "state": "CO",
                "zip_code": "80202",
                "payout_method": "PayPal",
                "terms_agree": "1",
                "privacy_agree": "1",
            },
        )

        self.assertTrue(status.startswith("200"))
        self.assertIn("Zelvari will follow up manually", body)
        self.assertRegex(body, r"ZEL-[0-9]{6}-[0-9A-F]{16}")
        orders = self.store.list_orders()
        self.assertEqual(len(orders), 1)
        quote_match = re.search(r"ZEL-[0-9]{6}-[0-9A-F]{16}", body)
        self.assertIsNotNone(quote_match)
        if quote_match is None:
            self.fail("confirmation page did not include a high-entropy quote number")
        self.assertEqual(orders[0]["quote_number"], quote_match.group(0))
        self.assertEqual(orders[0]["payout_method"], "PayPal")

    def test_public_pages_include_premium_branding_catalog_support_demo_auth_dashboard_empty_states(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, home = client.get("/")
        self.assertTrue(status.startswith("200"))
        for text in [
            "ZELVARI",
            "AI-Powered Quotes. Human Trust.",
            "Sell Your Phone the Smart Way",
            "the Smart Way",
            "Get Your Instant Quote",
            "Phone Brand",
            "Phone Model",
            "Storage",
            "Carrier",
            "Brand New",
            "Like New",
            "Good",
            "Fair",
            "Damaged",
            "Not Working",
            "Final value is confirmed after inspection.",
            "No fees. No obligation. 100% free.",
            "Choose Your Device",
            "Get an Instant Offer",
            "Ship It for Free",
            "Get Paid Fast",
            "Apple iPhone",
            "Samsung Galaxy",
            "Google Pixel",
            "OnePlus",
            "Motorola",
            "Xiaomi",
            "Nothing",
            "Other Brands",
            "Load More",
            "No catalog matches",
            "Why Choose Zelvari",
            "Fast Payment",
            "Free Shipping",
            "Trusted Quotes",
            "Secure Data Protection",
            "Better for the Planet",
            "Top Trade-In Values",
            "Top Pick",
            "Verified Seller",
            "The smarter way to sell your phone.",
            "Good for your wallet. Better for the planet.",
            "mobile-menu-toggle",
        ]:
            self.assertIn(text, home)
        top_section_match = re.search(r'<section class="top" id="top">(?P<section>.*?)</section>', home, re.S)
        self.assertIsNotNone(top_section_match)
        if top_section_match is None:
            self.fail("Top Trade-In Values section was not rendered")
        top_section = top_section_match.group("section")
        self.assertEqual(top_section.count("class=\"device-visual\""), 3)
        self.assertEqual(top_section.count("Top Pick"), 1)
        for text in ["Model", "Storage", "Condition", "Estimated payout", "Get Quote"]:
            self.assertIn(text, top_section)
        self.assertIn("Based on 2 seeded demo reviews", home)

        dashboard_status, _headers, dashboard = client.get("/dashboard")
        self.assertTrue(dashboard_status.startswith("200"))
        for text in ["Active Quotes", "Shipping Status", "Devices Received", "Inspection Results", "Payments", "Completed Sales", "Saved Devices", "Profile", "Support", "Quote Created", "Payment Sent"]:
            self.assertIn(text, dashboard)

        auth_status, _headers, auth = client.get("/signin")
        self.assertTrue(auth_status.startswith("200"))
        for text in ["Sign Up", "Sign In", "Forgot Password", "Email Verification", "Secure Sessions", "Sign Out", "customer accounts are not active yet"]:
            self.assertIn(text, auth)

        support_status, _headers, support = client.get("/support")
        self.assertTrue(support_status.startswith("200"))
        for text in ["Support Center", "searchable help articles", "quote-status lookup", "shipping help", "payment help", "device preparation", "activation lock", "sale cancellation"]:
            self.assertIn(text, support)

    def test_empty_pricing_catalog_and_quote_status_lookup_have_safe_empty_states(self):
        empty_db = os.path.join(self.tempdir.name, "empty.sqlite3")
        BuybackStore(empty_db)
        app = create_app(empty_db)
        client = WsgiTestClient(app)

        status, _headers, body = client.get("/")
        self.assertTrue(status.startswith("200"))
        self.assertIn("Pricing is not available yet", body)
        self.assertIn("No catalog matches", body)

        lookup_status, _headers, lookup = client.post("/support/lookup", {"quote_number": "ZEL-000000-FAKE", "lookup_verifier": "80202"})
        self.assertTrue(lookup_status.startswith("404"))
        self.assertIn("No quote was found for that number", lookup)
        self.assertNotIn("michael@example.com", lookup)

    def test_condition_questionnaire_answers_affect_value_or_explain_no_impact(self):
        baseline = calculate_condition_offer(
            self.store,
            brand="Apple iPhone",
            model="iPhone 15 Pro Max",
            storage="256GB",
            carrier="Unlocked",
            condition="Good",
            answers={},
        )

        value_changing_answers = {
            "power_on": "no",
            "buttons": "no",
            "cameras": "no",
            "charging": "no",
            "swollen_battery": "yes",
            "missing_parts": "yes",
        }
        for key, answer in value_changing_answers.items():
            with self.subTest(answer=key):
                offer = calculate_condition_offer(
                    self.store,
                    brand="Apple iPhone",
                    model="iPhone 15 Pro Max",
                    storage="256GB",
                    carrier="Unlocked",
                    condition="Good",
                    answers={key: answer},
                )
                self.assertTrue(offer["eligible"])
                self.assertNotEqual(offer["offer_cents"], baseline["offer_cents"])
                self.assertIn(key.replace("_", " "), offer["adjustment_summary"].lower())

        repair_history = calculate_condition_offer(
            self.store,
            brand="Apple iPhone",
            model="iPhone 15 Pro Max",
            storage="256GB",
            carrier="Unlocked",
            condition="Good",
            answers={"repair_history": "yes"},
        )
        self.assertEqual(repair_history["offer_cents"], baseline["offer_cents"])
        self.assertIn("Repair history noted", repair_history["adjustment_summary"])

    def test_seller_submission_persists_hardware_adjusted_server_value(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)
        payload = {
            "brand": "Apple iPhone",
            "model": "iPhone 15 Pro Max",
            "storage": "256GB",
            "carrier": "Unlocked",
            "condition": "Good",
            "estimated_payout_cents": "999999",
            "power_on": "no",
            "full_name": "Hardware Tester",
            "email": "hardware@example.com",
            "phone": "555-555-1001",
            "street_address": "123 Main St",
            "apartment": "",
            "city": "Denver",
            "state": "CO",
            "zip_code": "80202",
            "payout_method": "PayPal",
            "terms_agree": "1",
            "privacy_agree": "1",
        }
        expected = calculate_condition_offer(
            self.store,
            brand="Apple iPhone",
            model="iPhone 15 Pro Max",
            storage="256GB",
            carrier="Unlocked",
            condition="Good",
            answers={"power_on": "no"},
        )["offer_cents"]

        status, _headers, body = client.post("/seller", payload)

        self.assertTrue(status.startswith("200"), body)
        saved = self.store.list_orders()[0]
        self.assertEqual(saved["estimated_payout_cents"], expected)
        self.assertIn("Power on issue", saved["adjustment_summary"])

    def test_quote_numbers_are_high_entropy_and_duplicate_generation_retries(self):
        stamp = datetime.now(timezone.utc).strftime("%y%m%d")
        duplicate = f"ZEL-{stamp}-DEADBEEFDEADBEEF"
        first_payload = self._order_payload(full_name="First Duplicate", email="first@example.com", quote_number=duplicate)
        self.store.create_order(first_payload)

        with mock.patch("loops_app.buyback.secrets.token_hex", side_effect=["deadbeefdeadbeef", "cafebabecafebabe"]):
            second = self.store.create_order(self._order_payload(full_name="Retry Duplicate", email="retry@example.com"))

        self.assertEqual(second["quote_number"], f"ZEL-{stamp}-CAFEBABECAFEBABE")
        self.assertRegex(second["quote_number"], r"^ZEL-[0-9]{6}-[0-9A-F]{16}$")

    def test_quote_status_lookup_requires_customer_verifier_and_hides_mismatches(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)
        order = self.store.create_order(self._order_payload(full_name="Lookup Customer", email="lookup@example.com", zip_code="80202"))

        no_verifier_status, _headers, no_verifier = client.post("/support/lookup", {"quote_number": order["quote_number"]})
        wrong_status, _headers, wrong = client.post("/support/lookup", {"quote_number": order["quote_number"], "lookup_verifier": "99999"})
        ok_status, _headers, ok = client.post("/support/lookup", {"quote_number": order["quote_number"], "lookup_verifier": "lookup@example.com"})

        self.assertTrue(no_verifier_status.startswith("404"))
        self.assertTrue(wrong_status.startswith("404"))
        self.assertNotIn("Quote Created", no_verifier)
        self.assertNotIn("Quote Created", wrong)
        self.assertTrue(ok_status.startswith("200"))
        self.assertIn("status: Quote Created", ok)

    def test_catalog_json_is_script_safe_and_option_builder_uses_text_content(self):
        malicious = "Bad </script><script>window.XSS=1</script> & \u2028 marker"
        self.store.upsert_pricing(
            brand=malicious,
            model='Model "quoted" <img src=x onerror=alert(1)>',
            storage="128GB & <tag>",
            base_value_cents=10000,
            maximum_payout_cents=12000,
        )
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, home = client.get("/")

        self.assertTrue(status.startswith("200"))
        self.assertNotIn("</script><script>window.XSS=1</script>", home)
        self.assertNotIn("select.innerHTML", home)
        self.assertIn("document.createElement('option')", home)
        self.assertIn("textContent", home)
        self.assertIn("Bad &lt;/script&gt;&lt;script&gt;window.XSS=1&lt;/script&gt;", home)

    def test_admin_authentication_fails_closed_updates_pricing_orders_and_shows_stats(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)
        first_price = self.store.list_pricing()[0]

        forged = WsgiTestClient(app)
        forged.cookies["buyback_admin"] = "not-real"
        blocked_status, _headers, blocked_body = forged.get("/admin")
        update_status, _headers, _body = forged.post("/admin/pricing/update", {"id": str(first_price["id"]), "base_value_cents": "12345"})
        self.assertTrue(blocked_status.startswith("401"))
        self.assertTrue(update_status.startswith("401"))
        self.assertNotIn("SQL", blocked_body)

        os.environ["BUYBACK_ADMIN_USERNAME"] = "michael"
        os.environ["BUYBACK_ADMIN_PASSWORD"] = "safe-password"
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_USERNAME", None)
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_PASSWORD", None)

        login_status, _headers, admin = client.post("/admin/login", {"username": "michael", "password": "safe-password"})
        self.assertTrue(login_status.startswith("200"))
        for text in ["Total Quotes", "Accepted Quotes", "Devices Received", "Devices Inspected", "Payments Sent", "Average Payout", "Conversion Rate", "Total Buyback Value", "Phone brands/models", "Reviews", "FAQs"]:
            self.assertIn(text, admin)

        pricing_status, _headers, pricing_body = client.post(
            "/admin/pricing/update",
            {"id": str(first_price["id"]), "base_value_cents": "77777", "maximum_payout_cents": "99999", "active": "1"},
        )
        self.assertTrue(pricing_status.startswith("200"))
        self.assertIn("$999.99", pricing_body)
        updated = next(row for row in self.store.list_pricing() if row["id"] == first_price["id"])
        self.assertEqual(updated["base_value_cents"], 77777)

        order = self.store.create_order(
            {
                "brand": "Apple iPhone",
                "model": "iPhone 15 Pro Max",
                "storage": "256GB",
                "carrier": "Unlocked",
                "condition": "Good",
                "estimated_payout_cents": 67600,
                "full_name": "Michael Rod",
                "email": "michael@example.com",
                "phone": "555-100-2000",
                "street_address": "123 Main St",
                "apartment": "",
                "city": "Denver",
                "state": "CO",
                "zip_code": "80202",
                "payout_method": "Venmo",
                "adjustment_summary": "Good condition",
            }
        )
        status_status, _headers, status_body = client.post(
            "/admin/order/update",
            {
                "quote_number": order["quote_number"],
                "status": "Payment Sent",
                "inspection_result": "Approved",
                "internal_notes": "Looks clean",
                "decision": "Approved",
                "final_payout_cents": "65000",
                "payment_sent": "1",
            },
        )
        self.assertTrue(status_status.startswith("200"))
        self.assertIn("Payment Sent", status_body)
        saved = self.store.get_order(order["quote_number"])
        self.assertEqual(saved["status"], "Payment Sent")
        self.assertEqual(saved["final_payout_cents"], 65000)

    def test_admin_pricing_update_edits_all_quote_adjustment_fields_and_recalculates_offers(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)
        os.environ["BUYBACK_ADMIN_USERNAME"] = "michael"
        os.environ["BUYBACK_ADMIN_PASSWORD"] = "safe-password"
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_USERNAME", None)
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_PASSWORD", None)
        first_price = self.store.list_pricing()[0]

        login_status, _headers, admin = client.post("/admin/login", {"username": "michael", "password": "safe-password"})

        self.assertTrue(login_status.startswith("200"))
        for field_name in [
            "carrier_adjustment_cents",
            "condition_deduction_cents",
            "screen_damage_deduction_cents",
            "back_glass_deduction_cents",
            "water_damage_deduction_cents",
            "non_working_value_cents",
            "promotional_bonus_cents",
        ]:
            self.assertIn(f"name='{field_name}'", admin)

        update_status, _headers, _body = client.post(
            "/admin/pricing/update",
            {
                "id": str(first_price["id"]),
                "base_value_cents": "50000",
                "maximum_payout_cents": "100000",
                "carrier_adjustment_cents": "1000",
                "condition_deduction_cents": "2000",
                "screen_damage_deduction_cents": "3000",
                "back_glass_deduction_cents": "4000",
                "water_damage_deduction_cents": "5000",
                "non_working_value_cents": "6000",
                "promotional_bonus_cents": "7000",
                "active": "1",
            },
        )

        self.assertTrue(update_status.startswith("200"))
        updated = self.store.get_pricing_by_id(first_price["id"])
        self.assertIsNotNone(updated)
        if updated is None:
            self.fail("updated pricing row was not found")
        for field_name, expected in {
            "base_value_cents": 50000,
            "maximum_payout_cents": 100000,
            "carrier_adjustment_cents": 1000,
            "condition_deduction_cents": 2000,
            "screen_damage_deduction_cents": 3000,
            "back_glass_deduction_cents": 4000,
            "water_damage_deduction_cents": 5000,
            "non_working_value_cents": 6000,
            "promotional_bonus_cents": 7000,
        }.items():
            self.assertEqual(updated[field_name], expected)
        recalculated = calculate_offer(
            self.store,
            brand=updated["brand"],
            model=updated["model"],
            storage=updated["storage"],
            carrier="Unlocked",
            condition="Good",
            cracked_screen="yes",
            cracked_back_glass="yes",
            water_damage="yes",
        )
        self.assertEqual(recalculated["offer_cents"], 44000)
        self.assertIn("Promotional bonus +$70.00", recalculated["adjustment_summary"])

    def test_invalid_admin_pricing_values_return_clear_validation_and_preserve_row(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)
        os.environ["BUYBACK_ADMIN_USERNAME"] = "michael"
        os.environ["BUYBACK_ADMIN_PASSWORD"] = "safe-password"
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_USERNAME", None)
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_PASSWORD", None)
        first_price = self.store.list_pricing()[0]
        original_row = self.store.get_pricing_by_id(first_price["id"])
        client.post("/admin/login", {"username": "michael", "password": "safe-password"})

        for field_name, invalid_value in [("base_value_cents", "-1"), ("carrier_adjustment_cents", "not-a-number")]:
            with self.subTest(field_name=field_name):
                payload = {key: str(first_price[key]) for key in [
                    "base_value_cents",
                    "maximum_payout_cents",
                    "carrier_adjustment_cents",
                    "condition_deduction_cents",
                    "screen_damage_deduction_cents",
                    "back_glass_deduction_cents",
                    "water_damage_deduction_cents",
                    "non_working_value_cents",
                    "promotional_bonus_cents",
                ]}
                payload.update({"id": str(first_price["id"]), field_name: invalid_value, "active": "1"})

                status, _headers, body = client.post("/admin/pricing/update", payload)

                self.assertTrue(status.startswith("400"), body)
                self.assertIn("Pricing update failed", body)
                self.assertIn(field_name.replace("_", " "), body)
                self.assertNotIn("IntegrityError", body)
                self.assertNotIn("Traceback", body)
                self.assertNotIn("SQL", body)
                self.assertNotIn("Something went wrong", body)
                self.assertEqual(self.store.get_pricing_by_id(first_price["id"]), original_row)

    def test_demo_auth_flows_validate_but_do_not_store_customer_credentials(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        bad_status, _headers, bad_body = client.post("/signup", {"email": "not-an-email", "password": "123"})
        self.assertTrue(bad_status.startswith("400"))
        self.assertIn("Enter a valid email", bad_body)

        ok_status, _headers, ok_body = client.post("/signup", {"email": "customer@example.com", "password": "long-enough"})
        self.assertTrue(ok_status.startswith("200"))
        self.assertIn("Demo account flow complete", ok_body)
        self.assertEqual(self.store.count_demo_credentials(), 0)

    def test_seller_submission_recalculates_tampered_payout_and_blocks_ineligible_answers(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        payload = {
            "brand": "Apple iPhone",
            "model": "iPhone 15 Pro Max",
            "storage": "256GB",
            "carrier": "Unlocked",
            "condition": "Good",
            "estimated_payout_cents": "999999",
            "full_name": "Tamper Tester",
            "email": "tamper@example.com",
            "phone": "555-555-1000",
            "street_address": "123 Main St",
            "apartment": "",
            "city": "Denver",
            "state": "CO",
            "zip_code": "80202",
            "payout_method": "PayPal",
            "terms_agree": "1",
            "privacy_agree": "1",
        }
        expected = calculate_offer(
            self.store,
            brand="Apple iPhone",
            model="iPhone 15 Pro Max",
            storage="256GB",
            carrier="Unlocked",
            condition="Good",
        )["offer_cents"]

        status, _headers, body = client.post("/seller", payload)

        self.assertTrue(status.startswith("200"), body)
        saved = self.store.list_orders()[0]
        self.assertEqual(saved["estimated_payout_cents"], expected)
        self.assertNotEqual(saved["estimated_payout_cents"], 999999)

        blocked_status, _headers, blocked_body = client.post(
            "/seller",
            {**payload, "email": "blocked@example.com", "lost_stolen": "yes"},
        )

        self.assertTrue(blocked_status.startswith("400"))
        self.assertIn("Zelvari cannot accept this device", blocked_body)
        self.assertEqual(len(self.store.list_orders()), 1)

    def test_home_renders_working_catalog_questionnaire_results_and_accessible_mobile_script(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, home = client.get("/")

        self.assertTrue(status.startswith("200"))
        for text in [
            "data-catalog-search",
            "data-catalog-brand",
            "data-catalog-model",
            "data-catalog-storage",
            "data-catalog-sort",
            "data-load-more",
            "data-question-key=\"lost_stolen\"",
            "data-answer=\"yes\"",
            "questionnaireAnswers",
            "refreshQuestionnaire",
            "refreshCatalog",
            "refreshQuoteReview",
            "seller_brand",
            "seller_model",
            "seller_storage",
            "seller_estimated_payout_cents",
            "aria-expanded",
        ]:
            self.assertIn(text, home)
        self.assertNotIn("Phone visual, brand, model, storage, carrier, condition, estimated payout, offer expiration date, and adjustment summary appear before acceptance.", home)

    def test_admin_search_filters_by_customer_quote_number_and_safe_no_results(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)
        os.environ["BUYBACK_ADMIN_USERNAME"] = "michael"
        os.environ["BUYBACK_ADMIN_PASSWORD"] = "safe-password"
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_USERNAME", None)
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_PASSWORD", None)
        client.post("/admin/login", {"username": "michael", "password": "safe-password"})
        first = self.store.create_order(
            {
                "brand": "Apple iPhone",
                "model": "iPhone 15 Pro Max",
                "storage": "256GB",
                "carrier": "Unlocked",
                "condition": "Good",
                "estimated_payout_cents": 71500,
                "full_name": "Jane Searchable",
                "email": "jane@example.com",
                "phone": "555-222-3333",
                "street_address": "123 Main St",
                "apartment": "",
                "city": "Denver",
                "state": "CO",
                "zip_code": "80202",
                "payout_method": "Venmo",
                "adjustment_summary": "Good condition",
            }
        )
        self.store.create_order(
            {
                "brand": "Samsung Galaxy",
                "model": "Galaxy S24 Ultra",
                "storage": "512GB",
                "carrier": "Verizon",
                "condition": "Like New",
                "estimated_payout_cents": 62000,
                "full_name": "Bob Hidden",
                "email": "bob@example.com",
                "phone": "555-444-3333",
                "street_address": "99 Side St",
                "apartment": "",
                "city": "Denver",
                "state": "CO",
                "zip_code": "80202",
                "payout_method": "PayPal",
                "adjustment_summary": "Like New condition",
            }
        )

        customer_status, _headers, customer_body = client.get("/admin", query="customer=Jane")
        quote_status, _headers, quote_body = client.get("/admin", query=f"quote_number={first['quote_number'][-4:]}")
        empty_status, _headers, empty_body = client.get("/admin", query="customer=NoSuchCustomer&quote_number=NOPE")

        self.assertTrue(customer_status.startswith("200"))
        self.assertIn("Jane Searchable", customer_body)
        self.assertNotIn("Bob Hidden", customer_body)
        self.assertTrue(quote_status.startswith("200"))
        self.assertIn(first["quote_number"], quote_body)
        self.assertTrue(empty_status.startswith("200"))
        self.assertIn("No admin quote results match those filters.", empty_body)
        self.assertNotIn("Jane Searchable", empty_body)

    def test_route_specific_demo_auth_and_support_search_are_functional_demo_flows(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        forgot_status, _headers, forgot = client.get("/forgot-password")
        bad_forgot_status, _headers, bad_forgot = client.post("/forgot-password", {"email": "bad-email"})
        ok_forgot_status, _headers, ok_forgot = client.post("/forgot-password", {"email": "customer@example.com"})
        signin_status, _headers, signin = client.get("/signin")
        support_status, _headers, support = client.get("/support")

        self.assertTrue(forgot_status.startswith("200"))
        self.assertIn("Forgot Password", forgot)
        self.assertIn("Demo reset link", forgot)
        self.assertNotIn("Password must be at least 8 characters", forgot)
        self.assertTrue(bad_forgot_status.startswith("400"))
        self.assertIn("Enter a valid email", bad_forgot)
        self.assertTrue(ok_forgot_status.startswith("200"))
        self.assertIn("Demo password reset flow complete", ok_forgot)
        self.assertTrue(signin_status.startswith("200"))
        self.assertIn("Sign In", signin)
        self.assertIn("customer accounts are not active yet", signin)
        self.assertTrue(support_status.startswith("200"))
        self.assertIn("data-help-search", support)
        self.assertIn("data-help-article", support)
        self.assertIn("data-help-empty", support)
        self.assertIn("filterHelpArticles", support)

    def test_questionnaire_answers_have_visible_selected_state_and_aria_pressed(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, home = client.get("/")

        self.assertTrue(status.startswith("200"))
        self.assertIn("data-answer=\"yes\" aria-pressed=\"false\"", home)
        self.assertIn(".question [data-answer].selected", home)
        self.assertIn("linear-gradient(135deg,var(--purple),var(--blue))", home)
        self.assertIn("setAttribute('aria-pressed',other===button?'true':'false')", home)

    def test_mobile_hamburger_exposes_quote_and_sign_in_actions(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, home = client.get("/")

        self.assertTrue(status.startswith("200"))
        self.assertIn("@media(max-width:760px)", home)
        self.assertIn(".nav-open .actions", home)
        self.assertRegex(home, r"\.nav-open \.actions\{[^}]*display:flex")

    def test_catalog_renders_all_seeded_cards_so_xiaomi_filter_has_a_card(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, home = client.get("/")

        self.assertTrue(status.startswith("200"))
        self.assertEqual(home.count("class='phone-card' data-catalog-card"), len(self.store.list_pricing(active_only=True)))
        self.assertIn("data-brand='Xiaomi'", home)
        self.assertIn("Xiaomi 14 Ultra", home)

    def test_existing_legacy_pricing_schema_is_recovered_before_seed_sample(self):
        legacy_db = os.path.join(self.tempdir.name, "legacy-buyback.sqlite3")
        with sqlite3.connect(legacy_db) as connection:
            connection.execute(
                "CREATE TABLE pricing (id INTEGER PRIMARY KEY AUTOINCREMENT, brand TEXT NOT NULL, model TEXT NOT NULL, storage TEXT NOT NULL, base_price_cents INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT INTO pricing (brand, model, storage, base_price_cents) VALUES ('Legacy', 'Phone', '64GB', 12345)"
            )

        store = BuybackStore(legacy_db)
        seed_sample_data(store)

        rows = store.list_pricing(active_only=True)
        self.assertTrue(any(row["brand"] == "Apple iPhone" for row in rows))
        legacy_row = next(row for row in rows if row["brand"] == "Legacy")
        self.assertEqual(legacy_row["base_value_cents"], 12345)
        self.assertEqual(legacy_row["maximum_payout_cents"], 12345)

    def _order_payload(self, **overrides):
        payload = {
            "brand": "Apple iPhone",
            "model": "iPhone 15 Pro Max",
            "storage": "256GB",
            "carrier": "Unlocked",
            "condition": "Good",
            "estimated_payout_cents": 71500,
            "full_name": "Michael Rod",
            "email": "michael@example.com",
            "phone": "555-100-2000",
            "street_address": "123 Main St",
            "apartment": "",
            "city": "Denver",
            "state": "CO",
            "zip_code": "80202",
            "payout_method": "Venmo",
            "adjustment_summary": "Good condition",
        }
        payload.update(overrides)
        return payload


if __name__ == "__main__":
    unittest.main()
