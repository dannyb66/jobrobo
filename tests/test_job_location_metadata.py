"""Location evidence stays separate from company names in current job cards."""

import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from modules.job_pipeline.careers import location_reasons


class MissingElement(Exception):
    pass


class JobLocationTests(unittest.TestCase):
    location = "San Francisco Bay Area, United States"

    def test_out_of_area_office_jobs_are_excluded(self):
        for style in ("Hybrid", "On-site", "Unknown"):
            with self.subTest(style=style):
                self.assertEqual(location_reasons(["Covington, LA"], style, self.location), ["location_excluded"])

    def test_bay_area_offices_and_us_remote_policy_are_preserved(self):
        for locations, style in ((["Oakland, CA"], "Hybrid"), (["San Francisco Bay Area"], "On-site"), (["United States"], "Remote")):
            with self.subTest(locations=locations, style=style):
                self.assertEqual(location_reasons(locations, style, self.location), [])

    def test_missing_geographic_evidence_is_rejected(self):
        for location in ("", "Unknown", "Remote", "Hybrid", "N/A", "Not Available"):
            with self.subTest(location=location):
                self.assertEqual(location_reasons([location], "Unknown", self.location), ["unknown_location"])

    def test_empty_location_disables_only_geographic_gate(self):
        self.assertEqual(location_reasons(["Covington, LA"], "Hybrid", ""), [])


class JobCardMetadataTests(unittest.TestCase):
    def details(self, subtitle, caption=None):
        anchor = SimpleNamespace(text="Staff Engineer\nAdditional text", click=Mock())

        class Card:
            def get_dom_attribute(self, name):
                return "123"

            def find_element(self, by, name):
                if by == "tag" and name == "a":
                    return anchor
                if name == "artdeco-entity-lockup__subtitle":
                    return SimpleNamespace(text=subtitle)
                if name == "artdeco-entity-lockup__caption" and caption is not None:
                    return SimpleNamespace(text=caption)
                raise MissingElement(name)

        path = Path(__file__).resolve().parents[1] / "runAiBot.py"
        node = next(node for node in ast.parse(path.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == "get_job_main_details")
        node.returns = None
        for argument in [*node.args.args, *node.args.kwonlyargs]:
            argument.annotation = None
        namespace = {"re": re, "By": SimpleNamespace(TAG_NAME="tag", CLASS_NAME="class"), "scroll_to_view": Mock(), "buffer": Mock(), "click_gap": 0, "print_lg": Mock(), "driver": Mock(), "discard_job": Mock(), "NoSuchElementException": MissingElement}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), "exec"), namespace)
        result = namespace["get_job_main_details"](Card(), set(), set())
        anchor.click.assert_called_once()
        return result

    def test_separate_company_and_location_caption(self):
        result = self.details("MEDTRON Software Intelligence Corporation", "Covington, LA (Hybrid)")
        self.assertEqual(result[2:5], ("MEDTRON Software Intelligence Corporation", "Covington, LA", "Hybrid"))

    def test_legacy_combined_subtitle(self):
        result = self.details("Example · San Francisco, CA (Remote)")
        self.assertEqual(result[2:5], ("Example", "San Francisco, CA", "Remote"))

    def test_multiline_subtitle(self):
        result = self.details("Example\nOakland, CA (On-site)")
        self.assertEqual(result[2:5], ("Example", "Oakland, CA", "On-site"))

    def test_missing_location_remains_unknown(self):
        result = self.details("Example")
        self.assertEqual(result[2:5], ("Example", "", "Unknown"))


if __name__ == "__main__":
    unittest.main()
