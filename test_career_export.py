import io
import unittest
import zipfile

from career_export import build_resume_export, export_docx, export_pdf


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


if __name__ == "__main__":
    unittest.main()
