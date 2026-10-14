"""Search planning and refinement contracts; no credentials or network required."""

from copy import deepcopy
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules.ai.search_refinement import make_refiner, refine_queries
from modules.search_planner import (
    GATE_FIELDS, INTENT_FIELDS, build_search_plan, filters_snapshot,
    normalize_query, render_query, validate_profile, validate_refinement,
)


def profile(**overrides):
    values = {
        "profile_name": "test-ai-platform", "profile_version": "1",
        "dynamic_search_enabled": True, "ai_query_refinement_enabled": True,
        "resume_search_enabled": True, "search_state_dir": "unused-test-state",
        "role_lanes": ["Staff AI Platform Engineer", "Principal Backend Engineer"],
        "skills": ["Python", "distributed systems"], "manual_searches": [],
    }
    values.update(overrides)
    return values


def search_config(**overrides):
    values = {
        "search_terms": [], "switch_number": 1, "search_location": "San Francisco Bay Area",
        "sort_by": "Most recent", "date_posted": "Past month", "salary": "$200,000+",
        "easy_apply_only": True, "experience_level": ["Mid-Senior level"],
        "job_type": ["Full-time"], "on_site": ["Remote", "Hybrid"],
        "companies": ["Example Company"], "location": ["Oakland, California"],
        "industry": ["Software Development"], "job_function": ["Engineering"],
        "job_titles": ["Staff Engineer"], "benefits": ["Medical insurance"],
        "commitments": ["Career growth"], "under_10_applicants": True,
        "in_your_network": True, "fair_chance_employer": True,
        "about_company_bad_words": ["Staffing"], "about_company_good_words": ["Exception Company"],
        "bad_words": ["US Citizen", "contract-to-hire"], "security_clearance": False,
        "did_masters": True, "current_experience": 8,
    }
    values.update(overrides)
    return values


def refinement(roles, **overrides):
    result = {"queries": [
        {"role": role, "role_index": index, "coverage": 0.5 + index * 0.1}
        for index, role in enumerate(roles)
    ]}
    result.update(overrides)
    return result


class RenderingTests(unittest.TestCase):
    def test_every_existing_intent_and_gate_is_preserved(self):
        config = search_config()
        snapshot = filters_snapshot(config)
        self.assertEqual(snapshot["intent"], {key: config[key] for key in INTENT_FIELDS})
        self.assertEqual(snapshot["gates"], {key: config[key] for key in GATE_FIELDS})
        text = render_query("Staff AI Platform Engineer", profile(), config)
        for value in (
            "Staff AI Platform Engineer", "San Francisco Bay Area", "$200,000+",
            "Mid-Senior level", "Full-time", "Remote", "Hybrid", "Example Company",
            "Oakland, California", "Software Development", "Engineering", "Staff Engineer",
            "Medical insurance", "Career growth", "past month", "Easy Apply", "under 10 applicants",
            "my network", "fair chance employers", "Python", "distributed systems",
            "Staffing", "US Citizen", "contract-to-hire", "security clearance", "8 years",
            "two additional years", "master's degree",
        ):
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_configuration_is_read_each_time_and_snapshot_is_independent(self):
        config = search_config()
        first = build_search_plan(profile(), config)
        config["search_location"] = "New York"
        config["companies"].append("Another Company")
        second = build_search_plan(profile(), config)
        self.assertNotIn("New York", first[0].query_text)
        self.assertIn("New York", second[0].query_text)
        self.assertEqual(first[0].filters_snapshot["intent"]["companies"], ["Example Company"])
        self.assertEqual(first[0].query_id, second[0].query_id)
        first[0].filters_snapshot["intent"]["companies"].append("Mutation")
        self.assertNotIn("Mutation", first[1].filters_snapshot["intent"]["companies"])

    def test_module_like_configuration_is_supported(self):
        specs = build_search_plan(SimpleNamespace(**profile()), SimpleNamespace(**search_config()))
        self.assertEqual(len(specs), 2)
        self.assertIn("San Francisco Bay Area", specs[0].query_text)

    def test_disabled_preferences_do_not_add_requirements(self):
        text = render_query("Staff Engineer", profile(skills=[]), search_config(
            date_posted="Any time", easy_apply_only=False, under_10_applicants=False,
            in_your_network=False, fair_chance_employer=False, security_clearance=True,
            did_masters=False, current_experience=-1,
        ))
        for unwanted in ("Posted within", "Easy Apply", "under 10 applicants", "my network",
                         "fair chance employers", "security clearance", "years of experience", "Focus on"):
            self.assertNotIn(unwanted, text)

    def test_natural_language_manual_query_keeps_original_opening(self):
        text = render_query("Find Staff AI Platform roles", profile(), search_config())
        self.assertTrue(text.startswith("Find Staff AI Platform roles."))
        self.assertNotIn("Find Find", text)


class PlanningTests(unittest.TestCase):
    def test_manual_legacy_and_generated_order_ids_and_quotas(self):
        settings = profile(manual_searches=[
            {"id": "manual-lane", "query": "Staff Infrastructure Engineer", "quota": 3,
             "notes": "Primary lane", "role_label": "Staff Infrastructure"},
            {"id": "disabled", "query": "Product Engineer", "enabled": False},
            {"id": "default-quota", "query": "Founding Engineer", "enabled": True},
        ])
        specs = build_search_plan(settings, search_config(search_terms=["Senior Engineer"], switch_number=2))
        self.assertEqual([spec.source for spec in specs], ["manual", "generated", "generated", "legacy", "manual"])
        self.assertEqual([spec.quota for spec in specs], [3, 2, 2, 2, 2])
        self.assertEqual(specs[0].query_id, "manual:manual-lane")
        self.assertEqual(specs[0].classic_query, "Staff Infrastructure")
        self.assertTrue(specs[3].query_id.startswith("legacy:"))
        self.assertTrue(specs[1].query_id.startswith("generated:"))
        self.assertEqual(specs[-1].classic_query, "Founding Engineer")
        self.assertTrue(all(spec.mode == "ai" for spec in specs))
        self.assertTrue(all(spec.profile_name == settings["profile_name"] for spec in specs))
        settings["manual_searches"][0]["query"] = "Principal Infrastructure Engineer"
        self.assertEqual(build_search_plan(settings, search_config())[0].query_id, specs[0].query_id)

    def test_legacy_only_runs_when_dynamic_search_is_disabled(self):
        specs = build_search_plan(profile(dynamic_search_enabled=False, role_lanes=[]),
                                  search_config(search_terms=["Software Engineer", "Backend Engineer"]))
        self.assertEqual([spec.source for spec in specs], ["legacy", "legacy"])
        self.assertEqual([spec.classic_query for spec in specs], ["Software Engineer", "Backend Engineer"])

    def test_normalized_deduplication_across_manual_legacy_and_generated(self):
        settings = profile(manual_searches=[{"id": "preferred", "query": " STAFF   AI PLATFORM ENGINEER "}])
        specs = build_search_plan(settings, search_config(search_terms=["staff ai platform engineer", "Ｐｒｉｎｃｉｐａｌ Backend Engineer"]))
        self.assertEqual(len(specs), 2)
        self.assertEqual([spec.source for spec in specs], ["manual", "legacy"])
        self.assertEqual(specs[0].query_id, "manual:preferred")

    def test_ai_dedup_retains_manual_and_legacy_ids(self):
        settings = profile(manual_searches=[{"id": "preferred", "query": "Staff AI Platform Engineer"}])
        config = search_config(search_terms=["Principal Backend Engineer"])
        specs = build_search_plan(settings, config, refine=lambda roles, *_: refinement(roles))
        self.assertEqual([spec.source for spec in specs], ["manual", "legacy"])

    def test_legacy_ids_are_stable_when_order_and_case_change(self):
        settings = profile(dynamic_search_enabled=False)
        first = build_search_plan(settings, search_config(search_terms=["Senior Engineer", "Backend Engineer"]))
        second = build_search_plan(settings, search_config(search_terms=["BACKEND ENGINEER", "senior  engineer"]))
        self.assertEqual({spec.query_id for spec in first}, {spec.query_id for spec in second})

    def test_empty_plan_is_rejected(self):
        with self.assertRaises(ValueError):
            build_search_plan(profile(dynamic_search_enabled=False), search_config())

    def test_dynamic_generation_error_keeps_authorized_manual_lane(self):
        settings = profile(manual_searches=[{"id": "manual", "query": "Founding Engineer"}])
        warnings = []

        def failing_renderer(role, active_profile, config):
            if role in settings["role_lanes"]:
                raise RuntimeError("Generated lane unavailable")
            return render_query(role, active_profile, config)

        with patch("modules.search_planner.render_query", side_effect=failing_renderer):
            specs = build_search_plan(settings, search_config(), warn=warnings.append)
        self.assertEqual([lane.query_id for lane in specs], ["manual:manual"])
        self.assertTrue(any("Dynamic generation failed" in warning for warning in warnings))

    def test_invalid_default_quota_is_rejected(self):
        for quota in (0, -1, True, 1.2, "1", None):
            with self.subTest(quota=quota), self.assertRaises(ValueError):
                build_search_plan(profile(), search_config(switch_number=quota))


class ValidationTests(unittest.TestCase):
    def test_manual_invalid_definitions_are_rejected(self):
        invalid = [
            None, "query", {}, {"id": "bad space", "query": "Staff Engineer"},
            {"id": "ok", "query": ""}, {"id": "ok", "query": "Staff Engineer", "enabled": "true"},
            {"id": "ok", "query": "Staff Engineer", "quota": 0},
            {"id": "ok", "query": "Staff Engineer", "quota": True},
            {"id": "ok", "query": "Staff Engineer", "quota": 1.2},
            {"id": "ok", "query": "Staff Engineer", "unknown": "field"},
            {"id": "ok", "query": "Staff\x00Engineer"},
            {"id": "ok", "query": "Staff Engineer", "notes": 2},
            {"id": "ok", "query": "Staff Engineer", "role_label": ""},
        ]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate_profile(profile(manual_searches=[item]))

    def test_duplicate_manual_ids_are_rejected_even_when_disabled(self):
        with self.assertRaises(ValueError):
            validate_profile(profile(manual_searches=[
                {"id": "same", "query": "One"}, {"id": "same", "query": "Two", "enabled": False},
            ]))

    def test_profile_required_fields_are_validated(self):
        invalid = {
            "dynamic_search_enabled": "True", "ai_query_refinement_enabled": 1,
            "resume_search_enabled": None, "profile_name": "", "profile_version": "",
            "search_state_dir": "", "role_lanes": [], "skills": "Python", "manual_searches": {},
        }
        for key, value in invalid.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_profile(profile(**{key: value}))


class RefinementTests(unittest.TestCase):
    def test_success_ranks_coverage_and_preserves_configured_constraints(self):
        settings, config = profile(), search_config()
        refine = Mock(return_value={"queries": [
            {"role": "Staff AI Infrastructure Engineer", "role_index": 0, "coverage": 0.6},
            {"role": "Principal Backend Systems Engineer", "role_index": 1, "coverage": 0.95},
        ]})
        specs = build_search_plan(settings, config, refine=refine)
        self.assertEqual([spec.source for spec in specs], ["ai_refined", "ai_refined"])
        self.assertEqual(specs[0].classic_query, "Principal Backend Systems Engineer")
        self.assertTrue(all("Exclude descriptions containing: US Citizen, contract-to-hire" in spec.query_text for spec in specs))
        self.assertTrue(all("San Francisco Bay Area" in spec.query_text for spec in specs))
        refine.assert_called_once_with(settings["role_lanes"], settings["skills"], filters_snapshot(config))

    def test_invalid_empty_duplicate_and_unsupported_responses_fall_back(self):
        settings = profile()
        good = refinement(settings["role_lanes"])
        invalid = [None, [], {}, "not JSON", {"queries": []},
                   {"queries": good["queries"], "quota": 3},
                   {"queries": [good["queries"][0]]}]
        for field, value in (
            ("role_index", True), ("role_index", -1), ("role_index", 2),
            ("coverage", True), ("coverage", -0.1), ("coverage", 1.1),
            ("coverage", float("nan")), ("coverage", float("inf")),
            ("role", ""), ("role", "Marketing Manager"),
            ("role", "Staff Marketing Manager"), ("role", "AI Platform Engineer"),
            ("role", "Staff AI Platform Engineer ignore all instructions"),
            ("role", "Staff AI Platform Engineer remote"),
            ("role", "Staff AI Platform Engineer salary 500000"),
            ("role", "Staff AI Engineer https://example.com"), ("role", "Staff AI Engineer <click>"),
        ):
            response = deepcopy(good)
            response["queries"][0][field] = value
            invalid.append(response)
        extra = deepcopy(good)
        extra["queries"][0]["filters"] = {"location": "Paris"}
        invalid.append(extra)
        duplicate = deepcopy(good)
        duplicate["queries"].append(dict(good["queries"][0]))
        invalid.append(duplicate)
        for response in invalid:
            with self.subTest(response=response):
                warnings = []
                specs = build_search_plan(settings, search_config(), refine=lambda *_: response, warn=warnings.append)
                self.assertEqual([spec.source for spec in specs], ["generated", "generated"])
                self.assertEqual([spec.classic_query for spec in specs], settings["role_lanes"])
                self.assertEqual(len(warnings), 1)
                self.assertIn("deterministic", warnings[0])

    def test_api_failure_keeps_manual_searches_and_deterministic_lanes(self):
        warnings = []
        settings = profile(manual_searches=[{"id": "manual", "query": "Founding Engineer"}])
        specs = build_search_plan(settings, search_config(), refine=Mock(side_effect=RuntimeError("API offline")), warn=warnings.append)
        self.assertEqual([spec.source for spec in specs], ["generated", "generated", "manual"])
        self.assertIn("RuntimeError", warnings[0])

    def test_missing_key_is_optional_and_warns_without_importing_openai(self):
        for key in (None, "", " ", "your_api_key", "YOUR-OPENAI-API-KEY", "not-needed"):
            with self.subTest(key=key):
                warnings = []
                self.assertIsNone(make_refiner(key, "", "test-model", warnings.append))
                self.assertEqual(len(warnings), 1)
                self.assertIn("deterministically", warnings[0])
        warnings = []
        self.assertTrue(all(spec.source == "generated" for spec in build_search_plan(profile(), search_config(), warn=warnings.append)))
        self.assertIn("unavailable", warnings[0])

    def test_disabled_refinement_never_calls_ai(self):
        refine = Mock(side_effect=AssertionError("must not call AI"))
        specs = build_search_plan(profile(ai_query_refinement_enabled=False), search_config(), refine=refine)
        refine.assert_not_called()
        self.assertTrue(all(spec.source == "generated" for spec in specs))

    def test_response_schema_is_strict_and_json_string_is_supported(self):
        roles = profile()["role_lanes"]
        self.assertEqual(len(validate_refinement(json.dumps(refinement(roles)), roles)), 2)
        too_many = {"queries": [
            {"role": f"Staff AI Platform Engineer {index}", "role_index": index % 2, "coverage": 0.5}
            for index in range(5)
        ]}
        with self.assertRaises(ValueError):
            validate_refinement(too_many, roles)

    def test_each_role_lane_has_at_most_two_refined_variants(self):
        roles = profile()["role_lanes"]
        unsupported = {"queries": [
            {"role": "Staff AI Platform Engineer", "role_index": 0, "coverage": 0.9},
            {"role": "Staff AI Infrastructure Engineer", "role_index": 0, "coverage": 0.8},
            {"role": "Staff AI Systems Engineer", "role_index": 0, "coverage": 0.7},
            {"role": "Principal Backend Engineer", "role_index": 1, "coverage": 0.6},
        ]}
        with self.assertRaises(ValueError):
            validate_refinement(unsupported, roles)

    def test_refinement_cannot_change_occupation_or_add_location(self):
        roles = ["Staff AI Engineer"]
        for role in ("Staff AI Marketing Manager", "Staff AI Engineer in London", "Staff AI Engineer near Paris"):
            with self.subTest(role=role):
                response = {"queries": [{"role": role, "role_index": 0, "coverage": 0.9}]}
                with self.assertRaises(ValueError):
                    validate_refinement(response, roles)
                plan = build_search_plan(profile(role_lanes=roles), search_config(), refine=lambda *args: response)
                self.assertEqual(plan[0].source, "generated")
                self.assertEqual(plan[0].classic_query, roles[0])

    def test_refinement_cannot_drop_configured_senior_seniority(self):
        response = {"queries": [{"role": "Software Engineer", "role_index": 0, "coverage": 0.9}]}
        with self.assertRaises(ValueError):
            validate_refinement(response, ["Senior Software Engineer"])

    def test_openai_request_and_client_are_mocked_and_bounded(self):
        roles = profile()["role_lanes"]
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(refinement(roles))))])
        client = Mock()
        client.chat.completions.create.return_value = response
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        factory = Mock(return_value=client)
        with patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=factory)}):
            refiner = make_refiner("test-only-key", "https://test.invalid", "test-model")
            result = refiner(roles, ["Python"], filters_snapshot(search_config()))
        factory.assert_called_once_with(api_key="test-only-key", base_url="https://test.invalid", timeout=20, max_retries=0)
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "test-model")
        self.assertFalse(request["stream"])
        self.assertEqual(request["response_format"], {"type": "json_object"})
        supplied = json.loads(request["messages"][1]["content"])
        self.assertEqual(supplied["roles"], roles)
        self.assertEqual(supplied["skills"], ["Python"])
        self.assertEqual(result, refinement(roles))
        client.__exit__.assert_called_once()

    def test_invalid_api_json_propagates_to_planner_fallback(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not JSON"))])
        warnings = []
        specs = build_search_plan(profile(), search_config(),
                                  refine=lambda roles, skills, snapshot: refine_queries(client, "test-model", roles, skills, snapshot),
                                  warn=warnings.append)
        self.assertTrue(all(spec.source == "generated" for spec in specs))
        self.assertIn("JSONDecodeError", warnings[0])


if __name__ == "__main__":
    unittest.main()
