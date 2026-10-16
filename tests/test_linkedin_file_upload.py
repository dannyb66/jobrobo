"""Intercepted chooser uploads use fake DOM/CDP only; no browser or employer IO."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lxml import html, etree
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from modules.linkedin_file_upload import resume_upload_target
from modules.resume_upload import ResumeUploadError


class Element:
    def __init__(self, browser, node):
        self.browser, self.node = browser, node
        self.id = node.get("id") or str(id(node))

    def find_elements(self, by, value):
        nodes = self.node.xpath(".//*[@name=$name]", name=value) if by == "name" else self.node.xpath(value)
        return [Element(self.browser, node) for node in nodes]

    def find_element(self, by, value):
        matches = self.find_elements(by, value)
        if not matches:
            raise NoSuchElementException("Fake missing control")
        return matches[0]

    def is_displayed(self):
        return not any(node.get("hidden") is not None for node in [self.node, *self.node.iterancestors()])

    def is_enabled(self):
        return self.node.get("disabled") is None

    def get_attribute(self, name):
        return self.node.get(name)

    def click(self):
        self.browser.button_clicks += 1
        if self.browser.click_error:
            raise self.browser.click_error
        if not self.browser.intercepted:
            raise AssertionError("Native file chooser was not intercepted before click")
        for attributes in self.browser.new_inputs:
            etree.SubElement(self.browser.root.find("body"), "input", {"type": "file", **attributes})

    def send_keys(self, value):
        self.browser.sent.append((self.id, value))
        if self.browser.send_error:
            raise self.browser.send_error
        if self.browser.selection is not None:
            for radio in self.browser.modal.node.xpath(".//*[@role='radio']"):
                radio.set("aria-checked", "false")
            name = Path(value).name if self.browser.selection == "filename" else self.browser.selection
            parent = self.browser.root.find("body") if self.browser.outside_selection else self.browser.modal.node
            etree.SubElement(parent, "div", {"id": "selected-new", "role": "radio", "aria-label": name,
                                             "aria-checked": "true" if self.browser.selected else "false"})


class Browser:
    def __init__(self):
        self.root = html.fromstring('<html><body><dialog open="" id="application"><h2 id="dialog-header">Apply</h2>'
                                    '<div data-testid="dialog-content"><button>Upload resume</button></div></dialog></body></html>')
        self.modal = Element(self, self.root.xpath("//dialog")[0])
        self.intercepted = False
        self.calls, self.sent = [], []
        self.button_clicks = 0
        self.new_inputs = [{"id": "new-file", "accept": ".pdf,.doc,.docx", "hidden": ""}]
        self.selection, self.selected, self.outside_selection = "filename", True, False
        self.click_error = self.send_error = self.enable_error = self.disable_error = None

    def find_elements(self, by, value):
        return [Element(self, node) for node in self.root.xpath(value)]

    def execute_cdp_cmd(self, command, parameters):
        self.calls.append((command, parameters))
        if parameters["enabled"] and self.enable_error:
            raise self.enable_error
        if not parameters["enabled"] and self.disable_error:
            raise self.disable_error
        self.intercepted = parameters["enabled"]
        return {}


def bounded_wait(predicate):
    for _ in range(5):
        result = predicate(None)
        if result:
            return result
    raise TimeoutException("Fake upload state did not become ready")


class FileChooserUploadTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.pdf = Path(self.directory.name) / "verified output.pdf"
        self.pdf.write_bytes(b"test PDF bytes; content verification belongs upstream")
        self.browser = Browser()

    def attach(self):
        target = resume_upload_target(self.browser, self.browser.modal, wait=bounded_wait)
        target.find_element("name", "file").send_keys(str(self.pdf))

    def assert_cleaned(self):
        self.assertEqual(self.browser.calls[-1], ("Page.setInterceptFileChooserDialog", {"enabled": False}))
        self.assertFalse(self.browser.intercepted)

    def test_legacy_named_file_input_returns_original_modal_without_interception(self):
        etree.SubElement(self.browser.modal.node, "input", {"name": "file", "type": "file", "id": "legacy"})
        target = resume_upload_target(self.browser, self.browser.modal, wait=bounded_wait)
        self.assertIs(target, self.browser.modal)
        self.assertEqual(self.browser.calls, [])

    def test_upload_finds_new_hidden_nameless_input_outside_native_dialog_and_confirms_selection(self):
        self.attach()
        self.assertEqual(self.browser.calls[0], ("Page.setInterceptFileChooserDialog", {"enabled": True}))
        self.assertEqual(self.browser.button_clicks, 1)
        self.assertEqual(self.browser.sent, [("new-file", str(self.pdf.resolve()))])
        self.assertEqual(self.browser.modal.node.xpath(".//input[@type='file']"), [])
        self.assert_cleaned()

    def test_preexisting_document_file_input_is_never_used(self):
        etree.SubElement(self.browser.root.find("body"), "input", {"id": "old-file", "type": "file"})
        self.attach()
        self.assertEqual(self.browser.sent[0][0], "new-file")
        self.assert_cleaned()

    def test_irrelevant_new_image_input_is_ignored(self):
        self.browser.new_inputs.append({"id": "avatar", "accept": "image/*"})
        self.attach()
        self.assertEqual(self.browser.sent[0][0], "new-file")

    def test_multiple_relevant_new_inputs_are_rejected(self):
        self.browser.new_inputs.append({"id": "other-pdf", "accept": "application/pdf"})
        with self.assertRaisesRegex(ResumeUploadError, "ambiguous"):
            self.attach()
        self.assertEqual(self.browser.sent, [])
        self.assert_cleaned()

    def test_missing_new_input_times_out_and_restores_interception(self):
        self.browser.new_inputs = []
        with self.assertRaises(TimeoutException):
            self.attach()
        self.assertEqual(self.browser.sent, [])
        self.assert_cleaned()

    def test_disabled_new_input_is_not_used(self):
        self.browser.new_inputs[0]["disabled"] = ""
        with self.assertRaises(TimeoutException):
            self.attach()
        self.assertEqual(self.browser.sent, [])
        self.assert_cleaned()

    def test_contact_only_page_without_upload_button_returns_no_target(self):
        button = self.browser.modal.node.xpath(".//button")[0]
        button.text = "Next"
        target = resume_upload_target(self.browser, self.browser.modal, wait=bounded_wait)
        self.assertIsNone(target)
        self.assertEqual(self.browser.button_clicks, 0)
        self.assertEqual(self.browser.calls, [])

    def test_hidden_or_disabled_upload_button_returns_no_target(self):
        button = self.browser.modal.node.xpath(".//button")[0]
        for attribute in ("hidden", "disabled"):
            with self.subTest(attribute=attribute):
                button.set(attribute, "")
                self.assertIsNone(resume_upload_target(self.browser, self.browser.modal, wait=bounded_wait))
                del button.attrib[attribute]
        self.assertEqual(self.browser.calls, [])

    def test_multiple_scoped_upload_buttons_are_rejected(self):
        etree.SubElement(self.browser.modal.node, "button").text = "Upload resume"
        with self.assertRaisesRegex(ResumeUploadError, "Multiple Upload"):
            self.attach()
        self.assertEqual(self.browser.button_clicks, 0)
        self.assert_cleaned()

    def test_buttons_outside_modal_are_not_clicked(self):
        etree.SubElement(self.browser.root.find("body"), "button").text = "Upload resume"
        self.attach()
        self.assertEqual(self.browser.button_clicks, 1)

    def test_upload_button_failure_restores_interception(self):
        self.browser.click_error = RuntimeError("Button changed")
        with self.assertRaisesRegex(RuntimeError, "Button changed"):
            self.attach()
        self.assert_cleaned()

    def test_send_keys_failure_restores_interception(self):
        self.browser.send_error = RuntimeError("Attach failed")
        with self.assertRaisesRegex(RuntimeError, "Attach failed"):
            self.attach()
        self.assert_cleaned()

    def test_interception_enable_failure_still_attempts_disable(self):
        self.browser.enable_error = RuntimeError("CDP unavailable")
        with self.assertRaisesRegex(RuntimeError, "CDP unavailable"):
            self.attach()
        self.assertEqual(self.browser.button_clicks, 0)
        self.assert_cleaned()

    def test_unselected_new_attachment_does_not_report_success(self):
        self.browser.selected = False
        with self.assertRaises(TimeoutException):
            self.attach()
        self.assert_cleaned()

    def test_selected_different_filename_does_not_report_success(self):
        self.browser.selection = "old resume.pdf"
        with self.assertRaises(TimeoutException):
            self.attach()
        self.assert_cleaned()

    def test_selected_filename_outside_modal_does_not_report_success(self):
        self.browser.outside_selection = True
        with self.assertRaises(TimeoutException):
            self.attach()
        self.assert_cleaned()

    def test_preexisting_selected_same_filename_cannot_confirm_fresh_upload(self):
        etree.SubElement(self.browser.modal.node, "div", {"id": "old-selected", "role": "radio",
                         "aria-label": self.pdf.name, "aria-checked": "true"})
        self.browser.selection = None
        with self.assertRaises(TimeoutException):
            self.attach()
        self.assert_cleaned()

    def test_new_selection_element_can_confirm_same_filename_refresh(self):
        etree.SubElement(self.browser.modal.node, "div", {"id": "old-selected", "role": "radio",
                         "aria-label": self.pdf.name, "aria-checked": "true"})
        self.attach()
        self.assert_cleaned()

    def test_cleanup_failure_after_upload_is_not_reported_as_success(self):
        self.browser.disable_error = RuntimeError("CDP cleanup failed")
        with self.assertRaisesRegex(ResumeUploadError, "disable"):
            self.attach()

    def test_cleanup_failure_does_not_mask_original_upload_error(self):
        self.browser.send_error = RuntimeError("Original attach failure")
        self.browser.disable_error = RuntimeError("CDP cleanup failed")
        with self.assertRaisesRegex(RuntimeError, "Original attach failure"):
            self.attach()

    def test_keyboard_interruption_still_restores_interception(self):
        self.browser.click_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.attach()
        self.assert_cleaned()

    def test_missing_file_stops_before_browser_mutation(self):
        self.pdf.unlink()
        with self.assertRaises(ResumeUploadError):
            self.attach()
        self.assertEqual(self.browser.calls, [])

    def test_multifile_newline_path_is_rejected_before_browser_mutation(self):
        target = resume_upload_target(self.browser, self.browser.modal, wait=bounded_wait)
        with self.assertRaises(ResumeUploadError):
            target.find_element("name", "file").send_keys(str(self.pdf) + "\nother.pdf")
        self.assertEqual(self.browser.calls, [])

    def test_other_modal_lookup_is_delegated(self):
        target = resume_upload_target(self.browser, self.browser.modal, wait=bounded_wait)
        self.assertEqual(target.find_element("xpath", ".//h2").get_attribute("id"), "dialog-header")

    def test_invalid_timeout_is_rejected(self):
        for value in (True, 0, -1, float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resume_upload_target(self.browser, self.browser.modal, timeout=value)


if __name__ == "__main__":
    unittest.main()
