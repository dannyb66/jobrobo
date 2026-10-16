"""Preparation reporting is isolated from browser and applied-job history."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from modules.linkedin_preparation_report import PreparationReport


class PreparationReportTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "reports" / "prepare.json"
        self.report = PreparationReport(self.path, 2)

    def stored(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_limit_validation_and_empty_summary_have_no_file_side_effects(self):
        for limit in (True, False, None, 0, -1, 1.0, "10"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                PreparationReport(self.path, limit)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.report.summary(), {
            "submission_disabled": True, "limit": 2, "attempted": 0,
            "ready": 0, "failed": 0, "in_progress": 0, "records": [],
        })

    def test_interruption_leaves_started_attempt_durably_visible(self):
        self.report.record({"job_id": "101", "status": "started", "title": "Staff Engineer",
                            "query": "AI systems", "page": 2})
        persisted = self.stored()
        self.assertEqual((persisted["attempted"], persisted["in_progress"]), (1, 1))
        self.assertEqual(persisted["records"][0]["status"], "started")
        self.assertTrue(persisted["submission_disabled"])

    def test_outcome_upserts_preserve_audit_metadata_and_attempt_order(self):
        self.report.record({"job_id": "101", "status": "started", "title": "Staff Engineer",
                            "company": "Example", "query": "AI", "page": 1})
        self.report.record({"job_id": "102", "status": "started", "title": "Principal Engineer"})
        self.report.record({"job_id": "101", "status": "ready", "screenshot": "review.png",
                            "defaulted_questions": ["Preferred interview format"]})
        self.report.record({"job_id": "102", "status": "failed", "reason": "Required field blocked Next"})
        summary = self.stored()
        self.assertEqual((summary["attempted"], summary["ready"], summary["failed"], summary["in_progress"]), (2, 1, 1, 0))
        self.assertEqual([row["job_id"] for row in summary["records"]], ["101", "102"])
        self.assertEqual(summary["records"][0]["company"], "Example")
        self.assertEqual(summary["records"][1]["title"], "Principal Engineer")
        self.assertEqual(summary, self.report.summary())

    def test_duplicate_job_counts_once_and_terminal_updates_work_at_limit(self):
        self.report.record({"job_id": 101, "status": "started"})
        self.report.record({"job_id": "101", "status": "started"})
        self.assertEqual(self.report.attempted, 1)
        self.assertFalse(self.report.limit_reached)
        self.report.record({"job_id": "102", "status": "started"})
        self.assertTrue(self.report.limit_reached)
        self.report.record({"job_id": "102", "status": "ready"})
        self.assertEqual(self.report.attempted, 2)
        self.assertTrue(self.report.limit_reached)

    def test_limit_reached_remains_true_if_caller_reports_an_extra_attempt(self):
        for job_id in ("101", "102", "103"):
            self.report.record({"job_id": job_id, "status": "started"})
        self.assertTrue(self.report.limit_reached)
        self.assertEqual(self.report.attempted, 3)

    def test_ready_then_failed_preserves_preparation_evidence(self):
        self.report.record({"job_id": "101", "status": "ready", "screenshot": "review.png", "title": "Engineer"})
        self.report.record({"job_id": "101", "status": "failed", "reason": "Dialog closed during evidence capture"})
        self.assertEqual(self.report.records[0]["screenshot"], "review.png")
        self.assertEqual((self.report.summary()["ready"], self.report.summary()["failed"]), (0, 1))

    def test_invalid_records_preserve_previous_snapshot(self):
        self.report.record({"job_id": "101", "status": "started"})
        original = self.path.read_bytes()
        for entry in (None, [], {}, {"job_id": " ", "status": "started"},
                      {"job_id": True, "status": "started"}, {"job_id": "102", "status": "applied"},
                      {"job_id": "102", "status": []}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                self.report.record(entry)
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(self.report.attempted, 1)

    def test_serialization_failure_keeps_old_disk_and_memory_unchanged(self):
        self.report.record({"job_id": "101", "status": "started", "company": "Example"})
        original, summary = self.path.read_bytes(), self.report.summary()
        for unsupported in (object(), float("nan")):
            with self.subTest(value=type(unsupported).__name__), self.assertRaises((TypeError, ValueError)):
                self.report.record({"job_id": "101", "status": "ready", "extra": unsupported})
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(self.report.summary(), summary)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_existing_external_report_is_preserved_when_first_record_cannot_encode(self):
        self.path.parent.mkdir()
        self.path.write_text('{"previous": "report"}\n', encoding="utf-8")
        original = self.path.read_bytes()
        with self.assertRaises(TypeError):
            self.report.record({"job_id": "101", "status": "started", "extra": object()})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.report.attempted, 0)

    def test_replace_failure_preserves_old_report_and_removes_temporary_file(self):
        self.report.record({"job_id": "101", "status": "started"})
        original, summary = self.path.read_bytes(), self.report.summary()
        with patch("modules.linkedin_preparation_report.os.replace", side_effect=OSError("disk error")):
            with self.assertRaisesRegex(OSError, "disk error"):
                self.report.record({"job_id": "102", "status": "started"})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.report.summary(), summary)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])

    def test_report_is_atomically_published_from_fully_encoded_same_directory_file(self):
        import os
        replace = os.replace
        observed = []
        def check_before_replace(source, target):
            self.assertEqual(Path(source).parent, self.path.parent)
            self.assertEqual(Path(target), self.path)
            observed.append(json.loads(Path(source).read_text(encoding="utf-8"))["records"][0]["status"])
            return replace(source, target)
        with patch("modules.linkedin_preparation_report.os.replace", side_effect=check_before_replace):
            self.report.record({"job_id": "101", "status": "started"})
            self.report.record({"job_id": "101", "status": "ready"})
        self.assertEqual(observed, ["started", "ready"])

    def test_mutating_inputs_or_public_snapshots_does_not_change_report(self):
        original = {"job_id": "101", "status": "started", "defaulted_questions": ["Format"]}
        returned = self.report.record(original)
        original["defaulted_questions"].append("Changed")
        returned["status"] = "failed"
        self.report.records[0]["defaulted_questions"].append("Changed again")
        self.report.summary()["records"].clear()
        self.assertEqual(self.report.records[0]["defaulted_questions"], ["Format"])
        self.assertEqual(self.report.records[0]["status"], "started")

    def test_only_requested_report_file_is_written(self):
        history = self.root / "applied.csv"
        history.write_text("Job ID\nexisting\n", encoding="utf-8")
        self.report.record({"job_id": "101", "status": "ready"})
        self.assertEqual(history.read_text(encoding="utf-8"), "Job ID\nexisting\n")
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()),
                         ["applied.csv", "reports/prepare.json"])


if __name__ == "__main__":
    unittest.main()
