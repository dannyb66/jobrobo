"""Application cleanup replays native/classic dialogs; no real browser actions."""

import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from lxml import html, etree
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

from modules.linkedin_form_cleanup import discard_application, ApplicationCleanupError
from modules.linkedin_easy_apply import EasyApplyError, wait_for_application_modal


class Element:
    def __init__(self, browser, node):
        self.browser, self.node = browser, node
        self.id = node.get("data-fixture-id")

    @property
    def text(self):
        return " ".join(self.node.text_content().split())

    def get_attribute(self, name):
        return self.node.get(name)

    def is_displayed(self):
        return not any(n.get("hidden") is not None for n in [self.node, *self.node.iterancestors()])

    def is_enabled(self):
        return self.node.get("disabled") is None

    def find_elements(self, by, selector):
        return self.browser.query(self.node, by, selector)

    def click(self):
        self.browser.click(self.node)

    def send_keys(self, keys):
        self.browser.keys.append(keys)
        self.browser.dismiss()


class Browser:
    def __init__(self, classic=False):
        application = '<div class="jobs-easy-apply-modal" role="dialog"' if classic else '<dialog open="" data-testid="dialog"'
        closing = '</div>' if classic else '</dialog>'
        self.root = html.fromstring('<html><body>' + application + ' id="application" aria-labelledby="dialog-header">'
                                    '<h2 id="dialog-header">Apply to Example</h2><form><input name="email"></form>'
                                    '<button aria-label="Dismiss"></button><button>Submit application</button>' + closing + '</body></html>')
        self.now, self.tick, self.counter = 0., 0, 0
        self.clicks, self.keys = [], []
        self.mode, self.title = "confirm", "Save your application?"
        self.keep_application = False
        self.confirm_at = None
        self.confirm_stuck = False
        self.stale_close_once = False
        self.stale_discard_once = False
        self._stamp()

    def _stamp(self):
        for node in self.root.iter():
            if isinstance(node.tag, str) and not node.get("data-fixture-id"):
                self.counter += 1
                node.set("data-fixture-id", str(self.counter))

    def query(self, root, by, selector):
        self._stamp()
        if by == "css selector":
            soup = BeautifulSoup(etree.tostring(root, encoding="unicode"), "html.parser")
            identities = {n.get("data-fixture-id") for n in soup.select(selector)}
            nodes = [n for n in root.iter() if n.get("data-fixture-id") in identities]
        elif by == "id":
            nodes = root.xpath(".//*[@id=$wanted]", wanted=selector)
        else:
            nodes = root.xpath(selector)
        return [Element(self, node) for node in nodes]

    def find_elements(self, by, selector):
        return self.query(self.root, by, selector)

    def execute_script(self, script, parent, child):
        return parent.node in child.node.iterancestors()

    def application(self):
        return self.root.xpath("//*[@id='application']")[0]

    def confirm(self):
        dialog = html.fromstring('<dialog open="" id="confirmation"><h2>' + self.title + '</h2>'
                                 '<button>Save</button><button>Discard</button></dialog>')
        self.root.find("body").append(dialog)
        self._stamp()

    def dismiss(self):
        if self.mode == "stuck":
            return
        if not self.keep_application:
            self.application().set("hidden", "")
        if self.mode == "confirm":
            self.confirm()
        elif self.mode == "delayed":
            self.confirm_at = self.tick + 2

    def click(self, node):
        label = node.get("aria-label") or " ".join(node.text_content().split())
        if label in {"Submit application", "Save"}:
            raise AssertionError("Cleanup must never Save or Submit")
        if label in {"Dismiss", "Close"}:
            if self.stale_close_once:
                self.stale_close_once = False
                raise StaleElementReferenceException("Dialog close button changed")
            self.clicks.append(label)
            self.dismiss()
        elif label in {"Discard", "Discard application"}:
            if self.stale_discard_once:
                self.stale_discard_once = False
                raise StaleElementReferenceException("Discard button changed")
            self.clicks.append(label)
            if not self.confirm_stuck:
                self.root.xpath("//*[@id='confirmation']")[0].set("hidden", "")
                self.application().set("hidden", "")
        else:
            raise AssertionError("Unexpected cleanup action " + label)

    def wait(self, predicate):
        for _ in range(35):
            self.tick += 1
            self.now += .1
            if self.confirm_at is not None and self.tick >= self.confirm_at:
                self.confirm_at = None
                self.confirm()
            result = predicate(self)
            if result:
                return result
        raise TimeoutException("Fake cleanup did not finish")


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.browser = Browser()

    def cleanup(self):
        with patch("modules.linkedin_form_cleanup.monotonic", side_effect=lambda: self.browser.now):
            return discard_application(self.browser, wait=self.browser.wait)

    def test_native_dialog_dismisses_then_discards_without_save_or_submit(self):
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])
        self.assertEqual(self.browser.keys, [])

    def test_native_application_dismiss_excludes_nested_resume_upload_toast_dismiss(self):
        toast = etree.SubElement(self.browser.application(), "section", {"data-testid": "toasts"})
        etree.SubElement(toast, "p").text = "Resume uploaded successfully"
        etree.SubElement(toast, "button", {"aria-label": "Dismiss", "id": "toast-dismiss"})
        original = self.browser.click
        def reject_toast_click(node):
            self.assertNotEqual(node.get("id"), "toast-dismiss")
            original(node)
        self.browser.click = reject_toast_click
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])

    def test_header_dismiss_excludes_status_toast_dismiss(self):
        own = self.browser.application().xpath(".//button[@aria-label='Dismiss']")[0]
        header = etree.SubElement(self.browser.application(), "header", {"id": "dialog-header"})
        header.append(own)
        toast = etree.SubElement(self.browser.application(), "div", {"role": "status"})
        etree.SubElement(toast, "button", {"aria-label": "Dismiss", "id": "toast-dismiss"})
        original = self.browser.click
        def reject_toast_click(node):
            self.assertNotEqual(node.get("id"), "toast-dismiss")
            original(node)
        self.browser.click = reject_toast_click
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])

    def test_classic_application_dialog_is_supported(self):
        self.browser = Browser(classic=True)
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])

    def test_delayed_confirmation_prevents_premature_cleanup_success(self):
        self.browser.mode = "delayed"
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])
        self.assertGreaterEqual(self.browser.tick, 6)

    def test_discard_application_confirmation_and_exact_button_are_supported(self):
        self.browser.title = "Discard application?"
        original = self.browser.confirm
        def confirm():
            original()
            self.browser.root.xpath("//*[@id='confirmation']//button[normalize-space(.)='Discard']")[0].text = "Discard application"
        self.browser.confirm = confirm
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard application"])

    def test_underlying_application_can_remain_visible_behind_confirmation(self):
        self.browser.keep_application = True
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])

    def test_save_this_application_confirmation_with_underlying_apply_and_toast_discards(self):
        self.browser.title = "Save this application?"
        self.browser.keep_application = True
        original = self.browser.confirm
        def confirm():
            original()
            dialog = self.browser.root.xpath("//*[@id='confirmation']")[0]
            etree.SubElement(dialog, "button", {"aria-label": "Dismiss"})
            toast = etree.SubElement(dialog, "section", {"data-testid": "toasts"})
            etree.SubElement(toast, "p").text = "Resume uploaded successfully"
            etree.SubElement(toast, "button", {"aria-label": "Dismiss"})
        self.browser.confirm = confirm
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])
        self.assertIsNotNone(self.browser.application().get("hidden"))
        self.assertIsNotNone(self.browser.root.xpath("//*[@id='confirmation']")[0].get("hidden"))

    def test_save_the_application_confirmation_is_recognized(self):
        self.browser.title = "Save the application?"
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])

    def test_disappearing_underlying_app_and_confirmation_repoll_clear_ui_with_outside_toast(self):
        self.browser.keep_application = True
        self.browser.title = "Save this application?"
        calls = []
        def reacquire(driver, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                self.browser.application().set("hidden", "")
                self.browser.root.xpath("//*[@id='confirmation']")[0].set("hidden", "")
                toast = etree.SubElement(self.browser.root.find("body"), "section", {"role": "status"})
                etree.SubElement(toast, "p").text = "Resume uploaded successfully"
                raise EasyApplyError("open: application disappeared during reacquisition")
            return wait_for_application_modal(driver, **kwargs)
        with patch("modules.linkedin_form_cleanup.wait_for_application_modal", side_effect=reacquire):
            self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss"])
        self.assertGreaterEqual(self.browser.now, .5)

    def test_disappearing_underlying_app_still_discards_remaining_confirmation(self):
        self.browser.keep_application = True
        calls = []
        def reacquire(driver, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                self.browser.application().set("hidden", "")
                raise EasyApplyError("open: underlying application disappeared")
            return wait_for_application_modal(driver, **kwargs)
        with patch("modules.linkedin_form_cleanup.wait_for_application_modal", side_effect=reacquire):
            self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])

    def test_initial_application_disappearing_during_reacquisition_is_repolled(self):
        def reacquire(driver, **kwargs):
            self.browser.application().set("hidden", "")
            raise EasyApplyError("open: application disappeared")
        with patch("modules.linkedin_form_cleanup.wait_for_application_modal", side_effect=reacquire):
            self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, [])

    def test_persistent_unknown_dialog_does_not_pass_cleanup_when_reacquisition_fails(self):
        self.browser.application().set("hidden", "")
        self.browser.root.find("body").append(html.fromstring('<dialog open="" aria-label="Privacy settings"><button>Close</button></dialog>'))
        with patch("modules.linkedin_form_cleanup.wait_for_application_modal", side_effect=EasyApplyError("open: no application")):
            with self.assertRaises(ApplicationCleanupError):
                self.cleanup()
        self.assertEqual(self.browser.clicks, [])
        self.assertEqual(self.browser.keys, [])

    def test_slow_completed_actions_get_fresh_quiet_verification_budget(self):
        # Each live browser phase is below five seconds, but their cumulative
        # cost exceeds the old whole-operation deadline before quiet proof.
        original = self.browser.click
        def slow_completed_action(node):
            label = node.get("aria-label") or node.text_content().strip()
            self.browser.now += {"Dismiss": 3.2, "Discard": 2.1}.get(label, 0)
            original(node)
        self.browser.click = slow_completed_action
        def tick(seconds):
            self.browser.now += seconds
        with patch("modules.linkedin_form_cleanup.monotonic", side_effect=lambda: self.browser.now), \
                patch("selenium.webdriver.support.wait.time.monotonic", side_effect=lambda: self.browser.now), \
                patch("selenium.webdriver.support.wait.time.sleep", side_effect=tick):
            self.assertTrue(discard_application(self.browser, timeout=5))
        self.assertGreaterEqual(self.browser.now, 5.6)
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])
        self.assertIsNotNone(self.browser.application().get("hidden"))
        self.assertIsNotNone(self.browser.root.xpath("//*[@id='confirmation']")[0].get("hidden"))

    def test_stuck_confirmation_does_not_renew_phase_deadline(self):
        self.browser.confirm_stuck = True
        original = self.browser.click
        def slow_completed_discard(node):
            if node.text_content().strip() == "Discard":
                self.browser.now += 2
            original(node)
        self.browser.click = slow_completed_discard
        def tick(seconds):
            self.browser.now += seconds
        with patch("modules.linkedin_form_cleanup.monotonic", side_effect=lambda: self.browser.now), \
                patch("selenium.webdriver.support.wait.time.monotonic", side_effect=lambda: self.browser.now), \
                patch("selenium.webdriver.support.wait.time.sleep", side_effect=tick):
            with self.assertRaises(ApplicationCleanupError) as caught:
                discard_application(self.browser, timeout=5)
        details = caught.exception.diagnostics
        self.assertEqual(details["cause_type"], "TimeoutException")
        self.assertEqual(details["phase"], "await_discard_close")
        self.assertTrue(details["dismissed"])
        self.assertTrue(details["discarded"])
        self.assertGreater(details["elapsed_seconds"], 5)
        self.assertEqual(details["phase_budget"], 3)
        self.assertLess(details["elapsed_seconds"], 8)
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])
        self.assertIsNotNone(self.browser.application().get("hidden"))
        self.assertIsNone(self.browser.root.xpath("//*[@id='confirmation']")[0].get("hidden"))
        self.assertNotIn("Apply to Example", str(details))

    def test_close_button_without_confirmation_waits_for_quiet_ui(self):
        self.browser.mode = "none"
        self.browser.application().xpath(".//button[@aria-label='Dismiss']")[0].set("aria-label", "Close")
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Close"])
        self.assertGreaterEqual(self.browser.now, .4)

    def test_escape_fallback_only_targets_verified_application(self):
        button = self.browser.application().xpath(".//button[@aria-label='Dismiss']")[0]
        button.getparent().remove(button)
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.keys, ["\ue00c"])
        self.assertEqual(self.browser.clicks, ["Discard"])

    def test_no_dialogs_is_idempotent_and_waits_for_quiet_ui(self):
        self.browser.application().set("hidden", "")
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, [])
        self.assertEqual(self.browser.keys, [])

    def test_missing_exact_discard_never_uses_save(self):
        original = self.browser.confirm
        def confirm():
            original()
            self.browser.root.xpath("//*[@id='confirmation']//button[normalize-space(.)='Discard']")[0].text = "Discard and submit"
        self.browser.confirm = confirm
        with self.assertRaises(ApplicationCleanupError):
            self.cleanup()
        self.assertEqual(self.browser.clicks, ["Dismiss"])

    def test_conflicting_discard_accessible_name_is_rejected(self):
        original = self.browser.confirm
        def confirm():
            original()
            self.browser.root.xpath("//*[@id='confirmation']//button[normalize-space(.)='Discard']")[0].set("aria-label", "Save")
        self.browser.confirm = confirm
        with self.assertRaisesRegex(ApplicationCleanupError, "conflicting"):
            self.cleanup()
        self.assertEqual(self.browser.clicks, ["Dismiss"])

    def test_confirmation_that_remains_visible_fails_closed_without_repeat_clicks(self):
        self.browser.confirm_stuck = True
        with self.assertRaises(ApplicationCleanupError):
            self.cleanup()
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])

    def test_application_that_does_not_dismiss_fails_closed(self):
        self.browser.mode = "stuck"
        with self.assertRaises(ApplicationCleanupError):
            self.cleanup()
        self.assertEqual(self.browser.clicks, ["Dismiss"])

    def test_unrelated_visible_dialog_prevents_dismiss_or_escape(self):
        self.browser.root.find("body").append(html.fromstring('<dialog open="" aria-label="Privacy settings"><button>Close</button></dialog>'))
        with self.assertRaises(ApplicationCleanupError):
            self.cleanup()
        self.assertEqual(self.browser.clicks, [])
        self.assertEqual(self.browser.keys, [])

    def test_stale_dismiss_and_discard_are_refound(self):
        self.browser.stale_close_once = self.browser.stale_discard_once = True
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])

    def test_preexisting_confirmation_can_be_discarded(self):
        self.browser.application().set("hidden", "")
        self.browser.confirm()
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Discard"])

    def test_stale_after_dismiss_and_discard_does_not_repeat_completed_actions(self):
        original = self.browser.click
        raised = set()
        def detach_after_action(node):
            label = node.get("aria-label") or node.text_content().strip()
            original(node)
            if label not in raised:
                raised.add(label)
                raise StaleElementReferenceException("Action completed while dialog was replaced")
        self.browser.click = detach_after_action
        self.assertTrue(self.cleanup())
        self.assertEqual(self.browser.clicks, ["Dismiss", "Discard"])

    def test_multiple_discard_buttons_fail_closed(self):
        original = self.browser.confirm
        def confirm():
            original()
            etree.SubElement(self.browser.root.xpath("//*[@id='confirmation']")[0], "button").text = "Discard"
        self.browser.confirm = confirm
        with self.assertRaisesRegex(ApplicationCleanupError, "multiple Discard"):
            self.cleanup()
        self.assertEqual(self.browser.clicks, ["Dismiss"])

    def test_conflicting_dismiss_label_cannot_be_used_or_replaced_with_escape(self):
        self.browser.application().xpath(".//button[@aria-label='Dismiss']")[0].text = "Submit application"
        with self.assertRaisesRegex(ApplicationCleanupError, "conflicting"):
            self.cleanup()
        self.assertEqual(self.browser.clicks, [])
        self.assertEqual(self.browser.keys, [])

    def test_global_discard_button_is_not_used_as_confirmation_action(self):
        etree.SubElement(self.browser.root.find("body"), "button").text = "Discard"
        original = self.browser.confirm
        def confirm():
            original()
            self.browser.root.xpath("//*[@id='confirmation']//button[normalize-space(.)='Discard']")[0].set("disabled", "")
        self.browser.confirm = confirm
        with self.assertRaises(ApplicationCleanupError):
            self.cleanup()
        self.assertEqual(self.browser.clicks, ["Dismiss"])

    def test_invalid_timeout_is_rejected(self):
        for timeout in (0, -1, True, float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                discard_application(self.browser, timeout)


if __name__ == "__main__":
    unittest.main()
