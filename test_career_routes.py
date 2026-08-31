import io
import unittest

from flask import Flask

from career_routes import career_bp


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


if __name__ == "__main__":
    unittest.main()
