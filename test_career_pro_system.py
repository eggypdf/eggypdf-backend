import unittest
from unittest.mock import patch

from flask import Flask, jsonify

import career_pro_system
import career_pro_runtime_patch
from career_pro_system import career_system_bp


class CareerProSystemTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(career_system_bp)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_plans_default_to_annual_and_2000_credits(self):
        response = self.client.get("/api/career/plans")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["default_plan"], "annual")
        self.assertEqual(body["credits_per_month"], 2000)
        self.assertEqual(body["plans"]["annual"]["billed"], 48.0)
        self.assertEqual(body["plans"]["monthly"]["price_per_month"], 6.99)
        self.assertEqual(body["credit_costs"]["resume_optimizer"], 100)

    @patch("career_pro_system._rpc")
    @patch("career_pro_system.current_account_user")
    def test_creator_code_redeems_for_any_confirmed_signed_in_email(self, current_user, rpc):
        current_user.return_value = {
            "id": "user-creator",
            "email": "personal@example.com",
            "email_confirmed_at": "2026-09-14T00:00:00Z",
        }
        rpc.return_value = {
            "success": True,
            "plan": "promo",
            "monthly_credits": 2000,
            "expires_at": None,
        }
        response = self.client.post(
            "/api/career/redeem-creator-code",
            headers={"Authorization": "Bearer test"},
            json={"code": "eggy-creator-x7k92"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        rpc.assert_called_once_with(
            "career_redeem_creator_code",
            {"p_user_id": "user-creator", "p_code": "EGGY-CREATOR-X7K92"},
        )

    @patch("career_pro_system.career_routes._dodo")
    @patch("career_pro_system._product_id", return_value="pdt_annual_test")
    @patch("career_pro_system._career_status", return_value={"active": False})
    @patch("career_pro_system.current_account_user")
    def test_annual_checkout_is_account_bound(self, current_user, status, product, dodo):
        current_user.return_value = {"id": "user-123", "email": "buyer@example.com"}
        dodo.return_value = {
            "checkout_url": "https://test.checkout.example/annual",
            "session_id": "cks_test_annual",
        }
        response = self.client.post(
            "/api/career/subscription-checkout",
            headers={"Authorization": "Bearer test"},
            json={"plan": "annual"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["plan"], "annual")
        self.assertTrue(body["account_linked_checkout"])
        payload = dodo.call_args.kwargs["json"]
        self.assertEqual(payload["product_cart"][0]["product_id"], "pdt_annual_test")
        self.assertEqual(payload["metadata"]["account_user_id"], "user-123")
        self.assertEqual(payload["metadata"]["plan"], "annual")

    @patch("career_pro_system.career_routes._dodo")
    @patch("career_pro_system.current_account_user")
    def test_checkout_from_another_account_is_rejected(self, current_user, dodo):
        current_user.return_value = {"id": "user-new", "email": "new@example.com"}
        dodo.return_value = {
            "payment_status": "succeeded",
            "metadata": {
                "product": "career_pro",
                "plan": "annual",
                "account_user_id": "user-original",
            },
        }
        response = self.client.get(
            "/api/career/subscription-checkout/cks_test_wrong",
            headers={"Authorization": "Bearer test"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("different account", response.get_json()["error"])

    @patch("career_pro_system._refund")
    @patch("career_pro_system._consume", return_value={"balance": 1900})
    @patch("career_pro_system.current_account_user", return_value={"id": "user-123"})
    def test_failed_ai_action_refunds_reserved_credits(self, current_user, consume, refund):
        app = Flask(__name__)

        def failing_action():
            return jsonify({"success": False, "error": "AI unavailable"}), 503

        wrapped = career_pro_system._credit_wrapper(failing_action, "resume_optimizer", 100)
        with app.test_request_context("/", method="POST"):
            response = app.make_response(wrapped())
        self.assertEqual(response.status_code, 503)
        consume.assert_called_once()
        refund.assert_called_once()

    @patch("career_pro_runtime_patch._rpc")
    @patch("career_pro_runtime_patch._upsert_entitlement")
    @patch("career_pro_runtime_patch._product_id", return_value="pdt_annual_test")
    @patch("career_pro_runtime_patch._entitlement")
    @patch("career_pro_runtime_patch.career_routes._dodo")
    @patch("career_pro_runtime_patch.current_account_user")
    def test_revisiting_same_paid_checkout_does_not_grant_credits_twice(
        self, current_user, dodo, entitlement, product, upsert, rpc
    ):
        current_user.return_value = {"id": "user-123", "email": "buyer@example.com"}
        entitlement.return_value = {
            "user_id": "user-123",
            "status": "active",
            "plan": "annual",
            "dodo_checkout_id": "cks_test_paid",
            "purchased_at": "2026-09-14T00:00:00Z",
            "dodo_subscription_id": "sub_test_123",
        }
        dodo.side_effect = [
            {
                "payment_status": "succeeded",
                "payment_id": None,
                "subscription_id": "sub_test_123",
                "metadata": {
                    "product": "career_pro",
                    "plan": "annual",
                    "account_user_id": "user-123",
                },
            },
            {
                "subscription_id": "sub_test_123",
                "status": "active",
                "previous_billing_date": "2026-09-14T00:00:00Z",
                "next_billing_date": "2027-09-14T00:00:00Z",
                "cancel_at_next_billing_date": False,
                "customer": {"customer_id": "cus_test_123"},
            },
        ]
        app = Flask(__name__)
        app.register_blueprint(career_system_bp)
        app.view_functions["career_system.verify_subscription_checkout"] = career_pro_runtime_patch._verify_subscription_checkout
        app.config["TESTING"] = True
        client = app.test_client()
        response = client.get(
            "/api/career/subscription-checkout/cks_test_paid",
            headers={"Authorization": "Bearer test"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["paid"])
        self.assertFalse(body["credits_granted"])
        rpc.assert_not_called()
        saved = upsert.call_args.kwargs
        self.assertEqual(saved["current_period_end"], "2027-09-14T00:00:00Z")
        self.assertEqual(saved["dodo_customer_id"], "cus_test_123")

    @patch("career_pro_runtime_patch._career_status")
    def test_expired_or_inactive_entitlement_is_not_treated_as_pro(self, career_status):
        career_status.return_value = {"active": False}
        self.assertFalse(career_pro_runtime_patch._active_career_pro("user-expired"))
        career_status.assert_called_once_with("user-expired")


if __name__ == "__main__":
    unittest.main()
