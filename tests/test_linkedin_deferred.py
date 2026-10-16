"""Deferred jobs retain tested URLs independently of search result visibility."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from modules.linkedin_deferred import DeferredJobs
from modules.search_history import file_lock


class DeferredJobsTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "deferred" / "jobs.json"
        self.jobs = DeferredJobs(self.path)

    def info(self, **kwargs):
        return {"job_id": "12345", "title": "Staff Engineer", "company": "Example",
                "status": "ready", "submission_disabled": True, "run_id": "run-1",
                "source_report": "test-report.json", **kwargs}

    def test_empty_library_has_no_write_side_effect(self):
        self.assertEqual(self.jobs.summary(), {"path": str(self.path), "count": 0})
        self.assertEqual(self.jobs.records, [])
        self.assertFalse(self.path.exists())

    def test_canonical_url_ignores_untrusted_url_and_round_trips(self):
        result = self.jobs.record(self.info(job_id=12345, job_url="https://example.com/fake"))
        self.assertEqual(result["job_url"], "https://www.linkedin.com/jobs/view/12345/")
        self.assertEqual(result["job_id"], "12345")
        data = json.loads(self.path.read_text())
        self.assertEqual((data["version"], data["purpose"]), (1, "retry_prepared_applications"))
        self.assertEqual(DeferredJobs(self.path).records, self.jobs.records)

    def test_invalid_ids_rejected_without_replacing_library(self):
        self.jobs.record(self.info())
        old = self.path.read_bytes()
        for invalid in (True, False, None, 1.1, "", "  ", "12x", "-1", "12/34", "１２３", []):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.jobs.record(self.info(job_id=invalid))
            self.assertEqual(self.path.read_bytes(), old)

    def test_submission_flag_is_required_and_strictly_typed(self):
        for update in ({"submission_disabled": 1}, {"submission_disabled": "false"},
                       {"submit_enabled": "yes"}, {"submit_enabled": 0}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.jobs.record(self.info(**update))
        missing = self.info()
        missing.pop("submission_disabled")
        with self.assertRaises(ValueError):
            self.jobs.record(missing)
        self.assertFalse(self.path.exists())

    def test_validation_requires_record_and_status(self):
        for invalid in (None, [], {}, self.info(status=""), self.info(status=[])):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.jobs.record(invalid)

    def test_blank_backfill_preserves_description_and_metadata(self):
        self.jobs.record(self.info(description="A real job description", query="AI platforms", profile="staff"))
        self.jobs.record(self.info(description="", title="", company=None, query=""))
        row = self.jobs.records[0]
        self.assertEqual(row["description"], "A real job description")
        self.assertEqual((row["title"], row["company"], row["query"], row["profile"]),
                         ("Staff Engineer", "Example", "AI platforms", "staff"))

    def test_backfill_is_idempotent_and_deduplicates_history(self):
        self.jobs.record(self.info(last_seen="2026-10-15T18:00:00Z"))
        old = self.path.read_bytes()
        with patch("modules.linkedin_deferred.os.replace", side_effect=AssertionError("duplicate must not write")):
            self.jobs.record(self.info(last_seen="2026-10-15T18:00:00Z"))
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(self.jobs.records[0]["history"], [{
            "run_id": "run-1", "source_report": "test-report.json", "status": "ready",
            "submit_enabled": None, "submission_disabled": True, "last_seen": "2026-10-15T18:00:00Z"}])

    def test_normal_and_unknown_historical_run_flags_are_preserved(self):
        self.jobs.record(self.info(submission_disabled=False, submit_enabled=False, status="failed"))
        self.jobs.record(self.info(submission_disabled=None, run_id="old", status="failed"))
        history = self.jobs.records[0]["history"]
        self.assertIs(history[0]["submission_disabled"], False)
        self.assertIs(history[0]["submit_enabled"], False)
        self.assertIsNone(history[1]["submission_disabled"])
        self.assertIsNone(history[1]["submit_enabled"])
        self.assertIsNone(DeferredJobs(self.path).records[0]["submission_disabled"])

    def test_enabled_submit_button_does_not_imply_submission_was_allowed(self):
        self.jobs.record(self.info(submission_disabled=True, submit_enabled=True))
        event = self.jobs.records[0]["history"][0]
        self.assertIs(event["submission_disabled"], True)
        self.assertIs(event["submit_enabled"], True)
        self.assertIs(self.jobs.records[0]["submit_enabled"], True)
        self.jobs.record(self.info(status="failed"))
        self.assertIs(self.jobs.records[0]["submit_enabled"], True)
        self.assertIsNone(self.jobs.records[0]["history"][-1]["submit_enabled"])

    def test_placeholder_description_cannot_replace_known_job_description(self):
        self.jobs.record(self.info(description="Production AI systems"))
        for description in ("Unknown", " N/A ", "unknown", "na"):
            self.jobs.record(self.info(description=description))
        self.assertEqual(self.jobs.records[0]["description"], "Production AI systems")

    def test_interleaved_instances_reload_before_upsert_without_losing_jobs(self):
        other = DeferredJobs(self.path)
        self.jobs.record(self.info())
        other.record(self.info(job_id="23456", title="Principal Engineer"))
        self.jobs.record(self.info(status="failed", reason="Validation failed"))
        self.assertEqual([row["job_id"] for row in DeferredJobs(self.path).records], ["12345", "23456"])
        self.assertEqual(len(self.jobs.records[0]["history"]), 2)
        self.assertEqual(self.jobs.records[1]["title"], "Principal Engineer")

    def test_conflicting_lock_fails_closed_without_overwrite(self):
        self.jobs.record(self.info())
        old, records = self.path.read_bytes(), self.jobs.records
        with file_lock(str(self.path) + ".lock"):
            with self.assertRaises(OSError):
                self.jobs.record(self.info(job_id="23456"))
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(self.jobs.records, records)

    def test_failed_reasons_and_supplied_occurrence_timestamps_survive_upserts(self):
        self.jobs.record(self.info(status="failed", reason="Next blocked", observed_at="2026-10-15T18:00:00Z"))
        self.jobs.record(self.info(status="failed", reason="Cleanup blocked", observed_at="2026-10-15T18:02:00Z"))
        row = self.jobs.records[0]
        self.assertEqual(row["failed_reasons"], ["Next blocked", "Cleanup blocked"])
        self.assertEqual(row["history"][0]["reasons"], ["Next blocked", "Cleanup blocked"])
        self.assertEqual(row["history"][0]["observed_at"], "2026-10-15T18:02:00Z")

    def test_distinct_source_runs_and_outcomes_are_retained(self):
        self.jobs.record(self.info(status="started"))
        self.jobs.record(self.info())
        self.jobs.record(self.info(run_id="run-2"))
        self.jobs.record(self.info(run_id="run-2", source_report="other.json"))
        self.assertEqual(len(self.jobs.records[0]["history"]), 4)
        self.assertEqual(self.jobs.summary()["count"], 1)
        self.jobs.record(self.info(job_id="23456"))
        self.assertEqual([r["job_id"] for r in self.jobs.records], ["12345", "23456"])

    def test_occurrence_time_is_never_invented_and_ingestion_is_current(self):
        row = self.jobs.record(self.info(created_at="1900-01-01", updated_at="1900-01-01"))
        self.assertNotIn("last_seen", row)
        self.assertNotIn("last_seen", row["history"][0])
        self.assertNotEqual(row["created_at"], "1900-01-01")
        self.assertEqual(row["created_at"], row["updated_at"])

    def test_inputs_outputs_and_nested_snapshots_are_independent(self):
        original = self.info(extra={"labels": ["AI"]})
        returned = self.jobs.record(original)
        original["extra"]["labels"].append("mutated")
        returned["history"].clear()
        snapshot = self.jobs.records
        snapshot[0]["extra"]["labels"].clear()
        self.assertEqual(self.jobs.records[0]["extra"], {"labels": ["AI"]})
        self.assertEqual(len(self.jobs.records[0]["history"]), 1)

    def test_encode_and_replace_failure_preserve_disk_and_memory(self):
        self.jobs.record(self.info())
        old, records = self.path.read_bytes(), self.jobs.records
        for value in (object(), float("nan")):
            with self.subTest(value=type(value).__name__), self.assertRaises((TypeError, ValueError)):
                self.jobs.record(self.info(description=value))
            self.assertEqual(self.path.read_bytes(), old)
            self.assertEqual(self.jobs.records, records)
        with patch("modules.linkedin_deferred.os.replace", side_effect=OSError("disk error")):
            with self.assertRaisesRegex(OSError, "disk error"):
                self.jobs.record(self.info(job_id="23456"))
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(self.jobs.records, records)
        self.assertEqual(set(self.path.parent.iterdir()), {self.path, Path(str(self.path) + ".lock")})

    def test_publishes_complete_json_from_same_directory_and_fsyncs(self):
        replace, fsync = os.replace, os.fsync
        published = []
        def verify(source, target):
            self.assertEqual(Path(source).parent, self.path.parent)
            self.assertEqual(Path(target), self.path)
            published.append(json.loads(Path(source).read_text())["records"][0]["job_id"])
            return replace(source, target)
        with patch("modules.linkedin_deferred.os.replace", side_effect=verify), \
                patch("modules.linkedin_deferred.os.fsync", wraps=fsync) as flush:
            self.jobs.record(self.info())
        self.assertEqual(published, ["12345"])
        flush.assert_called_once()

    def test_corrupt_existing_library_is_not_silently_overwritten(self):
        self.path.parent.mkdir()
        for content in ("garbage", '{"version": 2}', '{"version": 1, "purpose": "retry_prepared_applications", "records": [{}]}'):
            self.path.write_text(content)
            with self.subTest(content=content), self.assertRaises((ValueError, TypeError)):
                DeferredJobs(self.path)
            self.assertEqual(self.path.read_text(), content)

    def test_markdown_export_escapes_table_and_omits_description(self):
        self.jobs.record(self.info(title="Staff | Engineer\nAI", company="Example\rLabs", description="Private JD body"))
        target = self.root / "index.md"
        self.assertEqual(self.jobs.export_markdown(target), target)
        text = target.read_text()
        self.assertIn("Staff \\| Engineer AI", text)
        self.assertIn("Example Labs", text)
        self.assertIn("https://www.linkedin.com/jobs/view/12345/", text)
        self.assertNotIn("Private JD body", text)
        old = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.jobs.export_markdown(self.path)
        self.assertEqual(self.path.read_bytes(), old)

    def test_stale_instance_exports_latest_committed_records_under_writer_lock(self):
        stale = DeferredJobs(self.path)
        self.jobs.record(self.info())
        stale.record(self.info(job_id="23456", title="Principal Engineer"))
        self.jobs.record(self.info(job_id="34567", title="AI Engineer"))
        target = self.root / "index.md"
        original = os.replace
        def verify_lock(source, destination):
            with self.assertRaises(OSError):
                with file_lock(str(self.path) + ".lock"):
                    self.fail("export did not hold the writer lock")
            return original(source, destination)
        with patch("modules.linkedin_deferred.os.replace", side_effect=verify_lock):
            stale.export_markdown(target)
        for job_id in ("12345", "23456", "34567"):
            self.assertIn("/" + job_id + "/", target.read_text())
        self.assertEqual(stale.records, self.jobs.records)

    def test_markdown_export_cannot_replace_writer_lock(self):
        self.jobs.record(self.info())
        with self.assertRaises(ValueError):
            self.jobs.export_markdown(str(self.path) + ".lock")


if __name__ == "__main__":
    unittest.main()
