"""Regression tests for empty bullets, blank tails, and one-line enforcement."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from modules.ai.resume_optimizer import ResumeOptimizer
from modules import resume_all_bullets as bullets

TEST_ROOT = Path(__file__).resolve().parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))


def response(entries):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({"rewritten_experience": entries})))])


class EmptyBulletTest(unittest.TestCase):
    def setUp(self):
        self.optimizer = ResumeOptimizer.__new__(ResumeOptimizer)
        self.optimizer.client = Mock()
        self.optimizer.rewrite_response_attempts = 2

    def source(self):
        return [{"company": "Example", "job_title": "Engineer", "bullets": [
            "Built production API services with Python and AWS for enterprise clients"]}]

    def test_whitespace_only_bullet_is_rejected_and_source_retained(self):
        self.optimizer.client.chat.completions.create.return_value = response([
            dict(self.source()[0], bullets=["   "])])
        result = self.optimizer._call_openai_to_rewrite_bullets(self.source(), "Engineer", "Python")
        self.assertEqual(result[0]["bullets"], self.source()[0]["bullets"])
        self.assertIn("empty", self.optimizer.last_bullet_rewrite_error)

    def test_empty_all_bullets_via_strict_validator(self):
        source = {"experience_id": "0", "company": "Example", "job_title": "Engineer",
                  "right_boundary": 200, "text_left": 50,
                  "context": ["EXAMPLE"], "bullets": [
                      {"bullet_id": "a", "source_text": "Built APIs with Python",
                       "source_text_hash": bullets.sha("Built APIs with Python"),
                       "fact_anchors": ["Python"], "paragraph_index": 0,
                       "right_boundary": 200, "text_left": 50}]}
        payload = {"experience_id": "0", "results": [{
            "bullet_id": "a", "source_text_hash": bullets.sha("Built APIs with Python"),
            "status": "rewritten", "rewritten_text": " ", "alternative_texts": [],
            "matched_jd_spans": [], "preserved_fact_anchors": ["Python"],
            "change_reason": "x", "blocked_reason": None}]}
        result = bullets.validate_response(payload, source, source["bullets"])
        self.assertEqual(result["a"]["status"], "blocked")
        self.assertEqual(result["a"]["rewritten_text"], "Built APIs with Python")
        self.assertIn("empty", result["a"]["reason"])

    def test_strict_inventory_counts_empty_bullet_and_rejects_one_line(self):
        source = {"experience_id": "0", "company": "Example", "job_title": "Engineer",
                  "right_boundary": 200, "text_left": 50,
                  "context": ["EXAMPLE"], "bullets": [
                      {"bullet_id": "a", "source_text": "Built APIs with Python",
                       "source_text_hash": bullets.sha("Built APIs with Python"),
                       "fact_anchors": ["Python"], "paragraph_index": 0,
                       "right_boundary": 200, "text_left": 50}]}
        rendered = [{"paragraph_index": 0, "kind": "bullet", "matched": True,
                     "line_count": 1, "lines": [{"page": 1, "x0": 50, "x1": 150}]}]
        self.assertTrue(bullets.strict_density(rendered, rendered, source)["passed"])
        rendered.append({"paragraph_index": 1, "kind": "bullet", "matched": True,
                         "line_count": 1, "lines": [{"page": 1, "x0": 50, "x1": 150}]})
        self.assertFalse(bullets.strict_density(rendered, rendered, source)["passed"])


class BlankPageTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.optimizer = ResumeOptimizer.__new__(ResumeOptimizer)

    def build(self, name, paragraphs):
        docx, pdf = self.root / (name + ".docx"), self.root / (name + ".pdf")
        doc = Document()
        doc.add_heading("SKILLS", 1)
        doc.add_paragraph("Python, AWS")
        doc.add_heading("PROFESSIONAL EXPERIENCE", 1)
        doc.add_paragraph("EXAMPLE\tRemote")
        doc.add_paragraph("Engineer\tJanuary 2020 - Present")
        for text, style in paragraphs:
            doc.add_paragraph(text, style=style)
        doc.save(docx)
        writer = canvas.Canvas(str(pdf), pagesize=letter)
        writer.setFont("Helvetica", 10)
        y = 730
        for text in ["SKILLS", "Python, AWS", "PROFESSIONAL EXPERIENCE", "EXAMPLE", "Engineer"]:
            writer.drawString(72, y, text); y -= 20
        for text, style in paragraphs:
            if style == "List Paragraph":
                writer.drawString(72, y, "• " + text); y -= 20
        writer.showPage()
        writer.setFont("Helvetica", 10)
        writer.drawString(72, 730, "1")
        writer.showPage()
        writer.save()
        return docx, pdf

    def test_number_only_trailing_page_is_blank(self):
        layout = self.optimizer._rendered_layout(
            str(self.build("period", [("Built APIs", "List Paragraph")])[1]), [])
        self.assertEqual(layout["page_count"], 2)
        self.assertFalse(layout["all_pages_have_text"])

    def test_empty_trailing_paragraph_in_docx_is_counted(self):
        docx, _ = self.build("empty", [("Built APIs", "List Paragraph")])
        doc = Document(docx)
        doc.add_paragraph("")
        doc.add_paragraph("   ")
        doc.save(docx)
        layout = self.optimizer._rendered_layout(str(self.build("x", [
            ("Built APIs", "List Paragraph")])[1]), [], str(docx))
        self.assertEqual(layout["empty_trailing_paragraphs"], 2)

    def test_wrapped_bullet_fails_format_even_without_strict_inventory(self):
        source_docx, source_pdf = self.build("source", [("Built APIs", "List Paragraph")])
        output_docx, output_pdf = self.build(
            "output", [("Built production APIs with Python and AWS", "List Paragraph")])
        # Simulate a second rendered line for the only bullet.
        writer = canvas.Canvas(str(output_pdf), pagesize=letter)
        writer.setFont("Helvetica", 10)
        y = 730
        for text in ["SKILLS", "Python, AWS", "PROFESSIONAL EXPERIENCE", "EXAMPLE", "Engineer",
                     "• Built production APIs", "  with Python and AWS"]:
            writer.drawString(72, y, text); y -= 20
        writer.showPage()
        writer.save()
        result = self.optimizer.verify_format(
            str(source_docx), str(output_docx), str(source_pdf), str(output_pdf), 1)
        self.assertTrue(result["details"]["optimized_layout"]["max_bullet_lines"] >= 2)
        self.assertIn("bullet_lines", result["checks"])
        self.assertFalse(result["checks"]["bullet_lines"])
class FullPipelineLayoutGateTest(unittest.TestCase):
    def setUp(self):
        import test_resume_pipeline as pipeline
        self.runner = pipeline.ResumePipelineTest(
            methodName="test_all_modes_change_only_intended_sections_and_record_reports")
        self.runner.setUp()
        self.addCleanup(self.runner.doCleanups)

    def convert(self, split=False, blank_page=False):
        import test_resume_pipeline as pipeline
        from docx import Document as ReadDocument
        def mocked(docx_path, pdf_path):
            lines = [paragraph.text.replace("\t", " ") for paragraph in ReadDocument(docx_path).paragraphs
                     if paragraph.text]
            if split:
                lines = ["Built production services", "using Python", "Enhanced API reliability on AWS"]
            pipeline.pdf_from_lines(pdf_path, lines)
            if blank_page:
                writer = canvas.Canvas(str(pdf_path), pagesize=letter)
                writer.setFont("Helvetica", 10)
                for index, line in enumerate(lines):
                    writer.drawString(72, 730 - index * 20, line)
                writer.showPage()
                writer.setFont("Helvetica", 10)
                writer.drawString(72, 730, "2")
                writer.showPage()
                writer.save()
            return True
        return mocked

    def test_wrapped_rewritten_bullet_rejects_resume(self):
        self.runner.optimizer.convert_docx_to_pdf.side_effect = self.convert(split=True)
        self.assertIsNone(self.runner.run_pipeline())
        report = self.runner.report()
        self.assertEqual(report["status"], "rejected")
        first = report["attempts"][0]["format_verification"]
        self.assertFalse(first["checks"]["bullet_lines"])

    def test_number_only_extra_page_rejects_resume(self):
        self.runner.optimizer.convert_docx_to_pdf.side_effect = self.convert(blank_page=True)
        self.runner.config["expected_page_count"] = 2
        self.assertIsNone(self.runner.run_pipeline())
        report = self.runner.report()
        self.assertEqual(report["status"], "rejected")
        first = report["attempts"][0]["format_verification"]
        self.assertFalse(first["checks"]["no_empty_rendered_pages"])

    def test_empty_bullet_paragraph_rejects_resume(self):
        doc = Document(self.runner.source)
        doc.add_paragraph("", style="List Paragraph")
        doc.save(self.runner.source)
        self.assertIsNone(self.runner.run_pipeline())
        report = self.runner.report()
        self.assertEqual(report["status"], "rejected")
        first = report["attempts"][0]["format_verification"]
        self.assertFalse(first["checks"]["no_empty_bullets"])
        self.assertGreaterEqual(first["details"]["optimized_layout"]["empty_bullets"], 1)

    def test_bullet_below_hard_fill_fails_final_verification(self):
        source = self.runner.source
        source_docx, source_pdf = self.runner.source, self.runner.source.with_suffix(".pdf")
        text = "Built " + "a" * 50
        output_docx, output_pdf = self._single_bullet_docx(90, text=text)
        self.runner.optimizer.rewrite_all_bullets = True
        self.runner.optimizer.strict_inventory = {"bullets": [{
            "source_text": text, "usable_line_width": 540, "right_boundary": 612, "text_left": 72,
            "paragraph_index": 0}]}
        self.runner.optimizer.rewrite_bullet_hard_min_fill_ratio = .80
        result = self.runner.optimizer.verify_format(
            str(source_docx), str(output_docx), str(source_pdf), str(output_pdf), 1)
        self.assertFalse(result["checks"]["bullet_fullness"])
        self.assertLess(result["details"]["bullet_fullness_shortages"][0]["fill_ratio"], .60)

    def test_bullet_below_eighty_percent_fails_and_exactly_eighty_passes(self):
        for width, expected in ((79.9, False), (79.96, True), (80.0, True)):
            with self.subTest(width=width):
                docx, pdf = self._single_bullet_docx(width)
                import pdfplumber
                with pdfplumber.open(pdf) as document:
                    words = document.pages[0].extract_words()
                    used = max(w["x1"] for w in words) - min(w["x0"] for w in words)
                self.runner.optimizer.strict_inventory = {"bullets": [{
                    "source_text": "Built APIs", "usable_line_width": used * 100 / width,
                    "right_boundary": 612, "text_left": 72, "paragraph_index": 0}]}
                self.runner.optimizer.rewrite_bullet_hard_min_fill_ratio = .80
                result = self.runner.optimizer.verify_format(
                    str(docx), str(docx), str(pdf), str(pdf), 1)
                self.assertEqual(result["checks"]["bullet_fullness"], expected)

    def test_unchanged_source_fallback_is_exempt_from_new_fullness_floor(self):
        docx, pdf = self._single_bullet_docx(60)
        self.runner.optimizer.strict_inventory = {"bullets": [{
            "bullet_id": "retained", "source_text": "Built APIs", "usable_line_width": 540,
            "right_boundary": 612, "text_left": 72, "paragraph_index": 0}]}
        self.runner.optimizer.source_fallback_ids = {"retained"}
        result = self.runner.optimizer.verify_format(str(docx),str(docx),str(pdf),str(pdf),1)
        self.assertTrue(result['checks']['bullet_fullness'])

    def _single_bullet_docx(self, width, text="Built APIs"):
        docx, pdf = self.runner.root / f"f{width}.docx", self.runner.root / f"f{width}.pdf"
        doc = Document()
        doc.add_paragraph(text, style="List Paragraph")
        doc.save(docx)
        writer = canvas.Canvas(str(pdf), pagesize=letter)
        writer.setFont("Helvetica", 10)
        writer.drawString(72, 730, text)
        writer.showPage(); writer.save()
        return docx, pdf


if __name__ == "__main__":
    unittest.main()
