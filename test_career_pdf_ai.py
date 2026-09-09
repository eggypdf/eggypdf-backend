import io
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from reportlab.pdfgen import canvas
from werkzeug.datastructures import FileStorage

import career_pdf_ai
from career_routes import career_bp


class PdfSummarizerUnitTests(unittest.TestCase):
    def _pdf(self, text="Quarterly report. Revenue increased by 12%. Action: submit the final report by Friday."):
        buff = io.BytesIO()
        c = canvas.Canvas(buff)
        c.drawString(72, 750, text)
        c.save()
        buff.seek(0)
        return FileStorage(stream=buff, filename="report.pdf", content_type="application/pdf")

    def test_extracts_text_from_pdf_in_memory(self):
        result = career_pdf_ai.extract_pdf_text(self._pdf())
        self.assertEqual(result["page_count"], 1)
        self.assertIn("Revenue increased by 12%", result["text"])
        self.assertGreater(result["characters"], 80)

    def test_rejects_non_pdf_extension(self):
        f = FileStorage(stream=io.BytesIO(b"hello"), filename="notes.txt", content_type="text/plain")
        with self.assertRaises(ValueError):
            career_pdf_ai.extract_pdf_text(f)

    @patch.dict("os.environ", {"GEMINI_API": "test-key"}, clear=False)
    @patch("career_pdf_ai.requests.post")
    def test_short_summary_returns_structured_result(self, post):
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"title":"Quarterly Report","overview":"This quarterly report explains that revenue increased by 12% and requires the final report to be submitted by Friday. It presents a concise status update and a clear next action for the reader.","key_points":["Revenue increased by 12%.","The final report is due Friday."],"action_items":["Submit the final report by Friday."],"important_details":["Revenue increase: 12%","Deadline: Friday"]}'}]}}]
        }
        post.return_value = response
        result = career_pdf_ai.summarize_pdf_text("Quarterly report text. " * 10, "short")
        self.assertEqual(result["title"], "Quarterly Report")
        self.assertEqual(result["detail"], "short")
        self.assertEqual(result["provider"], "gemini")
        self.assertIn("12%", result["key_points"][0])


class PdfSummarizerRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(career_bp)
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("career_routes.summarize_pdf_text")
    @patch("career_routes.extract_pdf_text")
    @patch("career_routes._dodo")
    def test_paid_user_can_summarize_pdf(self, dodo, extract, summarize):
        dodo.return_value = {"payment_status": "succeeded", "metadata": {"product": "career_pro"}}
        extract.return_value = {"text": "Document text " * 20, "page_count": 2, "characters": 280, "filename": "doc.pdf"}
        summarize.return_value = {
            "title": "Document Summary",
            "overview": "A sufficiently complete overview of the uploaded document for testing the paid Career Pro PDF summarizer endpoint.",
            "key_points": ["Point one"],
            "action_items": [],
            "important_details": [],
            "detail": "short",
            "mode": "ai",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "integrity_note": "Review it.",
        }
        data = {"session_id": "cks_test_123", "detail": "short", "pdf": (io.BytesIO(b"%PDF-test"), "doc.pdf")}
        r = self.client.post("/api/career/pro/pdf-summary", data=data, content_type="multipart/form-data")
        body = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["document"]["page_count"], 2)
        self.assertEqual(body["summary"]["title"], "Document Summary")

    @patch("career_routes._dodo")
    def test_unpaid_user_cannot_summarize_pdf(self, dodo):
        dodo.return_value = {"payment_status": "pending", "metadata": {"product": "career_pro"}}
        data = {"session_id": "cks_test_123", "detail": "short", "pdf": (io.BytesIO(b"%PDF-test"), "doc.pdf")}
        r = self.client.post("/api/career/pro/pdf-summary", data=data, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
