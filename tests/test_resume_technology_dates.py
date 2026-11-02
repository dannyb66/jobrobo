"""Technology/date guard: rewrite once without the late product."""
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import resume_technology_dates as dates
from modules import resume_all_bullets as bullets
import test_resume_all_bullets as fixtures
from docx import Document


class TechnologyDatesTest(unittest.TestCase):
    def group(self, period="January 2022 - May 2023"):
        inventory = fixtures.inv(1, 1)
        group = inventory["groups"][0]
        group["historical_title_dates"] = [f"Engineer\t{period}"]
        return inventory, group

    def test_role_period_includes_named_end_month(self):
        _, group = self.group()
        self.assertEqual(dates.role_period(group), (date(2022, 1, 1), date(2023, 5, 31)))

    def test_present_period_and_missing_dates_are_handled(self):
        _, group = self.group("June 2025 - Present")
        self.assertEqual(dates.role_period(group)[1], date.today())
        group["historical_title_dates"] = ["Engineer"]
        self.assertIsNone(dates.role_period(group))
        self.assertIsNone(dates.claim_issue("Used Kiro", group))

    def test_late_technology_is_detected_and_boundary_is_inclusive(self):
        _, group = self.group("June 2023 - September 2023")
        self.assertTrue(dates.claim_issue("Deployed TensorRT-LLM", group))
        self.assertFalse(dates.claim_issue("Used Kubernetes and Docker", group))
        self.assertIsNone(dates.claim_issue("Used TensorRT-LLM", self.group("June 2023 - November 2023")[1]))

    def test_earlier_release_is_allowed_and_aliases_are_matched(self):
        _, group = self.group("January 2020 - January 2022")
        self.assertIsNone(dates.claim_issue("Used OpenTelemetry and OTel", group))
        self.assertTrue(dates.claim_issue("Used Kiro", group))
        self.assertIsNone(dates.claim_issue("Used Docker and Terraform", group))

    def test_unknown_technology_is_not_an_allowlist_failure(self):
        _, group = self.group("January 2016 - January 2018")
        self.assertIsNone(dates.claim_issue("Used proprietary RelayRouter", group))

    def test_late_candidate_is_blocked_with_retry_terms(self):
        inventory, group = self.group()
        requested = inventory["bullets"]
        response = fixtures.response({"experience_id": "0", "requested_bullets": requested})
        response["results"][0]["rewritten_text"] = (
            "Built Kiro-assisted Python API services through customer workflow development")
        result = bullets.validate_response(response, group, requested,
                                           content_policy="synthetic_jd_test")["0"]
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["late_technologies"], ["Kiro"])
        self.assertIn("predates role end", result["reason"])

    def test_retry_payload_forbids_term_and_drops_its_opportunity(self):
        inventory, group = self.group()
        requested = inventory["bullets"]
        payload = bullets.compact_payload(
            inventory, "Build Kiro agents with Python", "Engineer", "synthetic_jd_test",
            group, requested, forbidden_technologies={"0": ["Kiro"]})
        row = payload["requested_bullets"][0]
        self.assertEqual(row["forbidden_technologies"], ["Kiro"])
        self.assertNotIn("Kiro", " ".join(row["jd_keyword_opportunities"]))
        self.assertEqual(payload["technology_period"]["end"], "2023-05-31")
        self.assertIn("technology_dates", payload["acceptance_criteria"])

    def test_in_period_retry_is_accepted(self):
        inventory, group = self.group()
        requested = inventory["bullets"]
        response = fixtures.response({"experience_id": "0", "requested_bullets": requested})
        response["results"][0]["rewritten_text"] = (
            "Built Python API services through customer workflow development for enterprise clients")
        result = bullets.validate_response(response, group, requested,
                                           content_policy="synthetic_jd_test")["0"]
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["late_technologies"], [])

    def test_rewrite_wave_retries_without_late_term_and_accepts(self):
        inventory, group = self.group()
        calls = []

        def provider(stage, payload, timeout):
            calls.append(payload)
            response = fixtures.response(payload)
            if len(calls) == 1:
                response["results"][0]["rewritten_text"] = (
                    "Built Kiro-assisted Python API services through customer workflow development")
            else:
                self.assertEqual(
                    payload["requested_bullets"][0]["forbidden_technologies"], ["Kiro"])
                response["results"][0]["rewritten_text"] = (
                    "Built Python API services through customer workflow development for enterprise clients")
            return response

        scheduler = bullets.Scheduler(fixtures.config(), 1)
        records = bullets.rewrite_inventory(
            inventory, "Build Kiro agents with Python", "Engineer",
            "synthetic_jd_test", scheduler, provider)
        self.assertEqual(len(calls), 2)
        self.assertEqual(records[0]["status"], "candidate")
        self.assertNotIn("Kiro", records[0]["rewritten_text"])

    def test_legacy_extraction_retains_dates_separately_from_title(self):
        from modules.ai.resume_optimizer import ResumeOptimizer
        optimizer = object.__new__(ResumeOptimizer)
        document = Document()
        document.add_heading("PROFESSIONAL EXPERIENCE", 1)
        document.add_paragraph("CHILL PANDA TECH\tSan Francisco")
        document.add_paragraph("Engineer\tJanuary 2022 - May 2023")
        document.add_paragraph("Built Python APIs", style="List Paragraph")
        entry = optimizer._extract_experience_bullets(document)[0]
        self.assertEqual(entry["job_title"], "Engineer")
        self.assertIn("May 2023", optimizer.experience_periods[(entry["company"], entry["job_title"])])

    def test_unreadable_docx_is_an_audit_failure(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.docx"
            output = Path(directory) / "output.docx"
            source.write_bytes(b"not a DOCX")
            output.write_bytes(b"not a DOCX")
            self.assertTrue(bullets.technology_date_conflicts(source, output))

    def test_final_audit_matches_company_section_with_changed_paragraph_count(self):
        with TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.docx", Path(directory) / "output.docx"
            original = Document()
            original.add_paragraph("SUMMARY")
            original.add_paragraph("Engineer")
            original.add_heading("OLD COMPANY", 2)
            original.add_paragraph("Engineer\tJanuary 2022 - May 2023")
            original.add_paragraph("Built Python APIs", style="List Paragraph")
            original.add_heading("NEW COMPANY", 2)
            original.add_paragraph("Engineer\tJune 2025 - Present")
            original.add_paragraph("Built agent tools", style="List Paragraph")
            original.save(source)
            result = Document(source)
            result.paragraphs.insert(1, result.paragraphs[1].insert_paragraph_before("extra summary paragraph"))
            for paragraph in result.paragraphs:
                if paragraph.text == "Built Python APIs":
                    paragraph.text = "Built Kiro-assisted Python APIs"
                if paragraph.text == "Built agent tools":
                    paragraph.text = "Built Kiro agent tools"
            result.save(output)
            conflicts = dates.audit_document(source, output)
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(conflicts[0]["company"], "old company")
            self.assertEqual(conflicts[0]["late"][0]["technology"], "Kiro")


if __name__ == "__main__":
    unittest.main()
