import unittest
from unittest.mock import patch

from flask import Flask

import career_regen
from career_routes import career_bp


SOURCE = """Jane Doe
Professional Summary
Data analyst experienced in SQL and Excel.
Experience
Data Analyst | Example Co | 2023 - Present
- Analyzed customer data for recurring reports.
- Improved reporting time by 35%.
Education
Bachelor of Science
Skills
SQL, Excel
"""

OPTIMIZED = """Jane Doe
Professional Summary
Data analyst with SQL and Excel experience supporting recurring reporting.
Experience
Data Analyst | Example Co | 2023 - Present
- Analyzed customer data to support recurring business reports.
- Improved reporting time by 35% through more efficient reporting workflows.
Education
Bachelor of Science
Skills
SQL, Excel
"""

JOB = "We need a data analyst with SQL, Excel, reporting and customer data analysis skills."

PAID_CHECKOUT = {"payment_status": "succeeded", "metadata": {"product": "career_pro"}}


class SectionRegenerationUnitTests(unittest.TestCase):
    @patch.dict("os.environ", {"GEMINI_API": "test-key"}, clear=False)
    @patch("career_regen._call_gemini")
    def test_regenerates_summary_and_applies_to_resume(self, gemini):
        current = "Data analyst with SQL and Excel experience supporting recurring reporting."
        gemini.return_value = (
            "Data analyst using SQL and Excel to support accurate, recurring business reporting.",
            "Made the summary more specific to the target reporting role.",
        )
        result = career_regen.regenerate_section(SOURCE, OPTIMIZED, JOB, "summary", current)
        self.assertEqual(result["section_type"], "summary")
        self.assertIn("accurate, recurring business reporting", result["regenerated_text"])
        self.assertIn(result["regenerated_text"], result["updated_resume"])
        self.assertNotIn(current, result["updated_resume"])
        self.assertGreater(result["change_ratio"], 0)

    @patch.dict("os.environ", {"GEMINI_API": "test-key"}, clear=False)
    @patch("career_regen._call_gemini")
    def test_regenerates_single_bullet_and_preserves_metric(self, gemini):
        current = "Improved reporting time by 35% through more efficient reporting workflows."
        gemini.return_value = (
            "Reduced reporting turnaround time by 35% by streamlining recurring reporting workflows.",
            "Used stronger action-oriented phrasing while preserving the 35% result.",
        )
        result = career_regen.regenerate_section(SOURCE, OPTIMIZED, JOB, "bullet", current)
        self.assertIn("35%", result["regenerated_text"])
        self.assertIn(result["regenerated_text"], result["updated_resume"])

    def test_invalid_section_type_is_rejected(self):
        with self.assertRaises(ValueError):
            career_regen.regenerate_section(SOURCE, OPTIMIZED, JOB, "skills", "SQL, Excel")


class SectionRegenerationRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(career_bp)
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("career_routes.regenerate_section")
    @patch("career_routes._dodo")
    def test_paid_user_can_regenerate_section(self, dodo, regen):
        dodo.return_value = PAID_CHECKOUT
        regen.return_value = {
            "section_type": "summary",
            "original_text": "old",
            "regenerated_text": "new",
            "updated_resume": OPTIMIZED,
            "change_ratio": 30,
            "reason": "Improved clarity.",
            "mode": "ai",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "integrity_note": "Review it.",
        }
        r = self.client.post(
            "/api/career/pro/regenerate-section",
            json={
                "session_id": "cks_test_123",
                "source_resume": SOURCE,
                "optimized_resume": OPTIMIZED,
                "job_description": JOB,
                "section_type": "summary",
                "current_text": "Data analyst with SQL and Excel experience supporting recurring reporting.",
            },
        )
        body = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["regeneration"]["regenerated_text"], "new")

    @patch("career_routes._dodo")
    def test_unpaid_user_cannot_regenerate_section(self, dodo):
        dodo.return_value = {"payment_status": "pending", "metadata": {"product": "career_pro"}}
        r = self.client.post(
            "/api/career/pro/regenerate-section",
            json={
                "session_id": "cks_test_123",
                "source_resume": SOURCE,
                "optimized_resume": OPTIMIZED,
                "job_description": JOB,
                "section_type": "summary",
                "current_text": "Data analyst with SQL and Excel experience supporting recurring reporting.",
            },
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
