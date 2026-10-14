"""Configured stage budgets and resumability using real temporary stores."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from config import job_pipeline as configured
from modules.job_pipeline.linkedin import fresh_role
from modules.job_pipeline.models import StageResult
from modules.job_pipeline.service import discover_companies, verify_careers
from modules.job_pipeline.store import PipelineStore


def employer(number, employees=None):
    return {"id": f"company:{number}", "name": f"Company {number}", "domain": f"company{number}.example.com",
            "employee_count": employees, "sources": []}


def roles(company):
    return {"records": [{"id": "role:" + company["id"], "company": company, "company_id": company["id"],
                         "title": "Staff Platform Engineer", "description": "Build software infrastructure",
                         "career_url": "https://" + company["domain"] + "/jobs/platform", "status": "open",
                         "eligible": True, "verified_at": datetime.now(timezone.utc).isoformat()}],
            "errors": [], "complete": True, "status": "hiring"}


class StageConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = str(Path(temporary.name) / "pipeline.sqlite3")
        self.config = {"db_path": self.db, "default_set": "configured", "sources": ["a16z"]}

    def artifact(self, *companies):
        return StageResult.create("companies", "input", "input-run", list(companies))

    def test_target_stops_then_expands_using_saved_cursor_without_losing_companies(self):
        calls = []

        def discover(source, config, *, cursor, limit, **kwargs):
            offset = cursor["offset"] if cursor else 0
            calls.append((offset, limit))
            return {"records": [employer(index) for index in range(offset, offset + limit)],
                    "errors": [], "cursor": {"offset": offset + limit}, "complete": False}

        config = dict(self.config, discovery_limit_per_source=10, discovery_target_companies=2)
        first = discover_companies(config=config, discover=discover)
        unchanged = discover_companies(config=config, discover=discover)
        self.assertEqual(len(first.records), 2)
        self.assertEqual(len(unchanged.records), 2)
        self.assertEqual(calls, [(0, 2)])
        expanded = discover_companies(config=config, target_companies=3, discover=discover)
        self.assertEqual(len(expanded.records), 3)
        self.assertEqual(calls, [(0, 2), (2, 1)])
        self.assertEqual(len(expanded.delta), 1)

    def test_explicit_import_is_preserved_when_it_already_exceeds_target(self):
        adapter = Mock()
        result = discover_companies([self.artifact(employer(1), employer(2))],
                                    config=dict(self.config, discovery_target_companies=1), discover=adapter)
        self.assertEqual(len(result.records), 2)
        adapter.assert_not_called()

    def test_explicit_store_set_and_source_override_unused_invalid_defaults(self):
        unused = {"db_path": "", "default_set": 99, "sources": "broken"}
        result = discover_companies([self.artifact(employer(1))], db_path=self.db, set_name="overridden",
                                    sources=[], config=unused)
        self.assertEqual((result.set_name, len(result.records)), ("overridden", 1))
        verified = verify_careers([self.artifact(employer(1))], db_path=self.db, set_name="verified",
                                  config=unused, verify=Mock(return_value=roles(employer(1))))
        self.assertEqual((verified.set_name, len(verified.records)), ("verified", 1))

    def test_configured_freshness_rechecks_expired_company_and_reaches_linkedin_guard(self):
        company = employer(1, 100)
        adapter = Mock(return_value=roles(company))
        config = dict(self.config, verification_freshness_days=1)
        first = verify_careers([self.artifact(company)], config=config, verify=adapter)
        checked = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with PipelineStore(self.db) as store:
            store.save_checkpoint("verify:" + company["id"], "configured", {"complete": True, "verified_at": checked})
        second = verify_careers([self.artifact(company)], config=config, verify=adapter)
        self.assertEqual(adapter.call_count, 2)
        self.assertNotEqual(first.run_id, second.run_id)
        with patch.object(configured, "verification_freshness_days", 1):
            self.assertFalse(fresh_role({"verified_at": checked}))
        with patch.object(configured, "verification_freshness_days", 3):
            self.assertTrue(fresh_role({"verified_at": checked}))

    def test_cached_roles_use_current_maturity_without_resetting_verification_evidence(self):
        company = employer(1, 60)
        adapter = Mock(return_value=roles(company))
        first = verify_careers([self.artifact(company)], config=self.config, verify=adapter)
        self.assertEqual(first.records[0]["priority_tier"], 1)
        second = verify_careers([self.artifact(company)], config=dict(self.config, established_min_employees=100), verify=adapter)
        self.assertEqual(adapter.call_count, 1)
        self.assertEqual(second.records[0]["priority_tier"], 3)
        self.assertEqual(second.records[0]["verification_run_id"], first.run_id)
        self.assertEqual(second.records[0]["verified_at"], first.records[0]["verified_at"])

    def test_enabled_renderer_is_shared_and_closed_on_interruption(self):
        events, renderer = [], Mock()

        @contextmanager
        def managed(config):
            events.append("entered")
            try:
                yield renderer
            finally:
                events.append("closed")

        def discover(*args, **kwargs):
            self.assertIs(kwargs["render"], renderer)
            raise KeyboardInterrupt()

        with patch("modules.job_pipeline.rendering.public_renderer", managed):
            with self.assertRaises(KeyboardInterrupt):
                discover_companies(config=dict(self.config, discovery_render_enabled=True), discover=discover)
        self.assertEqual(events, ["entered", "closed"])
        with PipelineStore(self.db) as store:
            self.assertEqual(store.connection.execute("SELECT status FROM runs").fetchone()[0], "interrupted")

    def test_rendering_is_disabled_by_default_and_can_be_explicitly_disabled(self):
        adapter = Mock(return_value={"records": [], "errors": [], "cursor": None, "complete": True})
        with patch("modules.job_pipeline.rendering.public_renderer") as factory:
            discover_companies(config=self.config, discover=adapter)
            discover_companies(config=dict(self.config, discovery_render_enabled=True), render_enabled=False,
                               refresh=True, discover=adapter)
        factory.assert_not_called()
        self.assertIsNone(adapter.call_args.kwargs["render"])


if __name__ == "__main__":
    unittest.main()
