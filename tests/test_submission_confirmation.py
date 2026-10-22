"""Ashby-style confirmation regressions; all submissions use local fixtures."""
import json
import os
from http.server import ThreadingHTTPServer
from threading import Thread
import time
from unittest import TestCase, skipUnless

import test_generic_submit as fixtures
from modules.external_apply import _confirmed
from modules.generic_prepare import SNAPSHOT_JS
from modules.manual_tabs import ManualTabs, PROBE
from modules.submit_state import status


MESSAGE = "Your application was successfully submitted. We'll contact you if there are next steps."


class BannerHandler(fixtures.Handler):
    def header(self):
        # Preserve the real structure: unchanged job heading, Success heading,
        # success paragraph inside a status container, and no remaining form.
        role = 'alert' if '/alert/' in self.path else 'status'
        if '/class-only/' in self.path:
            role = ''
        banner = '<div class="ashby-application-form-success-container"'+(' role="'+role+'"' if role else '')+'><h2>Success</h2><p>'+MESSAGE+'</p></div>'
        initial = banner if '/preexisting/' in self.path else ''
        script = """new MutationObserver(() => {
          const h=document.querySelector('h1');
          if(h?.textContent!=='Application submitted successfully')return;
          h.textContent='Staff Engineer';
          if(!document.querySelector('.ashby-application-form-success-container'))
            document.body.insertAdjacentHTML('beforeend', BANNER);
          document.querySelector('form')?.remove();
        }).observe(document.body,{childList:true,subtree:true});""".replace('BANNER', json.dumps(banner))
        return super().header()+initial+'<script>'+script+'</script>'


@skipUnless(os.getenv('JOBROBO_BROWSER_TESTS') == '1', 'Opt-in local Chrome fixtures')
class SubmissionConfirmationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), BannerHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    tearDownClass = classmethod(fixtures.SubmitBrowserTests.tearDownClass.__func__)
    setUp = fixtures.SubmitBrowserTests.setUp
    jobs = fixtures.SubmitBrowserTests.jobs
    run_jobs = fixtures.SubmitBrowserTests.run_jobs

    def tearDown(self):
        for driver in self.drivers:
            driver.quit()

    def test_actual_ashby_banner_automatic_submit_is_confirmed_once(self):
        result = self.run_jobs(self.jobs('/status/a', '/class-only/b', '/alert/c'), pause='never')
        self.assertEqual(result['counts'], {'applied': 3})
        self.assertEqual(len(fixtures.Handler.receipts), 3)
        self.assertEqual(json.loads((self.root/'run/needs-review.json').read_text())['jobs'], [])

    def test_actual_ashby_banner_manual_submit_is_confirmed_once(self):
        outer = self

        class Review(ManualTabs):
            def wait(monitor, on_change):
                outer.assertEqual(fixtures.Handler.receipts, [])
                monitor.driver.find_element('id', 'submit').click()
                deadline = time.monotonic()+4
                while time.monotonic() < deadline:
                    monitor.poll()
                    if status(monitor.run.directory)['counts'] == {'applied': 1}:
                        on_change()
                        return
                    time.sleep(.05)
                outer.fail('Manual status-banner confirmation was missed')

        result = self.run_jobs(self.jobs('/status/manual'), tab_monitor_factory=Review)
        self.assertEqual(result['counts'], {'applied': 1})
        self.assertEqual(len(fixtures.Handler.receipts), 1)

    def test_preexisting_success_banner_does_not_confirm_new_activation(self):
        result = self.run_jobs(self.jobs('/preexisting/a'), pause='never')
        self.assertEqual(result['counts'], {'submission_uncertain': 1})
        self.assertEqual(len(fixtures.Handler.receipts), 1)

    def test_both_probes_ignore_hidden_banner_and_unrelated_body_copy(self):
        driver = self.factory()
        driver.get(self.base+'/status/probe')
        driver.execute_script("document.body.innerHTML='<h1>Staff Engineer</h1>'+arguments[0]", '<div role="status" style="display:none">'+MESSAGE+'</div><p>'+MESSAGE+'</p>')
        for probe in (SNAPSHOT_JS, 'return '+PROBE):
            self.assertFalse(_confirmed(driver.execute_script(probe)))
        driver.execute_script("document.querySelector('[role=status]').style.display='block'")
        for probe in (SNAPSHOT_JS, 'return '+PROBE):
            self.assertTrue(_confirmed(driver.execute_script(probe)))
