import io
import os
import sys
import tempfile
import unittest
from urllib.parse import urlencode

from loops_app.app_factory import create_app
from loops_app.buyback import BuybackStore, calculate_offer, seed_sample_pricing


class WsgiTestClient:
    def __init__(self, app):
        self.app = app
        self.cookies = {}

    def get(self, path):
        return self._request("GET", path)

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

    def _request(self, method, path, body=b"", headers=None):
        headers = headers or {}
        status_headers = {}
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
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
        seed_sample_pricing(self.store)
        self.addCleanup(self.tempdir.cleanup)

    def test_calculates_offer_from_pricing_table_and_condition_multiplier(self):
        iphone_offer = calculate_offer(
            self.store,
            brand="iPhone",
            model="iPhone 15 Pro",
            storage="256GB",
            condition="Good",
        )
        samsung_offer = calculate_offer(
            self.store,
            brand="Samsung Galaxy",
            model="Galaxy S24 Ultra",
            storage="512GB",
            condition="Fair",
        )

        self.assertEqual(iphone_offer["offer_cents"], 54400)
        self.assertEqual(samsung_offer["offer_cents"], 46200)
        self.assertEqual(iphone_offer["condition_multiplier"], 0.85)
        self.assertEqual(samsung_offer["condition_multiplier"], 0.70)

    def test_customer_selectors_hide_unsupported_models_storage_and_conditions(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, body = client.get("/")

        self.assertTrue(status.startswith("200"))
        self.assertIn("iPhone 15 Pro", body)
        self.assertIn("Galaxy S24 Ultra", body)
        self.assertIn("256GB", body)
        self.assertIn("New/Like New", body)
        self.assertIn("Cracked/Damaged", body)
        self.assertNotIn("Google Pixel", body)
        self.assertNotIn("128GB", body)
        self.assertNotIn("Manual Review", body)
        self.assertNotIn("$0", body)

    def test_valid_offer_request_is_saved_with_contact_device_estimate_and_notes(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, body = client.post(
            "/request",
            {
                "name": "Michael Rod",
                "email": "michael@example.com",
                "phone": "555-100-2000",
                "brand": "iPhone",
                "model": "iPhone 15 Pro",
                "storage": "256GB",
                "condition": "Good",
                "notes": "Unlocked and includes original box.",
            },
        )

        self.assertTrue(status.startswith("200"))
        self.assertIn("Zelvari will follow up manually", body)
        requests = self.store.list_offer_requests()
        self.assertEqual(len(requests), 1)
        saved = requests[0]
        self.assertEqual(saved["name"], "Michael Rod")
        self.assertEqual(saved["email"], "michael@example.com")
        self.assertEqual(saved["phone"], "555-100-2000")
        self.assertEqual(saved["brand"], "iPhone")
        self.assertEqual(saved["model"], "iPhone 15 Pro")
        self.assertEqual(saved["storage"], "256GB")
        self.assertEqual(saved["condition"], "Good")
        self.assertEqual(saved["estimate_cents"], 54400)
        self.assertEqual(saved["notes"], "Unlocked and includes original box.")

    def test_missing_required_customer_fields_show_errors_and_do_not_save(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, body = client.post(
            "/request",
            {
                "name": "",
                "email": "",
                "phone": "555-100-2000",
                "brand": "iPhone",
                "model": "iPhone 15 Pro",
                "storage": "256GB",
                "condition": "Good",
            },
        )

        self.assertTrue(status.startswith("400"))
        self.assertIn("Name is required", body)
        self.assertIn("Email is required", body)
        self.assertEqual(self.store.list_offer_requests(), [])

    def test_admin_routes_reject_unauthenticated_access_and_accept_env_login(self):
        os.environ["BUYBACK_ADMIN_USERNAME"] = "michael"
        os.environ["BUYBACK_ADMIN_PASSWORD"] = "safe-password"
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_USERNAME", None)
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_PASSWORD", None)
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        blocked_status, _headers, blocked_body = client.get("/admin")
        self.assertTrue(blocked_status.startswith("401"))
        self.assertIn("Admin login required", blocked_body)

        login_status, _headers, login_body = client.post(
            "/admin/login",
            {"username": "michael", "password": "safe-password"},
        )
        self.assertTrue(login_status.startswith("200"))
        self.assertIn("Pricing Table", login_body)
        self.assertIn("Saved Offer Requests", login_body)

    def test_admin_routes_fail_closed_with_forged_cookie_when_credentials_are_unset(self):
        os.environ.pop("BUYBACK_ADMIN_USERNAME", None)
        os.environ.pop("BUYBACK_ADMIN_PASSWORD", None)
        app = create_app(self.db_path)
        client = WsgiTestClient(app)
        client.cookies["buyback_admin"] = "06700c44aaaf426a054948d7db657adee600e9550c1eda6baeb05be4d16c4891"
        original_pricing = self.store.list_pricing(active_only=False)[0]
        pricing_id = original_pricing["id"]

        admin_status, _headers, admin_body = client.get("/admin")
        update_status, _headers, _body = client.post(
            "/admin/pricing/update",
            {"id": str(pricing_id), "base_price_cents": "12345", "active": "1"},
        )

        self.assertTrue(admin_status.startswith("401"))
        self.assertNotIn("Pricing Table", admin_body)
        self.assertNotIn("Saved Offer Requests", admin_body)
        self.assertTrue(update_status.startswith("401"))
        unchanged = next(row for row in self.store.list_pricing(active_only=False) if row["id"] == pricing_id)
        self.assertEqual(unchanged["base_price_cents"], original_pricing["base_price_cents"])

    def test_empty_pricing_data_shows_graceful_no_options_state(self):
        empty_db = os.path.join(self.tempdir.name, "empty.sqlite3")
        BuybackStore(empty_db)
        app = create_app(empty_db)
        client = WsgiTestClient(app)

        status, _headers, body = client.get("/")

        self.assertTrue(status.startswith("200"))
        self.assertIn("Pricing is not available yet", body)
        self.assertNotIn("<select", body)

    def test_prompt_builder_get_shows_required_public_ui(self):
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, body = client.get("/prompt-builder")

        self.assertTrue(status.startswith("200"))
        self.assertIn("Write Better Prompts", body)
        self.assertIn("name=\"prompt\"", body)
        self.assertIn("maxlength=\"4000\"", body)
        self.assertIn("0 / 4000", body)
        self.assertIn("Goal", body)
        self.assertIn("name=\"goal\"", body)
        self.assertIn("Tone", body)
        self.assertIn("name=\"tone\"", body)
        self.assertIn("Platform", body)
        self.assertIn("name=\"platform\"", body)
        self.assertIn("Improve Prompt", body)
        self.assertIn("Improved Prompt", body)
        self.assertIn("Copy", body)
        self.assertIn("Your prompts are private and never stored", body)

    def test_empty_prompt_submission_validates_inline_without_running_command(self):
        os.environ["PROMPT_BUILDER_COMMAND_JSON"] = '["/definitely/not/run"]'
        self.addCleanup(os.environ.pop, "PROMPT_BUILDER_COMMAND_JSON", None)
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, body = client.post(
            "/prompt-builder",
            {"prompt": "   ", "goal": "general", "tone": "professional", "platform": "any"},
        )

        self.assertTrue(status.startswith("400"))
        self.assertIn("Please enter a prompt to improve.", body)
        self.assertIn("Write Better Prompts", body)

    def test_valid_prompt_submission_renders_improved_prompt_only_and_does_not_store_prompt_text(self):
        stub = (
            "import sys; "
            "sys.stdin.read(); "
            "print('Improved safe prompt with clear objectives and a strong CTA.')"
        )
        os.environ["PROMPT_BUILDER_COMMAND_JSON"] = json_command([sys.executable, "-c", stub])
        self.addCleanup(os.environ.pop, "PROMPT_BUILDER_COMMAND_JSON", None)
        raw_prompt = "rough <script>alert('x')</script> landing page prompt"
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, body = client.post(
            "/prompt-builder",
            {
                "prompt": raw_prompt,
                "goal": "marketing",
                "tone": "professional",
                "platform": "website",
            },
        )

        self.assertTrue(status.startswith("200"))
        self.assertIn("Improved safe prompt with clear objectives and a strong CTA.", body)
        self.assertIn("Copy", body)
        self.assertNotIn("Token", body)
        self.assertNotIn("Model", body)
        self.assertNotIn("Prompt Score", body)
        self.assertNotIn(raw_prompt, body)
        self.assertEqual(self.store.list_offer_requests(), [])

    def test_failing_prompt_command_shows_sanitized_temporary_unavailable_error(self):
        secret = "super-secret-command-token"
        os.environ["PROMPT_BUILDER_COMMAND_JSON"] = json_command(
            [sys.executable, "-c", f"import sys; sys.stderr.write('{secret}'); raise SystemExit(2)"]
        )
        self.addCleanup(os.environ.pop, "PROMPT_BUILDER_COMMAND_JSON", None)
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        status, _headers, body = client.post(
            "/prompt-builder",
            {"prompt": "Make this better", "goal": "general", "tone": "professional", "platform": "any"},
        )

        self.assertTrue(status.startswith("503"))
        self.assertIn("Prompt improvement is temporarily unavailable", body)
        self.assertNotIn(secret, body)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("PROMPT_BUILDER_COMMAND_JSON", body)

    def test_prompt_builder_text_is_not_exposed_in_buyback_admin(self):
        stub = "import sys; sys.stdin.read(); print('Private improved prompt output')"
        os.environ["PROMPT_BUILDER_COMMAND_JSON"] = json_command([sys.executable, "-c", stub])
        os.environ["BUYBACK_ADMIN_USERNAME"] = "michael"
        os.environ["BUYBACK_ADMIN_PASSWORD"] = "safe-password"
        self.addCleanup(os.environ.pop, "PROMPT_BUILDER_COMMAND_JSON", None)
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_USERNAME", None)
        self.addCleanup(os.environ.pop, "BUYBACK_ADMIN_PASSWORD", None)
        app = create_app(self.db_path)
        client = WsgiTestClient(app)

        prompt_status, _prompt_headers, _prompt_body = client.post(
            "/prompt-builder",
            {"prompt": "Private raw prompt", "goal": "general", "tone": "professional", "platform": "any"},
        )
        login_status, _headers, admin_body = client.post(
            "/admin/login",
            {"username": "michael", "password": "safe-password"},
        )

        self.assertTrue(prompt_status.startswith("200"))
        self.assertTrue(login_status.startswith("200"))
        self.assertEqual(self.store.list_offer_requests(), [])
        self.assertNotIn("Private raw prompt", admin_body)
        self.assertNotIn("Private improved prompt output", admin_body)


def json_command(command):
    import json

    return json.dumps(command)


if __name__ == "__main__":
    unittest.main()
