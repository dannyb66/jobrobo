"""Exercise the real runner loop without importing its browser/secrets bootstrap."""

import ast
import csv
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException

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
    if 'execute_search_plan' in names:
        names = tuple(dict.fromkeys((*names, 'description_geography_rejections')))
        namespace.setdefault('re', __import__('re'))
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

    def get(self, url):
        self.current_url = url

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
        self.reconciliation = patch('modules.linkedin_failure_recovery.reconcile_submission', return_value=False)
        self.reconcile = self.reconciliation.start()
        self.addCleanup(self.reconciliation.stop)
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
            "prepare_search": self.prepare_search,
            "get_search_cards": lambda browser: browser.find_elements("xpath", "//li[@data-occludable-job-id]"),
            "search_card_id": lambda card: card.get_dom_attribute("data-occludable-job-id"),
            "search_results_ready": lambda browser: ("jobs" if browser.find_elements("xpath", "//li[@data-occludable-job-id]") else "empty") if browser.query_id is not None else False,
            "next_search_page": self.next_search_page,
            "apply_filters": lambda search: ["Unavailable optional filter"],
            "get_job_main_details": self.main_details,
            "find_by_class": self.find_by_class,
            "check_blacklist": lambda rejected, *args: (rejected, set(), self.modal),
            "get_job_description": lambda: ("A suitable job", 1, False, "", ""),
            "try_xp": lambda *args: True,
            "open_easy_apply": lambda browser, job_id, **kwargs: self.namespace["try_xp"](browser, job_id),
            "clear_post_submit_ui": lambda *args, **kwargs: None,
            "wait_span_click": self.click,
            "answer_questions": lambda modal, questions, *args, **kwargs: questions,
            "follow_company": lambda *args: None,
            "discard_job": Mock(),
            "wait_for_application_modal": lambda browser: self.modal,
            "advance_to_review": self.advance_to_review,
            "current_submit_button": lambda browser: (self.modal, SimpleNamespace(
                click=lambda: self.namespace["wait_span_click"](self.modal, "Submit application"))),
            "wait_for_submission_confirmation": Mock(return_value=True),
            "submission_receipts": lambda browser, **kwargs: set(),
            "resume_upload_target": lambda browser, modal: modal if modal.find_elements("name", "file") else None,
        }
        self.browser.execute_script = Mock()
        self.browser.save_screenshot = Mock(return_value=True)
        extract_functions(self.namespace, "prepare_easy_apply", "execute_search_plan", "checkpoint_job", "failed_job", "submitted_jobs", "get_applied_job_ids")

    def advance_to_review(self, browser, fill_step, **kwargs):
        fill_step(self.modal)
        return self.modal

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

    def prepare_search(self, browser, search, wait_for_search, wait_for_results, filters):
        result = self.namespace["start_search"](browser, search, wait_for_search, wait_for_results)
        search.mode = result.mode
        result.warnings.extend(filters(search) or [])
        return result

    def next_search_page(self, browser, current_page):
        try:
            browser.page_info()[0].find_element().click()
            return True
        except MissingElement:
            return False

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

    def test_details_error_is_deferred_and_next_card_in_same_query_applies(self):
        from modules.linkedin_job_details import JobDetailsUnavailable
        search = spec('details-recovery', 2)
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        original = self.namespace['get_job_main_details']
        def details(job, *args):
            if job.job_id == '1':
                raise JobDetailsUnavailable('1', {'predicate_error': 'Missing employer header'})
            return original(job, *args)
        self.namespace['get_job_main_details'] = details
        self.execute(manifest)
        self.assertEqual([r['Job ID'] for r in self.rows()], ['2'])
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'in_progress')
        self.assertTrue(manifest.query(search.query_id)['application_failures'][0]['report_path'])

    def test_unexpected_job_error_is_captured_and_next_job_applies(self):
        search = spec('unexpected', 2)
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        description = self.namespace['get_job_description']
        self.namespace['get_job_description'] = Mock(side_effect=[ValueError('Broken job layout'), description()])
        self.execute(manifest)
        self.assertEqual([r['Job ID'] for r in self.rows()], ['2'])
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'failed')
        self.assertTrue(Path(manifest.query(search.query_id)['application_failures'][0]['report_path']).is_file())

    def test_disconnected_readiness_during_error_handling_does_not_abort_later_query(self):
        first, second = spec('lost-connection'), spec('available')
        manifest = self.manifest([first, second], {first.query_id: [['1']], second.query_id: [['2']]})
        original = self.namespace['start_search']
        def start(browser, search, *args):
            if search.query_id == first.query_id:
                raise RuntimeError('Browser connection was interrupted')
            return original(browser, search, *args)
        self.namespace['start_search'] = start
        self.namespace['search_results_ready'] = Mock(side_effect=RuntimeError('Browser disconnected'))
        self.execute(manifest)
        self.assertEqual(manifest.query(first.query_id)['status'], 'pending')
        self.assertEqual([r['Job ID'] for r in self.rows()], ['2'])

    def test_delayed_confirmation_is_reconciled_without_second_submit(self):
        search = spec('late-receipt')
        manifest = self.manifest([search], {search.query_id: [['1']]})
        self.namespace['wait_for_submission_confirmation'] = Mock(side_effect=RuntimeError('Receipt delayed'))
        self.reconcile.return_value = True
        self.execute(manifest)
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'applied')
        self.assertEqual(self.events.count('Submit application'), 1)
        self.assertEqual(self.namespace['failed_count'], 0)

    def test_resumed_confirmed_hold_does_not_count_as_a_new_submission(self):
        from modules.application_budget import ApplicationBudget
        search = spec('resume-reconciliation', 3)
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        manifest.record_job(search, '1', 'submitting')
        self.reconcile.return_value = True
        budget = ApplicationBudget(2)
        self.execute(manifest, application_budget=budget)
        self.assertEqual(self.visited, ['2'])
        self.assertEqual(manifest.query(search.query_id)['applied_count'], 2)
        self.assertEqual(budget.count, 1)
        self.assertEqual(self.events.count('Submit application'), 1)

    def test_engineering_query_skips_interior_manager_before_opening_application(self):
        search = spec('engineering', 2)
        search.classic_query = 'Staff Software Engineer'
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        self.namespace['get_job_main_details'] = Mock(side_effect=[
            ('1','Interior Manager','Example','California','Remote',False),
            ('2','Staff Software Engineer','Example','California','Remote',False)])
        self.execute(manifest)
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'skipped')
        self.assertEqual([r['Job ID'] for r in self.rows()], ['2'])

    def test_daily_limit_preserves_job_and_query_for_resume_without_failure_or_cleanup(self):
        from modules.linkedin_easy_apply import EasyApplyLimitReached
        from modules.linkedin_deferred import DeferredJobs
        first, second = spec('limited', 3), spec('later')
        manifest = self.manifest([first, second], {'limited': [['1', '2']], 'later': [['3']]})
        self.namespace['open_easy_apply'] = Mock(side_effect=EasyApplyLimitReached())
        self.execute(manifest)
        self.assertEqual(self.visited, ['1'])
        self.assertTrue(self.namespace['dailyEasyApplyLimitReached'])
        self.assertEqual(manifest.data['stop_reason'], 'daily_easy_apply_limit')
        self.assertEqual(manifest.query('limited')['status'], 'pending')
        self.assertEqual(manifest.query('limited')['jobs']['1']['status'], 'in_progress')
        self.assertNotIn('1', manifest.processed_ids())
        self.assertEqual(self.namespace['failed_count'], 0)
        self.namespace['discard_job'].assert_not_called()
        self.assertNotIn('Submit application', self.events)
        records = DeferredJobs(self.directory / 'deferred_applications' / 'retry_jobs.json').records
        self.assertEqual(records[0]['status'], 'platform_limit')
        self.assertFalse(records[0]['requires_submission_check'])
        self.namespace['dailyEasyApplyLimitReached'] = False
        self.namespace['open_easy_apply'] = Mock(return_value=True)
        resumed = SearchManifest.find_resume(self.directory / 'state', plan_fingerprint([first, second]))
        self.execute(resumed)
        self.assertEqual(self.visited, ['1', '1', '2', '3'])
        self.assertEqual(self.events.count('Submit application'), 3)

    def test_daily_limit_after_success_keeps_confirmed_history_and_retries_only_unsubmitted(self):
        from modules.linkedin_easy_apply import EasyApplyLimitReached
        first, second, third = spec('completed'), spec('limited'), spec('untouched')
        manifest = self.manifest([first, second, third], {'completed': [['1']], 'limited': [['2']], 'untouched': [['3']]})
        self.namespace['open_easy_apply'] = Mock(side_effect=[True, EasyApplyLimitReached()])
        self.execute(manifest)
        self.assertEqual(self.visited, ['1', '2'])
        self.assertEqual(manifest.query('completed')['status'], 'complete')
        self.assertEqual(manifest.query('completed')['jobs']['1']['status'], 'applied')
        self.assertEqual(manifest.query('limited')['jobs']['2']['status'], 'in_progress')
        self.assertEqual(self.events.count('Submit application'), 1)
        self.assertEqual([row['Job ID'] for row in self.rows()], ['1'])

    def test_prepare_only_daily_limit_does_not_discard_or_report_form_failure(self):
        from modules.linkedin_easy_apply import EasyApplyLimitReached
        search = spec('limited-preparation')
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        self.namespace['open_easy_apply'] = Mock(side_effect=EasyApplyLimitReached())
        with patch('modules.linkedin_form_cleanup.discard_application') as cleanup:
            self.namespace['execute_search_plan'](manifest, prepare_only=True)
        cleanup.assert_not_called()
        self.assertEqual(manifest.data['stop_reason'], 'daily_easy_apply_limit')
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'in_progress')
        self.assertEqual(self.namespace['failed_count'], 0)
        self.assertNotIn('Submit application', self.events)

    def test_missing_entry_is_retryable_and_not_an_external_skip(self):
        from modules.linkedin_easy_apply import EasyApplyError
        search = spec('entry-failure')
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        self.namespace['open_easy_apply'] = Mock(side_effect=EasyApplyError('entry: control remained unavailable'))
        external = self.namespace['external_apply'] = Mock()
        self.execute(manifest)
        external.assert_not_called()
        self.assertEqual(self.visited, ['1', '2'])
        self.assertEqual(self.namespace['failed_count'], 2)
        self.assertEqual(manifest.query(search.query_id)['stop_reason'], 'job_cards_pending')
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'in_progress')
        self.assertNotIn('1', manifest.processed_ids())
        self.namespace['discard_job'].assert_not_called()

    def test_daily_limit_during_form_wait_propagates_without_discard_or_failed_history(self):
        from modules.linkedin_easy_apply import EasyApplyLimitReached
        search = spec('limited-form')
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        self.namespace['prepare_easy_apply'] = Mock(side_effect=EasyApplyLimitReached())
        self.execute(manifest)
        self.assertEqual(self.visited, ['1'])
        self.assertEqual(manifest.data['stop_reason'], 'daily_easy_apply_limit')
        self.assertEqual(self.namespace['failed_count'], 0)
        self.namespace['discard_job'].assert_not_called()
        self.assertNotIn('Submit application', self.events)

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

    def test_unready_modern_results_remain_pending_without_opening_application(self):
        search = spec("modern-results-unready")
        manifest = self.manifest([search], {search.query_id: [[]]})
        self.namespace["search_results_ready"] = lambda browser: False
        self.execute(manifest)
        self.assertEqual(manifest.query(search.query_id)["status"], "pending")
        self.assertEqual(manifest.query(search.query_id)["stop_reason"], "search_error:ValueError")
        self.assertEqual(self.visited, [])
        self.assertNotIn("Easy Apply", self.events)
        self.assertNotIn("Submit application", self.events)

    def test_verified_classic_pagination_with_retained_cards_does_not_require_staleness_again(self):
        search = spec("classic-retained-pagination", quota=3)
        manifest = self.manifest([search], {search.query_id: [["1"], ["1", "2"]]})
        retained = {"1": Job("1"), "2": Job("2")}
        scans, wait_inputs = [], []

        def cards(browser):
            page = [retained[job_id] for job_id in browser.pages[browser.query_id][browser.page]]
            scans.append(page)
            return page

        def wait_results(previous):
            wait_inputs.append(list(previous))
            if previous:
                raise RuntimeError("Legacy cards were retained after a verified page transition")

        self.namespace["get_search_cards"] = cards
        self.namespace["wait_for_search_results"] = wait_results
        self.execute(manifest)
        self.assertEqual(self.visited, ["1", "2"])
        self.assertIs(scans[0][0], scans[1][0])
        self.assertTrue(wait_inputs)
        self.assertTrue(all(previous == [] for previous in wait_inputs))
        self.assertEqual(self.events.count("Submit application"), 2)
        self.assertEqual(manifest.query(search.query_id)["stop_reason"], "results_exhausted")

    def test_prepared_modern_search_records_verified_transport_before_application(self):
        search = spec("modern-prepared")
        manifest = self.manifest([search], {search.query_id: [["1", "1", "2"]]})
        filters = Mock(side_effect=AssertionError("Modern controls must be prepared once"))
        self.namespace["apply_filters"] = filters

        def prepared(browser, current, *args):
            browser.start(current)
            return SearchResult("ai", ui_variant="modern_prompt", transport="native_ui",
                                verified_filters=["search_location", "easy_apply_only"],
                                results_state="jobs", executed_query=current.query_text)

        self.namespace["prepare_search"] = prepared
        self.execute(manifest)
        filters.assert_not_called()
        self.assertEqual(self.visited, ["1"])
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(manifest.query(search.query_id)["search_mode"], "ai")
        diagnostics = manifest.query(search.query_id)["search_diagnostics"]
        self.assertEqual(diagnostics["ui_variant"], "modern_prompt")
        self.assertEqual(diagnostics["transport"], "native_ui")
        self.assertIn("search_location", diagnostics["verified_filters"])

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

    def test_failed_configured_resume_upload_never_submits_previous_attachment(self):
        search = spec("configured-resume-rejected")
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.modal.find_elements = lambda *args: [Mock()]
        self.namespace.update({"useNewResume": True, "ResumeUploadError": ResumeUploadError,
                               "default_resume_path": "source.pdf",
                               "upload_resume": Mock(return_value=(False, "Previous resume"))})
        self.execute(manifest)
        self.assertNotIn("Submit application", self.events)
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "failed")

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
        uncertain, retry = spec("uncertain", 3), spec("retry")
        manifest = self.manifest([uncertain, retry], {"uncertain": [["10", "12"]], "retry": [["11"]]})
        manifest.begin_query(uncertain)
        manifest.record_job(uncertain, "10", "submitting")
        manifest.begin_query(retry)
        manifest.record_job(retry, "11", "in_progress")
        manifest.interrupt("KeyboardInterrupt")
        resumed = SearchManifest.find_resume(self.directory / "state", plan_fingerprint([uncertain, retry]))
        self.execute(resumed)
        self.assertEqual(self.visited, ["12", "11"])
        self.assertEqual(self.browser.started, ["uncertain", "retry"])
        self.assertEqual(resumed.query("uncertain")["jobs"]["10"]["status"], "submitting")
        self.assertEqual(resumed.query("uncertain")["stop_reason"], "submission_uncertain")
        self.assertEqual(resumed.query("uncertain")["status"], "pending")
        self.assertEqual(resumed.query("retry")["jobs"]["11"]["status"], "applied")
        self.assertEqual(resumed.data["status"], "interrupted")

    def test_ambiguous_submit_holds_job_but_allows_other_jobs_and_never_reapplies(self):
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
        self.assertEqual(self.browser.started, ["uncertain", "uncertain", "other"])
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

    def test_missing_application_dialog_preserves_cause_and_never_reviews_or_submits(self):
        search = spec("missing-dialog")
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        error = RuntimeError("open: visible Easy Apply dialog not found")
        self.namespace["wait_for_application_modal"] = Mock(side_effect=error)
        original_find = self.namespace["find_by_class"]
        self.namespace["find_by_class"] = lambda target, name, *args: (
            (_ for _ in ()).throw(error) if name == "jobs-easy-apply-modal"
            else original_find(target, name, *args))
        self.execute(manifest)
        self.assertNotIn("Review", self.events)
        self.assertNotIn("Submit application", self.events)
        self.assertNotIn("confirm", self.events)
        self.assertIn("visible Easy Apply dialog not found", self.rows("failed.csv")[0]["Stack Trace"])

    def test_normal_form_failure_recovers_and_continues_when_discard_fails(self):
        search = spec("normal-cleanup-failure")
        manifest = self.manifest([search], {search.query_id: [["1", "2"]]})
        self.namespace["answer_questions"] = Mock(side_effect=RuntimeError("Missing required answer"))
        self.namespace["discard_job"] = Mock(side_effect=RuntimeError("Discard confirmation remained open"))
        self.execute(manifest)
        self.assertEqual(self.visited, ["1", "2"])
        self.assertNotIn("Submit application", self.events)
        self.assertEqual(manifest.data["status"], "complete")

    def test_pre_submit_cleanup_failure_restarts_search_and_continues_next_job(self):
        from modules.linkedin_easy_apply import MissingApplicationAnswer
        from modules.linkedin_deferred import DeferredJobs
        search = spec('cleanup-recovered', 2)
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        self.browser.get = Mock()
        self.namespace['answer_questions'] = Mock(side_effect=[
            MissingApplicationAnswer('Required personal answer is missing: 3 References (1 Direct Manager)'), set()])
        self.namespace['discard_job'] = Mock(side_effect=RuntimeError('cleanup: unrelated blocking dialog remains'))
        self.execute(manifest)
        self.assertEqual(self.visited, ['1', '2'])
        self.assertEqual(self.events.count('Submit application'), 1)
        self.browser.get.assert_called_once_with('https://www.linkedin.com/jobs/')
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'failed')
        self.assertEqual(manifest.query(search.query_id)['jobs']['2']['status'], 'applied')
        records = DeferredJobs(self.directory / 'deferred_applications' / 'retry_jobs.json').records
        self.assertEqual(records[0]['job_id'], '1')
        self.assertFalse(records[0]['requires_submission_check'])
        self.assertEqual(manifest.query(search.query_id)['ui_recoveries'][0]['status'], 'recovered')
        self.assertTrue(list((self.directory / 'application_ui_diagnostics').glob('*.json')))

    def test_cleanup_recovery_restarts_page_one_without_reapplying_completed_jobs(self):
        search = spec('cleanup-page-reset', 3)
        manifest = self.manifest([search], {search.query_id: [['1', '2'], ['3']]})
        self.browser.get = Mock()
        self.namespace['answer_questions'] = Mock(side_effect=[set(), RuntimeError('Missing answer'), set()])
        self.namespace['discard_job'] = Mock(side_effect=RuntimeError('cleanup failed'))
        self.execute(manifest)
        self.assertEqual(self.visited, ['1', '2', '3'])
        self.assertEqual(self.events.count('Submit application'), 2)
        self.assertEqual([r['Job ID'] for r in self.rows()], ['1', '3'])
        self.assertEqual(self.browser.started, [search.query_id, search.query_id])

    def test_uncertain_submission_is_held_while_search_restarts_for_other_jobs(self):
        search = spec('cleanup-uncertain', 2)
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        self.browser.get = Mock()
        self.namespace['wait_for_submission_confirmation'] = Mock(side_effect=RuntimeError('No confirmation'))
        self.namespace['discard_job'] = Mock(side_effect=RuntimeError('cleanup failed'))
        self.execute(manifest)
        self.assertTrue(all(call.args[0] == 'https://www.linkedin.com/jobs/' for call in self.browser.get.call_args_list))
        self.assertEqual(self.visited, ['1', '2'])
        self.assertEqual(self.events.count('Submit application'), 2)
        self.assertTrue(manifest.has_uncertain_submission(search))

    def test_cleanup_recovery_stops_if_restored_search_is_still_blocked(self):
        search = spec('cleanup-still-blocked', 2)
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        self.browser.get = Mock()
        self.namespace['answer_questions'] = Mock(side_effect=RuntimeError('Missing answer'))
        self.namespace['discard_job'] = Mock(side_effect=RuntimeError('cleanup failed'))
        self.namespace['clear_post_submit_ui'] = Mock(side_effect=RuntimeError('Unrecognized overlay remains'))
        self.execute(manifest)
        self.assertEqual(self.visited, ['1'])
        self.browser.get.assert_called_once()
        self.assertEqual(self.events.count('Submit application'), 0)
        self.assertEqual(manifest.query(search.query_id)['stop_reason'], 'job_cards_pending')
        self.assertEqual(manifest.query(search.query_id)['ui_recoveries'][0]['status'], 'failed')

    def test_prepare_only_cleanup_failure_recovers_and_validates_next_job(self):
        from modules.linkedin_easy_apply import MissingApplicationAnswer
        search = spec('prepare-cleanup-recovered', 3)
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        self.browser.get = Mock()
        self.namespace['prepare_easy_apply'] = Mock(side_effect=[
            MissingApplicationAnswer('Missing references'), (self.modal, set(), True, 'verified.pdf')])
        with patch('modules.linkedin_form_cleanup.discard_application',
                   side_effect=[RuntimeError('cleanup failed'), True]):
            self.namespace['execute_search_plan'](manifest, prepare_only=True, preparation_limit=2)
        self.assertEqual(self.visited, ['1', '2'])
        self.assertNotIn('Submit application', self.events)
        self.assertEqual(manifest.query(search.query_id)['jobs']['2']['status'], 'prepared')
        self.assertEqual(manifest.query(search.query_id)['ui_recoveries'][0]['status'], 'recovered')

    def test_answer_failure_never_enters_review_or_submission(self):
        search = spec("answer-error")
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace["answer_questions"] = Mock(side_effect=RuntimeError("Cannot fill required field"))
        self.execute(manifest)
        self.assertNotIn("Review", self.events)
        self.assertNotIn("confirm", self.events)
        self.assertNotIn("Submit application", self.events)
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "failed")

    def test_review_navigation_changed_before_submit_does_not_create_uncertain_attempt(self):
        search = spec("changed-review")
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace["current_submit_button"] = Mock(side_effect=RuntimeError("review: not on final screen"))
        self.execute(manifest)
        self.assertNotIn("Submit application", self.events)
        self.assertFalse(manifest.has_uncertain_submission(search))
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "failed")

    def test_no_receipt_after_submit_remains_uncertain_and_does_not_consume_quota(self):
        search = spec("no-receipt")
        manifest = self.manifest([search], {search.query_id: [["1", "2"]]})
        self.namespace["wait_for_submission_confirmation"] = Mock(side_effect=RuntimeError("submit: confirmation unavailable"))
        self.execute(manifest)
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(self.visited, ["1"])
        self.assertTrue(manifest.has_uncertain_submission(search))
        self.assertEqual(manifest.query(search.query_id)["applied_count"], 0)
        self.assertFalse((self.directory / "applied.csv").exists())

    def test_dialog_open_failure_on_second_job_cannot_reuse_first_jobs_modal(self):
        search = spec("fresh-dialog", 2)
        manifest = self.manifest([search], {search.query_id: [["1", "2"]]})
        self.namespace["wait_for_application_modal"] = Mock(side_effect=[self.modal, RuntimeError("open: no current dialog")])
        self.execute(manifest)
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(manifest.query(search.query_id)["applied_count"], 1)
        self.assertEqual(manifest.query(search.query_id)["jobs"]["2"]["status"], "failed")
        self.assertIn("open: no current dialog", self.rows("failed.csv")[0]["Stack Trace"])

    def test_closing_review_confirmation_discards_without_submission(self):
        search = spec("review-closed")
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace["pyautogui"].confirm = lambda *args: None
        self.execute(manifest)
        self.assertNotIn("Submit application", self.events)
        self.assertFalse(manifest.has_uncertain_submission(search))

    def test_confirmed_submission_survives_optional_receipt_dismiss_failure(self):
        search = spec('confirmed-before-dismiss-error')
        manifest = self.manifest([search], {search.query_id: [['1']]})
        self.namespace['actions'] = Mock()
        self.namespace['actions'].send_keys.return_value.perform.side_effect = RuntimeError('Receipt already disappeared')
        self.execute(manifest)
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'applied')
        # Successful jobs remain in the audit ledger and are excluded from
        # retry selection by their applied status.
        ledger = json.loads((self.directory / 'deferred_applications' / 'retry_jobs.json').read_text())
        self.assertEqual(ledger['records'][0]['status'], 'applied')
        self.assertEqual(self.namespace['failed_count'], 0)
        self.assertEqual(self.rows()[0]['Job ID'], '1')

    def test_stale_synthetic_references_block_a_normal_submission(self):
        search = spec('stale-test-references')
        manifest = self.manifest([search], {search.query_id: [['1']]})
        self.namespace['answer_questions'] = Mock(return_value={
            ('References', 'TEST DATA ONLY — Sample Manager', 'textarea', '')})
        self.execute(manifest)
        self.assertNotIn('Submit application', self.events)
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'failed')
        self.namespace['wait_for_submission_confirmation'].assert_not_called()

    def test_prepare_only_stops_after_ten_forms_without_any_submission_or_applied_history(self):
        import json
        search = spec("ten-preparations", 1)
        manifest = self.manifest([search], {search.query_id: [[str(i) for i in range(1, 13)]]})
        def already_retained(browser):
            archive = json.loads((self.directory / 'deferred_applications' / 'retry_jobs.json').read_text())
            record = next(row for row in archive['records'] if row['job_id'] == self.visited[-1])
            self.assertEqual(record['status'], 'ready')
            self.assertEqual(record['description'], 'A suitable job')
            self.assertEqual(record['job_url'], 'https://www.linkedin.com/jobs/view/' + self.visited[-1] + '/')
            self.assertTrue(record['submission_disabled'])
        with patch('modules.linkedin_form_cleanup.discard_application', side_effect=already_retained) as cleanup:
            self.namespace['execute_search_plan'](manifest, prepare_only=True, preparation_limit=10)
        self.assertEqual(self.visited, [str(i) for i in range(1, 11)])
        self.assertEqual(cleanup.call_count, 10)
        self.assertNotIn('Submit application', self.events)
        self.assertNotIn('confirm', self.events)
        self.namespace['wait_for_submission_confirmation'].assert_not_called()
        self.assertEqual(manifest.query(search.query_id)['applied_count'], 0)
        self.assertTrue(all(row['status'] == 'prepared' for row in manifest.query(search.query_id)['jobs'].values()))
        self.assertFalse((self.directory / 'applied.csv').exists())
        report = json.loads(next((self.directory / 'form_validations').glob('*.json')).read_text())
        self.assertEqual((report['attempted'], report['ready'], report['failed']), (10, 10, 0))
        self.assertTrue(report['submission_disabled'])

    def test_prepare_only_skips_external_application_and_continues_after_form_failure(self):
        search = spec('preparation-failure', 1)
        manifest = self.manifest([search], {search.query_id: [['1', '2', '3', '4']]})
        self.namespace['try_xp'] = lambda *args: self.visited[-1] != '1'
        external = self.namespace['external_apply'] = Mock()
        original = self.namespace['answer_questions']
        self.namespace['answer_questions'] = lambda *a, **k: (
            (_ for _ in ()).throw(RuntimeError('Question validation failed'))
            if self.visited[-1] == '2' else original(*a, **k))
        with patch('modules.linkedin_form_cleanup.discard_application'):
            self.namespace['execute_search_plan'](manifest, prepare_only=True, preparation_limit=2)
        self.assertEqual(self.visited, ['1', '2', '3'])
        external.assert_not_called()
        self.assertNotIn('Submit application', self.events)
        self.assertEqual(manifest.query(search.query_id)['jobs']['2']['status'], 'failed')
        self.assertEqual(manifest.query(search.query_id)['jobs']['3']['status'], 'prepared')
        import json
        archive = json.loads((self.directory / 'deferred_applications' / 'retry_jobs.json').read_text())
        failed = next(row for row in archive['records'] if row['job_id'] == '2')
        self.assertIn('Question validation failed', failed['failed_reasons'])

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

    def test_repeated_filter_failure_stops_after_one_fresh_query_recovery(self):
        from modules.linkedin_search import SearchUIError
        searches = [spec("first"), spec("second"), spec("third")]
        manifest = self.manifest(searches, {})
        self.namespace['prepare_search'] = Mock(side_effect=lambda *args: (_ for _ in ()).throw(
            SearchUIError('Date options unavailable', stage='filter',
                          details={'filter': 'date_posted', 'substep': 'read_options',
                                   'error_type': 'TimeoutException'})))
        self.execute(manifest)
        self.assertEqual(self.namespace['prepare_search'].call_count, 2)
        self.assertEqual(manifest.data['stop_reason'], 'search_filter_unavailable')
        self.assertEqual(manifest.data['status'], 'interrupted')
        self.assertTrue(self.namespace['application_ui_blocked'])
        self.assertTrue(all(manifest.query(row.query_id)['status'] == 'pending' for row in searches))
        self.assertEqual(self.visited, [])

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

    def test_uncertain_external_submission_retained_while_remaining_capacity_is_used(self):
        from modules.application_budget import ApplicationBudget
        from modules.external_apply import ExternalApplicationResult
        from modules.linkedin_deferred import DeferredJobs
        first, second = spec('external-held', 3), spec('next', 3)
        manifest = self.manifest([first, second], {'external-held': [['1', '2']], 'next': [['1', '3', '4']]})
        extract_functions(self.namespace, 'checkpoint_external_application')
        self.namespace['try_xp'] = lambda *args: self.visited[-1] != '1'
        self.namespace['external_apply'] = Mock(return_value=ExternalApplicationResult(
            'submitting', 'https://example.test/application', reason='Receipt not confirmed'))
        budget = ApplicationBudget(3)
        self.execute(manifest, budget)
        self.assertEqual(self.visited, ['1', '2', '3'])
        self.namespace['external_apply'].assert_called_once()
        self.assertEqual(budget.count, 2)
        self.assertEqual(budget.reserved_ids, {'1'})
        self.assertEqual(manifest.query(first.query_id)['jobs']['1']['status'], 'submitting')
        self.assertEqual(manifest.query(first.query_id)['stop_reason'], 'submission_uncertain')
        self.assertEqual(load_applied_job_ids(self.directory / 'applied.csv'), {'2', '3'})
        held = next(r for r in DeferredJobs(self.directory / 'deferred_applications/retry_jobs.json').records if r['job_id'] == '1')
        self.assertEqual(held['status'], 'submission_uncertain')
        self.assertTrue(held['requires_submission_check'])
        self.assertEqual(held['company'], 'Example')

    def test_uncertain_external_submission_reserves_last_capacity_slot(self):
        from modules.application_budget import ApplicationBudget
        from modules.external_apply import ExternalApplicationResult
        search = spec('held-at-cap', 3)
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        extract_functions(self.namespace, 'checkpoint_external_application')
        self.namespace['try_xp'] = lambda *args: False
        self.namespace['external_apply'] = Mock(return_value=ExternalApplicationResult('submitting', 'https://example.test/application'))
        budget = ApplicationBudget(1)
        self.execute(manifest, budget)
        self.assertEqual(self.visited, ['1'])
        self.assertEqual(budget.count, 0)
        self.assertEqual(budget.reserved_ids, {'1'})
        self.assertEqual(manifest.data['stop_reason'], 'submission_uncertain')

    def test_uncertain_external_cleanup_recovers_search_without_reapplying_held_job(self):
        from modules.external_apply import ExternalApplicationResult
        search = spec('external-cleanup', 3)
        manifest = self.manifest([search], {search.query_id: [['1', '2']]})
        extract_functions(self.namespace, 'checkpoint_external_application')
        self.namespace['try_xp'] = lambda *args: self.visited[-1] != '1'
        self.namespace['external_apply'] = Mock(return_value=ExternalApplicationResult('submitting', 'https://example.test/application'))
        self.namespace['clear_post_submit_ui'] = Mock(side_effect=[RuntimeError('Overlay remains'), None, None])
        self.execute(manifest)
        self.assertEqual(self.visited, ['1', '2'])
        self.namespace['external_apply'].assert_called_once()
        self.assertEqual(manifest.query(search.query_id)['ui_recoveries'][0]['status'], 'recovered')
        self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'], 'submitting')
        self.assertEqual(manifest.query(search.query_id)['jobs']['2']['status'], 'applied')

    def test_easy_apply_only_never_opens_an_employer_site(self):
        extract_functions(self.namespace, 'external_apply')
        self.namespace['easy_apply_only'] = True
        self.namespace['driver'] = Mock()
        self.namespace['wait'].until = Mock()
        result = self.namespace['external_apply'](None, '123', 'https://www.linkedin.com/jobs/view/123/',
                                                  'resume.pdf', datetime.now(), '', '')
        self.assertTrue(result[0])
        self.namespace['driver'].get.assert_not_called()
        self.namespace['wait'].until.assert_not_called()

    def test_successful_submission_survives_later_modal_failure(self):
        first, second = spec("first"), spec("second")
        manifest = self.manifest([first, second], {"first": [["1"]], "second": [["1", "2"]]})

        self.namespace['actions'] = Mock()
        self.namespace['actions'].send_keys.return_value.perform.side_effect = RuntimeError('Confirmation receipt disappeared')
        self.execute(manifest)
        self.assertEqual(self.visited, ["1", "2"])
        self.assertEqual(self.events.count("Submit application"), 2)
        self.assertEqual(manifest.query("first")["jobs"]["1"]["status"], "applied")
        self.assertEqual(manifest.query("first")["applied_count"], 1)
        self.assertEqual(self.namespace["failed_count"], 0)
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
        search.filters_snapshot["intent"] = {"easy_apply_only": True, "under_10_applicants": True,
                                            "search_location": "San Francisco Bay Area"}
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
            "buffer": lambda *args: None, "set_search_location": Mock(return_value=None),
            "scroll_to_view": Mock(), "try_xp": Mock(),
            "pause_after_filters": False, "apply_configured_filters": apply_configured_filters,
            "actions": SimpleNamespace(move_to_element=lambda control: (
                moves.append(control) or SimpleNamespace(click=lambda: SimpleNamespace(perform=lambda: None)))),
        }
        extract_functions(namespace, "apply_filters")
        warnings = namespace["apply_filters"](search)
        self.assertEqual(moves, [unselected])
        self.assertFalse(any("easy_apply_only" in warning or "under_10_applicants" in warning for warning in warnings))
        namespace["set_search_location"].assert_called_once_with("San Francisco Bay Area")

    def test_classic_external_mode_clears_previous_easy_apply_switch(self):
        search = spec('external-filters')
        search.mode = 'classic'
        search.filters_snapshot['intent'] = {'application_mode':'external_only', 'easy_apply_only':False}
        selected = [True]
        label = Mock()
        label.click.side_effect = lambda: selected.__setitem__(0, False)
        control = SimpleNamespace(is_selected=lambda: selected[0], find_elements=lambda *a: [label])
        browser = Mock()
        browser.find_elements.side_effect = lambda by, xpath: [control] if '//fieldset[' in xpath else []
        namespace = {'driver':browser, 'By':self.namespace['By'], 'NoSuchElementException':MissingElement,
            'buffer':Mock(), 'scroll_to_view':Mock(), 'try_xp':Mock(), 'pause_after_filters':False,
            'apply_configured_filters':apply_configured_filters}
        extract_functions(namespace, 'apply_filters')
        namespace['apply_filters'](search)
        label.click.assert_called_once()
        self.assertFalse(selected[0])

    def test_out_of_area_hybrid_job_skips_before_description_form_upload_or_submit(self):
        search = spec("bay-area")
        search.filters_snapshot["intent"]["search_location"] = "San Francisco Bay Area"
        manifest = self.manifest([search], {search.query_id: [["1"]]})

        def outside(job, *args):
            self.visited.append(job.job_id)
            return job.job_id, "Staff Platform Engineer", "Example", "New York, NY (Hybrid)", "Hybrid", False

        self.namespace["get_job_main_details"] = outside
        description, form, upload = Mock(), Mock(), Mock()
        self.namespace.update({"get_job_description": description, "try_xp": form,
                               "upload_optimized_resume": upload, "use_AI_for_resume": True})
        self.execute(manifest)
        description.assert_not_called()
        form.assert_not_called()
        upload.assert_not_called()
        self.assertNotIn("confirm", self.events)
        self.assertNotIn("Submit application", self.events)
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "skipped")
        self.assertIn("location_excluded", manifest.query(search.query_id)["jobs"]["1"]["reason"])
        self.assertIn("location_excluded", self.rows("failed.csv")[0]["Assumed Reason"])

    def test_out_of_area_on_site_job_is_rejected_using_snapshot_not_global_location(self):
        search = spec("bay-area-snapshot")
        search.filters_snapshot["intent"]["search_location"] = "San Francisco Bay Area"
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace["search_location"] = "New York, United States"
        self.namespace["get_job_main_details"] = lambda job, *args: (
            job.job_id, "Staff Platform Engineer", "Example", "New York, United States", "On-site", False)
        form = self.namespace["try_xp"] = Mock()
        self.execute(manifest)
        form.assert_not_called()
        self.assertNotIn("Submit application", self.events)
        self.assertIn("location_excluded", manifest.query(search.query_id)["jobs"]["1"]["reason"])

    def test_bay_area_hybrid_job_remains_eligible_for_application(self):
        search = spec("bay-area-hybrid")
        search.filters_snapshot["intent"]["search_location"] = "San Francisco Bay Area"
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace["get_job_main_details"] = lambda job, *args: (
            job.job_id, "Staff Platform Engineer", "Example", "Palo Alto, California (Hybrid)", "Hybrid", False)
        self.execute(manifest)
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "applied")

    def test_us_remote_job_remains_eligible_under_existing_bay_area_policy(self):
        search = spec("bay-area-remote")
        search.filters_snapshot["intent"]["search_location"] = "San Francisco Bay Area"
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace["get_job_main_details"] = lambda job, *args: (
            job.job_id, "Staff Platform Engineer", "Example", "United States (Remote)", "Remote", False)
        self.execute(manifest)
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "applied")

    def test_missing_job_geography_is_skipped_when_search_location_is_configured(self):
        search = spec("bay-area-unknown")
        search.filters_snapshot["intent"]["search_location"] = "San Francisco Bay Area"
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace["get_job_main_details"] = lambda job, *args: (
            job.job_id, "Staff Platform Engineer", "Example", "", "Remote", False)
        form = self.namespace["try_xp"] = Mock()
        self.execute(manifest)
        form.assert_not_called()
        self.assertIn("unknown_location", manifest.query(search.query_id)["jobs"]["1"]["reason"])

    def test_empty_snapshot_location_does_not_restrict_jobs_using_stale_global_location(self):
        search = spec("any-location")
        search.filters_snapshot["intent"]["search_location"] = ""
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace["search_location"] = "San Francisco Bay Area"
        self.namespace["get_job_main_details"] = lambda job, *args: (
            job.job_id, "Staff Platform Engineer", "Example", "New York, NY (Hybrid)", "Hybrid", False)
        self.execute(manifest)
        self.assertEqual(self.events.count("Submit application"), 1)
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "applied")

    def test_classic_location_selection_error_leaves_query_resumable_without_processing_jobs(self):
        from modules.linkedin_search import LocationSelectionError

        search = spec("uncommitted-location")
        search.filters_snapshot["intent"]["search_location"] = "San Francisco Bay Area"
        manifest = self.manifest([search], {search.query_id: [["1"]]})
        self.namespace["apply_filters"] = Mock(side_effect=LocationSelectionError("Requested location was not committed"))
        self.execute(manifest)
        self.assertEqual(self.visited, [])
        self.assertNotIn("Submit application", self.events)
        self.assertEqual(manifest.query(search.query_id)["status"], "pending")
        self.assertEqual(manifest.query(search.query_id)["stop_reason"], "search_error:LocationSelectionError")
        self.assertEqual(manifest.data["status"], "interrupted")

    def test_uncommitted_location_with_wrong_geography_no_results_banner_is_still_resumable(self):
        from modules.linkedin_search import LocationSelectionError

        search = spec("wrong-location-empty-results")
        search.filters_snapshot["intent"]["search_location"] = "San Francisco Bay Area"
        manifest = self.manifest([search], {search.query_id: [[]]})
        self.namespace["apply_filters"] = Mock(side_effect=LocationSelectionError("Wrong geography still selected"))
        original = self.browser.find_elements

        def with_empty_results(by, selector):
            if "jobs-search-no-results" in selector:
                return [SimpleNamespace(text="No matching jobs found")]
            return original(by, selector)

        self.browser.find_elements = with_empty_results
        self.execute(manifest)
        self.assertEqual(self.visited, [])
        self.assertEqual(manifest.query(search.query_id)["status"], "pending")
        self.assertEqual(manifest.query(search.query_id)["stop_reason"], "search_error:LocationSelectionError")
        self.assertEqual(manifest.data["status"], "interrupted")

    def test_ai_location_picker_warning_does_not_bypass_mandatory_job_geography_gate(self):
        search = spec("ai-location-gate")
        search.filters_snapshot["intent"]["search_location"] = "San Francisco Bay Area"
        manifest = self.manifest([search], {search.query_id: [["1"]]})

        def start(browser, search, *args):
            browser.start(search)
            return SearchResult("ai")

        self.namespace["start_search"] = start
        self.namespace["apply_filters"] = lambda current: ["AI search location UI unavailable; configured job geography gate remains active"]
        self.namespace["get_job_main_details"] = lambda job, *args: (
            job.job_id, "Staff Platform Engineer", "Example", "New York, NY (Hybrid)", "Hybrid", False)
        form = self.namespace["try_xp"] = Mock()
        self.execute(manifest)
        form.assert_not_called()
        self.assertIn("location_excluded", manifest.query(search.query_id)["jobs"]["1"]["reason"])
        self.assertTrue(any("location UI unavailable" in warning for warning in manifest.query(search.query_id)["warnings"]))

    def test_selected_job_geography_uses_live_details_instead_of_saved_location(self):
        search = spec("selected-location")
        search.filters_snapshot["intent"]["search_location"] = "San Francisco Bay Area"
        manifest = self.manifest([search], {})
        selected = {search.query_id: [{"id": "1", "linkedin_id": "1", "location": "San Francisco, California", "workplace_type": "Hybrid"}]}
        self.browser.get = Mock()
        self.namespace["selected_live_details"] = Mock(return_value=(
            "1", "Staff Platform Engineer", "Example", "New York, NY (Hybrid)", "Hybrid", False))
        form, upload = Mock(), Mock()
        self.namespace.update({"try_xp": form, "upload_optimized_resume": upload, "use_AI_for_resume": True})
        self.namespace["execute_search_plan"](manifest, selected_jobs=selected)
        manifest.finish()
        self.browser.get.assert_called_once_with("https://www.linkedin.com/jobs/view/1")
        self.namespace["selected_live_details"].assert_called_once()
        form.assert_not_called()
        upload.assert_not_called()
        self.assertNotIn("Submit application", self.events)
        self.assertIn("location_excluded", manifest.query(search.query_id)["jobs"]["1"]["reason"])

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


class SearchResultsTransitionTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.previous = SimpleNamespace(detached=False)

        def stale_condition(element):
            def condition(driver):
                self.events.append("old_cards_detached" if element.detached else "old_cards_retained")
                return element.detached
            return condition

        self.staleness = Mock(side_effect=stale_condition)

        def ready(driver):
            self.events.append("results_ready")
            return "jobs"

        def until(condition):
            for _ in range(3):
                result = condition(self.namespace["driver"])
                if result:
                    return result
                self.previous.detached = True
            raise AssertionError("Search result transition never completed")

        self.namespace = {"driver": SimpleNamespace(), "EC": SimpleNamespace(staleness_of=self.staleness),
                          "WebDriverWait": lambda *args: SimpleNamespace(until=until),
                          "search_results_ready": ready}
        extract_functions(self.namespace, "wait_for_search_results")

    def test_classic_new_query_waits_for_previous_cards_before_accepting_ready_list(self):
        with patch("modules.linkedin_modern_search.detect_modern_ui", return_value=False):
            self.namespace["wait_for_search_results"]([self.previous])
        self.staleness.assert_called_once_with(self.previous)
        self.assertEqual(self.events, ["old_cards_retained", "old_cards_detached", "results_ready"])

    def test_modern_reused_cards_wait_for_ready_state_without_requiring_staleness(self):
        with patch("modules.linkedin_modern_search.detect_modern_ui", return_value=True):
            self.namespace["wait_for_search_results"]([self.previous])
        self.staleness.assert_not_called()
        self.assertEqual(self.events, ["results_ready"])
        self.assertFalse(self.previous.detached)

    def test_identical_classic_query_with_no_previous_cards_does_not_wait_for_staleness(self):
        with patch("modules.linkedin_modern_search.detect_modern_ui", return_value=False):
            self.namespace["wait_for_search_results"]([])
        self.staleness.assert_not_called()
        self.assertEqual(self.events, ["results_ready"])




class EasyApplyEntryRegressionTests(unittest.TestCase):
    """Sanitized replay of the captured anchor and native limit dialog."""

    def browser(self, control=None):
        from test_linkedin_easy_apply import Browser
        control = control or '<a aria-disabled="false" aria-label="Easy Apply to this job" href="https://www.linkedin.com/jobs/search-results/?currentJobId=123">Easy Apply</a>'
        browser = Browser(['<main data-view-name="job-detail-page"><section id="JobDetails_AboutTheJob_123">Job</section>' + control + '</main>'])
        browser.current_url = 'https://www.linkedin.com/jobs/search-results/?currentJobId=123'
        return browser

    def test_modern_anchor_is_found_without_clicking(self):
        from modules.linkedin_job_details import modern_easy_apply_button
        browser = self.browser()
        control = modern_easy_apply_button(browser, '123')
        self.assertIsNotNone(control)
        self.assertEqual(control.get_attribute('aria-label'), 'Easy Apply to this job')
        self.assertEqual(browser.clicks, [])

    def test_entry_anchor_and_button_open_form_without_submitting(self):
        from modules.linkedin_easy_apply import open_easy_apply
        from test_linkedin_easy_apply import form
        for tag in ('a', 'button'):
            browser = self.browser(f'<{tag} aria-label="Easy Apply to this job">Easy Apply</{tag}>')
            browser.pages.append(form(action='Submit application'))
            self.assertTrue(open_easy_apply(browser, '123', timeout=.01))
            self.assertEqual(browser.clicks, ['Easy Apply'])

    def test_native_limit_after_anchor_is_not_a_missing_form(self):
        from modules.linkedin_easy_apply import open_easy_apply, EasyApplyLimitReached
        browser = self.browser()
        browser.pages.append('<dialog open data-testid="dialog"><p>You reached today’s Easy Apply limit</p><p>Save this job and continue applying tomorrow.</p><button>Got it</button></dialog>')
        with self.assertRaises(EasyApplyLimitReached):
            open_easy_apply(browser, '123', timeout=.01)
        self.assertEqual(browser.clicks, ['Easy Apply'])

    def test_limit_detected_before_form_and_ignores_hidden_dialog(self):
        from modules.linkedin_easy_apply import wait_for_application_modal, EasyApplyLimitReached
        from test_linkedin_easy_apply import Browser, form
        limit = '<dialog open><p>You reached today’s Easy Apply limit</p></dialog>'
        with self.assertRaises(EasyApplyLimitReached):
            wait_for_application_modal(Browser([limit]), timeout=.01)
        browser = Browser([limit.replace('<dialog open>', '<dialog open hidden>') + form(action='Submit application')])
        self.assertTrue(wait_for_application_modal(browser, timeout=.01))
        self.assertEqual(browser.clicks, [])

    def test_wrong_job_or_disabled_control_never_clicked(self):
        from modules.linkedin_easy_apply import open_easy_apply, EasyApplyError
        for control in ('<a aria-disabled="true" aria-label="Easy Apply to this job">Easy Apply</a>',
                        '<a aria-label="Easy Apply to this job" href="https://www.linkedin.com/jobs/view/999/">Easy Apply</a>'):
            browser = self.browser(control)
            with self.assertRaises(EasyApplyError):
                open_easy_apply(browser, '123', timeout=.01)
            self.assertEqual(browser.clicks, [])
        browser = self.browser()
        with self.assertRaises(EasyApplyError):
            open_easy_apply(browser, '999', timeout=.01)
        self.assertEqual(browser.clicks, [])

    def test_missing_entry_is_an_error_and_external_is_explicit(self):
        from modules.linkedin_easy_apply import open_easy_apply, EasyApplyError
        browser = self.browser('<p>Loading</p>')
        with self.assertRaisesRegex(EasyApplyError, 'entry:'):
            open_easy_apply(browser, '123', timeout=.01)
        browser = self.browser('<a aria-label="Apply to this job" href="https://example.test/careers">Apply</a>')
        self.assertFalse(open_easy_apply(browser, '123', timeout=.01))
        self.assertEqual(browser.clicks, [])


    def test_classic_button_opens_form_without_submitting(self):
        from modules.linkedin_easy_apply import open_easy_apply
        from test_linkedin_easy_apply import Browser, form
        browser = Browser(['<div class="jobs-unified-top-card"><button class="jobs-apply-button" aria-label="Easy Apply to Example">Easy Apply</button></div>', form(classic=True)])
        browser.current_url = 'https://www.linkedin.com/jobs/view/123/'
        self.assertTrue(open_easy_apply(browser, '123', timeout=.01))
        self.assertEqual(browser.clicks, ['Easy Apply'])

    def test_stale_or_intercepted_entry_is_reacquired_and_clicked_once(self):
        from modules.linkedin_easy_apply import open_easy_apply
        from selenium.common.exceptions import StaleElementReferenceException, ElementClickInterceptedException
        from test_linkedin_easy_apply import Node, form
        original = Node.click
        for error in (StaleElementReferenceException, ElementClickInterceptedException):
            browser = self.browser()
            browser.pages.append(form())
            attempts = []
            def click(node):
                attempts.append(node.revision)
                if len(attempts) == 1:
                    browser.render()
                    raise error('rerendered entry')
                original(node)
            with patch.object(Node, 'click', click):
                self.assertTrue(open_easy_apply(browser, '123', timeout=.3))
            self.assertEqual(browser.clicks, ['Easy Apply'])
            self.assertEqual(len(attempts), 2)
            self.assertNotEqual(attempts[0], attempts[1])

    def test_entry_waits_for_control_to_appear(self):
        from modules.linkedin_easy_apply import open_easy_apply
        from test_linkedin_easy_apply import form
        browser = self.browser('<p>Loading</p>')
        original = browser.find_elements
        polls = []
        def elements(by, selector):
            polls.append(selector)
            if len(polls) == 6:
                browser.pages[0] = '<main data-view-name="job-detail-page"><section id="JobDetails_AboutTheJob_123">Job</section><button aria-label="Easy Apply to this job">Easy Apply</button></main>'
                browser.render()
            return original(by, selector)
        browser.find_elements = elements
        browser.pages.append(form())
        self.assertTrue(open_easy_apply(browser, '123', timeout=.5))
        self.assertEqual(browser.clicks, ['Easy Apply'])

    def test_click_retries_are_bounded_and_do_not_bypass_overlay(self):
        from modules.linkedin_easy_apply import open_easy_apply, EasyApplyError
        from selenium.common.exceptions import ElementClickInterceptedException
        from test_linkedin_easy_apply import Node
        browser = self.browser()
        with patch.object(Node, 'click', side_effect=ElementClickInterceptedException()) as click:
            with self.assertRaisesRegex(EasyApplyError, '3 attempts'):
                open_easy_apply(browser, '123', timeout=1)
        self.assertEqual(click.call_count, 3)
        self.assertEqual(browser.clicks, [])

    def test_preexisting_limit_never_clicks_entry_or_got_it(self):
        from modules.linkedin_easy_apply import open_easy_apply, EasyApplyLimitReached
        browser = self.browser()
        browser.pages[0] += '<dialog open><p>You reached today’s Easy Apply limit</p><button>Got it</button></dialog>'
        browser.render()
        with self.assertRaises(EasyApplyLimitReached):
            open_easy_apply(browser, '123', timeout=.01)
        self.assertEqual(browser.clicks, [])




class ReceiptRecoveryTests(unittest.TestCase):
    def test_standalone_profile_promotion_selects_not_now_without_receipt_wording(self):
        from modules.linkedin_post_submit import clear_post_submit_ui
        browser=self.browser(['''<div role="dialog"><h2>Next best action</h2>
            <p>You can keep track of your application in the "Applied" tab of My Jobs</p>
            <h3>Turn your resume into a profile that recruiters notice</h3>
            <button aria-label="Dismiss"></button><button>Not now</button><button>Update profile</button>
            </div>''','<main>Jobs</main>'])
        clear_post_submit_ui(browser,'123',timeout=.1,quiet_seconds=0)
        self.assertEqual(browser.clicks,['Not now'])

    def test_profile_promotion_with_active_fields_is_not_dismissed(self):
        from modules.linkedin_post_submit import clear_post_submit_ui,PostSubmitUIBlocked
        browser=self.browser(['''<dialog open><h2>Turn your resume into a profile that recruiters notice</h2>
            <form><input name="current-employer"></form><button>Not now</button><button>Update profile</button></dialog>'''])
        with self.assertRaises(PostSubmitUIBlocked):
            clear_post_submit_ui(browser,'123',timeout=.01,quiet_seconds=0)
        self.assertEqual(browser.clicks,[])

    def checkbox_form(self,markup,**settings):
        import re
        from test_linkedin_modern_search import DOMBrowser
        from selenium.common.exceptions import NoSuchElementException
        from selenium.webdriver.common.by import By
        browser=DOMBrowser('<dialog open>'+markup+'</dialog>')
        def click(node):
            if node.tag=='label':node=browser.root.xpath('//*[@id=$ident]',ident=node.get('for'))[0]
            if node.get('role')=='checkbox':node.set('aria-checked','false' if node.get('aria-checked')=='true' else 'true')
            elif node.get('checked') is None:node.set('checked','')
            else:node.attrib.pop('checked')
            browser.clicks.append(node.get('id'))
        browser.click=click
        def locate(root,query,*args):
            matches=root.find_elements(By.XPATH,query)
            return matches[0] if matches else False
        def missing(*args):raise NoSuchElementException()
        actions=SimpleNamespace(move_to_element=lambda node:SimpleNamespace(click=lambda:SimpleNamespace(perform=node.click)))
        ns=dict(By=By,re=re,driver=browser,try_xp=locate,find_by_class=missing,NoSuchElementException=NoSuchElementException,
                actions=actions,print_lg=Mock(),overwrite_previous_answers=False,**settings)
        extract_functions(ns,'answer_questions','answer_common_questions',
                          '_resume_work_history_dates','_fill_resume_work_history_dates')
        return browser,ns

    def test_binary_sponsorship_group_selects_only_configured_yes(self):
        markup = '''<div componentkey="easyApplyFieldFocus_ea_validation_p2_0_1">
          <p>Would you require visa sponsorship?*</p><fieldset>
          <div id="yes" role="checkbox" aria-checked="false"><input id="y" type="checkbox" style="display:none"><label for="y"></label><p>Yes</p></div>
          <div id="no" role="checkbox" aria-checked="false"><input id="n" type="checkbox" style="display:none"><label for="n"></label><p>No</p></div>
          </fieldset><p>This field is required</p></div>'''
        browser, ns = self.checkbox_form(markup, require_visa='Yes')
        questions = ns['answer_questions'](browser.find_element('css selector', 'dialog'), set(), 'Bay Area')
        self.assertEqual(browser.clicks, ['yes'])
        self.assertTrue(any(q[:3] == ('Would you require visa sponsorship?*', 'Yes', 'checkbox_group') for q in questions))
        ns['answer_questions'](browser.find_element('css selector', 'dialog'), questions, 'Bay Area')
        self.assertEqual(browser.clicks, ['yes'])  # A second fill must not toggle it off.

    def test_binary_group_clears_conflicting_selection_before_selecting(self):
        browser, ns = self.checkbox_form('''<p>Would you require visa sponsorship?*</p><fieldset>
          <div id="yes" role="checkbox" aria-checked="false"><input id="y" type="checkbox"><p>Yes</p></div>
          <div id="no" role="checkbox" aria-checked="true"><input id="n" type="checkbox"><p>No</p></div>
          </fieldset>''', require_visa='Yes')
        ns['answer_questions'](browser.find_element('css selector','dialog'),set(),'Bay Area')
        self.assertEqual(browser.clicks, ['no', 'yes'])

    def test_binary_group_verifies_click_persisted(self):
        browser, ns = self.checkbox_form('''<p>Would you require visa sponsorship?*</p><fieldset>
          <div role="checkbox" aria-checked="false"><input type="checkbox"><p>Yes</p></div>
          <div role="checkbox" aria-checked="false"><input type="checkbox"><p>No</p></div>
          </fieldset>''', require_visa='Yes')
        browser.click = lambda node: None
        from modules.linkedin_easy_apply import MissingApplicationAnswer
        with self.assertRaisesRegex(MissingApplicationAnswer, 'did not persist'):
            ns['answer_questions'](browser.find_element('css selector','dialog'),set(),'Bay Area')

    def test_binary_agreement_cannot_bypass_existing_confirmation_requirement(self):
        browser, ns = self.checkbox_form('''<p>Do you agree to sign electronically?*</p><fieldset>
          <div role="checkbox" aria-checked="false"><input type="checkbox"><p>Yes</p></div>
          <div role="checkbox" aria-checked="false"><input type="checkbox"><p>No</p></div></fieldset>''')
        from modules.linkedin_easy_apply import MissingApplicationAnswer
        with self.assertRaisesRegex(MissingApplicationAnswer, 'needs confirmation'):
            ns['answer_questions'](browser.find_element('css selector','dialog'),set(),'Bay Area')
        self.assertEqual(browser.clicks, [])

    def test_required_checkboxes_selected_and_optional_preferences_preserved(self):
        browser,ns=self.checkbox_form('<div><input id="required" type="checkbox" required><label for="required">Required selection*</label></div>'
            '<div><input id="sms" type="checkbox"><label for="sms">Send optional SMS updates</label></div>')
        ns['answer_questions'](browser.find_element('css selector','dialog'),set(),'Bay Area')
        self.assertEqual(browser.clicks,['required'])

    def test_standalone_aria_checkbox_selected_and_state_verified(self):
        browser,ns=self.checkbox_form('<div id="required" role="checkbox" aria-required="true" aria-checked="false" aria-label="Required selection"></div>')
        ns['answer_questions'](browser.find_element('css selector','dialog'),set(),'Bay Area')
        self.assertEqual(browser.clicks,['required'])

    def test_electronic_signature_requires_job_specific_confirmation(self):
        from modules.linkedin_easy_apply import MissingApplicationAnswer
        import os
        for approved,job,expected in [('', '123',False),('999','123',False),('123','123',True)]:
            browser,ns=self.checkbox_form('<div><p>*</p><input id="sign" type="checkbox"><label for="sign">Yes, I agree to sign electronically.</label></div>')
            with patch.dict(os.environ,{'JOBROBO_APPROVED_E_SIGNATURE_JOB_IDS':approved}):
                if expected:ns['answer_questions'](browser.find_element('css selector','dialog'),set(),'Bay Area',job_id=job)
                else:
                    with self.assertRaises(MissingApplicationAnswer):ns['answer_questions'](browser.find_element('css selector','dialog'),set(),'Bay Area',job_id=job)
            self.assertEqual(browser.clicks,['sign'] if expected else [])

    def test_optional_ai_draft_failure_leaves_blank_without_blocking(self):
        from test_linkedin_easy_apply import NavigationTests
        from modules.linkedin_easy_apply import MissingApplicationAnswer
        browser,questions=NavigationTests().answer_native_form('<dialog open><label for="q">Optional descriptive answer</label><textarea id="q"></textarea></dialog>',
            ai_descriptive_answers_enabled=True,_draft_answer=Mock(side_effect=MissingApplicationAnswer('provider unavailable')))
        self.assertEqual(browser.find_element('css selector','#q').get_attribute('value'),None)

    def test_modern_hidden_checkbox_uses_wrapper_text_and_checked_state(self):
        import os
        markup=('<div role="checkbox" aria-checked="false"><div><div>'
            '<input id="sign" type="checkbox" style="display:none"><label for="sign"></label>'
            '</div><p>Yes, I agree to sign electronically.</p></div></div>'
            '<div role="checkbox" aria-checked="false"><input id="sms" type="checkbox" style="display:none">'
            '<label for="sms"></label><p>(Optional) Receive text updates</p></div>')
        browser,ns=self.checkbox_form(markup)
        with patch.dict(os.environ,{'JOBROBO_APPROVED_E_SIGNATURE_JOB_IDS':'123'}):
            questions=ns['answer_questions'](browser.find_element('css selector','dialog'),set(),'Bay Area',job_id='123')
        wrappers=browser.find_elements('css selector','[role="checkbox"]')
        self.assertEqual([n.get_attribute('aria-checked') for n in wrappers],['true','false'])
        self.assertEqual(len(browser.clicks),1)
        self.assertTrue(any('sign electronically' in q[0] and q[1] is True for q in questions))

    def test_preparation_never_opens_help_needed_popup(self):
        h=SearchRunnerTests();h.setUp()
        try:
            h.namespace['pause_at_failed_question']=True
            def blocked(browser,fill,**options):
                self.assertFalse(options['on_blocked']('Required field unavailable'))
                raise ValueError('blocked')
            h.namespace['advance_to_review']=blocked
            with self.assertRaises(ValueError):h.namespace['prepare_easy_apply']('123','Role','JD','Bay Area')
            h.namespace['pyautogui'].alert.assert_not_called()
        finally:h.doCleanups()

    def test_descriptive_provider_failure_retries_once_without_help_popup(self):
        from modules.application_drafts import DraftError
        from modules.ai.application_drafting import ApplicationDraftingError
        h=SearchRunnerTests();h.setUp()
        try:
            source=h.directory/'source.pdf';source.write_bytes(b'%PDF-fixture')
            h.namespace['default_resume_docx_path']=str(source)
            h.namespace['ai_descriptive_answers_enabled']=True
            h.namespace['resume_upload_target']=Mock(return_value=h.modal)
            h.namespace['use_AI_for_resume']=True
            def upload(*args,**kwargs):kwargs['on_attached'](str(source));return True,str(source)
            h.namespace['upload_optimized_resume']=upload
            def answer(modal,questions,*args,draft_answer=None,**kwargs):
                return {('Why this role?',draft_answer('Why this role?','descriptive'),'textarea','')}
            h.namespace['answer_questions']=answer
            error=DraftError('provider failed');error.__cause__=ApplicationDraftingError('request failed')
            drafts=Mock();drafts.answer.side_effect=[error,'A grounded answer'];drafts.artifact_summary.return_value={}
            with patch('modules.application_drafts.ApplicationDrafts',return_value=drafts), \
                 patch('modules.ai.application_drafting.create_drafting_client',return_value=Mock()), \
                 patch('modules.ai.application_drafting.make_drafting_provider',return_value=Mock()):
                h.namespace['prepare_easy_apply']('123','Role','JD','Bay Area')
            self.assertEqual(drafts.answer.call_count,2)
            h.namespace['pyautogui'].alert.assert_not_called()
        finally:h.doCleanups()

    def test_custom_numeric_validation_refills_once_without_manual_popup(self):
        from selenium.webdriver.common.by import By
        h=SearchRunnerTests();h.setUp()
        try:
            h.namespace['By']=By
            h.modal.find_elements=Mock(return_value=[Mock()])
            h.namespace['resume_upload_target']=Mock(return_value=None)
            answer=Mock(return_value=set())
            h.namespace['answer_questions']=answer
            def blocked(browser,fill,**options):
                fill(h.modal)
                self.assertTrue(options['on_blocked']('next blocked by form validation (Invalid input)'))
                self.assertFalse(options['on_blocked']('next blocked by form validation (Invalid input)'))
                return h.modal
            h.namespace['advance_to_review']=blocked
            with patch('modules.linkedin_work_history.repair_work_history_dates',return_value=False), \
                 patch('modules.linkedin_form_fields.field_limit',return_value=20), \
                 patch('modules.linkedin_form_fields.short_numeric_rejection',return_value=True):
                h.namespace['prepare_easy_apply']('123','Role','JD','Bay Area')
            self.assertEqual(answer.call_count,2)
            h.namespace['pyautogui'].alert.assert_not_called()
        finally:h.doCleanups()

    def test_stale_answer_controls_reacquired_without_reupload_or_navigation(self):
        h=SearchRunnerTests();h.setUp()
        try:
            source=h.directory/'source.pdf';source.write_bytes(b'%PDF-fixture')
            h.namespace['default_resume_docx_path']=str(source)
            h.namespace['use_AI_for_resume']=True
            h.namespace['resume_upload_target']=Mock(return_value=h.modal)
            def upload(*args,**kwargs):kwargs['on_attached'](str(source));return True,str(source)
            h.namespace['upload_optimized_resume']=Mock(side_effect=upload)
            fresh=Modal()
            h.namespace['wait_for_application_modal']=Mock(side_effect=[h.modal,h.modal,fresh])
            answer=Mock(side_effect=[StaleElementReferenceException('React replaced a field'),set()])
            h.namespace['answer_questions']=answer
            h.namespace['prepare_easy_apply']('123','Role','JD','Bay Area')
            self.assertEqual(answer.call_count,2)
            self.assertIs(answer.call_args_list[-1].args[0],fresh)
            h.namespace['upload_optimized_resume'].assert_called_once()
            self.assertEqual(h.events,[])
            h.namespace['pyautogui'].alert.assert_not_called()
        finally:h.doCleanups()

    def test_persistently_stale_fields_stop_after_three_attempts(self):
        h=SearchRunnerTests();h.setUp()
        try:
            answer=Mock(side_effect=StaleElementReferenceException('Repeated rerender'))
            h.namespace['answer_questions']=answer
            with self.assertRaises(StaleElementReferenceException):
                h.namespace['prepare_easy_apply']('123','Role','JD','Bay Area')
            self.assertEqual(answer.call_count,3)
            self.assertEqual(h.events,[])
        finally:h.doCleanups()

    def test_nonmodal_messaging_does_not_block_clear_job_card(self):
        from modules.linkedin_post_submit import select_job_card
        browser=self.browser(['<aside role="dialog" aria-label="Messaging">'+'<input>'*6+'</aside>'])
        def execute(script,*args):
            if 'jobrobo-dialog-obstruction' in script:return {'blocking':False,'reason':'nonmodal_outside_jobs'}
            return True
        browser.execute_script=execute
        card=SimpleNamespace(click=Mock())
        select_job_card(browser,'123',lambda:('123',card),timeout=.2)
        card.click.assert_called_once()
        self.assertEqual(browser.clicks,[])

    def test_card_local_failure_keeps_pending_and_continues_jobs_then_next_query(self):
        from modules.linkedin_post_submit import JobCardBlocked
        h=SearchRunnerTests();h.setUp()
        try:
            first,second=spec('card-local',3),spec('next-query')
            manifest=h.manifest([first,second],{first.query_id:[['1','2']],second.query_id:[['3']]})
            original=h.namespace['get_job_main_details']
            count=[0]
            def detail(*args):
                count[0]+=1
                if count[0]==1:raise JobCardBlocked('1',{'stage':'select_job_card','cause_type':'CardClickPointObscured'})
                return original(*args)
            h.namespace['get_job_main_details']=detail
            h.execute(manifest)
            self.assertEqual([r['Job ID'] for r in h.rows()],['2','3'])
            self.assertEqual(manifest.query(first.query_id)['jobs']['1']['status'],'in_progress')
            self.assertNotIn('1',manifest.processed_ids())
            self.assertEqual(manifest.query(first.query_id)['stop_reason'],'job_cards_pending')
            self.assertEqual(manifest.query(second.query_id)['status'],'complete')
        finally:h.doCleanups()

    def test_shadow_application_cleanup_closes_form_without_submitting(self):
        from test_linkedin_easy_apply import Browser, form
        from modules.linkedin_form_cleanup import discard_application
        shadow=Browser([form(action='Submit application',extra='<button>Close</button>'),'<main>Jobs</main>'])
        host=SimpleNamespace(id='open-host',shadow_root=shadow)
        browser=Browser(['<main>Jobs</main>'])
        browser.execute_script=Mock(return_value=[host])
        self.assertTrue(discard_application(browser,timeout=.5))
        self.assertEqual(shadow.clicks,['Close'])

    def test_form_inside_unmarked_open_shadow_root_is_found(self):
        from test_linkedin_easy_apply import Browser, form
        from modules.linkedin_easy_apply import wait_for_application_modal
        shadow=Browser([form(action='Submit application')])
        host=SimpleNamespace(id='open-host',shadow_root=shadow)
        browser=Browser(['<main>Jobs</main>'])
        browser.execute_script=Mock(return_value=[host])
        modal=wait_for_application_modal(browser,timeout=.01)
        self.assertIn('Apply',modal.get_attribute('aria-label'))
        self.assertEqual(shadow.clicks,[])

    def test_read_only_containment_adapter_still_finds_document_dialog(self):
        from test_linkedin_easy_apply import Browser, form
        from modules.linkedin_easy_apply import wait_for_application_modal
        browser=Browser([form(action='Submit application')])
        browser.execute_script=lambda script,parent,child:parent.node in child.node.parents
        self.assertTrue(wait_for_application_modal(browser,timeout=.01))
        self.assertEqual(browser.clicks,[])

    def test_fit_warning_inside_shadow_root_continues_only_once(self):
        from test_linkedin_easy_apply import Browser, form
        from modules.linkedin_easy_apply import wait_for_application_modal
        shadow=Browser(['<dialog open><p>This job may not be the best fit</p>'
            '<button>Continue applying</button></dialog>',form(action='Submit application')])
        host=SimpleNamespace(id='open-host',shadow_root=shadow)
        browser=Browser(['<main>Jobs</main>'])
        browser.execute_script=Mock(return_value=[host])
        wait_for_application_modal(browser,timeout=.01)
        self.assertEqual(shadow.clicks,['Continue applying'])

    def test_daily_limit_inside_shadow_root_still_stops(self):
        from test_linkedin_easy_apply import Browser, form
        from modules.linkedin_easy_apply import wait_for_application_modal
        from modules.linkedin_easy_apply import EasyApplyLimitReached
        shadow=Browser(['<dialog open>You reached today’s Easy Apply limit</dialog>'])
        host=SimpleNamespace(id='open-host',shadow_root=shadow)
        browser=Browser(['<main>Jobs</main>'])
        browser.execute_script=Mock(return_value=[host])
        with self.assertRaises(EasyApplyLimitReached):
            wait_for_application_modal(browser,timeout=.01)

    def browser(self, pages):
        from test_linkedin_easy_apply import Browser
        browser=Browser(pages)
        # BeautifulSoup has no layout engine. Real hit-testing is exercised by
        # the separate local Chrome replay; these fixtures model a blocking host.
        browser.execute_script=Mock(return_value=True)
        return browser

    def test_profile_promotion_receipt_prefers_not_now_over_update_profile(self):
        from modules.linkedin_post_submit import clear_post_submit_ui
        browser=self.browser(['''<dialog open><p>Your application was sent to jscreen!</p>
            <h2>Turn your resume into a profile that recruiters notice</h2>
            <button aria-label="Close dialog">×</button><button>Not now</button>
            <button>Update profile</button></dialog>''','<main>Jobs</main>'])
        clear_post_submit_ui(browser,'123',timeout=.1,quiet_seconds=0)
        self.assertEqual(browser.clicks,['Not now'])

    def test_not_now_in_unrelated_or_active_dialog_is_never_clicked(self):
        from modules.linkedin_post_submit import clear_post_submit_ui, PostSubmitUIBlocked
        for body in ('<p>Update your profile</p>',
                     '<p>Your application was sent</p><input><button>Submit application</button>'):
            browser=self.browser(['<dialog open>'+body+'<button>Not now</button></dialog>'])
            with self.assertRaises(PostSubmitUIBlocked):
                clear_post_submit_ui(browser,'123',timeout=.01,quiet_seconds=0)
            self.assertEqual(browser.clicks,[])

    def test_late_receipt_at_card_hit_test_is_dismissed_then_card_reacquired(self):
        from modules.linkedin_post_submit import select_job_card
        from unittest.mock import patch
        browser=SimpleNamespace(execute_script=Mock(side_effect=[None,False,None,True]))
        target=SimpleNamespace(click=Mock())
        acquire=Mock(return_value=('123',target))
        with patch('modules.linkedin_post_submit.clear_post_submit_ui') as cleanup:
            select_job_card(browser,'123',acquire,timeout=1)
        self.assertGreaterEqual(cleanup.call_count,3)
        self.assertGreaterEqual(acquire.call_count,2)
        target.click.assert_called_once()

    def test_clean_entry_failure_continues_other_query_without_retrying_current_job(self):
        from modules.linkedin_easy_apply import EasyApplyError
        h=SearchRunnerTests();h.setUp()
        try:
            first,second=spec('entry-recoverable',2),spec('other-query')
            manifest=h.manifest([first,second],{first.query_id:[['1','2']],second.query_id:[['3']]})
            h.namespace['open_easy_apply']=Mock(side_effect=[EasyApplyError('open: form unavailable'),True,True])
            h.execute(manifest)
            self.assertEqual(h.visited,['1','2','3'])
            self.assertEqual(manifest.query(first.query_id)['jobs']['1']['status'],'in_progress')
            self.assertNotIn('1',manifest.processed_ids())
            self.assertEqual([r['Job ID'] for r in h.rows()],['2','3'])
        finally:h.doCleanups()

    def test_entry_failure_with_unknown_dialog_defers_query_and_tries_next_query(self):
        from modules.linkedin_easy_apply import EasyApplyError
        from modules.linkedin_post_submit import PostSubmitUIBlocked
        h=SearchRunnerTests();h.setUp()
        try:
            first,second=spec('entry-blocked'),spec('untouched')
            manifest=h.manifest([first,second],{first.query_id:[['1']],second.query_id:[['2']]})
            h.namespace['open_easy_apply']=Mock(side_effect=EasyApplyError('open: form unavailable'))
            h.namespace['clear_post_submit_ui']=Mock(side_effect=PostSubmitUIBlocked('1',{'stage':'entry_cleanup'}))
            h.execute(manifest)
            self.assertEqual(h.visited,['1','2'])
            self.assertTrue(manifest.query(first.query_id)['ui_recoveries'])
            self.assertNotIn('1',manifest.processed_ids())
            self.assertFalse((h.directory/'applied.csv').exists())
        finally:h.doCleanups()

    def test_known_receipt_done_closes_without_submit_or_discard(self):
        from modules.linkedin_post_submit import clear_post_submit_ui
        from test_linkedin_easy_apply import Browser
        browser=self.browser(['<div id="interop-outlet"><dialog open><p>Your application was sent</p><button>Done</button></dialog></div>','<main>Jobs</main>'])
        clear_post_submit_ui(browser,'123',timeout=.1,quiet_seconds=0)
        self.assertEqual(browser.clicks,['Done'])
        browser=self.browser(['<dialog open><p>Your application was sent</p><button aria-label="Dismiss">×</button><button>Done</button></dialog>','<main>Jobs</main>'])
        clear_post_submit_ui(browser,'123',timeout=.1,quiet_seconds=0)
        self.assertEqual(browser.clicks,['Done'])

    def test_slow_native_dismissal_gets_a_fresh_clearance_phase(self):
        from modules.linkedin_post_submit import clear_post_submit_ui
        from time import sleep
        browser=self.browser(['<dialog open><p>Your application was sent</p><button>Done</button></dialog>','<main>Jobs</main>'])
        def close(node):
            sleep(.03)
            browser.page=1
            browser.render()
        browser.on_click=close
        clear_post_submit_ui(browser,'123',timeout=.01,quiet_seconds=0)
        self.assertEqual(browser.clicks,['Done'])

    def test_unknown_overlay_is_not_dismissed_or_clicked_through(self):
        from modules.linkedin_post_submit import clear_post_submit_ui, PostSubmitUIBlocked
        from test_linkedin_easy_apply import Browser
        browser=self.browser(['<div id="interop-outlet"><dialog open><p>Unrecognized message</p><button>Continue</button><button>Submit</button></dialog></div>'])
        with self.assertRaises(PostSubmitUIBlocked):clear_post_submit_ui(browser,'123',timeout=.01,quiet_seconds=0)
        self.assertEqual(browser.clicks,[])

    def test_active_application_form_is_never_closed_as_a_receipt(self):
        from modules.linkedin_post_submit import clear_post_submit_ui, PostSubmitUIBlocked
        from test_linkedin_easy_apply import Browser
        browser=self.browser(['<dialog open><p>Your application was sent</p><form><input></form><button>Dismiss</button></dialog>'])
        with self.assertRaises(PostSubmitUIBlocked):clear_post_submit_ui(browser,'123',timeout=.01,quiet_seconds=0)
        self.assertEqual(browser.clicks,[])

    def test_receipt_with_follow_checkbox_can_close_but_submit_form_cannot(self):
        from modules.linkedin_post_submit import clear_post_submit_ui, PostSubmitUIBlocked
        browser=self.browser(['<dialog open><p>Your application was sent</p><input type="checkbox"><button>Done</button></dialog>','<main>Jobs</main>'])
        clear_post_submit_ui(browser,'123',timeout=.1,quiet_seconds=0)
        self.assertEqual(browser.clicks,['Done'])
        browser=self.browser(['<dialog open><p>Your application was sent</p><button>Submit application</button><button>Dismiss</button></dialog>'])
        with self.assertRaises(PostSubmitUIBlocked):clear_post_submit_ui(browser,'123',timeout=.01,quiet_seconds=0)
        self.assertEqual(browser.clicks,[])

    def test_empty_nonblocking_outlet_does_not_stall_next_job(self):
        from modules.linkedin_post_submit import clear_post_submit_ui
        from test_linkedin_easy_apply import Browser
        browser=self.browser(['<div id="interop-outlet"></div>'])
        browser.execute_script=Mock(return_value=False)
        clear_post_submit_ui(browser,'123',timeout=.01,quiet_seconds=0)

    def test_card_reacquired_after_stale_reference(self):
        from modules.linkedin_post_submit import select_job_card
        browser=SimpleNamespace(find_elements=lambda *a:[],execute_script=Mock(return_value=True))
        stale=SimpleNamespace(click=Mock(side_effect=StaleElementReferenceException()))
        fresh=SimpleNamespace(click=Mock())
        acquire=Mock(side_effect=[('123',stale),('123',fresh)])
        select_job_card(browser,'123',acquire,timeout=.2)
        self.assertEqual(acquire.call_count,2);fresh.click.assert_called_once()

    def test_card_click_attempts_bounded_and_wrong_job_never_clicked(self):
        from modules.linkedin_post_submit import select_job_card, JobCardBlocked
        browser=SimpleNamespace(find_elements=lambda *a:[],execute_script=Mock(return_value=True))
        target=SimpleNamespace(click=Mock(side_effect=ElementClickInterceptedException()))
        with self.assertRaises(JobCardBlocked):
            select_job_card(browser,'123',lambda:('123',target),timeout=.2,max_attempts=3)
        self.assertEqual(target.click.call_count,3)
        target.click.reset_mock()
        with self.assertRaises(JobCardBlocked):
            select_job_card(browser,'123',lambda:('999',target),timeout=.2)
        target.click.assert_not_called()

    def test_post_submit_block_preserves_success_when_search_reset_also_fails(self):
        from modules.linkedin_post_submit import PostSubmitUIBlocked
        from test_search_runner import SearchRunnerTests,spec
        h=SearchRunnerTests();h.setUp()
        try:
            search=spec('receipt-blocked',2);manifest=h.manifest([search],{search.query_id:[['1','2']]})
            h.namespace['clear_post_submit_ui']=Mock(side_effect=PostSubmitUIBlocked('123',{'stage':'post_submit_cleanup'}))
            h.execute(manifest)
            self.assertEqual(h.visited,['1']);self.assertEqual(h.namespace['failed_count'],0)
            self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'],'applied')
            self.assertEqual(h.rows()[0]['Job ID'],'1')
            self.assertEqual(manifest.query(search.query_id)['stop_reason'],'job_cards_pending')
        finally:h.doCleanups()

    def test_blocked_card_is_pending_and_not_processed(self):
        from modules.linkedin_post_submit import JobCardBlocked
        from test_search_runner import SearchRunnerTests,spec
        h=SearchRunnerTests();h.setUp()
        try:
            search=spec('card-blocked',2);manifest=h.manifest([search],{search.query_id:[['1','2']]})
            h.namespace['get_job_main_details']=Mock(side_effect=JobCardBlocked('1',{'stage':'select_job_card','cause_type':'OverlayRemainsVisible'}))
            h.execute(manifest)
            self.assertEqual(manifest.query(search.query_id)['jobs']['1']['status'],'in_progress')
            self.assertNotIn('1',manifest.processed_ids());self.assertNotIn('Submit application',h.events)
            self.assertEqual(manifest.query(search.query_id)['stop_reason'],'job_cards_pending')
        finally:h.doCleanups()

    def test_refinement_fallback_logs_validation_reason_without_provider_error_payload(self):
        from modules.search_planner import build_search_plan
        from test_search_planner import profile,search_config
        messages=[]
        build_search_plan(profile(),search_config(),refine=lambda *a:{'queries':[]},warn=messages.append)
        self.assertTrue(any('Invalid number of refined query lanes' in message for message in messages))
        messages=[]
        build_search_plan(profile(),search_config(),refine=Mock(side_effect=ValueError('private-provider-payload')),warn=messages.append)
        self.assertFalse(any('private-provider-payload' in message for message in messages))




class LazyResultTests(unittest.TestCase):
    def test_scroll_new_cards_are_processed_before_exhaustion(self):
        from test_linkedin_modern_search import DOMBrowser
        from unittest.mock import Mock,patch
        from modules.linkedin_modern_search import extend_search_results
        browser=DOMBrowser('<main></main>')
        browser.execute_script=Mock(return_value={'at_end':True})
        with patch('modules.linkedin_search.get_search_cards',side_effect=[['1'],['1'],['1','2']]), \
             patch('modules.linkedin_search.search_card_id',side_effect=lambda node:node):
            self.assertTrue(extend_search_results(browser,{'1'},timeout=.01))

    def test_stable_scroll_end_exhausts_results(self):
        from test_linkedin_modern_search import DOMBrowser
        from unittest.mock import Mock,patch
        from modules.linkedin_modern_search import extend_search_results
        browser=DOMBrowser('<main></main>')
        browser.execute_script=Mock(return_value={'at_end':True})
        with patch('modules.linkedin_search.get_search_cards',return_value=['1']), \
             patch('modules.linkedin_search.search_card_id',side_effect=lambda node:node):
            self.assertFalse(extend_search_results(browser,{'1'},timeout=.01))

    def test_unknown_scroll_state_is_not_reported_as_exhausted(self):
        from test_linkedin_modern_search import DOMBrowser
        from unittest.mock import Mock,patch
        from modules.linkedin_modern_search import extend_search_results
        from modules.linkedin_search import SearchUIError
        browser=DOMBrowser('<main></main>')
        browser.execute_script=Mock(return_value=None)
        with patch('modules.linkedin_search.get_search_cards',return_value=['1']), \
             patch('modules.linkedin_search.search_card_id',side_effect=lambda node:node):
            with self.assertRaises(SearchUIError):
                extend_search_results(browser,{'1'},timeout=.01)



if __name__ == "__main__":
    unittest.main()
