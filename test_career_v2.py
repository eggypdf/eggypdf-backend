import unittest
from unittest.mock import patch

import career_v2


RESUME = """Jane Doe
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

JOB = "We need a data analyst with SQL, Excel, reporting, customer data analysis and communication skills."

REWRITE = {
    "optimized_summary": "Data analyst with SQL and Excel experience supporting customer-data reporting.",
    "optimized_bullets": [
        "Analyzed customer data to support recurring business reports.",
        "Improved reporting time by 35% through more efficient reporting workflows.",
    ],
    "skills_to_highlight": ["SQL", "Excel"],
    "keywords_to_review": ["communication"],
    "optimized_resume": """Jane Doe
Professional Summary
Data analyst with SQL and Excel experience supporting customer-data reporting.
Experience
Data Analyst | Example Co | 2023 - Present
- Analyzed customer data to support recurring business reports.
- Improved reporting time by 35% through more efficient reporting workflows.
Education
Bachelor of Science
Skills
SQL, Excel
""",
    "changes": [
        "Made the professional summary more specific to the target role.",
        "Rewrote experience bullets with clearer action-oriented phrasing.",
    ],
}


class CareerV2ComparisonTests(unittest.TestCase):
    @patch.dict("os.environ", {"GEMINI_API": "test-key"}, clear=False)
    @patch("career_v2._gemini_request", return_value=REWRITE.copy())
    def test_optimizer_returns_structured_before_after_comparison(self, gemini):
        result = career_v2.optimize_with_gemini(RESUME, JOB)
        comparison = result["comparison"]

        self.assertEqual(
            comparison["summary"]["before"],
            "Data analyst experienced in SQL and Excel.",
        )
        self.assertIn("customer-data reporting", comparison["summary"]["after"])
        self.assertEqual(len(comparison["bullets"]), 2)
        self.assertEqual(
            comparison["bullets"][0]["before"],
            "Analyzed customer data for recurring reports.",
        )
        self.assertIn("support recurring business reports", comparison["bullets"][0]["after"])
        self.assertEqual(comparison["score"]["before"], result["current_resume_score"])
        self.assertEqual(comparison["score"]["after"], result["optimized_resume_score"])
        self.assertEqual(
            comparison["keyword_match"]["before"], result["current_keyword_match"]
        )
        self.assertEqual(
            comparison["keyword_match"]["after"], result["optimized_keyword_match"]
        )
        self.assertGreater(comparison["change_ratio"], 0)
        self.assertTrue(comparison["changes"])
        self.assertTrue(result["rewrite_applied"])
        gemini.assert_called_once()


if __name__ == "__main__":
    unittest.main()
