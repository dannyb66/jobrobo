"""AI request failures and source retention cannot masquerade as a live rewrite."""
import json
import os
import unittest
from unittest.mock import patch

from docx import Document
from modules.ai.resume_optimizer import ResumeOptimizer
from modules.ai.resume_optimizer import _source_fact_issue
import modules.ai.resume_optimizer as module
import test_resume_pipeline as pipeline


class AuthenticationFailure(Exception):
    status_code = 401


class ResumeAIStatusTest(unittest.TestCase):
    def setUp(self):
        self.runner = pipeline.ResumePipelineTest(methodName="test_all_modes_change_only_intended_sections_and_record_reports")
        self.runner.setUp()
        self.addCleanup(self.runner.doCleanups)
        self.runner.rewrite.side_effect = lambda entries, *args: ResumeOptimizer._call_openai_to_rewrite_bullets(
            self.runner.optimizer, entries, *args)

    def reply(self, content):
        reply = pipeline.api_response(json.dumps(content))
        reply.id = "chatcmpl-synthetic-unit-test"
        return reply

    def entries(self, transform=lambda value: value):
        entries = self.runner.optimizer._extract_experience_bullets(Document(self.runner.source))
        return {"rewritten_experience": [dict(entry, bullets=[transform(b) for b in entry["bullets"]]) for entry in entries]}

    def test_missing_key_is_zero_requests_not_authentication_failure(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertIsNone(self.runner.run_pipeline())
        report = self.runner.report()
        self.assertEqual(report["error_code"], "missing_credentials")
        self.assertEqual(report["ai_activity"]["state"], "not_attempted_missing_credentials")
        self.assertEqual(report["ai_activity"]["request_attempts"], 0)
        self.assertFalse(report["rewrite_completed"])

    def test_keyword_auth_failure_stops_before_generation_and_redacts_key(self):
        self.runner.optimizer.client.chat.completions.create.side_effect = AuthenticationFailure("Bad key sk-private-synthetic")
        self.assertIsNone(self.runner.run_pipeline())
        report = self.runner.report()
        self.assertEqual(report["status"], "ai_unavailable")
        self.assertEqual(report["error_code"], "keyword_authentication_error")
        self.assertEqual(report["attempts"], [])
        self.assertEqual(report["ai_activity"]["responses_received"], 0)
        self.assertNotIn("sk-private-synthetic", json.dumps(report))

    def test_bullet_auth_failure_cannot_become_skills_or_source_fallback_success(self):
        self.runner.optimizer.client.chat.completions.create.side_effect = [
            self.reply({"keywords": ["Python", "AWS"]}), AuthenticationFailure("Bad key sk-private-synthetic")]
        self.assertIsNone(self.runner.run_pipeline())
        report = self.runner.report()
        self.assertEqual(report["status"], "ai_unavailable")
        self.assertEqual(report["error_code"], "bullet_authentication_error")
        self.assertEqual(len(report["attempts"]), 1)
        self.assertFalse(report["attempts"][0]["conversion_succeeded"])
        self.assertFalse(report["rewrite_completed"])

    def test_successful_response_returning_source_is_not_a_completed_rewrite(self):
        self.runner.optimizer.client.chat.completions.create.side_effect = [
            self.reply({"keywords": ["Python", "AWS"]}), self.reply(self.entries())]
        self.assertIsNone(self.runner.run_pipeline("bullets"))
        report = self.runner.report()
        self.assertEqual(report["status"], "not_rewritten")
        self.assertTrue(report["format_verification"]["passed"])
        self.assertEqual(report["rewrite_summary"]["materially_changed_bullets"], 0)
        self.assertEqual(report["rewrite_summary"]["retained_source_bullets"], 2)
        self.assertFalse(report["rewrite_completed"])

    def test_punctuation_only_changes_are_not_counted_as_rewrites(self):
        self.runner.optimizer.client.chat.completions.create.side_effect = [
            self.reply({"keywords": ["Python", "AWS"]}), self.reply(self.entries(lambda value: value + "."))]
        self.assertIsNone(self.runner.run_pipeline("bullets"))
        self.assertEqual(self.runner.report()["rewrite_summary"]["materially_changed_bullets"], 0)

    def test_provider_rewrite_is_counted_after_final_pdf_validation(self):
        self.runner.optimizer.client.chat.completions.create.side_effect = [
            self.reply({"keywords": ["Python", "AWS"]}),
            self.reply(self.entries(lambda value: value.replace("using", "with").replace("Improved", "Enhanced")))]
        result = self.runner.run_pipeline("bullets")
        self.assertIsNotNone(result)
        report = self.runner.report(result)
        self.assertTrue(report["rewrite_completed"])
        self.assertEqual(report["rewrite_summary"]["model_attributed_bullets"], 2)
        self.assertEqual(report["ai_activity"]["request_attempts"], 2)

    def test_fixture_can_never_claim_a_live_ai_rewrite(self):
        self.runner.optimizer.client.chat.completions.create.side_effect = [
            self.reply({"keywords": ["Python", "AWS"]}),
            self.reply(self.entries(lambda value: value.replace("using", "with").replace("Improved", "Enhanced")))]
        result = module.run_resume_optimization("Python AWS", str(self.runner.source), "fixture", "Engineer", "Test", "Candidate",
                                                "bullets", ai_execution_kind="offline_fixture")
        self.assertIsNotNone(result)
        report = self.runner.report(result)
        self.assertEqual(report["artifact_kind"], "offline_validation_preview")
        self.assertEqual(report["ai_activity"]["state"], "offline_fixture")
        self.assertFalse(report["ai_activity"]["live_provider_response_observed"])
        self.assertFalse(report["rewrite_completed"])

    def test_source_metric_subject_and_unsupported_qualifier_are_rejected(self):
        self.assertEqual(_source_fact_issue("Improved decision-making by 35%", "Improved decision reliability by 35%"),
                         "source metric label changed")
        self.assertEqual(_source_fact_issue("Achieved 50% revenue growth", "Achieved 50% revenue growth over target"),
                         "new unsupported achievement qualifier")
        self.assertEqual(_source_fact_issue("Built backend services", "Built backend services efficiently"), "new filler ending")

    def test_source_numbers_cannot_be_added_or_omitted(self):
        self.assertEqual(_source_fact_issue("Built APIs", "Built 50 APIs"), "new unsupported numeric claim")
        self.assertEqual(_source_fact_issue("Built 50 APIs", "Built APIs"), "source numeric claim omitted")


if __name__ == "__main__":
    unittest.main()
