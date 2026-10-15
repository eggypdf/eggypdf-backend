import io
import os
import shutil
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

    def test_compress_all_three_levels_can_reduce(self):
        original = self._pdf_bytes()

        for level in ("low", "medium", "high"):
            def fake_run(cmd, **kwargs):
                out_arg = next(x for x in cmd if x.startswith("-sOutputFile="))
                out_path = out_arg.split("=", 1)[1]
                with open(out_path, "wb") as fh:
                    fh.write(original[: max(100, len(original) // 2)])
                return mock.Mock(returncode=0)

            with self.subTest(level=level):
                with mock.patch.object(app_module.subprocess, "run", side_effect=fake_run):
                    response = self.client.post(
                        "/api/compress",
                        data={"file": (io.BytesIO(original), "sample.pdf"), "level": level},
                        content_type="multipart/form-data",
                    )
                self.assertEqual(response.status_code, 200)
                self.assertLess(len(response.data), len(original))

    def test_compress_accepts_small_real_saving(self):
        original = self._pdf_bytes()
        target_size = max(100, len(original) - 1)

        def fake_run(cmd, **kwargs):
            out_arg = next(x for x in cmd if x.startswith("-sOutputFile="))
            out_path = out_arg.split("=", 1)[1]
            with open(out_path, "wb") as fh:
                fh.write(original[:target_size])
            return mock.Mock(returncode=0)

        with mock.patch.object(app_module.subprocess, "run", side_effect=fake_run):
            response = self.client.post(
                "/api/compress",
                data={"file": (io.BytesIO(original), "sample.pdf"), "level": "low"},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        self.assertLess(len(response.data), len(original))

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


def _photo_like(width, height):
    """Photo-like test image (smooth gradients + noise) built with Pillow only."""
    from PIL import ImageChops
    base = Image.linear_gradient("L").resize((width, height))
    channels = []
    for shift in (0, 60, 120):
        noise = Image.effect_noise((width, height), 40)
        channels.append(ImageChops.add(base.rotate(shift % 90), noise, scale=2))
    return Image.merge("RGB", channels)


def _image_pdf(pages, px_w, px_h, jpeg_quality):
    """A4 PDF with one full-width JPEG per page. dpi ~= px_w / 7.27in."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    from reportlab.lib.utils import ImageReader
    for _ in range(pages):
        img_buf = io.BytesIO()
        _photo_like(px_w, px_h).save(img_buf, "JPEG", quality=jpeg_quality)
        img_buf.seek(0)
        c.drawImage(ImageReader(img_buf), 30, 120, 535, 700)
        c.showPage()
    c.save()
    return buf.getvalue()


@unittest.skipUnless(shutil.which("gs"), "Ghostscript is required for real compression tests")
class RealCompressionTests(unittest.TestCase):
    """Runs the real Ghostscript pipeline (no mocks).

    Regression guard for: Low compression returning 2 MB as 1.95 MB because
    images already at or below the target DPI were passed through untouched.
    """

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _compress(self, data, level):
        response = self.client.post(
            "/api/compress",
            data={"file": (io.BytesIO(data), "in.pdf"), "level": level},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))
        return response.data

    def test_low_level_compresses_images_already_below_target_dpi(self):
        # ~110 dpi at JPEG quality 92: below every Low-level DPI step, so only
        # real JPEG recompression can shrink it. (The old pass-through code
        # saved ~20% here; the fixed ladder saves ~50%.)
        original = _image_pdf(pages=3, px_w=800, px_h=1000, jpeg_quality=92)
        result = self._compress(original, "low")
        saving = 1 - len(result) / len(original)
        self.assertGreaterEqual(saving, 0.35, f"Low level only saved {saving:.1%}")

    def test_levels_are_ordered_and_never_larger_than_original(self):
        original = _image_pdf(pages=3, px_w=1400, px_h=1800, jpeg_quality=90)
        sizes = {lvl: len(self._compress(original, lvl)) for lvl in ("low", "medium", "high")}
        for lvl, size in sizes.items():
            self.assertLessEqual(size, len(original), lvl)
        self.assertGreaterEqual(sizes["low"], sizes["medium"])
        self.assertGreaterEqual(sizes["medium"], sizes["high"])
        self.assertLess(sizes["high"], len(original) * 0.5)

    def test_unshrinkable_pdf_is_returned_valid_and_not_larger(self):
        original = CorePdfToolRegressionTests._pdf_bytes(None)
        for lvl in ("low", "medium", "high"):
            result = self._compress(original, lvl)
            self.assertLessEqual(len(result), len(original))


if __name__ == "__main__":
    unittest.main()
