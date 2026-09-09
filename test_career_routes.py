import io
import os
import unittest
from unittest.mock import patch

from flask import Flask

from career_routes import DODO_PRODUCT_ID, career_bp


RESUME = """Jane Doe
Email: jane@example.com
Phone: +971 50 123 4567
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

PAID_CHECKOUT = {
    "payment_status": "succeeded",
    "metadata": {"product": "career_pro"},
}

OPTIMIZATION = {
    "mode": "ai",
    "rewrite_applied": True,
    "change_ratio": 24,
    "current_match": 70,
    "optimized_match": 82,
    "optimized_summary": "Data analyst with experience using SQL, Excel and Power BI to improve reporting.",
    "optimized_bullets": ["Analyzed customer data and improved reporting time by 35%."],
    "skills_to_highlight": ["SQL", "Excel", "Power BI", "Communication"],
    "keywords_to_review": ["Tableau"],
    "optimized_resume": RESUME.replace(
        "Data analyst experienced in SQL, Excel and Power BI.",
        "Data analyst with experience using SQL, Excel and Power BI to improve reporting.",
    ),
    "changes": ["Rewrote the professional summary for the target data analyst role."],
    "integrity_note": "AI rewrite applied. Review every line before use.",
}

AI_COVER_LETTER = {
    "cover_letter": "Dear Example Labs,\n\nI am applying for the Data Analyst role. My experience using SQL, Excel and Power BI includes analyzing customer data and improving reporting time by 35%. This background aligns with the analytical and reporting priorities in your job description.\n\nI would welcome the opportunity to discuss how my data analysis and communication experience could support Example Labs.\n\nSincerely,\nJane Doe",
    "subject_line": "Application for Data Analyst — Jane Doe",
    "strengths_used": ["SQL", "Excel", "Power BI", "35% reporting improvement"],
    "unsupported_requirements": ["Tableau"],
    "mode": "ai",
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "tone": "professional",
    "integrity_note": "AI-generated from the resume and job description. Review every claim before sending.",
}


class CareerRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(career_bp)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_health(self):
        r = self.client.get("/api/career/health")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("ai-cover-letter", body["features"])
        self.assertIn("ai_cover_letter_configured", body)

    def test_json_ats_analysis(self):
        r = self.client.post(
            "/api/career/ats/analyze",
            json={"resume_text": RESUME, "job_description": JOB},
        )
        b = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b["success"])
        self.assertIn("score", b["analysis"])
        self.assertIn("tableau", b["analysis"]["keyword_analysis"]["missing"])

    def test_txt_upload(self):
        r = self.client.post(
            "/api/career/ats/analyze",
            data={"resume": (io.BytesIO(RESUME.encode()), "resume.txt"), "job_description": JOB},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])

    def test_rejects_unsupported_upload(self):
        r = self.client.post(
            "/api/career/ats/analyze",
            data={"resume": (io.BytesIO(b"hello"), "resume.exe"), "job_description": JOB},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 400)

    def test_job_match_requires_job_description(self):
        r = self.client.post("/api/career/job-match", json={"resume_text": RESUME})
        self.assertEqual(r.status_code, 400)

    @patch("career_routes._dodo")
    def test_checkout_uses_career_pro_product(self, dodo):
        dodo.return_value = {
            "checkout_url": "https://checkout.example/session",
            "session_id": "cks_test_123",
        }
        r = self.client.post("/api/career/checkout")
        b = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b["success"])
        args, kwargs = dodo.call_args
        self.assertEqual(args[:2], ("POST", "/checkouts"))
        self.assertEqual(
            kwargs["json"]["product_cart"],
            [{"product_id": DODO_PRODUCT_ID, "quantity": 1}],
        )
        self.assertNotIn("authorization", str(b).lower())

    @patch("career_routes._dodo")
    def test_checkout_fails_safely_when_dodo_fails(self, dodo):
        dodo.side_effect = RuntimeError("Payment service is temporarily unavailable.")
        r = self.client.post("/api/career/checkout")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn(
            os.getenv("DODO_PAYMENTS_API_KEY", "never-expose-this"),
            str(r.get_json()),
        )

    @patch("career_routes._dodo")
    def test_unpaid_checkout_does_not_unlock_pro(self, dodo):
        dodo.return_value = {
            "payment_status": "pending",
            "metadata": {"product": "career_pro"},
        }
        b = self.client.get("/api/career/checkout/cks_test_123").get_json()
        self.assertFalse(b["paid"])
        self.assertIsNone(b["feature_id"])

    @patch("career_routes._dodo")
    def test_successful_verified_checkout_unlocks_career_pro(self, dodo):
        dodo.return_value = PAID_CHECKOUT
        b = self.client.get("/api/career/checkout/cks_test_123").get_json()
        self.assertTrue(b["paid"])
        self.assertEqual(b["feature_id"], "career_pro")

    @patch("career_routes._dodo")
    def test_wrong_product_metadata_does_not_unlock_pro(self, dodo):
        dodo.return_value = {
            "payment_status": "succeeded",
            "metadata": {"product": "something_else"},
        }
        b = self.client.get("/api/career/checkout/cks_test_123").get_json()
        self.assertFalse(b["paid"])

    def test_invalid_checkout_session_is_rejected(self):
        self.assertEqual(
            self.client.get("/api/career/checkout/not%20valid!").status_code,
            400,
        )

    @patch("career_routes.optimize_with_gemini", return_value=OPTIMIZATION)
    @patch("career_routes._dodo")
    def test_paid_user_can_optimize_resume(self, dodo, optimizer):
        dodo.return_value = PAID_CHECKOUT
        r = self.client.post(
            "/api/career/pro/optimize",
            json={
                "session_id": "cks_test_123",
                "resume_text": RESUME,
                "job_description": JOB,
            },
        )
        b = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b["success"])
        self.assertTrue(b["optimization"]["rewrite_applied"])
        self.assertNotEqual(b["optimization"]["optimized_resume"], RESUME)
        optimizer.assert_called_once_with(RESUME.strip(), JOB.strip())

    @patch("career_routes._dodo")
    def test_unpaid_user_cannot_optimize_resume(self, dodo):
        dodo.return_value = {
            "payment_status": "pending",
            "metadata": {"product": "career_pro"},
        }
        r = self.client.post(
            "/api/career/pro/optimize",
            json={
                "session_id": "cks_test_123",
                "resume_text": RESUME,
                "job_description": JOB,
            },
        )
        self.assertEqual(r.status_code, 403)

    @patch("career_routes._dodo")
    def test_paid_user_can_extract_txt_resume(self, dodo):
        dodo.return_value = PAID_CHECKOUT
        r = self.client.post(
            "/api/career/pro/extract-resume",
            data={
                "session_id": "cks_test_123",
                "resume": (io.BytesIO(RESUME.encode()), "resume.txt"),
            },
            content_type="multipart/form-data",
        )
        b = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b["success"])
        self.assertIn("Data analyst", b["resume_text"])

    @patch("career_routes.generate_cover_letter_with_gemini", return_value=AI_COVER_LETTER)
    @patch("career_routes._dodo")
    def test_paid_user_can_generate_ai_cover_letter(self, dodo, generator):
        dodo.return_value = PAID_CHECKOUT
        r = self.client.post(
            "/api/career/pro/cover-letter",
            json={
                "session_id": "cks_test_123",
                "resume_text": RESUME,
                "job_description": JOB,
                "applicant_name": "Jane Doe",
                "company": "Example Labs",
                "role": "Data Analyst",
                "tone": "professional",
            },
        )
        b = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b["success"])
        self.assertEqual(b["mode"], "ai")
        self.assertEqual(b["provider"], "gemini")
        self.assertIn("Example Labs", b["cover_letter"])
        self.assertIn("Tableau", b["unsupported_requirements"])
        generator.assert_called_once_with(
            RESUME.strip(), JOB.strip(), "Jane Doe", "Example Labs", "Data Analyst", "professional"
        )

    @patch("career_routes.generate_cover_letter_with_gemini")
    @patch("career_routes._dodo")
    def test_invalid_cover_letter_tone_is_rejected(self, dodo, generator):
        dodo.return_value = PAID_CHECKOUT
        generator.side_effect = ValueError("Tone must be professional, confident, or concise.")
        r = self.client.post(
            "/api/career/pro/cover-letter",
            json={
                "session_id": "cks_test_123",
                "resume_text": RESUME,
                "job_description": JOB,
                "tone": "salesy",
            },
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("Tone", r.get_json()["error"])

    @patch("career_routes._dodo")
    def test_unpaid_user_cannot_generate_cover_letter(self, dodo):
        dodo.return_value = {
            "payment_status": "failed",
            "metadata": {"product": "career_pro"},
        }
        r = self.client.post(
            "/api/career/pro/cover-letter",
            json={
                "session_id": "cks_test_123",
                "resume_text": RESUME,
                "job_description": JOB,
            },
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
