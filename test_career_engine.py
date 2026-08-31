import unittest

from career_engine import analyze_resume, extract_skills


SAMPLE_RESUME = """
AHMAD KHAN
Email: ahmad@example.com | Phone: +971500000000 | LinkedIn: linkedin.com/in/ahmad

PROFESSIONAL SUMMARY
Digital marketing specialist with experience in SEO, Google Ads and content marketing.

EXPERIENCE
Marketing Specialist | Example LLC | 2024 - Present
- Increased organic traffic by 45% through SEO improvements.
- Managed Google Ads campaigns for 12 clients.
- Created content strategy and improved lead generation by 20%.

EDUCATION
Bachelor of Business Administration

SKILLS
SEO, Google Ads, Canva, Excel, Communication
"""

SAMPLE_JOB = """
We are hiring a Digital Marketing Specialist with SEO, Google Ads, social media,
content marketing, analytics, communication and lead generation experience.
"""


class CareerEngineTests(unittest.TestCase):
    def test_analysis_is_explainable_and_bounded(self):
        result = analyze_resume(SAMPLE_RESUME, SAMPLE_JOB)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertTrue(result["checks"])
        self.assertIn("keyword_analysis", result)
        self.assertIn("recommendations", result)

    def test_relevant_skills_are_detected(self):
        skills = extract_skills(SAMPLE_RESUME)
        self.assertIn("seo", skills)
        self.assertIn("google ads", skills)
        self.assertIn("canva", skills)
        self.assertIn("excel", skills)

    def test_job_match_finds_missing_terms(self):
        result = analyze_resume(SAMPLE_RESUME, SAMPLE_JOB)
        analysis = result["keyword_analysis"]
        self.assertGreater(analysis["match_percentage"], 0)
        self.assertTrue("social" in analysis["missing"] or "media" in analysis["missing"])


if __name__ == "__main__":
    unittest.main()
