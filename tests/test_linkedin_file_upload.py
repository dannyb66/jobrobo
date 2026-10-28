"""Intercepted chooser uploads use fake DOM/CDP only; no browser or employer IO."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lxml import html, etree
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from unittest.mock import Mock,patch

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

    def test_slow_upload_extends_wait_without_duplicate_attachment(self):
        self.browser.selection = None
        spinner = etree.SubElement(self.browser.modal.node, 'span')
        spinner.text = 'Uploading'
        polls = 0
        messages = []
        def wait(predicate):
            nonlocal polls
            if not self.browser.sent:
                return bounded_wait(predicate)
            for _ in range(5):
                polls += 1
                if polls == 7:
                    spinner.getparent().remove(spinner)
                    etree.SubElement(self.browser.modal.node, 'div', {'id':'ready', 'role':'radio',
                        'aria-label':self.pdf.name,'aria-checked':'true'})
                result = predicate(None)
                if result:
                    return result
            raise TimeoutException('Upload still processing')
        target = resume_upload_target(self.browser, self.browser.modal, wait=wait, log=messages.append)
        target.find_element('name', 'file').send_keys(str(self.pdf))
        self.assertEqual(len(self.browser.sent), 1)
        self.assertEqual(self.browser.button_clicks, 1)
        self.assertTrue(any('90s total' in message for message in messages))
        self.assert_cleaned()

    def test_uploading_spinner_is_not_success_even_with_matching_selected_filename(self):
        spinner = etree.SubElement(self.browser.modal.node, 'span')
        spinner.text = 'Uploading'
        messages = []
        target = resume_upload_target(self.browser, self.browser.modal, wait=bounded_wait, log=messages.append)
        with self.assertRaisesRegex(ResumeUploadError, 'exact uploaded PDF.*uploading observed: True'):
            target.find_element('name', 'file').send_keys(str(self.pdf))
        self.assertEqual(len(self.browser.sent), 1)
        self.assertEqual(len(messages), 1)  # Only one bounded extension.
        self.assert_cleaned()

    def test_long_generation_refreshes_stale_modal_and_reuses_verified_pdf(self):
        from modules.resume_upload import upload_verified_resume
        original=self.browser.modal
        target=resume_upload_target(self.browser,original,wait=bounded_wait,
            refresh_modal=lambda:self.browser.modal)
        def generate(**kwargs):
            self.browser.root=Browser().root
            self.browser.modal=Element(self.browser,self.browser.root.xpath('//dialog')[0])
            original.find_elements=Mock(side_effect=StaleElementReferenceException('old modal'))
            original.find_element=Mock(side_effect=StaleElementReferenceException('old modal'))
            return str(self.pdf)
        optimize=Mock(side_effect=generate)
        with patch('modules.config_loader.peek_runtime_config',return_value={
                'rewrite_all_bullets':False,'source_checks_enabled':True}):
            result=upload_verified_resume(target,str(self.pdf),'JD','123',optimize=optimize)
        self.assertEqual(result,(True,self.pdf.name))
        optimize.assert_called_once()
        self.assertEqual(self.browser.sent,[('new-file',str(self.pdf.resolve()))])
        self.assert_cleaned()

    def test_refresh_retries_stale_lookup_without_restarting_generation(self):
        stale=Mock()
        stale.find_element.side_effect=StaleElementReferenceException('rerender')
        refresh=Mock(side_effect=[stale,self.browser.modal,self.browser.modal,self.browser.modal])
        target=resume_upload_target(self.browser,self.browser.modal,wait=bounded_wait,refresh_modal=refresh)
        target.find_element('name','file').send_keys(str(self.pdf))
        self.assertEqual(self.browser.sent,[('new-file',str(self.pdf.resolve()))])
        self.assert_cleaned()

    def test_refresh_confirm_selection_from_replaced_modal(self):
        original=self.browser.modal
        replaced=False
        def refresh():
            nonlocal replaced
            if self.browser.sent and not replaced:
                self.browser.root=html.fromstring(etree.tostring(self.browser.root))
                self.browser.modal=Element(self.browser,self.browser.root.xpath('//dialog')[0])
                original.find_elements=Mock(side_effect=StaleElementReferenceException('old selection dialog'))
                replaced=True
            return self.browser.modal
        target=resume_upload_target(self.browser,original,wait=bounded_wait,refresh_modal=refresh)
        target.find_element('name','file').send_keys(str(self.pdf))
        self.assertTrue(replaced)
        self.assertEqual(len(self.browser.sent),1)
        self.assert_cleaned()

    def test_refresh_handles_legacy_inputs_and_bounds_repeated_staleness(self):
        etree.SubElement(self.browser.modal.node,'input',{'name':'file','type':'file','id':'legacy'})
        refresh=Mock(return_value=self.browser.modal)
        target=resume_upload_target(self.browser,self.browser.modal,wait=bounded_wait,refresh_modal=refresh)
        target.find_element('name','file').send_keys(str(self.pdf))
        self.assertEqual(self.browser.sent,[('legacy',str(self.pdf.resolve()))])
        self.assertEqual(self.browser.calls,[])
        self.browser.modal.find_element=Mock(side_effect=StaleElementReferenceException('still rerendering'))
        with self.assertRaisesRegex(ResumeUploadError,'kept replacing'):
            target.find_element('name','file').send_keys(str(self.pdf))
        self.assertEqual(self.browser.modal.find_element.call_count,3)

    def test_bot_wrapper_refreshes_same_job_and_rejects_changed_job(self):
        from test_search_runner import extract_functions
        from modules.resume_upload import upload_verified_resume
        for changed in (False,True):
            with self.subTest(changed_job=changed):
                self.browser=Browser();self.browser.current_url='https://www.linkedin.com/jobs/search-results/?currentJobId=123'
                def generate(**kwargs):
                    if changed:self.browser.current_url='https://www.linkedin.com/jobs/view/999/'
                    return str(self.pdf)
                optimize=Mock(side_effect=generate)
                namespace={'driver':self.browser,'wait_for_application_modal':lambda driver:driver.modal,
                    'ResumeUploadError':ResumeUploadError,'run_resume_optimization':optimize,
                    'upload_verified_resume':upload_verified_resume,'print_lg':Mock(),
                    'resume_upload_target':lambda driver,modal,**kw:resume_upload_target(driver,modal,wait=bounded_wait,**kw)}
                extract_functions(namespace,'upload_optimized_resume')
                with patch('modules.config_loader.peek_runtime_config',return_value={
                        'rewrite_all_bullets':True,'source_checks_enabled':True}),\
                     patch('modules.resume_all_bullets.verify_strict_attachment',return_value=True):
                    result=namespace['upload_optimized_resume'](self.browser.modal,str(self.pdf),'JD','123')
                self.assertEqual(result[0],not changed)
                optimize.assert_called_once()
                self.assertEqual(len(self.browser.sent),0 if changed else 1)

    def test_bot_wrapper_rejects_job_changed_during_modal_wait(self):
        from test_search_runner import extract_functions
        from modules.resume_upload import upload_verified_resume
        etree.SubElement(self.browser.modal.node,'input',{'name':'file','type':'file','id':'legacy'})
        self.browser.current_url='https://www.linkedin.com/jobs/view/123/'
        waits=[]
        def modal_wait(driver):
            waits.append(True)
            if len(waits)==2:driver.current_url='https://www.linkedin.com/jobs/view/999/'
            return driver.modal
        optimize=Mock(return_value=str(self.pdf))
        namespace={'driver':self.browser,'wait_for_application_modal':modal_wait,
            'ResumeUploadError':ResumeUploadError,'run_resume_optimization':optimize,
            'upload_verified_resume':upload_verified_resume,'print_lg':Mock(),
            'resume_upload_target':lambda driver,modal,**kw:resume_upload_target(driver,modal,wait=bounded_wait,**kw)}
        extract_functions(namespace,'upload_optimized_resume')
        with patch('modules.config_loader.peek_runtime_config',return_value={
                'rewrite_all_bullets':True,'source_checks_enabled':True}),\
             patch('modules.resume_all_bullets.verify_strict_attachment',return_value=True):
            result=namespace['upload_optimized_resume'](self.browser.modal,str(self.pdf),'JD','123')
        self.assertFalse(result[0])
        self.assertEqual(self.browser.sent,[])
        optimize.assert_called_once()

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
        with self.assertRaisesRegex(ResumeUploadError, 'timed out'):
            self.attach()
        self.assertEqual(self.browser.sent, [])
        self.assert_cleaned()

    def test_disabled_new_input_is_not_used(self):
        self.browser.new_inputs[0]["disabled"] = ""
        with self.assertRaisesRegex(ResumeUploadError, 'timed out'):
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
        with self.assertRaisesRegex(ResumeUploadError, 'timed out'):
            self.attach()
        self.assert_cleaned()

    def test_selected_different_filename_does_not_report_success(self):
        self.browser.selection = "old resume.pdf"
        with self.assertRaisesRegex(ResumeUploadError, 'timed out'):
            self.attach()
        self.assert_cleaned()

    def test_selected_filename_outside_modal_does_not_report_success(self):
        self.browser.outside_selection = True
        with self.assertRaisesRegex(ResumeUploadError, 'timed out'):
            self.attach()
        self.assert_cleaned()

    def test_preexisting_selected_same_filename_cannot_confirm_fresh_upload(self):
        etree.SubElement(self.browser.modal.node, "div", {"id": "old-selected", "role": "radio",
                         "aria-label": self.pdf.name, "aria-checked": "true"})
        self.browser.selection = None
        with self.assertRaisesRegex(ResumeUploadError, 'timed out'):
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
