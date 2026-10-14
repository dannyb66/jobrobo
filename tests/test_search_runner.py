"""Exercise the real runner loop without importing its browser/secrets bootstrap."""

import ast
import csv
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from modules.linkedin_search import SearchResult, apply_configured_filters
from modules.search_history import append_history, load_applied_job_ids, search_metadata
from modules.search_planner import SearchSpec
from modules.search_state import SearchManifest, plan_fingerprint
from modules.resume_upload import ResumeUploadError


RUNNER = Path(__file__).resolve().parents[1] / "runAiBot.py"


class MissingElement(Exception):
    pass


def extract_functions(namespace, *names):
    """Compile only requested functions, skipping all import/bootstrap side effects."""
    parsed = ast.parse(RUNNER.read_text())
    functions = [node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(functions) != len(names):
        raise AssertionError("Requested runner function is missing")
    for function in functions:
        function.returns = None
        for argument in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]:
            argument.annotation = None
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(module, str(RUNNER), "exec"), namespace)


def spec(query_id, quota=1):
    return SearchSpec(query_id, f"Find {query_id} roles in California.", "manual", "ai",
                      "test-profile", "1", {"intent": {}, "gates": {}}, quota, query_id)


class Job:
    def __init__(self, job_id):
        self.job_id = job_id

    def get_dom_attribute(self, attribute):
        return self.job_id


class Modal:
    def find_element(self, *args):
        raise MissingElement("Form is already on review screen")

    def find_elements(self, *args):
        return []


class Browser:
    def __init__(self, pages):
        self.pages = pages
        self.query_id = None
        self.page = 0
        self.started = []
        self.turns = []

    def start(self, search):
        self.query_id, self.page = search.query_id, 0
        self.started.append(search.query_id)

    def find_elements(self, by, selector):
        if selector == "//li[@data-occludable-job-id]":
            return [Job(job_id) for job_id in self.pages[self.query_id][self.page]]
        return []

    def page_info(self):
        browser = self

        class Pagination:
            def find_element(self, *args):
                if browser.page + 1 >= len(browser.pages[browser.query_id]):
                    raise MissingElement("Last results page")

                def advance():
                    browser.page += 1
                    browser.turns.append((browser.query_id, browser.page + 1))

                return SimpleNamespace(click=advance)

        return Pagination(), self.page + 1


class SearchRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.events = []
        self.visited = []
        self.browser = Browser({})
        self.modal = Modal()
        self.namespace = {
            "datetime": datetime,
            "By": SimpleNamespace(XPATH="xpath", CLASS_NAME="class", TAG_NAME="tag", NAME="name"),
            "Keys": SimpleNamespace(ESCAPE="escape"),
            "EC": SimpleNamespace(presence_of_all_elements_located=lambda locator: locator,
                                  presence_of_element_located=lambda locator: locator),
            "NoSuchElementException": MissingElement,
            "ElementClickInterceptedException": MissingElement,
            "driver": self.browser,
            "wait": SimpleNamespace(until=lambda condition: True),
            "WebDriverWait": lambda *args: SimpleNamespace(until=Mock(side_effect=MissingElement())),
            "buffer": lambda *args: None,
            "print_lg": lambda *args: None,
            "critical_error_log": Mock(),
            "actions": SimpleNamespace(send_keys=lambda *args: SimpleNamespace(perform=lambda: None)),
            "pyautogui": SimpleNamespace(confirm=self.confirm, alert=Mock(), press=Mock()),
            "current_city": " California ",
            "failed_count": 0, "skip_count": 0, "easy_applied_count": 0,
            "external_jobs_count": 0, "tabs_count": 1,
            "pause_before_submit": True, "pause_at_failed_question": False,
            "useNewResume": False, "use_AI": False, "use_AI_for_resume": False,
            "first_name": "Test", "last_name": "Candidate",
            "keep_screen_awake": False, "click_gap": 0,
            "dailyEasyApplyLimitReached": False,
            "file_name": str(self.directory / "applied.csv"),
            "failed_file_name": str(self.directory / "failed.csv"),
            "active_manifest": None, "active_search": None, "active_page": 1,
            "active_application_budget": None,
            "append_history": append_history, "search_metadata": search_metadata,
            "load_applied_job_ids": load_applied_job_ids,
            "SearchManifest": SearchManifest,
            "search_profile": SimpleNamespace(search_state_dir=str(self.directory / "state")),
            "get_page_info": self.browser.page_info,
            "wait_for_search": lambda: None,
            "wait_for_search_results": lambda *args: None,
            "start_search": self.start_search,
            "apply_filters": lambda search: ["Unavailable optional filter"],
            "get_job_main_details": self.main_details,
            "find_by_class": self.find_by_class,
            "check_blacklist": lambda rejected, *args: (rejected, set(), self.modal),
            "get_job_description": lambda: ("A suitable job", 1, False, "", ""),
            "try_xp": lambda *args: True,
            "wait_span_click": self.click,
            "answer_questions": lambda modal, questions, *args, **kwargs: questions,
            "follow_company": lambda *args: None,
            "discard_job": Mock(),
        }
        extract_functions(self.namespace, "execute_search_plan", "checkpoint_job", "failed_job", "submitted_jobs", "get_applied_job_ids")

    def confirm(self, *args):
        self.events.append("confirm")
        return "Submit Application"

    def click(self, target, label, *args, **kwargs):
        self.events.append(label)
        return True

    def find_by_class(self, target, name, *args):
        if name == "jobs-s-apply__application-link":
            raise MissingElement("Not already applied")
        return self.modal

    def main_details(self, job, *args):
        self.visited.append(job.job_id)
        return job.job_id, "Engineer", "Example", "California", "Remote", False

    def start_search(self, browser, search, wait_for_search, *args):
        browser.start(search)
        return SearchResult("classic", "AI search unavailable", ["Capability fallback"])

    def manifest(self, searches, pages):
        self.browser.pages = pages
        manifest = SearchManifest.create(self.directory / "state", searches)
        self.namespace["active_manifest"] = manifest
        return manifest

    def execute(self, manifest, application_budget=None):
        self.namespace["active_manifest"] = manifest
        previous_budget = self.namespace["active_application_budget"]
        self.namespace["active_application_budget"] = application_budget
        try:
            if application_budget is None:
                self.namespace["execute_search_plan"](manifest)
            else:
                self.namespace["execute_search_plan"](manifest, application_budget=application_budget)
            manifest.finish()
        finally:
            self.namespace["active_application_budget"] = previous_budget

    def rows(self, name="applied.csv"):
        with (self.directory / name).open(newline="") as handle:
            return list(csv.DictReader(handle))

    def test_quota_stops_same_page_and_writes_actual_classic_metadata(self):
        search = spec("manual-a", 1)
        manifest = self.manifest([search], {search.query_id: [["1", "2"], ["3"]]})
        self.execute(manifest)
        self.assertEqual(self.visited, ["1"])
        self.assertEqual(self.browser.turns, [])
        self.assertEqual(manifest.query(search.query_id)["stop_reason"], "quota_met")
        self.assertEqual(manifest.data["status"], "complete")
        row = self.rows()[0]
        self.assertEqual(row["Search Run ID"], manifest.data["run_id"])
        self.assertEqual(row["Search Query ID"], search.query_id)
        self.assertEqual(row["Search Query"], search.classic_query)
        self.assertEqual(row["Search Mode"], "classic")
        self.assertEqual(row["Search Profile"], "test-profile@1")
        self.assertEqual(row["Search Source"], "manual")
        self.assertLess(self.events.index("confirm"), self.events.index("Submit application"))

    def test_missing_verified_resume_stops_before_submit_without_consuming_search_quota(self):
        search = spec("resume-rejected")
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace.update({
            "use_AI_for_resume": True, "ResumeUploadError": ResumeUploadError,
            "default_resume_docx_path": "source.docx",
            "upload_optimized_resume": Mock(return_value=(False, "No verified resume")),
        })
        self.modal.find_elements = lambda *args: [Mock()]
        self.execute(manifest)
        self.namespace["upload_optimized_resume"].assert_called_once()
        self.assertNotIn("Submit application", self.events)
        self.assertNotIn("confirm", self.events)
        self.assertEqual(manifest.query(search.query_id)["applied_count"], 0)
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "failed")
        self.assertFalse(manifest.has_uncertain_submission(search))
        self.assertFalse((self.directory / "applied.csv").exists())

    def test_verified_resume_submission_retains_search_metadata_and_quota(self):
        search = spec("resume-verified")
        manifest = self.manifest([search], {search.query_id: [["1", "2"]]})
        self.namespace.update({
            "use_AI_for_resume": True, "ResumeUploadError": ResumeUploadError,
            "default_resume_docx_path": "source.docx",
            "upload_optimized_resume": Mock(return_value=(True, "verified.pdf")),
        })
        self.modal.find_elements = lambda *args: [Mock()]
        self.execute(manifest)
        self.namespace["upload_optimized_resume"].assert_called_once()
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(self.visited, ["1"])
        self.assertEqual(manifest.query(search.query_id)["applied_count"], 1)
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "applied")
        self.assertEqual(self.rows()[0]["Search Query ID"], search.query_id)

    def test_duplicate_job_in_next_query_and_applied_history_are_skipped(self):
        append_history(self.directory / "applied.csv", ["Job ID", "Date Applied"],
                       {"Job ID": "99", "Date Applied": "2026-10-12"})
        first, second = spec("first"), spec("second")
        manifest = self.manifest([first, second], {"first": [["99", "1"]], "second": [["1", "2"]]})
        self.execute(manifest)
        self.assertEqual(self.visited, ["1", "2"])
        self.assertEqual(load_applied_job_ids(self.directory / "applied.csv"), {"99", "1", "2"})
        self.assertEqual(manifest.query("first")["jobs"]["99"]["status"], "skipped")
        self.assertEqual(manifest.query("first")["applied_count"], 1)
        self.assertEqual(manifest.query("second")["applied_count"], 1)

    def test_ai_mode_records_natural_language_query_in_successful_history(self):
        search = spec("ai-search")
        manifest = self.manifest([search], {"ai-search": [["1"]]})

        def start(browser, search, *args):
            browser.start(search)
            return SearchResult("ai")

        self.namespace["start_search"] = start
        self.execute(manifest)
        row = self.rows()[0]
        self.assertEqual(row["Search Mode"], "ai")
        self.assertEqual(row["Search Query"], search.query_text)
        self.assertEqual(manifest.query("ai-search")["executed_query"], search.query_text)
        self.assertIsNone(manifest.query("ai-search")["fallback_reason"])

    def test_resume_starts_page_one_skips_processed_and_completed_queries(self):
        first, second = spec("first"), spec("second", 2)
        manifest = self.manifest([first, second], {"first": [["1"]], "second": [["1", "2"], ["3"]]})
        manifest.record_job(first, "1", "applied", page=4)
        manifest.finish_query(first, "quota_met")
        manifest.begin_query(second)
        manifest.record_job(second, "2", "applied", page=5)
        manifest.interrupt("KeyboardInterrupt")
        resumed = SearchManifest.find_resume(self.directory / "state", plan_fingerprint([first, second]))
        self.execute(resumed)
        self.assertEqual(self.browser.started, ["second"])
        self.assertEqual(self.visited, ["3"])
        self.assertEqual(self.browser.turns, [("second", 2)])
        self.assertEqual(resumed.query("second")["applied_count"], 2)
        self.assertEqual(resumed.query("second")["last_page"], 2)

    def test_resume_retries_unsubmitted_in_progress_but_skips_uncertain_submission(self):
        uncertain, retry = spec("uncertain"), spec("retry")
        manifest = self.manifest([uncertain, retry], {"uncertain": [["10", "12"]], "retry": [["11"]]})
        manifest.begin_query(uncertain)
        manifest.record_job(uncertain, "10", "submitting")
        manifest.begin_query(retry)
        manifest.record_job(retry, "11", "in_progress")
        manifest.interrupt("KeyboardInterrupt")
        resumed = SearchManifest.find_resume(self.directory / "state", plan_fingerprint([uncertain, retry]))
        self.execute(resumed)
        self.assertEqual(self.visited, ["11"])
        self.assertEqual(self.browser.started, ["retry"])
        self.assertEqual(resumed.query("uncertain")["jobs"]["10"]["status"], "submitting")
        self.assertEqual(resumed.query("uncertain")["stop_reason"], "submission_uncertain")
        self.assertEqual(resumed.query("uncertain")["status"], "pending")
        self.assertEqual(resumed.query("retry")["jobs"]["11"]["status"], "applied")
        self.assertEqual(resumed.data["status"], "interrupted")

    def test_ambiguous_submit_preserves_uncertainty_blocks_lane_and_cannot_retry_on_resume_or_new_run(self):
        uncertain, other = spec("uncertain"), spec("other")
        manifest = self.manifest([uncertain, other], {"uncertain": [["1", "2"]], "other": [["1", "3"]]})

        def click(target, label, *args, **kwargs):
            if label == "Submit application" and self.visited[-1] == "1":
                self.events.append(label)
                raise RuntimeError("Submit may have reached LinkedIn before browser failed")
            return self.click(target, label, *args, **kwargs)

        self.namespace["wait_span_click"] = click
        self.execute(manifest)
        self.assertEqual(self.visited, ["1", "3"])
        self.assertEqual(self.events.count("Submit application"), 2)
        self.assertEqual(manifest.query("uncertain")["jobs"]["1"]["status"], "submitting")
        self.assertEqual(manifest.query("uncertain")["stop_reason"], "submission_uncertain")
        self.assertEqual(manifest.query("uncertain")["status"], "pending")
        self.assertEqual(manifest.query("uncertain")["applied_count"], 0)
        self.assertEqual(manifest.query("other")["jobs"]["3"]["status"], "applied")
        self.assertEqual(manifest.data["status"], "interrupted")
        self.assertTrue(any("Post-submit issue" in warning for warning in manifest.query("uncertain")["warnings"]))
        failure = self.rows("failed.csv")[0]
        self.assertEqual(failure["Job ID"], "1")
        self.assertEqual(failure["Search Query ID"], "uncertain")
        self.assertEqual(failure["Search Run ID"], manifest.data["run_id"])

        resumed = SearchManifest.find_resume(self.directory / "state", plan_fingerprint([uncertain, other]))
        self.execute(resumed)
        self.assertEqual(self.visited, ["1", "3"])
        self.assertEqual(self.browser.started, ["uncertain", "other"])
        self.assertEqual(resumed.query("uncertain")["jobs"]["1"]["status"], "submitting")
        self.assertEqual(resumed.data["status"], "interrupted")

        fresh = spec("fresh")
        new_run = self.manifest([fresh], {"fresh": [["1", "4"]]})
        self.execute(new_run)
        self.assertEqual(self.visited, ["1", "3", "4"])
        self.assertEqual(self.events.count("Submit application"), 3)
        self.assertEqual(new_run.query("fresh")["jobs"]["1"]["status"], "skipped")
        self.assertEqual(new_run.query("fresh")["jobs"]["4"]["status"], "applied")

    def test_user_discards_before_submit_logs_failure_without_using_quota(self):
        search = spec("discard")
        manifest = self.manifest([search], {"discard": [["1"]]})
        self.namespace["pyautogui"].confirm = lambda *args: "Discard Application"
        self.execute(manifest)
        self.assertNotIn("Submit application", self.events)
        self.assertFalse((self.directory / "applied.csv").exists())
        self.assertEqual(manifest.query("discard")["applied_count"], 0)
        self.assertEqual(manifest.query("discard")["jobs"]["1"]["status"], "failed")
        row = self.rows("failed.csv")[0]
        self.assertEqual(row["Search Run ID"], manifest.data["run_id"])
        self.assertEqual(row["Search Query"], search.classic_query)
        self.assertEqual(row["Search Mode"], "classic")

    def test_failed_jobs_do_not_consume_quota_and_page_through_to_success(self):
        search = spec("gates")
        manifest = self.manifest([search], {"gates": [["1"], ["2", "3"]]})
        descriptions = iter([("Excluded", 1, True, "Description gate", "Bad words"),
                             ("A suitable job", 1, False, "", "")])
        self.namespace["get_job_description"] = lambda: next(descriptions)
        self.execute(manifest)
        self.assertEqual(self.visited, ["1", "2"])
        self.assertEqual(self.browser.turns, [("gates", 2)])
        self.assertEqual(manifest.query("gates")["jobs"]["1"]["status"], "skipped")
        self.assertEqual(manifest.query("gates")["applied_count"], 1)
        self.assertEqual(self.rows("failed.csv")[0]["Assumed Reason"], "Description gate")

    def test_browser_search_error_remains_resumable_and_next_query_executes(self):
        first, second = spec("broken"), spec("working")
        manifest = self.manifest([first, second], {"working": [["1"]]})

        def start(browser, search, wait_for_search, *args):
            if search.query_id == "broken":
                raise RuntimeError("Browser lost its search UI")
            return self.start_search(browser, search, wait_for_search)

        self.namespace["start_search"] = start
        self.execute(manifest)
        self.assertEqual(manifest.data["status"], "interrupted")
        self.assertEqual(manifest.query("broken")["status"], "pending")
        self.assertEqual(manifest.query("broken")["stop_reason"], "search_error:RuntimeError")
        self.assertEqual(manifest.query("working")["status"], "complete")
        self.assertEqual(self.visited, ["1"])

    def test_pending_external_link_is_collected_once_without_claiming_submission(self):
        first, second = spec("first"), spec("second")
        manifest = self.manifest([first, second], {"first": [["1"]], "second": [["1", "2"]]})
        self.namespace["try_xp"] = lambda *args: False
        self.namespace["external_apply"] = lambda *args: (False, "https://example.test/apply", 1)
        self.execute(manifest)
        self.assertEqual(self.visited, ["1", "2"])
        self.assertEqual(load_applied_job_ids(self.directory / "applied.csv"), set())
        self.assertEqual([row["Date Applied"] for row in self.rows()], ["Pending", "Pending"])
        self.assertEqual(manifest.query("first")["applied_count"], 0)
        self.assertEqual(manifest.query("first")["collected_count"], 1)

    def test_successful_submission_survives_later_modal_failure(self):
        first, second = spec("first"), spec("second")
        manifest = self.manifest([first, second], {"first": [["1"]], "second": [["1", "2"]]})

        def click(target, label, *args, **kwargs):
            if label == "Done":
                raise RuntimeError("Confirmation modal changed after submit")
            return self.click(target, label, *args, **kwargs)

        self.namespace["wait_span_click"] = click
        self.execute(manifest)
        self.assertEqual(self.visited, ["1", "2"])
        self.assertEqual(self.events.count("Submit application"), 2)
        self.assertEqual(manifest.query("first")["jobs"]["1"]["status"], "applied")
        self.assertEqual(manifest.query("first")["applied_count"], 1)
        self.assertTrue(any("Post-submit issue" in item for item in manifest.query("first")["warnings"]))
        self.assertEqual(load_applied_job_ids(self.directory / "applied.csv"), {"1", "2"})

    def test_new_run_skips_success_when_csv_logging_failed(self):
        first = spec("first")
        manifest = self.manifest([first], {"first": [["1"]]})
        self.namespace["append_history"] = Mock(side_effect=PermissionError("CSV is open elsewhere"))
        self.execute(manifest)
        self.assertEqual(manifest.data["status"], "complete")
        self.assertEqual(manifest.query("first")["jobs"]["1"]["status"], "applied")
        self.assertFalse((self.directory / "applied.csv").exists())
        self.namespace["append_history"] = append_history
        second = spec("second")
        next_run = self.manifest([second], {"second": [["1", "2"]]})
        self.execute(next_run)
        self.assertEqual(self.visited, ["1", "2"])
        self.assertEqual(self.events.count("Submit application"), 2)
        self.assertEqual(next_run.query("second")["jobs"]["1"]["status"], "skipped")
        self.assertEqual(load_applied_job_ids(self.directory / "applied.csv"), {"2"})

    def test_new_run_skips_uncertain_submission_from_interrupted_manifest(self):
        first = spec("first")
        manifest = self.manifest([first], {"first": [["1"]]})
        manifest.begin_query(first)
        manifest.record_job(first, "1", "submitting", "Submit requested")
        manifest.interrupt("KeyboardInterrupt")
        second = spec("second")
        next_run = self.manifest([second], {"second": [["1", "2"]]})
        self.execute(next_run)
        self.assertEqual(self.visited, ["2"])
        self.assertEqual(next_run.query("second")["jobs"]["1"]["status"], "skipped")
        self.assertEqual(manifest.query("first")["jobs"]["1"]["status"], "submitting")

    def test_classic_boolean_switches_are_selected_without_toggling_existing_selection(self):
        search = spec("filters")
        search.mode = "classic"
        search.filters_snapshot["intent"] = {"easy_apply_only": True, "under_10_applicants": True}
        selected = SimpleNamespace(is_selected=lambda: True)
        unselected = SimpleNamespace(is_selected=lambda: False)
        moves = []

        class FilterBrowser:
            def find_element(self, *args):
                return SimpleNamespace(click=lambda: None)

            def find_elements(self, by, selector):
                if "//h3" in selector and "Easy Apply" in selector:
                    return [selected]
                if "//h3" in selector and "Under 10 applicants" in selector:
                    return [unselected]
                return []

        namespace = {
            "driver": FilterBrowser(), "By": self.namespace["By"],
            "NoSuchElementException": MissingElement,
            "buffer": lambda *args: None, "set_search_location": Mock(),
            "scroll_to_view": Mock(), "try_xp": Mock(),
            "pause_after_filters": False, "apply_configured_filters": apply_configured_filters,
            "actions": SimpleNamespace(move_to_element=lambda control: (
                moves.append(control) or SimpleNamespace(click=lambda: SimpleNamespace(perform=lambda: None)))),
        }
        extract_functions(namespace, "apply_filters")
        warnings = namespace["apply_filters"](search)
        self.assertEqual(moves, [unselected])
        self.assertFalse(any("easy_apply_only" in warning or "under_10_applicants" in warning for warning in warnings))
        namespace["set_search_location"].assert_called_once()

    def test_application_cap_stops_before_next_query_after_first_confirmed_submission(self):
        from modules.application_budget import ApplicationBudget

        first, second = spec("first"), spec("second")
        manifest = self.manifest([first, second], {"first": [["1"]], "second": [["2"]]})
        budget = ApplicationBudget(1)
        self.execute(manifest, budget)
        self.assertEqual(self.visited, ["1"])
        self.assertEqual(self.browser.started, ["first"])
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(budget.applied_ids, {"1"})
        self.assertTrue(budget.reached)
        self.assertEqual(manifest.query("first")["status"], "complete")
        self.assertEqual(manifest.query("first")["stop_reason"], "quota_met")
        self.assertEqual(manifest.query("second")["status"], "pending")
        self.assertEqual(manifest.data["status"], "interrupted")
        self.assertEqual(manifest.data["stop_reason"], "application_limit_reached")

    def test_application_cap_overrides_high_manual_quota_before_next_job_or_page(self):
        from modules.application_budget import ApplicationBudget

        search = spec("manual-large-quota", 4)
        manifest = self.manifest([search], {search.query_id: [["1", "2"], ["3", "4"]]})
        budget = ApplicationBudget(1)
        self.execute(manifest, budget)
        self.assertEqual(self.visited, ["1"])
        self.assertEqual(self.browser.turns, [])
        self.assertEqual(manifest.query(search.query_id)["applied_count"], 1)
        self.assertNotEqual(manifest.query(search.query_id)["status"], "complete")
        self.assertEqual(manifest.data["stop_reason"], "application_limit_reached")

    def test_reached_shared_budget_does_not_begin_another_query(self):
        from modules.application_budget import ApplicationBudget

        budget = ApplicationBudget(1)
        budget.record("previous-cycle-job")
        search = spec("next-cycle")
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.execute(manifest, budget)
        self.assertEqual(self.browser.started, [])
        self.assertEqual(self.visited, [])
        self.assertEqual(manifest.query(search.query_id)["status"], "pending")
        self.assertIsNone(manifest.data["current_query_id"])
        self.assertEqual(manifest.data["stop_reason"], "application_limit_reached")

    def test_failed_skipped_and_external_jobs_do_not_consume_confirmed_application_cap(self):
        from modules.application_budget import ApplicationBudget

        first, second = spec("mixed", 2), spec("unstarted")
        manifest = self.manifest([first, second], {"mixed": [["1", "2", "3", "4", "5"]], "unstarted": [["6"]]})
        self.namespace["get_job_description"] = lambda: (
            ("Excluded", 1, True, "Description gate", "Bad words") if self.visited[-1] == "1"
            else ("A suitable job", 1, False, "", ""))
        self.namespace["pyautogui"].confirm = lambda *args: "Discard Application" if self.visited[-1] == "2" else "Submit Application"
        self.namespace["try_xp"] = lambda *args: self.visited[-1] != "3"
        self.namespace["external_apply"] = lambda *args: (False, "https://example.test/apply", 1)
        budget = ApplicationBudget(1)
        self.execute(manifest, budget)
        self.assertEqual(self.visited, ["1", "2", "3", "4"])
        self.assertEqual(budget.applied_ids, {"4"})
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual({key: row["status"] for key, row in manifest.query("mixed")["jobs"].items()},
                         {"1": "skipped", "2": "failed", "3": "collected", "4": "applied"})
        self.assertEqual(manifest.query("mixed")["collected_count"], 1)
        self.assertEqual(manifest.query("mixed")["applied_count"], 1)
        self.assertEqual(manifest.query("unstarted")["status"], "pending")

    def test_post_submit_ui_failure_still_counts_once_and_stops_command(self):
        from modules.application_budget import ApplicationBudget

        first, second = spec("first"), spec("second")
        manifest = self.manifest([first, second], {"first": [["1"]], "second": [["2"]]})

        def click(target, label, *args, **kwargs):
            if label == "Done":
                raise RuntimeError("Confirmation UI changed after confirmed submission")
            return self.click(target, label, *args, **kwargs)

        self.namespace["wait_span_click"] = click
        budget = ApplicationBudget(1)
        self.execute(manifest, budget)
        self.assertEqual(self.visited, ["1"])
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(budget.applied_ids, {"1"})
        self.assertEqual(manifest.query("first")["jobs"]["1"]["status"], "applied")
        self.assertEqual(manifest.query("second")["status"], "pending")

    def test_post_submit_csv_failure_still_counts_once_and_stops_command(self):
        from modules.application_budget import ApplicationBudget

        first, second = spec("first"), spec("second")
        manifest = self.manifest([first, second], {"first": [["1"]], "second": [["2"]]})
        self.namespace["append_history"] = Mock(side_effect=PermissionError("History is temporarily locked"))
        budget = ApplicationBudget(1)
        self.execute(manifest, budget)
        self.assertEqual(self.visited, ["1"])
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(budget.applied_ids, {"1"})
        self.assertEqual(manifest.query("first")["jobs"]["1"]["status"], "applied")
        self.assertEqual(manifest.query("second")["status"], "pending")
        self.assertFalse((self.directory / "applied.csv").exists())

    def test_transient_applied_checkpoint_save_failure_cannot_bypass_command_cap(self):
        from modules.application_budget import ApplicationBudget

        first, second = spec("first"), spec("second")
        manifest = self.manifest([first, second], {"first": [["1"]], "second": [["2"]]})
        original_save = manifest.save
        failed_once = []

        def transient_failure():
            confirmed = manifest.query("first")["jobs"].get("1", {}).get("status") == "applied"
            if confirmed and not failed_once:
                failed_once.append(True)
                raise OSError("Applied checkpoint could not be written once")
            original_save()

        manifest.save = transient_failure
        budget = ApplicationBudget(1)
        self.execute(manifest, budget)
        self.assertEqual(failed_once, [True])
        self.assertEqual(self.visited, ["1"])
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(budget.count, 1)
        self.assertEqual(budget.applied_ids, {"1"})
        self.assertEqual(manifest.query("first")["jobs"]["1"]["status"], "applied")
        self.assertEqual(manifest.query("second")["status"], "pending")
        self.assertEqual(manifest.data["invocation_applied_count"], 1)
        self.assertEqual(manifest.data["stop_reason"], "application_limit_reached")

    def test_fresh_invocation_budget_resumes_higher_quota_and_skips_prior_applications(self):
        from modules.application_budget import ApplicationBudget

        first, second = spec("first", 3), spec("second")
        searches = [first, second]
        manifest = self.manifest(searches, {"first": [["1", "2", "3"]], "second": [["1", "4"]]})
        first_budget = ApplicationBudget(1)
        self.execute(manifest, first_budget)
        original_run = manifest.data["run_id"]
        for expected_id in ("2", "3", "4"):
            resumed = SearchManifest.find_resume(self.directory / "state", plan_fingerprint(searches))
            self.assertIsNotNone(resumed)
            self.assertEqual(resumed.data["run_id"], original_run)
            budget = ApplicationBudget(1)
            self.execute(resumed, budget)
            self.assertEqual(budget.applied_ids, {expected_id})
            manifest = resumed
        self.assertEqual(self.visited, ["1", "2", "3", "4"])
        self.assertEqual(self.events.count("Submit application"), 4)
        self.assertEqual(load_applied_job_ids(self.directory / "applied.csv"), {"1", "2", "3", "4"})
        self.assertEqual(manifest.query("first")["applied_count"], 3)
        self.assertEqual(manifest.query("second")["applied_count"], 1)
        self.assertEqual(manifest.data["status"], "complete")

    def test_uncertain_submission_blocks_capped_command_without_counting_as_confirmed(self):
        from modules.application_budget import ApplicationBudget

        uncertain, other = spec("uncertain"), spec("other")
        manifest = self.manifest([uncertain, other], {"uncertain": [["1", "3"]], "other": [["2"]]})

        def click(target, label, *args, **kwargs):
            if label == "Submit application" and self.visited[-1] == "1":
                self.events.append(label)
                raise RuntimeError("Submit outcome is uncertain")
            return self.click(target, label, *args, **kwargs)

        self.namespace["wait_span_click"] = click
        budget = ApplicationBudget(1)
        self.execute(manifest, budget)
        self.assertEqual(self.visited, ["1"])
        self.assertEqual(budget.applied_ids, set())
        self.assertEqual(manifest.query("uncertain")["jobs"]["1"]["status"], "submitting")
        self.assertEqual(manifest.query("uncertain")["applied_count"], 0)
        self.assertEqual(manifest.query("other")["status"], "pending")
        self.assertEqual(manifest.data["stop_reason"], "submission_uncertain")
        resumed = SearchManifest.find_resume(self.directory / "state", plan_fingerprint([uncertain, other]))
        self.execute(resumed, ApplicationBudget(1))
        self.assertEqual(self.visited, ["1"])


if __name__ == "__main__":
    unittest.main()
