import io
import unittest
import zipfile
from unittest.mock import patch

from flask import Flask

from career_export import build_resume_export, export_docx, export_pdf
from career_routes import career_bp


RESUME = """Jane Doe
jane@example.com | +971 50 123 4567

PROFESSIONAL SUMMARY
Data analyst experienced in SQL, Excel and Power BI.

EXPERIENCE
Data Analyst | Example Co | 2023 - Present
- Analyzed customer data and improved reporting time by 35%.
- Built recurring Excel and Power BI reports for stakeholders.

EDUCATION
Bachelor of Science

SKILLS
SQL, Excel, Power BI, Communication
"""

PAID_CHECKOUT = {
    "payment_status": "succeeded",
    "metadata": {"product": "career_pro"},
}


class CareerExportTests(unittest.TestCase):
    def test_docx_export_is_valid_office_document(self):
        data = export_docx(RESUME)
        self.assertTrue(data.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            self.assertIn("word/document.xml", names)
            xml = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("Jane Doe", xml)
            self.assertIn("35%", xml)

    def test_pdf_export_is_valid_pdf(self):
        data = export_pdf(RESUME)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 1000)

    def test_build_resume_export_returns_expected_metadata(self):
        data, mime, name = build_resume_export(RESUME, "docx")
        self.assertTrue(data)
        self.assertEqual(mime, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(name, "EggyPDF-Optimized-Resume.docx")

        data, mime, name = build_resume_export(RESUME, "pdf")
        self.assertTrue(data)
        self.assertEqual(mime, "application/pdf")
        self.assertEqual(name, "EggyPDF-Optimized-Resume.pdf")

    def test_invalid_format_is_rejected(self):
        with self.assertRaises(ValueError):
            build_resume_export(RESUME, "rtf")


class CareerExportRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(career_bp)
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("career_routes._dodo")
    def test_paid_user_can_export_docx(self, dodo):
        dodo.return_value = PAID_CHECKOUT
        r = self.client.post(
            "/api/career/pro/export-resume",
            json={
                "session_id": "cks_test_123",
                "resume_text": RESUME,
                "format": "docx",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.mimetype,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertTrue(r.data.startswith(b"PK"))
        self.assertIn("EggyPDF-Optimized-Resume.docx", r.headers.get("Content-Disposition", ""))

    @patch("career_routes._dodo")
    def test_paid_user_can_export_pdf(self, dodo):
        dodo.return_value = PAID_CHECKOUT
        r = self.client.post(
            "/api/career/pro/export-resume",
            json={
                "session_id": "cks_test_123",
                "resume_text": RESUME,
                "format": "pdf",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF"))

    @patch("career_routes._dodo")
    def test_unpaid_user_cannot_export_resume(self, dodo):
        dodo.return_value = {
            "payment_status": "pending",
            "metadata": {"product": "career_pro"},
        }
        r = self.client.post(
            "/api/career/pro/export-resume",
            json={
                "session_id": "cks_test_123",
                "resume_text": RESUME,
                "format": "pdf",
            },
        )
        self.assertEqual(r.status_code, 403)

    @patch("career_routes._dodo")
    def test_invalid_export_format_is_rejected(self, dodo):
        dodo.return_value = PAID_CHECKOUT
        r = self.client.post(
            "/api/career/pro/export-resume",
            json={
                "session_id": "cks_test_123",
                "resume_text": RESUME,
                "format": "rtf",
            },
        )
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
