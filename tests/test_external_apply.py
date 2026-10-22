"""Hosted application contracts use synthetic fields/PDFs; no live applications."""
from pathlib import Path
import tempfile
import unittest
from reportlab.pdfgen import canvas

from modules.application_budget import ApplicationBudget
from modules.external_apply import (
    ExternalApplicationLedger, ExternalApplicationResult, apply_hosted_application,
    field_key, identify_ats, identity_matches,
)

LEVER = "https://jobs.lever.co/example/11111111-1111-4111-8111-111111111111/apply"
GREENHOUSE = "https://job-boards.greenhouse.io/example/jobs/1234"
ASHBY = "https://jobs.ashbyhq.com/example/11111111-1111-4111-8111-111111111111/application"


class Element:
    def __init__(self, data, browser=None):
        self.data, self.browser = data, browser
        self.actions = []

    def clear(self):
        self.data["value"] = ""
        self.actions.append("clear")

    def send_keys(self, value):
        self.actions.append(value)
        if self.data.get("type") == "file":
            path = Path(value)
            self.data["files"] = [{"name": path.name, "size": path.stat().st_size}]
        else:
            self.data["value"] = value

    def click(self):
        self.browser.clicks += 1
        if self.browser.click_error:
            raise RuntimeError("click interrupted")
        self.browser.after_click = True


class Browser:
    def __init__(self, provider="lever"):
        self.url = GREENHOUSE if provider == "greenhouse" else ASHBY if provider == "ashby" else LEVER
        self.title = "Job Application for Staff Platform Engineer at Example" if provider == "greenhouse" else "Staff Platform Engineer @ Example" if provider == "ashby" else "Example - Staff Platform Engineer"
        self.fields = []
        self.clicks, self.after_click = 0, False
        self.challenge = False
        self.click_error = False
        self.confirm = True
        self.confirm_url = None
        self.prior_confirmation = False
        for name in (["first_name", "last_name", "email", "phone"] if provider == "greenhouse" else ["_systemfield_name", "_systemfield_email", "phone"] if provider == "ashby" else ["name", "email", "phone"]):
            self.add_field(name, "text", required=True)
        self.resume = self.add_field("_systemfield_resume" if provider == "ashby" else "resume", "file", required=True)
        self.submit = Element({"type": "submit"}, self)
        self.navigations = []

    def add_field(self, name, kind="text", required=False, label=""):
        data = {"name": name, "id": name, "type": kind, "required": required, "visible": True,
                "disabled": False, "label": label or name, "value": "", "files": []}
        data["element"] = Element(data, self)
        self.fields.append(data)
        return data

    def get(self, url):
        self.url = url
        self.navigations.append(url)

    def execute_script(self, script):
        headings = ["Staff Platform Engineer"]
        if self.prior_confirmation or self.after_click and self.confirm:
            headings.append("Thank you for applying")
        return {"url": self.confirm_url if self.after_click and self.confirm_url else self.url,
                "title": self.title, "fields": self.fields,
                "buttons": [{"element": self.submit, "text": "Submit application"}],
                "headings": headings, "challenge": self.challenge}


class HostedApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pdf = Path(self.temp.name) / "synthetic-resume.pdf"
        writer = canvas.Canvas(str(self.pdf))
        writer.drawString(40, 700, "Synthetic applicant test resume")
        writer.save()
        self.browser = Browser()
        self.applicant = {"first_name": "Test", "last_name": "Applicant", "full_name": "Test Applicant", "email": "test@example.test", "phone": "5550100", "linkedin": "https://www.linkedin.com/in/synthetic-test/"}
        self.events = []

    def checkpoint(self, outcome):
        self.events.append((outcome.status, self.browser.clicks))

    def apply(self, **options):
        settings = dict(verify_pdf=lambda path: True, company="Example", title="Staff Platform Engineer", timeout=0, on_status=self.checkpoint)
        settings.update(options)
        return apply_hosted_application(self.browser, self.browser.url, self.applicant, self.pdf, **settings)

    def test_prepares_known_fields_verified_resume_and_leaves_custom_question_manual(self):
        question = self.browser.add_field("custom_fit", "textarea", required=True, label="Why this employer?")
        result = self.apply()
        self.assertEqual(result.status, "awaiting_review")
        self.assertEqual(question["value"], "")
        self.assertEqual(next(field for field in self.browser.fields if field["name"] == "name")["value"], "Test Applicant")
        self.assertEqual(result.manual_questions, ["Why this employer?"])
        self.assertEqual(result.resume_name, self.pdf.name)
        self.assertEqual(self.browser.clicks, 0)

    def test_both_hosted_contracts_require_explicit_review_and_checkpoint_before_click(self):
        for provider in ("lever", "greenhouse", "ashby"):
            with self.subTest(provider=provider):
                self.browser = Browser(provider)
                self.events = []
                result = self.apply(review=lambda details: "Submit application")
                self.assertEqual(result.status, "applied")
                self.assertEqual(self.events, [("submitting", 0), ("applied", 1)])
                self.assertTrue(result.submitted_at)

    def test_manual_custom_required_question_must_be_completed(self):
        self.browser.add_field("custom_fit", "textarea", required=True, label="Why this employer?")
        result = self.apply(review=lambda details: "Submit application")
        self.assertEqual(result.status, "handoff")
        self.assertEqual(self.browser.clicks, 0)

    def test_operator_can_complete_unknown_question_during_review(self):
        question = self.browser.add_field("custom_fit", "textarea", required=True, label="Why this employer?")
        def review(details):
            question["value"] = "Synthetic truthful answer entered manually"
            return "Submit application"
        self.assertEqual(self.apply(review=review).status, "applied")

    def test_discard_and_leave_open_do_not_submit(self):
        for decision, expected in [("Discard application", "discarded"), ("Leave open", "awaiting_review"), (None, "awaiting_review")]:
            with self.subTest(decision=decision):
                self.browser = Browser()
                self.assertEqual(self.apply(review=lambda details: decision).status, expected)
                self.assertEqual(self.browser.clicks, 0)

    def test_unsupported_hosts_are_explicit_handoffs(self):
        for url in ("https://company.example/careers/role", "https://apply.workable.com/example/j/role/"):
            with self.subTest(url=url):
                self.browser.url = url
                result = self.apply()
                self.assertEqual(result.status, "handoff")
                self.assertTrue(all(not field["element"].actions for field in self.browser.fields))

    def test_wrong_official_job_identity_is_rejected_before_any_fill(self):
        result = self.apply(official_role_urls=[LEVER.replace("11111111", "22222222")])
        self.assertEqual(result.status, "handoff")
        self.assertTrue(all(not field["element"].actions for field in self.browser.fields))

    def test_unknown_company_or_title_is_not_filled(self):
        for values in ({"company": "Different Company"}, {"title": "Junior Engineer"}):
            with self.subTest(values=values):
                self.browser = Browser()
                result = self.apply(**values)
                self.assertEqual(result.status, "handoff")
                self.assertTrue(all(not field["element"].actions for field in self.browser.fields))

    def test_partial_company_name_is_not_identity_evidence(self):
        self.browser.title = "Example Consulting - Staff Platform Engineer"
        self.assertEqual(self.apply().status, "handoff")
        self.assertTrue(all(not field["element"].actions for field in self.browser.fields))

    def test_access_challenge_is_a_handoff_without_filling(self):
        self.browser.challenge = True
        self.assertEqual(self.apply().status, "handoff")
        self.assertTrue(all(not field["element"].actions for field in self.browser.fields))

    def test_unverified_or_missing_pdf_never_fills_or_submits(self):
        self.assertEqual(self.apply(verify_pdf=lambda path: False).status, "failed")
        self.assertTrue(all(not field["element"].actions for field in self.browser.fields))
        self.pdf.unlink()
        self.assertEqual(self.apply().status, "failed")
        self.assertEqual(self.browser.clicks, 0)

    def test_changed_pdf_during_review_never_submits(self):
        def review(details):
            self.pdf.write_bytes(b"changed unverified document")
            return "Submit application"
        self.assertEqual(self.apply(review=review).status, "failed")
        self.assertEqual(self.browser.clicks, 0)

    def test_attachment_replaced_during_review_never_submits(self):
        def review(details):
            self.browser.resume["files"] = [{"name": "other.pdf", "size": 1}]
            return "Submit application"
        self.assertEqual(self.apply(review=review).status, "failed")
        self.assertEqual(self.browser.clicks, 0)

    def test_checkpoint_write_failure_prevents_submit_click(self):
        def failure(outcome):
            raise OSError("disk full")
        result = self.apply(review=lambda details: "Submit application", on_status=failure)
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.browser.clicks, 0)

    def test_missing_checkpoint_callback_prevents_submit(self):
        result = self.apply(review=lambda details: "Submit application", on_status=None)
        self.assertEqual(result.status, "awaiting_review")
        self.assertEqual(self.browser.clicks, 0)

    def test_click_or_confirmation_failure_keeps_uncertain_submission(self):
        for click_error in (True, False):
            with self.subTest(click_error=click_error):
                self.browser = Browser()
                self.browser.click_error, self.browser.confirm = click_error, False
                result = self.apply(review=lambda details: "Submit application")
                self.assertEqual(result.status, "submitting")
                self.assertEqual(self.browser.clicks, 1)

    def test_preexisting_thank_you_heading_cannot_confirm_submission(self):
        self.browser.prior_confirmation, self.browser.confirm = True, False
        self.assertEqual(self.apply(review=lambda details: "Submit application").status, "submitting")

    def test_confirmation_on_other_host_or_job_cannot_confirm_submission(self):
        for url in (LEVER.replace("jobs.lever.co", "evil.example"), LEVER.replace("11111111", "22222222")):
            with self.subTest(url=url):
                self.browser = Browser()
                self.browser.confirm_url = url
                self.assertEqual(self.apply(review=lambda details: "Submit application").status, "submitting")

    def test_generic_shared_domain_confirmation_is_not_success(self):
        for path in ("/thanks", "/other-employer/thanks", "/other-employer"):
            with self.subTest(path=path):
                self.browser = Browser()
                self.browser.confirm_url = "https://jobs.lever.co" + path
                self.assertEqual(self.apply(review=lambda details: "Submit application").status, "submitting")

    def test_same_job_scoped_confirmation_route_can_confirm(self):
        self.browser.confirm_url = LEVER.removesuffix("/apply") + "/thanks"
        self.assertEqual(self.apply(review=lambda details: "Submit application").status, "applied")

    def test_confirmed_submission_counts_once_and_uncertainty_counts_zero(self):
        for confirm in (True, False):
            with self.subTest(confirm=confirm):
                self.browser = Browser()
                self.browser.confirm = confirm
                budget = ApplicationBudget(1)
                def checkpoint(outcome):
                    if outcome.status == "applied":
                        budget.record("123")
                result = self.apply(review=lambda details: "Submit application", on_status=checkpoint)
                self.assertEqual(budget.count, int(confirm))
                self.assertEqual(result.status, "applied" if confirm else "submitting")

    def test_post_confirmation_tracking_failure_does_not_erase_remote_success(self):
        def checkpoint(outcome):
            if outcome.status == "applied":
                raise OSError("history write failed")
        result = self.apply(review=lambda details: "Submit application", on_status=checkpoint)
        self.assertEqual(result.status, "applied")
        self.assertTrue(result.submitted_at)

    def test_combobox_and_arbitrary_question_labels_are_not_auto_answered(self):
        self.assertIsNone(field_key({"type": "text", "name": "question_1", "label": "Work authorization"}, "greenhouse"))
        self.assertIsNone(field_key({"type": "text", "id": "country", "label": "Country", "combobox": True}, "greenhouse"))


class ATSIdentityTests(unittest.TestCase):
    def test_greenhouse_old_and_new_domains_share_job_identity(self):
        self.assertEqual(identify_ats(GREENHOUSE).key, identify_ats(GREENHOUSE.replace("job-boards", "boards")).key)

    def test_strict_https_hosts_paths_and_ids(self):
        invalid = [LEVER.replace("https", "http"), LEVER.replace("jobs.lever.co", "jobs.lever.co.evil.example"),
                   LEVER.replace("jobs.lever.co", "user@jobs.lever.co"), LEVER.replace("jobs.lever.co", "jobs.lever.co:444"),
                   LEVER.replace("11111111-1111-4111-8111-111111111111", "not-a-job-id"), "https://jobs.lever.co/example", GREENHOUSE + "/other"]
        for url in invalid:
            with self.subTest(url=url):
                self.assertIsNone(identify_ats(url))


class ExternalLedgerTests(unittest.TestCase):
    def test_ats_target_is_protected_across_linkedin_ids_and_domain_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ExternalApplicationLedger(Path(directory) / "external/applications.json")
            outcome = ExternalApplicationResult("submitting", GREENHOUSE)
            ledger.record(outcome, "linkedin-one")
            self.assertTrue(ledger.protected(GREENHOUSE.replace("job-boards", "boards")))
            ledger.record(ExternalApplicationResult("failed", GREENHOUSE), "linkedin-two")
            self.assertTrue(ledger.protected(GREENHOUSE))
            ledger.record(ExternalApplicationResult("applied", GREENHOUSE, attempt_id=outcome.attempt_id), "linkedin-one")
            ledger.record(ExternalApplicationResult("awaiting_review", GREENHOUSE), "linkedin-two")
            self.assertTrue(ledger.protected(GREENHOUSE))

    def test_stale_concurrent_prechecks_cannot_claim_two_submission_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "external/applications.json"
            first, second = ExternalApplicationLedger(path), ExternalApplicationLedger(path)
            self.assertFalse(first.protected(LEVER))
            self.assertFalse(second.protected(LEVER))
            owner = ExternalApplicationResult("submitting", LEVER)
            first.record(owner, "linkedin-one")
            with self.assertRaisesRegex(RuntimeError, "already claimed"):
                second.record(ExternalApplicationResult("submitting", LEVER), "linkedin-two")
            self.assertEqual(first._read()[first.target_key(LEVER)]["attempt_id"], owner.attempt_id)
            self.assertEqual(first._read()[first.target_key(LEVER)]["linkedin_id"], "linkedin-one")

    def test_losing_atomic_claim_prevents_second_submit_click(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ExternalApplicationLedger(Path(directory) / "external/applications.json")
            owner = ExternalApplicationResult("submitting", LEVER)
            ledger.record(owner, "linkedin-one")
            browser = Browser()
            pdf = Path(directory) / "test.pdf"
            pdf.write_bytes(b"synthetic test upload")
            result = apply_hosted_application(browser, LEVER, {"full_name": "Synthetic", "email": "synthetic@example.test", "phone": "555"}, pdf,
                                              verify_pdf=lambda path: True, company="Example", title="Staff Platform Engineer",
                                              review=lambda details: "Submit application", on_status=lambda outcome: ledger.record(outcome, "linkedin-two"), timeout=0)
            self.assertEqual(result.status, "failed")
            self.assertEqual(browser.clicks, 0)
            self.assertEqual(ledger._read()[ledger.target_key(LEVER)]["attempt_id"], owner.attempt_id)

    def test_manual_handoff_is_not_claimed_as_applied_or_submitting(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ExternalApplicationLedger(Path(directory) / "external/applications.json")
            ledger.record(ExternalApplicationResult("handoff", LEVER), "123")
            self.assertFalse(ledger.protected(LEVER))


if __name__ == "__main__":
    unittest.main()
