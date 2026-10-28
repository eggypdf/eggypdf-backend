import io
import os
import tempfile
import unittest
from unittest import mock

from PIL import Image
from reportlab.pdfgen import canvas

import app as app_module


class CorePdfToolRegressionTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _pdf_bytes(self):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(300, 400))
        c.drawString(40, 340, "EggyPDF regression test")
        c.rect(40, 250, 180, 50)
        c.save()
        buf.seek(0)
        return buf.getvalue()

    def test_compress_all_levels_return_valid_pdf_when_ghostscript_times_out(self):
        # Compression must complete safely even if Ghostscript is too slow.
        from pypdf import PdfReader
        original = self._pdf_bytes()

        for level in ("low", "medium", "high"):
            with self.subTest(level=level):
                with mock.patch.object(
                    app_module.subprocess, "run",
                    side_effect=app_module.subprocess.TimeoutExpired(cmd="gs", timeout=40),
                ) as runner:
                    response = self.client.post(
                        "/api/compress",
                        data={"file": (io.BytesIO(original), "sample.pdf"), "level": level},
                        content_type="multipart/form-data",
                    )
                self.assertEqual(response.status_code, 200, response.data[:200])
                self.assertEqual(response.mimetype, "application/pdf")
                self.assertEqual(len(PdfReader(io.BytesIO(response.data)).pages), 1)
                self.assertEqual(runner.call_count, 1)
                self.assertEqual(runner.call_args.kwargs["timeout"], 40)

    def test_compress_does_not_return_broken_ghostscript_output(self):
        from pypdf import PdfReader
        original = self._pdf_bytes()

        def invalid_ghostscript_output(cmd, **kwargs):
            out_arg = next(x for x in cmd if x.startswith("-sOutputFile="))
            with open(out_arg.split("=", 1)[1], "wb") as fh:
                fh.write(b"%PDF-invalid")
            return mock.Mock(returncode=0)

        with mock.patch.object(app_module.subprocess, "run", side_effect=invalid_ghostscript_output):
            response = self.client.post(
                "/api/compress",
                data={"file": (io.BytesIO(original), "sample.pdf"), "level": "medium"},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200, response.data[:200])
        self.assertEqual(len(PdfReader(io.BytesIO(response.data)).pages), 1)

    def test_compress_invalid_level_rejected(self):
        response = self.client.post(
            "/api/compress",
            data={"file": (io.BytesIO(self._pdf_bytes()), "sample.pdf"), "level": "ultra"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_split_page_range_returns_valid_zip(self):
        from pypdf import PdfReader
        import zipfile

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(300, 400))
        for page in range(12):
            c.drawString(40, 340, f"Page {page+1}")
            c.showPage()
        c.save()
        response = self.client.post(
            "/api/split",
            data={"file": (io.BytesIO(buf.getvalue()), "sample.pdf"), "type": "range", "range": "3-6"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.data[:200])
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.namelist(), ["split_pages.pdf"])
            pages = PdfReader(io.BytesIO(archive.read("split_pages.pdf"))).pages
            self.assertEqual(len(pages), 4)

    def test_pdf_to_word_layout_mode_creates_docx(self):
        pdf_bytes = self._pdf_bytes()

        def fake_run(cmd, **kwargs):
            # Layout mode calls pdftoppm with a final output prefix.
            prefix = cmd[-1]
            image_path = prefix + "-1.jpg"
            Image.new("RGB", (600, 800), "white").save(image_path, "JPEG")
            return mock.Mock(returncode=0)

        with mock.patch.object(app_module.subprocess, "run", side_effect=fake_run):
            response = self.client.post(
                "/api/pdf-to-word",
                data={"file": (io.BytesIO(pdf_bytes), "sample.pdf"), "mode": "layout"},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"PK"))
        self.assertEqual(
            response.mimetype,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_pdf_to_word_rejects_unknown_mode(self):
        response = self.client.post(
            "/api/pdf-to-word",
            data={"file": (io.BytesIO(self._pdf_bytes()), "sample.pdf"), "mode": "unknown"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_limit_returns_json(self):
        app_module.app.config["MAX_CONTENT_LENGTH"] = 16
        try:
            response = self.client.post(
                "/api/pdf-to-word",
                data={"file": (io.BytesIO(b"x" * 128), "large.pdf")},
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 413)
            self.assertIn("Maximum upload size", response.get_json()["error"])
        finally:
            app_module.app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


if __name__ == "__main__":
    unittest.main()
