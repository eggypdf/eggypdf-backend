import os
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from account_routes import account_bp


class AccountRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(account_bp)
        self.client = self.app.test_client()
        self.env = patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "anon-test",
            "SUPABASE_SERVICE_ROLE_KEY": "service-test",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_health_reports_configured(self):
        r = self.client.get("/api/account/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["auth_configured"])
        self.assertTrue(r.get_json()["database_configured"])

    def test_signup_rejects_short_password(self):
        r = self.client.post("/api/account/signup", json={"email": "a@example.com", "password": "123"})
        self.assertEqual(r.status_code, 400)

    @patch("account_routes.requests.post")
    def test_login_returns_safe_session(self, post):
        resp = Mock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
            "expires_at": 123,
            "token_type": "bearer",
            "user": {"id": "u1", "email": "a@example.com", "email_confirmed_at": "now", "secret": "ignore"},
        }
        post.return_value = resp
        r = self.client.post("/api/account/login", json={"email": "a@example.com", "password": "password123"})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["session"]["user"]["id"], "u1")
        self.assertNotIn("secret", data["session"]["user"])

    @patch("account_routes.requests.get")
    def test_me_rejects_expired_token(self, get):
        resp = Mock()
        resp.ok = False
        resp.status_code = 401
        get.return_value = resp
        r = self.client.get("/api/account/me", headers={"Authorization": "Bearer expired"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
