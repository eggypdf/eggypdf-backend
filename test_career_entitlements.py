import unittest
from unittest.mock import patch

from flask import Flask

from career_routes import career_bp, DODO_PRODUCT_ID


class CareerEntitlementTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(career_bp)
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("career_routes.current_account_user")
    @patch("career_routes._dodo")
    def test_signed_in_checkout_carries_account_id(self, dodo, current_user):
        current_user.return_value = {"id": "user-123", "email": "test@example.com"}
        dodo.return_value = {
            "checkout_url": "https://checkout.example/session",
            "session_id": "cks_test_123",
        }
        response = self.client.post(
            "/api/career/checkout",
            headers={"Authorization": "Bearer valid"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["account_linked_checkout"])
        _, kwargs = dodo.call_args
        self.assertEqual(kwargs["json"]["metadata"]["account_user_id"], "user-123")

    @patch("career_routes.grant_career_pro")
    @patch("career_routes.current_account_user")
    @patch("career_routes._dodo")
    def test_verified_checkout_grants_entitlement(self, dodo, current_user, grant):
        current_user.return_value = {"id": "user-123", "email": "test@example.com"}
        dodo.return_value = {
            "payment_status": "succeeded",
            "payment_id": "pay_test_123",
            "metadata": {
                "product": "career_pro",
                "account_user_id": "user-123",
            },
        }
        grant.return_value = {
            "user_id": "user-123",
            "status": "active",
            "product_id": DODO_PRODUCT_ID,
        }
        response = self.client.get(
            "/api/career/checkout/cks_test_123",
            headers={"Authorization": "Bearer valid"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["paid"])
        self.assertTrue(body["account_linked"])
        grant.assert_called_once_with(
            "user-123",
            product_id=DODO_PRODUCT_ID,
            checkout_id="cks_test_123",
            payment_id="pay_test_123",
        )

    @patch("career_routes.user_has_career_pro", return_value=True)
    @patch("career_routes.current_account_user")
    @patch("career_routes.optimize_with_gemini")
    def test_database_entitlement_allows_pro_without_dodo_session(
        self, optimizer, current_user, has_pro
    ):
        current_user.return_value = {"id": "user-123", "email": "test@example.com"}
        optimizer.return_value = {"optimized_resume": "updated", "rewrite_applied": True}
        response = self.client.post(
            "/api/career/pro/optimize",
            headers={"Authorization": "Bearer valid"},
            json={
                "resume_text": "Resume text long enough to process.",
                "job_description": "Job description long enough to process.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        has_pro.assert_called_once_with("user-123")

    @patch("career_routes.grant_career_pro")
    @patch("career_routes.current_account_user")
    @patch("career_routes._dodo")
    def test_legacy_verified_purchase_can_migrate_to_signed_in_account(
        self, dodo, current_user, grant
    ):
        current_user.return_value = {"id": "user-123", "email": "test@example.com"}
        dodo.return_value = {
            "payment_status": "succeeded",
            "metadata": {"product": "career_pro"},
        }
        grant.return_value = {"user_id": "user-123", "status": "active"}
        response = self.client.get(
            "/api/career/checkout/cks_legacy_123",
            headers={"Authorization": "Bearer valid"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["account_linked"])
        grant.assert_called_once_with(
            "user-123",
            product_id=DODO_PRODUCT_ID,
            checkout_id="cks_legacy_123",
            payment_id=None,
        )


if __name__ == "__main__":
    unittest.main()
