"""Stage configuration and conservative company-priority contracts."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules.job_pipeline.settings import (
    company_maturity, employee_count_lower_bound, prioritize_companies,
    resolve_config,
)


class ConfigurationTests(unittest.TestCase):
    def test_settings_import_does_not_load_runtime_or_configuration(self):
        script = """
import sys
from modules.job_pipeline import settings
for name in ('config.job_pipeline', 'selenium', 'pyautogui', 'openai', 'requests', 'modules.open_chrome'):
    assert name not in sys.modules, name
assert settings.resolve_config({}, 'discovery')['discovery_limit_per_source'] == 50
assert 'config.job_pipeline' not in sys.modules
"""
        result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_none_loads_current_configuration_lazily(self):
        from config import job_pipeline
        with patch.object(job_pipeline, "verification_limit_companies", 17, create=True):
            self.assertEqual(resolve_config(None, "verification")["verification_limit_companies"], 17)

    def test_partial_configuration_uses_new_stage_defaults(self):
        discovery = resolve_config({}, "discovery")
        verification = resolve_config({}, "verification")
        self.assertEqual(discovery["discovery_limit_per_source"], 50)
        self.assertEqual(discovery["discovery_target_companies"], 250)
        self.assertEqual(verification["verification_limit_companies"], 25)
        self.assertEqual(verification["verification_freshness_days"], 7)

    def test_legacy_limit_is_fallback_and_explicit_stage_budget_wins(self):
        for stage, field in (("discovery", "discovery_limit_per_source"),
                             ("verification", "verification_limit_companies")):
            with self.subTest(stage=stage):
                self.assertEqual(resolve_config({"default_limit": 9}, stage)[field], 9)
                self.assertEqual(resolve_config({"default_limit": 9, field: 12}, stage)[field], 12)

    def test_module_and_mapping_inputs_preserve_adapter_options(self):
        supplied = SimpleNamespace(discovery_limit_per_source=31, request_timeout=8,
                                   source_config={"yc": {"url": "https://example.org/directory"}})
        resolved = resolve_config(supplied)
        self.assertEqual(resolved["discovery_limit_per_source"], 31)
        self.assertEqual(resolved["request_timeout"], 8)
        resolved["source_config"]["yc"]["url"] = "https://changed.example.org"
        self.assertEqual(supplied.source_config["yc"]["url"], "https://example.org/directory")

    def test_defaults_and_source_collections_are_not_shared(self):
        supplied = {"sources": ["a16z", "yc", "a16z"], "discovery_source_limits": {"a16z": 100}}
        resolved = resolve_config(supplied)
        self.assertEqual(resolved["sources"], ["a16z", "yc"])
        resolved["sources"].append("hn")
        resolved["discovery_source_limits"]["a16z"] = 2
        self.assertEqual(supplied["sources"], ["a16z", "yc", "a16z"])
        self.assertEqual(supplied["discovery_source_limits"]["a16z"], 100)
        self.assertEqual(resolve_config({})["discovery_source_limits"], {})

    def test_stage_budgets_reject_bools_zero_negative_strings_and_floats(self):
        for stage, field in (("discovery", "discovery_limit_per_source"),
                             ("verification", "verification_limit_companies")):
            for value in (True, False, 0, -1, "50", 1.5, None):
                with self.subTest(stage=stage, value=value), self.assertRaisesRegex(ValueError, field):
                    resolve_config({field: value}, stage)

    def test_target_can_be_disabled_and_other_targets_are_positive_integers(self):
        self.assertIsNone(resolve_config({"discovery_target_companies": None})["discovery_target_companies"])
        for value in (True, 0, -1, "250", 1.5):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "discovery_target_companies"):
                resolve_config({"discovery_target_companies": value})

    def test_per_source_limits_and_options_are_validated(self):
        for value in (None, [], {"a16z": True}, {"yc": 0}, {"unknown": 50}, {"yc": "10"}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "discovery_source_limits"):
                resolve_config({"discovery_source_limits": value})
        for value in (None, [], {"yc": 50}, {"unknown": {}}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "source_config"):
                resolve_config({"source_config": value})

    def test_sources_require_a_sequence_of_supported_names(self):
        self.assertEqual(resolve_config({"sources": []})["sources"], [])
        for value in ("yc", {"yc": {}}, [True], ["unknown"], None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "sources"):
                resolve_config({"sources": value})

    def test_selected_stage_validates_booleans(self):
        for stage in ("discovery", "verification"):
            fields = [stage + "_refresh", stage + "_render_enabled"]
            if stage == "verification":
                fields.append("verification_prioritize_established")
            for field in fields:
                for value in (0, 1, "true", None):
                    with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, field):
                        resolve_config({field: value}, stage)

    def test_only_selected_stage_fields_are_validated(self):
        resolve_config({"verification_limit_companies": False, "verification_freshness_days": "old"})
        resolve_config({"sources": "broken", "discovery_source_limits": [],
                        "discovery_limit_per_source": False}, "verification")

    def test_render_settings_have_finite_positive_bounds_when_enabled(self):
        resolve_config({"discovery_render_enabled": True, "public_render_max_pages": 3,
                        "public_render_timeout_seconds": 0.5})
        for stage in ("discovery", "verification"):
            for field, values in (("public_render_max_pages", [True, 0, -1, 1.5, "5"]),
                                  ("public_render_timeout_seconds", [True, 0, -1, "15", float("inf"), float("nan")])):
                for value in values:
                    with self.subTest(stage=stage, field=field, value=value), self.assertRaisesRegex(ValueError, field):
                        resolve_config({stage + "_render_enabled": True, field: value}, stage)
        # A disabled renderer is not a dependency of the selected HTTP stage.
        resolve_config({"public_render_max_pages": None, "public_render_timeout_seconds": "unused"})

    def test_verification_freshness_and_maturity_threshold_are_positive_integers(self):
        for field in ("verification_freshness_days", "established_min_employees"):
            for value in (True, 0, -1, "7", 0.5, None):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, field):
                    resolve_config({field: value}, "verification")

    def test_funding_stages_are_recognized_and_can_be_disabled(self):
        resolved = resolve_config({"established_funding_stages": []}, "verification")
        self.assertEqual(resolved["established_funding_stages"], [])
        for value in (None, "Series B", [True], [""], ["unproven"]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "established_funding_stages"):
                resolve_config({"established_funding_stages": value}, "verification")

    def test_bad_config_and_unknown_stage_raise_helpful_validation_errors(self):
        for config in (True, [], "config"):
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, "configuration"):
                resolve_config(config)
        for stage in ("apply", "companies", [], None):
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "stage"):
                resolve_config({}, stage)


class CompanyPriorityTests(unittest.TestCase):
    def test_counts_ranges_and_thresholds_are_conservative(self):
        for value, expected in ((50, 50), ("50+", 50), ("51-200", 51), ("50 – 99 employees", 50),
                                ("1,001 to 5,000", 1001), ("200—500", 200)):
            with self.subTest(value=value):
                self.assertEqual(employee_count_lower_bound(value), expected)
                self.assertEqual(company_maturity({"employee_count": value}, {}), "established")
        self.assertEqual(company_maturity({"employee_count": "1-100"}, {}), "early")
        self.assertEqual(company_maturity({"employee_count": 99}, {"established_min_employees": 100}), "early")

    def test_invalid_counts_and_unsourced_description_claims_stay_unknown(self):
        for value in (True, -1, 1.5, "many", "100-50", "1,,000", "more than 100", None):
            with self.subTest(value=value):
                self.assertIsNone(employee_count_lower_bound(value))
                self.assertEqual(company_maturity({"employee_count": value}, {}), "unknown")
        self.assertEqual(company_maturity({"name": "Big Public AI", "description": "Series C with 500 employees"}, {}), "unknown")

    def test_recognized_funding_establishes_maturity_and_unknown_labels_do_not(self):
        for stage in ("Series B", " series   C ", "Series Z+", "Series D round", "IPO", "Post-IPO", "Publicly traded"):
            with self.subTest(stage=stage):
                self.assertEqual(company_maturity({"funding_stage": stage}, {}), "established")
        for stage in ("Pre-seed", "Seed", "Series A"):
            with self.subTest(stage=stage):
                self.assertEqual(company_maturity({"funding_stage": stage}, {}), "early")
        for stage in ("Public benefit corporation", "unknown", "not Series B", "Series B rumor", None):
            with self.subTest(stage=stage):
                self.assertEqual(company_maturity({"funding_stage": stage}, {}), "unknown")

    def test_configured_funding_and_count_evidence_both_apply(self):
        self.assertEqual(company_maturity({"funding_stage": "Series B"}, {"established_funding_stages": ["Series C"]}), "unknown")
        self.assertEqual(company_maturity({"funding_stage": "Series A"}, {"established_funding_stages": ["Series A"]}), "established")
        self.assertEqual(company_maturity({"employee_count": 100, "funding_stage": "Seed"}, {}), "established")
        self.assertEqual(company_maturity({"employee_count": 10, "funding_stage": "Series B"}, {}), "established")

    def test_careers_priority_uses_configured_maturity_thresholds(self):
        from modules.job_pipeline.careers import priority_tier
        self.assertEqual(priority_tier({"employee_count": 75}, "Staff Platform Engineer", {}), 1)
        self.assertEqual(priority_tier({"employee_count": 75}, "Staff Platform Engineer",
                                       {"established_min_employees": 100}), 3)
        self.assertEqual(priority_tier({"funding_stage": "Series B"}, "Principal Systems Engineer",
                                       {"established_funding_stages": ["Series C"]}), 4)
        self.assertEqual(priority_tier({"funding_stage": "Series A"}, "Principal Systems Engineer",
                                       {"established_funding_stages": ["Series A"]}), 1)
        self.assertEqual(priority_tier({"employee_count": 75}, "Member of Technical Staff", {}), 2)
        self.assertEqual(priority_tier({"employee_count": 75}, "Founding Engineer", {}), 3)

    def test_priority_is_stable_within_each_bucket_and_does_not_mutate_records(self):
        records = [
            {"id": "unknown-one"}, {"id": "early-one", "employee_count": 10},
            {"id": "established-one", "funding_stage": "Series C"},
            {"id": "unknown-two"}, {"id": "established-two", "employee_count": 100},
            {"id": "early-two", "funding_stage": "Seed"},
        ]
        before = deepcopy(records)
        prioritized = prioritize_companies(iter(records), {})
        self.assertEqual([row["id"] for row in prioritized], [
            "established-one", "established-two", "early-one", "early-two", "unknown-one", "unknown-two",
        ])
        self.assertIs(prioritized[0], records[2])
        self.assertEqual(records, before)
        self.assertEqual(prioritize_companies(records, {"verification_prioritize_established": False}), records)


if __name__ == "__main__":
    unittest.main()
