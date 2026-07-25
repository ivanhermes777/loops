import io
import os
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

    def test_empty_pricing_data_shows_graceful_no_options_state(self):
        empty_db = os.path.join(self.tempdir.name, "empty.sqlite3")
        BuybackStore(empty_db)
        app = create_app(empty_db)
        client = WsgiTestClient(app)

        status, _headers, body = client.get("/")

        self.assertTrue(status.startswith("200"))
        self.assertIn("Pricing is not available yet", body)
        self.assertNotIn("<select", body)


if __name__ == "__main__":
    unittest.main()
