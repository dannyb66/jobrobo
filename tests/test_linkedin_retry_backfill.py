"""Offline fixtures prove retry recovery dates, provenance and applied exclusions."""

import json
from pathlib import Path
import tempfile
import unittest

from modules.linkedin_deferred import DeferredJobs
from scripts.backfill_linkedin_retries import backfill, collect_retry_records


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.logs = self.root / "logs"
        (self.logs / "search_runs").mkdir(parents=True)
        (self.logs / "form_validations").mkdir()
        self.history = self.root / "applied.csv"
        self.history.write_text("Company,Date Applied,Job ID\nExample,2026-10-15,900\nPending,Pending,901\n", encoding="utf-8")
        self.options = {"day": "2026-10-15", "applied_history": self.history}

    def write(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def manifest(self, name="current", *, started="2026-10-16T01:00:00+00:00", jobs=None, prepare=False):
        data = {"run_id": name, "started_at": started, "configuration_id": "config:prepare-only:10" if prepare else "config",
                "queries": [{"spec": {"query_id": "manual:test", "query_text": "Find Staff engineering", "mode": "ai"},
                             "jobs": jobs if jobs is not None else {"100": {"status": "failed", "reason": "Review blocked", "updated_at": "2026-10-16T01:10:00+00:00"}}}]}
        self.write(self.logs / "search_runs" / (name + ".json"), data)
        return data

    def collect(self, **kwargs):
        return collect_retry_records(self.logs, **{**self.options, **kwargs})

    def test_target_date_uses_local_timezone_and_skips_old_and_next_day_runs(self):
        self.manifest()
        self.manifest("old", started="2026-10-15T06:59:59+00:00", jobs={"200": {"status": "failed"}})
        self.manifest("future", started="2026-10-16T07:00:00+00:00", jobs={"300": {"status": "failed"}})
        records = self.collect()
        self.assertEqual([row["job_id"] for row in records], ["100"])
        self.assertIsNone(records[0]["submission_disabled"])
        self.assertTrue(records[0]["requires_submission_check"])
        self.assertEqual(records[0]["last_seen"], "2026-10-16T01:10:00+00:00")
        self.assertEqual(records[0]["query_id"], "manual:test")

    def test_header_safe_applied_ids_and_applied_checkpoints_are_excluded(self):
        self.manifest(jobs={"900": {"status": "failed"}, "901": {"status": "prepared"}, "902": {"status": "submitting"}, "903": {"status": "in_progress"}, "904": {"status": "skipped"}})
        self.manifest("later", jobs={"902": {"status": "applied"}})
        self.assertEqual({row["job_id"] for row in self.collect()}, {"901", "903"})

    def test_preparation_report_preserves_ready_reason_and_observed_button_enabled(self):
        self.manifest(prepare=True)
        self.write(self.logs / "form_validations/current.json", {"submission_disabled": True, "records": [
            {"job_id": "100", "status": "failed", "reason": "Missing references", "title": "Staff Engineer", "query_id": "manual:test"},
            {"job_id": "101", "status": "ready", "submit_enabled": True, "personal_answers": "must not copy"}]})
        records = self.collect()
        self.assertTrue(all(row["submission_disabled"] is True for row in records))
        self.assertTrue(all(row["requires_submission_check"] is False for row in records))
        ready = next(row for row in records if row["job_id"] == "101")
        self.assertTrue(ready["submit_enabled"])
        self.assertNotIn("personal_answers", ready)
        self.assertNotIn("last_seen", ready)
        self.assertEqual(ready["source_run_started_at"], "2026-10-16T01:00:00+00:00")
        failed = next(row for row in records if row.get("reason") == "Missing references")
        self.assertEqual(failed["last_seen"], "2026-10-16T01:10:00+00:00")

    def test_title_enrichment_and_readiness_evidence_recover_direct_urls(self):
        (self.logs / "log.txt").write_text('Trying to Apply to "Staff AI | Example Corp" job. Job ID: 777\n', encoding="utf-8")
        evidence = self.write(self.root / "readiness.json", [{"observed_at": "2026-10-16T01:12:00Z", "stage": "submit_ready", "path": "https://www.linkedin.com/jobs/view/777/", "submit_enabled": True, "employer_submissions": 0}])
        record = self.collect(readiness=evidence)[0]
        self.assertEqual((record["title"], record["company"]), ("Staff AI", "Example Corp"))
        self.assertEqual(record["job_url"], "https://www.linkedin.com/jobs/view/777/")
        self.assertEqual(record["status"], "ready")
        self.assertTrue(record["submission_disabled"])
        self.assertTrue(record["submit_enabled"])

    def test_only_explicit_zero_submission_ready_evidence_is_classified_safe(self):
        evidence = self.write(self.root / "readiness.json", [
            {"observed_at": "2026-10-16T01:12:00Z", "stage": stage, "path": "https://www.linkedin.com/jobs/view/777/", "employer_submissions": count}
            for stage, count in [("submit_ready", 1), ("open", 0), ("submit_ready", False)]])
        self.assertEqual(self.collect(readiness=evidence), [])

    def test_chronological_merge_is_idempotent_and_keeps_failed_reasons(self):
        self.manifest(prepare=True)
        self.write(self.logs / "form_validations/current.json", {"submission_disabled": True, "records": [{"job_id": "100", "status": "ready", "submit_enabled": True}]})
        output = self.root / "archive.json"
        first = backfill(self.logs, output=output, **self.options)
        second = backfill(self.logs, output=output, **self.options)
        self.assertEqual(first, second)
        archive = DeferredJobs(output)
        self.assertEqual(len(archive.records), 1)
        self.assertEqual(archive.records[0]["status"], "ready")
        self.assertEqual(archive.records[0]["failed_reasons"], ["Review blocked"])
        self.assertEqual(len(archive.records[0]["history"]), 2)
        self.assertIn("https://www.linkedin.com/jobs/view/100/", output.with_suffix(".md").read_text())

    def test_bad_json_or_timestamps_fail_before_writing_an_archive(self):
        self.manifest()
        path = self.logs / "form_validations/current.json"
        path.write_text('{"secret": "DO_NOT_EXPOSE",', encoding="utf-8")
        output = self.root / "archive.json"
        with self.assertRaises(ValueError) as caught:
            backfill(self.logs, output=output, **self.options)
        self.assertNotIn("DO_NOT_EXPOSE", str(caught.exception))
        self.assertFalse(output.exists())
        path.unlink()
        self.manifest("invalid", started="2026-10-16T01:00:00")
        with self.assertRaisesRegex(ValueError, "timestamp"):
            self.collect()

    def test_invalid_report_flags_and_lookalike_readiness_host_are_rejected(self):
        self.manifest()
        self.write(self.logs / "form_validations/current.json", {"submission_disabled": True, "records": [{"job_id": "100", "status": "ready", "submit_enabled": "true"}]})
        with self.assertRaisesRegex(ValueError, "flags"):
            self.collect()
        (self.logs / "form_validations/current.json").unlink()
        evidence = self.write(self.root / "readiness.json", [{"observed_at": "2026-10-16T01:12:00Z", "stage": "submit_ready", "path": "https://www.linkedin.com.evil.test/jobs/view/777/", "employer_submissions": 0}])
        with self.assertRaisesRegex(ValueError, "URL"):
            self.collect(readiness=evidence)

    def test_invalid_date_or_timezone_is_sanitized(self):
        for kwargs in ({"day": "tomorrow"}, {"timezone_name": "Not/AZone"}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "date or timezone"):
                self.collect(**kwargs)

    def test_malformed_query_and_url_types_raise_sanitized_value_error(self):
        manifest = self.manifest()
        manifest["queries"][0]["spec"]["query_id"] = ["invalid"]
        self.write(self.logs / "search_runs/current.json", manifest)
        with self.assertRaisesRegex(ValueError, "query identity"):
            self.collect()
        self.manifest()
        evidence = self.write(self.root / "readiness.json", [{"observed_at": "2026-10-16T01:12:00Z", "stage": "submit_ready", "path": {"private": "not printed"}, "employer_submissions": 0}])
        with self.assertRaisesRegex(ValueError, "URL") as caught:
            self.collect(readiness=evidence)
        self.assertNotIn("not printed", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
