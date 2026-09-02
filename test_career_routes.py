import io
import os
import unittest
from unittest.mock import patch

from flask import Flask

from career_routes import career_bp, DODO_PRODUCT_ID


RESUME = """Jane Doe
Email: jane@example.com
Phone: +971 50 123 4567
LinkedIn: linkedin.com/in/janedoe

Professional Summary
Data analyst experienced in SQL, Excel and Power BI.

Experience
Data Analyst | Example Co | 2023 - Present
- Analyzed customer data and improved reporting time by 35%.

Education
Bachelor of Science

Skills
SQL, Excel, Power BI, Communication
"""

JOB = "We are seeking a data analyst with SQL, Excel, Power BI, Tableau and communication skills."


class CareerRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(career_bp)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_health(self):
        response = self.client.get("/api/career/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_json_ats_analysis(self):
        response = self.client.post("/api/career/ats/analyze", json={
            "resume_text": RESUME,
            "job_description": JOB,
        })
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["success"])
        self.assertIn("score", body["analysis"])
        self.assertIn("tableau", body["analysis"]["keyword_analysis"]["missing"])

    def test_txt_upload(self):
        response = self.client.post(
            "/api/career/ats/analyze",
            data={
                "resume": (io.BytesIO(RESUME.encode("utf-8")), "resume.txt"),
                "job_description": JOB,
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

    def test_rejects_unsupported_upload(self):
        response = self.client.post(
            "/api/career/ats/analyze",
            data={
                "resume": (io.BytesIO(b"hello"), "resume.docx"),
                "job_description": JOB,
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])

    def test_job_match_requires_job_description(self):
        response = self.client.post("/api/career/job-match", json={"resume_text": RESUME})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])

    @patch("career_routes._dodo_request")
    def test_checkout_uses_career_pro_product(self, dodo_request):
        dodo_request.return_value = {
            "checkout_url": "https://checkout.example/session",
            "session_id": "cks_test_123",
        }
        response = self.client.post("/api/career/checkout")
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["success"])
        args, kwargs = dodo_request.call_args
        self.assertEqual(args[:2], ("POST", "/checkouts"))
        cart = kwargs["json"]["product_cart"]
        self.assertEqual(cart, [{"product_id": DODO_PRODUCT_ID, "quantity": 1}])
        self.assertNotIn("api_key", str(body).lower())
        self.assertNotIn("authorization", str(body).lower())

    @patch("career_routes._dodo_request")
    def test_checkout_fails_safely_when_dodo_fails(self, dodo_request):
        dodo_request.side_effect = RuntimeError("Payment service is temporarily unavailable.")
        response = self.client.post("/api/career/checkout")
        body = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(body["success"])
        self.assertNotIn(os.getenv("DODO_PAYMENTS_API_KEY", "never-expose-this"), str(body))

    @patch("career_routes._dodo_request")
    def test_unpaid_checkout_does_not_unlock_pro(self, dodo_request):
        dodo_request.return_value = {
            "payment_status": "pending",
            "metadata": {"product": "career_pro"},
        }
        response = self.client.get("/api/career/checkout/cks_test_123")
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(body["paid"])
        self.assertIsNone(body["feature_id"])

    @patch("career_routes._dodo_request")
    def test_successful_verified_checkout_unlocks_career_pro(self, dodo_request):
        dodo_request.return_value = {
            "payment_status": "succeeded",
            "metadata": {"product": "career_pro"},
        }
        response = self.client.get("/api/career/checkout/cks_test_123")
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["paid"])
        self.assertEqual(body["feature_id"], "career_pro")

    @patch("career_routes._dodo_request")
    def test_wrong_product_metadata_does_not_unlock_pro(self, dodo_request):
        dodo_request.return_value = {
            "payment_status": "succeeded",
            "metadata": {"product": "something_else"},
        }
        response = self.client.get("/api/career/checkout/cks_test_123")
        body = response.get_json()
        self.assertFalse(body["paid"])
        self.assertIsNone(body["feature_id"])

    def test_invalid_checkout_session_is_rejected(self):
        response = self.client.get("/api/career/checkout/not%20valid!")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
