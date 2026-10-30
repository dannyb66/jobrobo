"""Direct queues retain the inventory and protect resume, review and uncertain states."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules.direct_careers_apply import (digest, export_applications, load_queue, local_candidate, plan_queue,
                                         readiness, run_queue, text_digest, validate_queue, write_json)
from modules.external_apply import ExternalApplicationLedger, ExternalApplicationResult
from modules.job_pipeline.models import StageResult, write_artifact

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)
URL = "https://jobs.ashbyhq.com/example/11111111-1111-4111-8111-111111111111"


def role(index=1, **changes):
    result = {"id": f"role:{index}", "title": "Software Engineer", "description": "Build Python APIs.",
              "company_id": "company:1", "company": {"id": "company:1", "name": "Example"},
              "career_url": URL.replace("11111111-1111-4111-8111-111111111111", f"11111111-1111-4111-8111-{index:012d}"),
              "verification_eligible": True, "eligible": True, "application_eligible": False,
              "application_exclusion_reasons": ["location_mismatch", "outside_date_window"], "status": "open",
              "verified_at": NOW.isoformat(), "is_prospect": False,
              "sources": [{"kind": "career_verification", "url": "https://api.ashbyhq.com/posting-api/job-board/example", "observed_at": NOW.isoformat()}],
              "review_priority": {"tier": 1 if index == 2 else 3}}
    result.update(changes)
    return result


class DirectQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docx, self.pdf, self.input, self.queue = [self.root / name for name in ("source.docx", "source.pdf", "roles.json", "queue.json")]
        self.docx.write_bytes(b"Synthetic DOCX")
        self.pdf.write_bytes(b"Synthetic PDF")
        self.verifier = Mock(return_value={"passed": True})
        self.browser = Mock()

    def plan(self, roles=None, **kwargs):
        write_artifact(StageResult.create("verified_roles", "synthetic", "verify:1", roles or [role()]), self.input)
        return plan_queue(self.input, self.queue, self.docx, self.pdf, now=NOW, verifier=self.verifier, **kwargs)

    def run_queue(self, **kwargs):
        return run_queue(self.queue, execute=True, browser_factory=lambda: self.browser, review=lambda details: "Submit application",
                         candidate={"full_name": "Synthetic Applicant"}, now=NOW, verifier=self.verifier, browser_ready=lambda _: None, **kwargs)

    def applied(self, driver, url, applicant, pdf, **options):
        self.assertTrue(options["verify_pdf"](pdf))
        from modules.external_apply import identify_ats
        self.assertEqual(identify_ats(options["official_role_urls"][0]).key, identify_ats(url).key)
        self.assertIsNone(options["ai_answerer"])
        result = ExternalApplicationResult("submitting", url, resume_name=Path(pdf).name, resume_sha256=digest(pdf))
        options["on_status"](result)
        self.assertEqual(options["review"]({}), "Submit application")
        result.status, result.submitted_at = "applied", NOW.isoformat()
        options["on_status"](result)
        return result

    def test_all_rows_retained_in_input_rank_order_candidate_filters_are_only_warnings(self):
        queue = self.plan([role(2), role(1), role(3, career_url="https://example.com/careers/role")])
        self.assertEqual([r["role_id"] for r in queue["records"]], ["role:2", "role:1", "role:3"])
        self.assertEqual([r["status"] for r in queue["records"]], ["queued", "queued", "manual_handoff"])
        self.assertEqual(queue["records"][0]["candidate_filter_warnings"], ["location_mismatch", "outside_date_window"])
        self.assertFalse(queue["search_performed"])

    def test_different_url_variants_of_same_posting_retained_as_explicit_duplicate_handoff(self):
        q = self.plan([role(), role(2, career_url=role()["career_url"] + "/application?utm_source=test")])
        self.assertEqual(q["records"][0]["ats_identity"], q["records"][1]["ats_identity"])
        self.assertIn("duplicate_ats_posting_in_queue", q["records"][1]["handoff_reasons"])

    def test_original_resume_run_requires_no_key_no_optimizer_construction_or_question_ai(self):
        self.plan()
        with patch.dict("os.environ", {}, clear=True), patch("modules.ai.resume_optimizer.ResumeOptimizer.__init__", side_effect=AssertionError("No optimizer")), patch("modules.external_questions.make_local_ai_answerer", side_effect=AssertionError("No question AI")):
            q = self.run_queue(apply=self.applied, question_config={"ai": {"enabled": True, "model": "unused"}})
        self.assertEqual(q["records"][0]["status"], "applied")
        self.assertEqual(q["invocations"][-1]["confirmed_count"], 1)

    def test_default_cap_one_stops_second_application(self):
        self.plan([role(1), role(2)])
        apply = Mock(side_effect=self.applied)
        q = self.run_queue(apply=apply, max_attempts=90)
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(q["invocations"][-1]["stop_reason"], "application_limit_reached")
        self.assertEqual(q["records"][1]["status"], "queued")

    def test_uncertain_outcome_stops_and_checkpoint_resume_never_reclicks(self):
        self.plan([role(1), role(2)])
        def uncertain(driver, url, applicant, pdf, **options):
            result = ExternalApplicationResult("submitting", url)
            options["on_status"](result)
            return result
        q = self.run_queue(apply=uncertain, max_attempts=90)
        self.assertEqual(q["invocations"][-1]["stop_reason"], "submission_uncertain")
        apply = Mock(side_effect=AssertionError("Cannot retry uncertain application"))
        q = self.run_queue(apply=apply)
        self.assertEqual(q["invocations"][-1]["attempt_count"], 0)
        apply.assert_not_called()

    def test_other_queue_uncertain_shared_ledger_blocks_new_work(self):
        self.plan()
        ledger = self.root / "shared-ledger.json"
        ExternalApplicationLedger(ledger).record(ExternalApplicationResult("submitting", URL), "other-role")
        apply = Mock()
        q = self.run_queue(ledger_path=ledger, apply=apply)
        apply.assert_not_called()
        self.assertEqual(q["invocations"][-1]["stop_reason"], "submission_uncertain")

    def test_conservative_claim_survives_later_preparation_failure_and_stops_next_job(self):
        self.plan([role(1), role(2)])
        def claimed_then_failed(driver, url, candidate, pdf, **options):
            result = ExternalApplicationResult("submitting", url)
            options["on_status"](result)
            result.status = "failed"  # For example, a queue write failure blocked the actual click.
            return result
        q = self.run_queue(apply=claimed_then_failed, max_attempts=90)
        self.assertEqual(q["records"][0]["status"], "submitting")
        self.assertEqual(q["records"][1]["status"], "queued")
        self.assertEqual(q["invocations"][-1]["stop_reason"], "submission_uncertain")

    def test_stale_closed_missing_jd_and_prospect_retained_without_browser(self):
        rows = [role(1, verified_at=(NOW-timedelta(days=8)).isoformat()), role(2, status="closed"), role(3, description=""), role(4, is_prospect=True)]
        self.plan(rows)
        q = self.run_queue(apply=Mock(side_effect=AssertionError("No forms")), max_attempts=90)
        self.assertEqual([r["status"] for r in q["records"]], ["manual_handoff"] * 4)
        self.browser.get.assert_not_called()

    def test_verification_freshness_is_rechecked_at_execution(self):
        self.plan()
        q = run_queue(self.queue, execute=True, browser_factory=lambda: self.browser, review=lambda _: "Submit application",
                      verifier=self.verifier, now=NOW+timedelta(days=8))
        self.assertIn("verification_stale_or_future", q["records"][0]["handoff_reasons"])
        self.browser.get.assert_not_called()

    def test_resume_snapshot_changed_blocks_browser_and_original_file_change_does_not(self):
        q = self.plan()
        self.pdf.write_bytes(b"Source was edited after immutable copy")
        Path(q["records"][0]["resume"]["pdf"]["path"]).write_bytes(b"Snapshot corruption")
        q = self.run_queue(apply=Mock(side_effect=AssertionError("No forms")))
        self.assertEqual(q["records"][0]["handoff_reasons"], ["resume_snapshot_changed_or_invalid"])
        self.browser.get.assert_not_called()

    def test_failed_pre_submit_ledger_write_prevents_success(self):
        self.plan()
        with patch.object(ExternalApplicationLedger, "record", side_effect=OSError("disk failure")):
            q = self.run_queue(apply=self.applied)
        self.assertEqual(q["records"][0]["status"], "failed")
        self.assertEqual(q["invocations"][-1]["confirmed_count"], 0)

    def test_prepared_review_stays_visible_and_never_counts_as_submission(self):
        self.plan()
        def prepared(driver, url, applicant, pdf, **options):
            return ExternalApplicationResult("awaiting_review", url, resume_sha256=digest(pdf))
        q = self.run_queue(apply=prepared)
        self.assertEqual(q["invocations"][-1]["stop_reason"], "manual_review_open")
        self.assertEqual(q["invocations"][-1]["confirmed_count"], 0)
        self.browser.quit.assert_not_called()

    def test_completed_checkpoint_resume_skips_already_applied_and_continues_next(self):
        self.plan([role(1), role(2)])
        self.run_queue(apply=self.applied)
        q = self.run_queue(apply=self.applied)
        self.assertEqual([r["status"] for r in q["records"]], ["applied", "applied"])
        self.assertEqual(q["invocations"][-1]["confirmed_count"], 1)
        exported = export_applications(q)
        self.assertEqual(exported.stage, "applications")
        self.assertEqual(len(exported.records), 2)
        self.assertEqual(exported.records[0]["verification_run_id"], "verify:1")
        self.assertEqual(exported.records[0]["resume_mode"], "original")

    def test_only_explicit_selected_role_is_opened(self):
        self.plan([role(1), role(2)])
        q = self.run_queue(selected_role_ids=["role:2"], apply=self.applied)
        self.assertEqual([r["status"] for r in q["records"]], ["queued", "applied"])

    def test_optimized_mode_missing_selection_is_handoff_never_silent_source_fallback(self):
        self.plan(resume_mode="optimized")
        apply = Mock()
        q = self.run_queue(apply=apply)
        apply.assert_not_called()
        self.assertIn("no_selected_optimized_resume_for_role", q["records"][0]["handoff_reasons"])

    def optimized_selection(self):
        pdf, docx, report = [self.root / name for name in ("optimized.pdf", "optimized.docx", "match-report.json")]
        pdf.write_bytes(b"Optimized synthetic PDF")
        docx.write_bytes(b"Optimized synthetic DOCX")
        report.write_text(json.dumps({"status": "accepted", "format_verification": {"passed": True},
                                     "source_sha256": digest(self.docx), "job_title": role()["title"],
                                     "effective_mode": "bullets", "output_path": str(pdf)}))
        return {"role:1": {"pdf": str(pdf), "docx": str(docx), "report": str(report), "job_description_sha256": text_digest(role()["description"])}}

    def generated_output(self, **arguments):
        """An injected generator writes a full accepted contract inside its own workspace."""
        source = Path(arguments["resume_path"])
        self.assertEqual(digest(source), digest(self.docx))
        self.assertEqual(digest(source.with_suffix(".pdf")), digest(self.pdf))
        folder = source.parent.parent / "temp"
        folder.mkdir()
        pdf = folder / "generated.pdf"
        pdf.write_bytes(b"Fresh generated synthetic PDF")
        pdf.with_suffix(".docx").write_bytes(b"Fresh generated synthetic DOCX")
        pdf.with_suffix(".match_report.json").write_text(json.dumps({
            "status": "accepted", "format_verification": {"passed": True}, "source_sha256": digest(source),
            "job_id": arguments["job_id"], "job_title": arguments["job_title"], "output_path": str(pdf), "effective_mode": "bullets"}))
        return str(pdf)

    def test_generated_planning_is_zero_api_and_contains_no_fake_selected_pdf(self):
        with patch("modules.direct_careers_apply.generate_local_resume", side_effect=AssertionError("Plan must not generate")):
            q = self.plan([role(1), role(2)], resume_mode="generated")
        self.assertEqual([r["status"] for r in q["records"]], ["queued", "queued"])
        self.assertTrue(all(r["resume"]["pdf"] is None and r["resume"]["generation_attempts"] == [] for r in q["records"]))

    def test_generated_execution_requires_explicit_opt_in_one_role_cap_and_attempt(self):
        self.plan(resume_mode="generated")
        for changes, message in [({}, "generate-resume"), ({"generate_resumes": True}, "one explicit"),
                                  ({"generate_resumes": True, "selected_role_ids": ["role:1"], "max_applications": 2}, "cap 1"),
                                  ({"generate_resumes": True, "selected_role_ids": ["role:1"], "max_attempts": 2}, "one attempt")]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                self.run_queue(**changes)

    def test_generator_receives_selected_role_jd_title_and_paired_original_sources(self):
        self.plan([role(1), role(2)], resume_mode="generated")
        generator = Mock(side_effect=self.generated_output)
        q = self.run_queue(generate_resumes=True, selected_role_ids=["role:2"], generate=generator, apply=self.applied)
        generator.assert_called_once()
        arguments = generator.call_args.kwargs
        self.assertEqual(arguments["job_description"], role(2)["description"])
        self.assertEqual(arguments["job_title"], role(2)["title"])
        self.assertTrue(arguments["job_id"].startswith("direct-"))
        self.assertEqual([r["status"] for r in q["records"]], ["queued", "applied"])
        selected = q["records"][1]["resume"]
        self.assertEqual(selected["generation_binding"]["job_description_sha256"], text_digest(role(2)["description"]))
        self.assertEqual(selected["generation_binding"]["output_pdf_sha256"], selected["pdf"]["sha256"])
        self.assertEqual(q["invocations"][-1]["generation_count"], 1)
        self.assertEqual(q["invocations"][-1]["attempt_count"], 1)
        self.assertEqual(export_applications(q).records[0]["resume_mode"], "generated")

    def test_original_mode_never_calls_generator_and_rejects_accidental_generate_flag(self):
        self.plan()
        with patch("modules.direct_careers_apply.generate_local_resume", side_effect=AssertionError("No generation")):
            q = self.run_queue(apply=self.applied)
        self.assertEqual(q["invocations"][-1]["generation_count"], 0)
        with self.assertRaisesRegex(ValueError, "queue planned"):
            self.run_queue(generate_resumes=True)

    def test_failed_or_raised_generation_is_explicit_handoff_no_original_fallback_or_browser(self):
        self.plan(resume_mode="generated")
        for generator in (Mock(return_value=None), Mock(side_effect=RuntimeError("Synthetic secret must not enter tracking"))):
            with self.subTest(generator=generator):
                q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator)
                self.assertEqual(q["records"][0]["status"], "manual_handoff")
                self.assertIsNone(q["records"][0]["resume"]["pdf"])
                self.assertEqual(q["invocations"][-1]["stop_reason"], "resume_generation_failed")
                self.assertNotIn("Synthetic secret", self.queue.read_text())
        self.browser.get.assert_not_called()

    def test_independent_generated_format_rejection_blocks_browser(self):
        self.plan(resume_mode="generated")
        self.verifier.return_value = {"passed": False}
        q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=self.generated_output)
        self.assertEqual(q["records"][0]["handoff_reasons"], ["resume_generation_failed_no_source_fallback"])
        self.browser.get.assert_not_called()

    def test_generator_wrong_job_id_or_source_report_cannot_be_admitted(self):
        self.plan(resume_mode="generated")
        def wrong(**arguments):
            pdf = self.generated_output(**arguments)
            report = Path(pdf).with_suffix(".match_report.json")
            payload = json.loads(report.read_text())
            payload["job_id"] = "unrelated-job"
            report.write_text(json.dumps(payload))
            return pdf
        q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=wrong)
        self.assertEqual(q["records"][0]["status"], "manual_handoff")
        self.browser.get.assert_not_called()

    def test_uncertain_shared_submission_blocks_before_any_generation(self):
        self.plan(resume_mode="generated")
        ExternalApplicationLedger(self.root / "external-applications.json").record(ExternalApplicationResult("submitting", URL), "other")
        generator = Mock(side_effect=AssertionError("Must not spend"))
        q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator)
        generator.assert_not_called()
        self.assertEqual(q["invocations"][-1]["generation_count"], 0)
        self.assertEqual(q["invocations"][-1]["stop_reason"], "submission_uncertain")

    def test_applied_ledger_duplicate_and_stale_roles_never_generate(self):
        q = self.plan([role(1), role(2, verified_at=(NOW-timedelta(days=8)).isoformat())], resume_mode="generated")
        ExternalApplicationLedger(self.root / "external-applications.json").record(ExternalApplicationResult("applied", role()["career_url"]), "other")
        generator = Mock(side_effect=AssertionError("Must not spend"))
        for rid in ("role:1", "role:2"):
            q = self.run_queue(generate_resumes=True, selected_role_ids=[rid], generate=generator)
        generator.assert_not_called()
        self.assertEqual([r["status"] for r in q["records"]], ["duplicate", "manual_handoff"])

    def test_generated_draft_is_reused_after_leave_open_without_another_model_call(self):
        self.plan(resume_mode="generated")
        generator = Mock(side_effect=self.generated_output)
        def prepared(driver, url, candidate, pdf, **options):
            return ExternalApplicationResult("awaiting_review", url, resume_sha256=digest(pdf))
        self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator, apply=prepared)
        q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator, apply=self.applied)
        generator.assert_called_once()
        self.assertEqual(q["records"][0]["status"], "applied")
        self.assertEqual(q["invocations"][-1]["generation_count"], 0)

    def test_interrupted_generation_checkpoint_never_silently_repeats_paid_call(self):
        q = self.plan(resume_mode="generated")
        q["records"][0]["resume"]["generation_attempts"].append({"id": "interrupted", "status": "generating"})
        write_json(self.queue, q)
        generator = Mock(side_effect=AssertionError("Must not repeat an interrupted model call"))
        q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator)
        generator.assert_not_called()
        self.assertEqual(q["invocations"][-1]["stop_reason"], "resume_generation_interrupted")

    def test_failed_accepted_result_checkpoint_preserves_inflight_claim_without_repeating_generation(self):
        self.plan(resume_mode="generated")
        generator = Mock(side_effect=self.generated_output)
        original_write = write_json
        rejected = []
        def fail_once(path, payload):
            if isinstance(payload, dict) and payload.get("schema") and payload["records"][0]["resume"].get("pdf") and not rejected:
                rejected.append(True)
                raise OSError("Synthetic accepted checkpoint failure")
            return original_write(path, payload)
        with patch("modules.direct_careers_apply.write_json", side_effect=fail_once), self.assertRaises(OSError):
            self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator)
        self.assertEqual(load_queue(self.queue)["records"][0]["resume"]["generation_attempts"][-1]["status"], "generating")
        q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator)
        generator.assert_called_once()
        self.assertEqual(q["invocations"][-1]["stop_reason"], "resume_generation_interrupted")
        self.browser.get.assert_not_called()

    def test_failed_binding_file_write_preserves_inflight_claim_without_repeating_generation(self):
        self.plan(resume_mode="generated")
        generator = Mock(side_effect=self.generated_output)
        original_write = write_json
        def fail_binding(path, payload):
            if Path(path).name == "generation-binding.json":
                raise OSError("Synthetic generation binding disk failure")
            return original_write(path, payload)
        with patch("modules.direct_careers_apply.write_json", side_effect=fail_binding), self.assertRaises(OSError):
            self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator)
        q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator)
        generator.assert_called_once()
        self.assertEqual(q["invocations"][-1]["stop_reason"], "resume_generation_interrupted")
        self.browser.get.assert_not_called()

    def test_changed_source_snapshot_blocks_before_generation(self):
        q = self.plan(resume_mode="generated")
        Path(q["source_resume"]["docx"]["path"]).write_bytes(b"Changed")
        generator = Mock(side_effect=AssertionError("Must not spend"))
        q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=generator)
        generator.assert_not_called()
        self.assertEqual(q["records"][0]["status"], "failed")
        self.assertEqual(q["invocations"][-1]["generation_count"], 0)

    def test_default_generator_page_config_mismatch_hands_off_before_any_optimizer_call(self):
        self.plan(resume_mode="generated", expected_pages=1)
        with patch("modules.config_loader.load_runtime_config", return_value={"expected_page_count": 2}), patch("modules.direct_careers_apply.generate_local_resume") as generate:
            q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"])
        generate.assert_not_called()
        self.assertEqual(q["records"][0]["status"], "manual_handoff")
        self.assertEqual(q["records"][0]["handoff_reasons"], ["resume_optimizer_page_count_mismatch"])
        self.assertEqual(q["invocations"][-1]["generation_count"], 0)
        self.assertEqual(q["records"][0]["resume"]["generation_preflight"]["queue_expected_pages"], 1)
        self.browser.get.assert_not_called()

    def test_generation_workspace_shields_private_inputs_and_reports_under_ordinary_umask(self):
        self.plan(resume_mode="generated")
        locations = []
        def inspect_workspace(**arguments):
            source = Path(arguments["resume_path"])
            self.assertEqual(source.parent.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(source.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(source.stat().st_mode & 0o777, 0o600)
            self.assertEqual(source.with_suffix(".pdf").stat().st_mode & 0o777, 0o600)
            locations.append(source.parent.parent)
            return self.generated_output(**arguments)
        previous = os.umask(0o022)
        try:
            q = self.run_queue(generate_resumes=True, selected_role_ids=["role:1"], generate=inspect_workspace, apply=self.applied)
        finally:
            os.umask(previous)
        self.assertEqual(q["records"][0]["status"], "applied")
        self.assertEqual(locations[0].stat().st_mode & 0o777, 0o700)

    def test_selected_optimized_artifact_bound_to_resume_jd_report_and_verified_again(self):
        selected = self.optimized_selection()
        q = self.plan(resume_mode="optimized", optimized_map=selected)
        self.assertEqual(q["records"][0]["resume"]["mode"], "optimized")
        q = self.run_queue(apply=self.applied)
        self.assertEqual(q["records"][0]["status"], "applied")
        self.assertEqual(q["records"][0]["attempts"][0]["resume_sha256"], digest(selected["role:1"]["pdf"]))

    def test_mismatched_optimized_jd_rejected_not_fallback(self):
        selected = self.optimized_selection()
        selected["role:1"]["job_description_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.plan(resume_mode="optimized", optimized_map=selected)
        self.assertFalse(self.queue.exists())

    def test_queue_identity_and_result_provenance_tamper_rejected(self):
        q = self.plan()
        q["records"][0]["role"]["career_url"] = URL
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_queue(q)
        q = self.run_queue(apply=self.applied)
        q["records"][0]["attempts"][0]["job_description_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "provenance"):
            validate_queue(q)

    def test_existing_queue_cannot_be_overwritten(self):
        self.plan()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.plan()

    def test_cleanup_failure_does_not_change_confirmed_submission(self):
        self.plan()
        self.browser.quit.side_effect = RuntimeError("Browser already exited")
        q = self.run_queue(apply=self.applied)
        self.assertEqual(q["records"][0]["status"], "applied")
        self.assertEqual(load_queue(self.queue)["invocations"][-1]["confirmed_count"], 1)

    def test_resume_path_is_present_in_required_private_review(self):
        q = self.plan()
        captured = []
        def fake_apply(driver, url, candidate, pdf, **options):
            options["review"]({"answer_preview": []})
            return ExternalApplicationResult("awaiting_review", url, resume_sha256=digest(pdf))
        run_queue(self.queue, execute=True, browser_factory=lambda: self.browser, review=lambda details: captured.append(details) or "Leave open",
                  verifier=self.verifier, now=NOW, browser_ready=lambda _: None, apply=fake_apply)
        self.assertEqual(captured[0]["answer_preview"][0]["answer"], q["records"][0]["resume"]["pdf"]["path"])
        self.assertIn("Open and review", captured[0]["answer_preview"][0]["reason"])

    def test_result_for_different_ats_job_or_attachment_fails_contract(self):
        self.plan()
        q = self.run_queue(apply=self.applied)
        wrong = deepcopy(q)
        wrong["records"][0]["attempts"][0]["outcome"]["application_link"] = role(9)["career_url"]
        with self.assertRaisesRegex(ValueError, "posting differs"):
            validate_queue(wrong)
        wrong = deepcopy(q)
        wrong["records"][0]["attempts"][0]["outcome"]["resume_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "attachment differs"):
            validate_queue(wrong)

    def test_execute_and_review_explicit_and_no_browser_on_help(self):
        self.plan()
        with self.assertRaisesRegex(ValueError, "execute"):
            run_queue(self.queue)
        with self.assertRaisesRegex(ValueError, "mandatory"):
            run_queue(self.queue, execute=True, browser_factory=lambda: self.browser)
        result = subprocess.run([sys.executable, "direct_apply.py", "--help"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("plan", result.stdout)

    def test_import_is_safe_and_does_not_load_legacy_bot_or_ai_modules(self):
        script = "import sys; import modules.direct_careers_apply; assert 'runAiBot' not in sys.modules; assert 'openai' not in sys.modules; assert 'modules.ai.resume_optimizer' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_candidate_literal_config_has_no_execution_or_api_keys(self):
        (self.root / "personals.py").write_text("first_name = 'Synthetic'\nlast_name='Applicant'\nraise RuntimeError('Do not import')\n")
        (self.root / "questions.py").write_text("desired_salary=123456\nwork_authorization='Yes'\n")
        (self.root / "secrets.py").write_text("username='synthetic@example.test'\npassword='private'\napi_key='private-key'\n")
        candidate = local_candidate(self.root)
        self.assertEqual(candidate["full_name"], "Synthetic Applicant")
        self.assertEqual(candidate["email"], "synthetic@example.test")
        self.assertNotIn("api_key", candidate)
        self.assertNotIn("password", candidate)
        self.assertEqual(candidate["work_authorization"], "Yes")


if __name__ == "__main__":
    unittest.main()
