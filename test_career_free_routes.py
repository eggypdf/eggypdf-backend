import io
import unittest
from unittest.mock import patch

from flask import Flask

from career_free_routes import career_free_bp


class CareerFreeRoutesTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(career_free_bp)
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("career_free_routes.extract_resume_upload")
    def test_extract_resume_is_free_and_returns_text(self, extract):
        extract.return_value = "Experienced operations coordinator with scheduling and reporting experience."
        response = self.client.post(
            "/api/career/ats/extract-resume",
            data={"resume": (io.BytesIO(b"fake resume"), "candidate.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["success"])
        self.assertTrue(body["free_preview"])
        self.assertIn("operations coordinator", body["resume_text"])

    def test_extract_resume_requires_file(self):
        response = self.client.post("/api/career/ats/extract-resume")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])

    @patch("career_free_routes.extract_resume_upload")
    def test_extract_resume_returns_readable_validation_error(self, extract):
        extract.side_effect = ValueError("We couldn't extract enough readable text.")
        response = self.client.post(
            "/api/career/ats/extract-resume",
            data={"resume": (io.BytesIO(b"scan"), "scan.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("readable text", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
