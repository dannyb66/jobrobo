"""Offline outreach sender checks: no browser, no Gmail, nothing sent."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from modules import outreach_mail as om

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional
    BeautifulSoup = None

FIXTURE = Path(__file__).parent / "fixtures" / "gmail-compose.html"


def task7_draft(draft_id, email, readiness="Review draft before sending", **extra):
    return {"draft_id": draft_id, "email": email, "subject": f"Subject {draft_id}",
            "body_plain": "Dear Professor,\n\nHello.", "body_markdown": "ignored",
            "faculty": "Prof", "readiness": readiness, **extra}


class Tmp(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload)
        return path


class LoadDraftsTests(Tmp):
    def test_task7_ledger_shape_and_hold(self):
        path = self.write("d.json", {"metadata": {}, "drafts": [
            task7_draft("p01-1", "a@x.edu"),
            task7_draft("p18-1", "b@x.edu", readiness="Hold — contact restrictions")]})
        records = om.load_drafts(path)
        self.assertEqual([r["draft_id"] for r in records], ["p01-1", "p18-1"])
        self.assertEqual(records[0]["body"], "Dear Professor,\n\nHello.")
        self.assertEqual([r["hold"] for r in records], [False, True])

    def test_generic_shape(self):
        path = self.write("d.json", {"drafts": [
            {"id": "x1", "to": "a@x.edu", "subject": "S", "body": "B"},
            {"id": "x2", "to": ["b@x.edu"], "subject": "S", "body": "B", "hold": True}]})
        records = om.load_drafts(path)
        self.assertEqual(records[0]["email"], "a@x.edu")
        self.assertEqual(records[1]["email"], "b@x.edu")
        self.assertTrue(records[1]["hold"])

    def test_bare_list_accepted(self):
        path = self.write("d.json", [{"id": "x1", "to": "a@x.edu", "subject": "S", "body": "B"}])
        self.assertEqual(om.load_drafts(path)[0]["draft_id"], "x1")

    def test_cc_and_multiple_recipients_rejected(self):
        path = self.write("cc.json", {"drafts": [
            {"id": "x1", "to": "a@x.edu", "cc": ["c@x.edu"], "subject": "S", "body": "B"}]})
        with self.assertRaisesRegex(om.PreflightError, "cc/bcc"):
            om.load_drafts(path)
        path = self.write("many.json", {"drafts": [
            {"id": "x1", "to": ["a@x.edu", "b@x.edu"], "subject": "S", "body": "B"}]})
        with self.assertRaisesRegex(om.PreflightError, "exactly one"):
            om.load_drafts(path)

    def test_missing_and_bad_sources(self):
        with self.assertRaises(om.PreflightError):
            om.load_drafts(self.root / "nope.json")
        with self.assertRaises(om.PreflightError):
            om.load_drafts(self.write("bad.json", "{not json"))
        with self.assertRaises(om.PreflightError):
            om.load_drafts(self.write("empty.json", {"drafts": []}))


def records(*holds):
    return [{"draft_id": f"d{i}", "email": f"p{i}@x.edu", "subject": "S", "body": "B",
             "hold": hold} for i, hold in enumerate(holds, 1)]


class SelectTests(TestCase):
    def test_held_drafts_skipped(self):
        chosen, skipped = om.select(records(False, True, False))
        self.assertEqual([r["draft_id"] for r in chosen], ["d1", "d3"])
        self.assertIn(("d2", "on hold"), skipped)

    def test_only_held_needs_include_held(self):
        chosen, skipped = om.select(records(False, True), only=["d2"])
        self.assertEqual(chosen, [])
        self.assertEqual(skipped[0][0], "d2")
        chosen, _ = om.select(records(False, True), only=["d2"], include_held=True)
        self.assertEqual([r["draft_id"] for r in chosen], ["d2"])

    def test_include_held_alone_does_not_release_holds(self):
        chosen, _ = om.select(records(True, False), include_held=True)
        self.assertEqual([r["draft_id"] for r in chosen], ["d2"])

    def test_already_sent_start_and_limit(self):
        rows = records(False, False, False, False)
        chosen, skipped = om.select(rows, already_sent={("d2", "p2@x.edu"): {}},
                                    start=2, limit=1)
        self.assertEqual([r["draft_id"] for r in chosen], ["d3"])
        reasons = dict(skipped)
        self.assertEqual(reasons["d1"], "before --start 2")
        self.assertEqual(reasons["d2"], "already sent")
        self.assertEqual(reasons["d4"], "beyond --limit 1")

    def test_unknown_only_reported(self):
        _, skipped = om.select(records(False), only=["zz"])
        self.assertIn(("zz", "unknown draft id"), skipped)


class ValidateTests(Tmp):
    claim = [{"draft_id": "d1", "email": "a@x.edu", "subject": "S",
              "body": "I have attached my research resume."}]

    def test_attachment_claim_blocks_send_but_not_dry_run(self):
        _, warned = om.validate(self.claim, None, sending=False)
        self.assertEqual(len(warned), 1)
        with self.assertRaisesRegex(om.PreflightError, "claims an attachment"):
            om.validate(self.claim, None, sending=True)

    def test_attachment_must_be_existing_pdf(self):
        with self.assertRaisesRegex(om.PreflightError, "not found"):
            om.validate(self.claim, str(self.root / "cv.pdf"), sending=True)
        text = self.write("cv.txt", "x")
        with self.assertRaisesRegex(om.PreflightError, "not a PDF"):
            om.validate(self.claim, str(text), sending=True)
        pdf = self.write("cv.pdf", "%PDF-1.4")
        attach, warned = om.validate(self.claim, str(pdf), sending=True)
        self.assertEqual(attach, str(pdf.resolve()))
        self.assertEqual(warned, [])

    def test_bad_recipient_duplicate_and_empty(self):
        rows = [{"draft_id": "d1", "email": "nope", "subject": "", "body": " "},
                {"draft_id": "d1", "email": "a@x.edu", "subject": "S", "body": "B"}]
        with self.assertRaises(om.PreflightError) as caught:
            om.validate(rows)
        message = str(caught.exception)
        for part in ("invalid recipient", "empty subject", "empty body", "duplicate draft id"):
            self.assertIn(part, message)


class HtmlImportTests(Tmp):
    def test_records_from_html_and_drift(self):
        page = self.write("p.html", (
            '<details class="faculty90-draft" data-draft-id="p01-1"><p><strong>To:</strong> '
            'a@x.edu · x</p><p class="faculty90-subject">Subject: Hello &amp; hi</p>'
            '<div class="faculty90-body">Dear A,<br><br>See <a href="https://e.x">paper</a>.</div>'
            '</details>'))
        html_records = om.records_from_html(page)
        self.assertEqual(html_records[0]["email"], "a@x.edu")
        self.assertEqual(html_records[0]["subject"], "Hello & hi")
        self.assertEqual(html_records[0]["body"], "Dear A,\n\nSee paper (https://e.x).")
        same = [{"draft_id": "p01-1", "subject": "Hello & hi",
                 "body": "Dear A, See paper (https://e.x)."}]
        self.assertEqual(om.compare_sources(same, html_records), [])
        changed = [{"draft_id": "p01-1", "subject": "Other", "body": ""}]
        self.assertEqual(len(om.compare_sources(changed, html_records)), 1)
        self.assertEqual(om.compare_sources([], html_records), ["p01-1: absent from JSON"])


class FakeElement:
    def __init__(self, attrs=None, text="", children=None):
        self.attrs, self.text, self.children = attrs or {}, text, children or {}

    def get_attribute(self, name):
        return self.attrs.get(name)

    def find_elements(self, _by, selector):
        return self.children.get(selector, [])


class FakeDialog:
    def __init__(self, chips=(), to_value="", subject="S", body="Dear A,\n\nHi", text=""):
        self.by_selector = {
            om.RECIPIENT_CHIP: [FakeElement(attrs) for attrs in chips],
            om.TO_FIELD: [FakeElement({"value": to_value})],
            om.SUBJECT_FIELD: [FakeElement({"value": subject})],
            om.BODY_FIELD: [FakeElement({"innerText": body})],
        }
        self.text = text

    def find_elements(self, _by, selector):
        return self.by_selector.get(selector, [])

    def find_element(self, by, selector):
        return self.find_elements(by, selector)[0]


RECORD = {"draft_id": "d1", "email": "Prof@x.edu", "subject": "S", "body": "Dear A,\n\nHi"}


class VerifyTests(TestCase):
    def test_chip_only_recipient_passes(self):
        chip = {"data-hovercard-id": "prof@x.edu", "data-name": "prof@x.edu"}
        self.assertTrue(om.verify(FakeDialog(chips=[chip]), RECORD))

    def test_input_value_fallback_passes(self):
        self.assertTrue(om.verify(FakeDialog(to_value="prof@x.edu"), RECORD))

    def test_missing_wrong_or_extra_recipient_fails(self):
        for dialog in (FakeDialog(),
                       FakeDialog(chips=[{"email": "other@x.edu"}]),
                       FakeDialog(chips=[{"email": "prof@x.edu"}, {"email": "b@x.edu"}])):
            with self.assertRaisesRegex(RuntimeError, "recipients"):
                om.verify(dialog, RECORD)

    def test_subject_body_and_attachment_checked(self):
        chip = [{"email": "prof@x.edu"}]
        with self.assertRaisesRegex(RuntimeError, "subject differs"):
            om.verify(FakeDialog(chips=chip, subject="T"), RECORD)
        with self.assertRaisesRegex(RuntimeError, "body differs"):
            om.verify(FakeDialog(chips=chip, body="Other"), RECORD)
        with self.assertRaisesRegex(RuntimeError, "attachment chip missing"):
            om.verify(FakeDialog(chips=chip), RECORD, "/tmp/cv.pdf")
        self.assertTrue(om.verify(FakeDialog(chips=chip, text="cv.pdf 120K"), RECORD, "/tmp/cv.pdf"))


class FakeDriver:
    def __init__(self, title="", account_label=None):
        self.title, self.account_label = title, account_label

    def find_elements(self, _by, selector):
        if selector == om.ACCOUNT_BUTTON and self.account_label:
            return [FakeElement({"aria-label": self.account_label})]
        return []


class AccountAndUrlTests(TestCase):
    def test_signed_in_account_from_title_or_button(self):
        self.assertEqual(om.signed_in_account(FakeDriver("Inbox (3) - Danny@Example.com - Gmail")),
                         "danny@example.com")
        self.assertEqual(om.signed_in_account(
            FakeDriver("Gmail", "Google Account: Danny B (danny@example.com)")), "danny@example.com")
        self.assertIsNone(om.signed_in_account(FakeDriver("Gmail")))


@skipUnless(BeautifulSoup, "bs4 not installed")
class FixtureSelectorTests(TestCase):
    def test_every_selector_matches_fixture(self):
        soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")
        for name in ("COMPOSE_BUTTON", "DIALOG", "RESTORE_BUTTON", "TO_FIELD", "SUBJECT_FIELD", "BODY_FIELD",
                     "FILE_INPUT", "DISCARD_BUTTON", "RECIPIENT_CHIP", "ACCOUNT_BUTTON"):
            self.assertTrue(soup.select(getattr(om, name)), name)
        dialog = soup.select_one(om.DIALOG)
        chips = {el.get("data-hovercard-id") or el.get("email")
                 for el in dialog.select(om.RECIPIENT_CHIP)}
        self.assertEqual(chips, {"prof@example.edu"})
        sends = [el for el in dialog.select('div[role="button"]')
                 if (el.get("aria-label") or "").startswith("Send")]
        self.assertEqual(len(sends), 1)


class LedgerTests(Tmp):
    def test_ledger_round_trip_skips_bad_lines(self):
        run = self.root / "run1" / "sent.jsonl"
        om.append_ledger(run, {"draft_id": "d1", "email": "a@x.edu", "confirm": "unconfirmed"})
        with run.open("a") as handle:
            handle.write("not json\n")
        self.assertIn(("d1", "a@x.edu"), om.read_ledger(self.root))


class RunLoopTests(Tmp):
    """run() with every browser step faked: proves ledger and skip behaviour only."""

    def setUp(self):
        super().setUp()
        from unittest.mock import patch
        self.source = self.write("d.json", {"drafts": [
            task7_draft("p01-1", "a@x.edu"), task7_draft("p01-2", "b@x.edu"),
            task7_draft("p18-1", "c@x.edu", readiness="Hold — contact restrictions")]})
        self.sent_calls = []
        self.verified = []

        class Driver:
            def save_screenshot(self, path):
                Path(path).write_bytes(b"")

        def send(driver, dialog, wait, subject=None):
            self.sent_calls.append(dialog)
            if dialog == "p01-2":
                raise om.SendUnconfirmed("compose window did not close; send unconfirmed")
            return "snackbar"

        self.browsers = lambda: (Driver(), None, "127.0.0.1:1", False)
        for name, fake in {
            "frame_for": lambda driver: None,
            "preflight_message": lambda driver, expected=None: "danny@example.com",
            "open_compose": lambda driver, wait, record: (record["draft_id"], True),
            "fill": lambda driver, dialog, wait, record, *args, **kwargs: record,
            "send": send,
            "discard": lambda driver, dialog: None,
            "compose_dialog": lambda driver: None,
            "verify_rows": lambda driver, rows, printer=print: self.verified.append(
                [row["draft_id"] for row in rows]) or {
                "verdict": "BATCH VERIFIED", "confirmed": len(rows), "total": len(rows),
                "checked_utc": "t", "results": []},
        }.items():
            patcher = patch.object(om, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_once(self, **kwargs):
        return om.run(source=self.source, logs_root=self.root / "logs", delay=(0, 0),
                      browsers=self.browsers, printer=lambda *_: None, **kwargs)

    def test_send_records_confirmed_and_unconfirmed_and_skips_hold(self):
        summary = self.run_once()
        self.assertEqual([row["draft_id"] for row in summary["sent"]], ["p01-1"])
        self.assertEqual(summary["sent"][0]["confirm"], "snackbar")
        self.assertEqual(summary["sent"][0]["from"], "danny@example.com")
        self.assertEqual([row["draft_id"] for row in summary["failed"]], ["p01-2"])
        self.assertIn(("p18-1", "on hold"), summary["skipped"])
        self.assertEqual(self.verified, [["p01-1", "p01-2"]])  # unconfirmed sends are checked too
        self.assertEqual(summary["verification"]["verdict"], "BATCH VERIFIED")
        report = (Path(summary["directory"]) / "report.md").read_text()
        self.assertIn("## Verification — BATCH VERIFIED (2/2)", report)
        self.assertTrue((Path(summary["directory"]) / "verify.json").exists())
        ledger = om.read_ledger(self.root / "logs")
        self.assertEqual(ledger[("p01-2", "b@x.edu")]["confirm"], "unconfirmed")
        # A rerun must not resend either message.
        with self.assertRaisesRegex(om.PreflightError, "No drafts selected"):
            self.run_once()

    def test_dry_run_sends_and_records_nothing(self):
        summary = self.run_once(dry_run=True)
        self.assertEqual(self.sent_calls, [])
        self.assertEqual(self.verified, [])
        self.assertEqual(summary["sent"], [])
        self.assertEqual(om.read_ledger(self.root / "logs"), {})
        self.assertTrue((Path(summary["directory"]) / "report.md").exists())

    def test_real_send_refuses_attachment_claim_without_attach(self):
        self.write("d.json", {"drafts": [dict(task7_draft("p01-1", "a@x.edu"),
                                              body_plain="I have attached my research resume.")]})
        with self.assertRaisesRegex(om.PreflightError, "claims an attachment"):
            self.run_once()
        self.assertEqual(self.sent_calls, [])


class ChromeAttachTests(Tmp):
    def listing(self, profile, extra=""):
        return "\n".join([
            f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir={profile}{extra} https://x",
            f"/Applications/Google Chrome.app/Contents/Frameworks/Helper --type=renderer --user-data-dir={profile}",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir=/other/profile --remote-debugging-port=9333",
        ])

    def test_chrome_processes_reads_port_and_ignores_helpers_and_other_profiles(self):
        profile = self.root / "My Profile"
        self.assertEqual(om.chrome_processes(profile, self.listing(profile, " --remote-debugging-port=9222")), [9222])
        self.assertEqual(om.chrome_processes(profile, self.listing(profile)), [None])
        self.assertEqual(om.chrome_processes(profile, ""), [])

    def test_live_address_prefers_process_port_over_stale_marker(self):
        from unittest.mock import patch
        profile = self.root / "p"
        profile.mkdir()
        (profile / "DevToolsActivePort").write_text("57800\n/devtools/browser/x")
        with patch.object(om, "_port_open", lambda port: port == 9222):
            self.assertEqual(om.live_debugger_address(profile, self.listing(profile, " --remote-debugging-port=9222")),
                             "127.0.0.1:9222")
            self.assertIsNone(om.live_debugger_address(profile, ""))

    def test_launch_options_keep_real_keychain(self):
        options = om.launch_options(self.root / "p", 9555)
        self.assertIn("use-mock-keychain", options.experimental_options["excludeSwitches"])
        self.assertIn(f"--user-data-dir={self.root / 'p'}", options.arguments)
        self.assertIn("--remote-debugging-port=9555", options.arguments)

    def test_open_chrome_refuses_profile_open_without_port(self):
        from unittest.mock import patch
        calls = []
        with patch.object(om, "live_debugger_address", lambda profile: None), \
                patch.object(om, "chrome_processes", lambda profile: [None]):
            with self.assertRaisesRegex(om.PreflightError, "without a debug port"):
                om.open_chrome_window(self.root / "p", runner=lambda *a, **k: calls.append(a))
        self.assertEqual(calls, [])


class FormattingTests(TestCase):
    def test_signature_or_bold_in_body_fails_verification(self):
        dialog = FakeDialog(chips=[{"email": "prof@x.edu"}])
        dialog.by_selector[om.BODY_FIELD] = [FakeElement(
            {"innerText": RECORD["body"]},
            children={"b, i, strong, em, font, .gmail_signature": [FakeElement()]})]
        with self.assertRaisesRegex(RuntimeError, "formatting or a signature"):
            om.verify(dialog, RECORD)

    def test_discard_selector_matches_shortcut_suffix(self):
        self.assertIn('aria-label^="Discard draft"', om.DISCARD_BUTTON)


class ComposeWindowTests(TestCase):
    class Window:
        def __init__(self, shown):
            self.subject = type("S", (), {"is_displayed": lambda _self: shown})()

        def find_elements(self, _by, selector):
            return [self.subject] if selector == om.SUBJECT_FIELD else []

    def test_compose_windows_includes_minimised(self):
        windows = [self.Window(False), self.Window(True)]
        driver = type("D", (), {"find_elements": lambda _self, _by, sel: windows if sel == om.DIALOG else []})()
        self.assertEqual(om.compose_windows(driver), windows)
        self.assertIs(om.compose_dialog(driver), windows[-1])

    def test_dismiss_alert_tolerates_no_alert(self):
        class NoAlert:
            @property
            def alert(self):
                raise RuntimeError("no such alert")
        driver = type("D", (), {"switch_to": NoAlert()})()
        self.assertIsNone(om.dismiss_alert(driver))


class NoAttachTests(TestCase):
    def test_removes_only_the_attachment_sentence(self):
        body = ("Would it help?\n\nI have attached my research resume. Engineering portfolio "
                "(https://dannyb66.github.io/)\n\nBest regards,\nDanny")
        [record] = om.without_attachment_claim([{"draft_id": "d1", "email": "a@x.edu",
                                                 "subject": "S", "body": body}])
        self.assertEqual(record["body"], "Would it help?\n\nEngineering portfolio "
                                         "(https://dannyb66.github.io/)\n\nBest regards,\nDanny")
        attach, warned = om.validate([record], None, sending=True)
        self.assertIsNone(attach)
        self.assertEqual(warned, [])

    def test_validation_error_is_short_with_hint(self):
        rows = [{"draft_id": f"d{i}", "email": "a@x.edu", "subject": "S",
                 "body": "I have attached my research resume."} for i in range(90)]
        with self.assertRaises(om.PreflightError) as caught:
            om.validate(rows, None, sending=True)
        message = str(caught.exception)
        self.assertIn("...and 85 more", message)
        self.assertIn("--no-attach", message)
        self.assertLess(len(message.splitlines()), 10)


class WriteRemainingTests(Tmp):
    def test_drops_sent_keeps_rest_and_metadata(self):
        source = self.write("d.json", {"metadata": {"status": "drafts"}, "drafts": [
            task7_draft("p01-1", "a@x.edu"), task7_draft("p01-2", "b@x.edu"),
            task7_draft("p18-1", "c@x.edu", readiness="Hold — contact restrictions")]})
        before = source.read_bytes()
        om.append_ledger(self.root / "logs" / "r1" / "sent.jsonl", {"draft_id": "p01-1", "email": "a@x.edu"})
        target = self.root / "out" / "remaining.json"
        kept, dropped = om.write_remaining(source, self.root / "logs", target)
        self.assertEqual((kept, dropped), (["p01-2", "p18-1"], ["p01-1"]))
        payload = json.loads(target.read_text())
        self.assertEqual([d["draft_id"] for d in payload["drafts"]], ["p01-2", "p18-1"])
        self.assertEqual(payload["drafts"][0]["body_plain"], "Dear Professor,\n\nHello.")
        self.assertEqual(payload["metadata"]["status"], "drafts")
        self.assertEqual(payload["metadata"]["remaining"]["excluded_as_sent"], ["p01-1"])
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual([r["draft_id"] for r in om.load_drafts(target) if r["hold"]], ["p18-1"])

    def test_refuses_to_overwrite_source(self):
        source = self.write("d.json", {"drafts": [task7_draft("p01-1", "a@x.edu")]})
        with self.assertRaisesRegex(om.PreflightError, "must not overwrite"):
            om.write_remaining(source, self.root / "logs", source)


class ContactLineTests(TestCase):
    SIGNATURE = {"text": "Cheers,\nDanny Basavaraju\n+1-628-310-5660\nLinkedIn",
                 "links": [["LinkedIn", "https://www.linkedin.com/in/dannybasavaraju/"]]}
    BODY = "Dear Professor,\n\nHello.\n\nBest regards,\nDanny Basavaraju"

    def test_drops_sign_off_and_name_keeps_phone_and_linkedin_url(self):
        self.assertEqual(om.contact_lines(self.SIGNATURE, self.BODY),
                         ["+1-628-310-5660", "LinkedIn: https://www.linkedin.com/in/dannybasavaraju/"])

    def test_lines_go_directly_under_name(self):
        record = om.with_contact({"body": self.BODY + "\n"}, ["+1", "LinkedIn: u"])
        self.assertTrue(record["body"].endswith("Best regards,\nDanny Basavaraju\n+1\nLinkedIn: u"))

    def test_no_signature_gives_no_lines(self):
        self.assertEqual(om.contact_lines(None, self.BODY), [])
        self.assertIs(om.with_contact({"body": "x"}, [])["body"], "x")


class RunLockTests(Tmp):
    def test_second_run_is_refused_while_first_holds_lock(self):
        first = om.acquire_run_lock(self.root)
        with self.assertRaisesRegex(om.PreflightError, "in progress"):
            om.acquire_run_lock(self.root)
        first.close()
        om.acquire_run_lock(self.root).close()


class VerificationTests(Tmp):
    def test_fingerprint_ignores_whitespace_layout(self):
        self.assertEqual(om.body_fingerprint("Dear A,\n\nHi\nDanny"),
                         om.body_fingerprint("Dear A,\n\n\nHi\n Danny\n"))
        self.assertNotEqual(om.body_fingerprint("Hi"), om.body_fingerprint("Hello"))

    def test_sent_search_url_scopes_to_sent_recipient_subject(self):
        url = om.sent_search_url({"email": "a@x.edu", "subject": "Research contribution: A & B"})
        self.assertTrue(url.startswith(om.COMPOSE_URL + "#search/"))
        self.assertIn("in%3Asent%20to%3Aa%40x.edu%20subject%3A%22Research%20contribution", url)

    def test_find_run_dir_latest_and_id(self):
        logs = self.root / "logs"
        for name in ("20261115T220206Z-send", "20261115T220734Z-send", "20261115T221117Z-dry"):
            (logs / name).mkdir(parents=True)
        (logs / "20261115T220206Z-send" / "sent.jsonl").write_text("{}\n")
        (logs / "20261115T220734Z-send" / "sent.jsonl").write_text("{}\n")
        self.assertEqual(om.find_run_dir(logs, "latest").name, "20261115T220734Z-send")
        self.assertEqual(om.find_run_dir(logs, "20261115T220206Z-send").name, "20261115T220206Z-send")
        with self.assertRaises(om.PreflightError):
            om.find_run_dir(logs, "nope")

    def test_verification_appends_explicit_verdict_to_report(self):
        (self.root / "report.md").write_text("# Outreach run x\n")
        om.write_verification(self.root, {
            "verdict": "BATCH NOT VERIFIED", "confirmed": 1, "total": 2, "checked_utc": "t",
            "results": [{"draft_id": "d1", "email": "a@x.edu", "status": "confirmed", "detail": "ok"},
                        {"draft_id": "d2", "email": "b@x.edu", "status": "missing", "detail": "none"}]})
        report = (self.root / "report.md").read_text()
        self.assertIn("## Verification — BATCH NOT VERIFIED (1/2)", report)
        self.assertIn("- MISSING d2 -> b@x.edu: none", report)
        self.assertEqual(json.loads((self.root / "verify.json").read_text())["confirmed"], 1)


class RecipientEntryTests(TestCase):
    def test_retries_until_chip_appears(self):
        from unittest.mock import patch
        typed = []

        class To:
            def clear(self): pass
            def send_keys(self, keys): typed.append(keys)

        class Dialog:
            pass

        seen = iter([[], [], ["prof@x.edu"]])
        with patch.object(om, "visible_field", lambda dialog, wait, selector: To()), \
                patch.object(om, "insert", lambda element, text: typed.append(text)), \
                patch.object(om, "recipients", lambda dialog: next(seen, ["prof@x.edu"])), \
                patch.object(om, "RECIPIENT_TIMEOUT", 0.3):
            om.enter_recipient(Dialog(), None, "Prof@x.edu")
        self.assertIn("Prof@x.edu", typed)

    def test_gives_up_with_clear_error(self):
        from unittest.mock import patch

        class To:
            def clear(self): pass
            def send_keys(self, keys): pass

        with patch.object(om, "visible_field", lambda *a: To()), \
                patch.object(om, "insert", lambda *a: None), \
                patch.object(om, "recipients", lambda dialog: []), \
                patch.object(om, "RECIPIENT_TIMEOUT", 0.05):
            with self.assertRaisesRegex(RuntimeError, "did not register after 3 attempts"):
                om.enter_recipient(object(), None, "a@x.edu")


class RequeueTests(Tmp):
    def test_requeue_voids_only_missing_rows_and_ledger_forgets_them(self):
        logs = self.root / "logs"
        run = logs / "20261115T221301Z-send"
        for draft_id, email in (("p04-1", "a@x.edu"), ("p04-2", "b@x.edu")):
            om.append_ledger(run / "sent.jsonl", {"draft_id": draft_id, "email": email})
        (run / "verify.json").write_text(json.dumps({"results": [
            {"draft_id": "p04-1", "email": "a@x.edu", "status": "confirmed"},
            {"draft_id": "p04-2", "email": "b@x.edu", "status": "missing"}]}))
        self.assertEqual(om.requeue_missing("20261115T221301Z-send", logs_root=logs), ["p04-2"])
        self.assertEqual(set(om.read_ledger(logs)), {("p04-1", "a@x.edu")})
        # A later real send of the requeued draft is recorded again.
        om.append_ledger(logs / "20261116T000000Z-send" / "sent.jsonl", {"draft_id": "p04-2", "email": "b@x.edu"})
        self.assertIn(("p04-2", "b@x.edu"), om.read_ledger(logs))

    def test_requeue_needs_verification_first(self):
        run = self.root / "logs" / "r-send"
        run.mkdir(parents=True)
        with self.assertRaisesRegex(om.PreflightError, "not been verified"):
            om.requeue_missing("r-send", logs_root=self.root / "logs")


class SendConfirmationTests(TestCase):
    """send() must not treat a vanished/stale window as proof of sending."""

    def make(self, notices, open_subjects):
        from unittest.mock import patch
        button = type("B", (), {"get_attribute": lambda _s, n: "Send \u202a(\u2318Enter)\u202c",
                                 "click": lambda _s: None})()
        dialog = type("D", (), {"find_elements": lambda _s, _b, _sel: [button]})()
        feed = iter(notices)
        patches = [patch.object(om, "_snackbar_texts", lambda d: next(feed, notices[-1])),
                   patch.object(om, "_open_subjects", lambda d: open_subjects),
                   patch.object(om, "SENT_TIMEOUT", 0.5), patch.object(om, "NOTICE_CLEAR_TIMEOUT", 0.1)]
        return dialog, patches

    def run_send(self, notices, open_subjects):
        dialog, patches = self.make(notices, open_subjects)
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return om.send(object(), dialog, None, subject="S")

    def test_notice_and_closed_window_confirms(self):
        self.assertEqual(self.run_send([[], ["Message sent"]], []), "snackbar")

    def test_closed_window_without_notice_is_unconfirmed(self):
        with self.assertRaisesRegex(om.SendUnconfirmed, "never showed"):
            self.run_send([[]], [])

    def test_window_still_open_is_unconfirmed(self):
        with self.assertRaisesRegex(om.SendUnconfirmed, "still open"):
            self.run_send([["Message sent"]], ["S"])

    def test_gmail_error_raises(self):
        with self.assertRaisesRegex(RuntimeError, "Gmail reported"):
            self.run_send([[], ["Sending failed"]], [])


class ExclusionTests(Tmp):
    def setUp(self):
        super().setUp()
        self.source = self.write("d.json", {"metadata": {}, "drafts": [
            task7_draft("p04-2", "djr@x.edu"), task7_draft("p04-3", "ob2105@gsb.columbia.edu"),
            task7_draft("p07-3", "l@x.edu")]})
        self.logs = self.root / "logs"

    def test_exclude_by_email_blocks_selection_even_with_only(self):
        self.assertEqual(om.exclude(["OB2105@gsb.columbia.edu"], self.source, self.logs), ["p04-3"])
        records = om.load_drafts(self.source)
        exclusions = om.read_exclusions(self.logs)
        chosen, skipped = om.select(records, exclusions=exclusions)
        self.assertEqual([r["draft_id"] for r in chosen], ["p04-2", "p07-3"])
        self.assertIn(("p04-3", "excluded by user"), skipped)
        chosen, _ = om.select(records, only=["p04-3"], exclusions=exclusions)
        self.assertEqual(chosen, [])

    def test_exclude_by_id_and_rebuild_drops_it(self):
        om.exclude(["p04-3"], self.source, self.logs)
        kept, gone = om.write_remaining(self.source, self.logs, self.root / "r.json")
        self.assertEqual((kept, gone), (["p04-2", "p07-3"], ["p04-3"]))
        meta = json.loads((self.root / "r.json").read_text())["metadata"]["remaining"]
        self.assertEqual(meta["excluded_by_user"], ["p04-3"])

    def test_unknown_target_rejected(self):
        with self.assertRaisesRegex(om.PreflightError, "No draft matches"):
            om.exclude(["nobody@x.edu"], self.source, self.logs)


BATCH2_PAGE = '''<html><body><script>
const CSVROWS=[["id", "status", "school", "dept", "name", "email", "subject", "paper", "paper_url", "profile_url"], ["q01-1", "Ready for your review", "H", "Bio", "Tianxi Cai", "tcai@x.edu", "S1", "P", "u", "pu"], ["q02-2", "Check: confirm email on his site", "C", "Stats", "A D", "ad@x.edu", "S2", "P", "u", "pu"]];
const COPIES={"q01-1": {"to": "tcai@x.edu", "subject": "S1", "body": "Dear Professor Cai,\\n\\nI have attached my resume. Engineering portfolio: https://dannyb66.github.io/\\n\\nBest regards,\\nDanny Basavaraju"}, "q02-2": {"to": "ad@x.edu", "subject": "S2", "body": "Hi"}};
</script></body></html>'''


class Batch2ImportTests(Tmp):
    def test_import_marks_check_status_as_hold_and_round_trips(self):
        page = self.write("b2.html", BATCH2_PAGE)
        drafts = om.drafts_from_copies_html(page)
        self.assertEqual([d["draft_id"] for d in drafts], ["q01-1", "q02-2"])
        self.assertEqual(drafts[1]["readiness"], "Hold — Check: confirm email on his site")
        target = om.write_drafts_file(drafts, self.root / "out" / "b2.json", page)
        records = om.load_drafts(target)
        self.assertEqual([r["hold"] for r in records], [False, True])
        self.assertEqual(records[0]["body"], "Dear Professor Cai,\n\nI have attached my resume. "
                         "Engineering portfolio: https://dannyb66.github.io/\n\nBest regards,\nDanny Basavaraju")
        with self.assertRaisesRegex(om.PreflightError, "already exists"):
            om.write_drafts_file(drafts, target, page)

    def test_batch2_attachment_wording_is_detected_and_removed(self):
        body = "Hi.\n\nI have attached my resume. Engineering portfolio: https://dannyb66.github.io/"
        self.assertTrue(om.CLAIMS_ATTACHMENT.search(body))
        [record] = om.without_attachment_claim([{"draft_id": "q", "email": "a@x.edu", "subject": "S", "body": body}])
        self.assertEqual(record["body"], "Hi.\n\nEngineering portfolio: https://dannyb66.github.io/")
        self.assertFalse(om.CLAIMS_ATTACHMENT.search(record["body"]))
