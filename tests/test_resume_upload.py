import ast
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

from modules.resume_upload import ResumeUploadError, upload_verified_resume, verify_source_resume


class VerifiedResumeUploadTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "resume.docx"
        self.source.write_bytes(b"source docx")
        self.pdf = self.source.with_suffix(".pdf")
        self.pdf.write_bytes(b"source pdf")
        self.optimized = Path(self.directory.name) / "optimized.pdf"
        self.optimized.write_bytes(b"verified output pdf")
        self.file_input = Mock()
        self.modal = Mock()
        self.modal.find_element.return_value = self.file_input
        self.verify = Mock(return_value=True)

    def upload(self, optimize):
        return upload_verified_resume(
            self.modal, str(self.source), "JD", "123", "Staff Engineer",
            optimize=optimize, verify_source=self.verify,
        )

    def test_verified_output_attached_with_job_context(self):
        optimize = Mock(return_value=str(self.optimized))
        self.assertEqual(self.upload(optimize), (True, "optimized.pdf"))
        self.file_input.send_keys.assert_called_once_with(str(self.optimized.resolve()))
        self.assertEqual(optimize.call_args.kwargs["job_title"], "Staff Engineer")
        self.verify.assert_not_called()

    def test_rejection_attaches_independently_verified_source(self):
        self.assertEqual(self.upload(Mock(return_value=None)), (True, "resume.pdf"))
        self.verify.assert_called_once_with(self.source, self.pdf)
        self.file_input.send_keys.assert_called_once_with(str(self.pdf.resolve()))

    def test_optimizer_exception_uses_verified_source(self):
        self.assertEqual(self.upload(Mock(side_effect=RuntimeError("conversion failed"))), (True, "resume.pdf"))

    def test_nonexistent_output_uses_verified_source(self):
        self.assertEqual(self.upload(Mock(return_value=str(self.optimized.with_name("missing.pdf")))), (True, "resume.pdf"))

    def test_unverified_source_never_uploaded(self):
        self.verify.return_value = False
        self.assertEqual(self.upload(Mock(return_value=None)), (False, "No verified resume"))
        self.file_input.send_keys.assert_not_called()

    def test_missing_source_pdf_never_uploaded(self):
        self.pdf.unlink()
        self.assertEqual(self.upload(Mock(return_value=None)), (False, "No verified resume"))
        self.verify.assert_not_called()
        self.file_input.send_keys.assert_not_called()

    def test_failed_optimized_attachment_retries_source(self):
        self.file_input.send_keys.side_effect = [RuntimeError("upload failed"), None]
        self.assertEqual(self.upload(Mock(return_value=str(self.optimized))), (True, "resume.pdf"))
        self.assertEqual(self.file_input.send_keys.call_count, 2)

    def test_failed_source_attachment_never_reports_previous_resume_success(self):
        self.file_input.send_keys.side_effect = RuntimeError("upload failed")
        self.assertEqual(self.upload(Mock(return_value=None)), (False, "No verified resume"))

    def bot_finally(self):
        # Compile the real Easy Apply finally block without importing the bot,
        # whose imports start Chrome. No Selenium/network interaction is needed.
        path = Path(__file__).resolve().parents[1] / "runAiBot.py"
        tree = ast.parse(path.read_text())
        block = next(
            node.finalbody for node in ast.walk(tree)
            if isinstance(node, ast.Try) and node.finalbody
            and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id == "follow_company"
                    for stmt in node.finalbody for child in ast.walk(stmt))
        )
        return path, block

    def test_bot_finally_blocks_submit_when_attachment_is_missing(self):
        path, block = self.bot_finally()
        submit = Mock()
        namespace = {
            "use_AI_for_resume": True, "uploaded": False,
            "ResumeUploadError": ResumeUploadError, "wait_span_click": submit,
        }
        with self.assertRaises(ResumeUploadError):
            exec(compile(ast.Module(body=block, type_ignores=[]), str(path), "exec"), namespace)
        submit.assert_not_called()

    def test_bot_finally_allows_submit_after_verified_attachment(self):
        path, block = self.bot_finally()
        submit = Mock(return_value=True)
        namespace = {
            "use_AI_for_resume": True, "uploaded": True,
            "ResumeUploadError": ResumeUploadError, "wait_span_click": submit,
            "questions_list": [], "errored": "", "pause_before_submit": False,
            "driver": Mock(), "modal": Mock(), "follow_company": Mock(),
            "datetime": datetime,
        }
        exec(compile(ast.Module(body=block, type_ignores=[]), str(path), "exec"), namespace)
        self.assertTrue(any(call.args[1] == "Submit application" for call in submit.call_args_list))

    def test_source_fallback_requires_configured_pdf_page_count(self):
        from reportlab.pdfgen import canvas

        for pages, expected in ((2, True), (1, False), (3, False)):
            pdf = Path(self.directory.name) / f"source-{pages}.pdf"
            document = canvas.Canvas(str(pdf))
            for page in range(pages):
                document.drawString(50, 700, f"Source resume page {page + 1}")
                document.showPage()
            document.save()
            with patch("modules.config_loader.load_runtime_config", return_value={"expected_page_count": 2}):
                self.assertEqual(verify_source_resume(pdf, pdf), expected)

    def test_unrelated_companion_pdf_cannot_be_used_as_source_fallback(self):
        from docx import Document
        from reportlab.pdfgen import canvas

        doc = Document()
        doc.add_heading("SKILLS", level=1)
        doc.add_paragraph("Python, AWS")
        doc.add_heading("PROFESSIONAL EXPERIENCE", level=1)
        doc.add_paragraph("Designed a production Python platform", style="List Paragraph")
        doc.save(self.source)
        pdf = canvas.Canvas(str(self.pdf))
        for page in range(2):
            pdf.drawString(50, 700, "Unrelated document text")
            pdf.showPage()
        pdf.save()
        with patch("modules.config_loader.load_runtime_config", return_value={"expected_page_count": 2}):
            self.assertFalse(verify_source_resume(self.source, self.pdf))


if __name__ == "__main__":
    unittest.main()
