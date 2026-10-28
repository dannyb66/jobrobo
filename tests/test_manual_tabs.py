"""Retained-tab tests use synthetic local forms and uploads only."""
import json
import os
import time
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from modules.manual_tabs import ManualTabs, close_browser_tab
from modules.submit_runner import run_submissions
from modules.submit_state import status
from test_generic_submit import SubmitBrowserTests, Handler


@skipUnless(os.getenv('JOBROBO_BROWSER_TESTS')=='1','Opt-in local Chrome forms only')
class RetainedTabBrowserTests(TestCase):
    setUpClass=classmethod(SubmitBrowserTests.setUpClass.__func__)
    tearDownClass=classmethod(SubmitBrowserTests.tearDownClass.__func__)
    setUp=SubmitBrowserTests.setUp
    jobs=SubmitBrowserTests.jobs
    run_jobs=SubmitBrowserTests.run_jobs

    def tearDown(self):
        for driver in self.drivers:
            try:driver.quit()
            except Exception:pass

    def until(self, monitor, expected, timeout=4):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            monitor.poll()
            if status(monitor.run.directory)['counts']==expected:return
            time.sleep(.05)
        self.assertEqual(status(monitor.run.directory)['counts'],expected)

    def test_default_fills_three_tabs_before_any_manual_submit_and_edits_work(self):
        outer=self
        class Review(ManualTabs):
            def wait(monitor,on_change):
                outer.assertEqual(len(monitor.tabs),3)
                outer.assertEqual(Handler.receipts,[])
                outer.assertEqual(status(monitor.run.directory)['counts'],{'awaiting_manual_submit':3})
                driver=monitor.driver
                handles=[s['tab_handle'] for _,s in monitor.run.rows()]
                outer.assertEqual(len(set(handles)),3)
                for handle in handles:
                    driver.switch_to.window(handle)
                    outer.assertEqual(driver.find_element('name','email').get_attribute('value'),'test@example.test')
                    outer.assertEqual(driver.execute_script("return document.querySelector('input[type=file]').files[0].size"),outer.pdf.stat().st_size)
                    # JS-generated clicks are blocked even after handoff.
                    driver.execute_script("document.querySelector('#submit').click()")
                outer.assertEqual(Handler.receipts,[])
                driver.switch_to.window(handles[0])
                driver.find_element('name','email').clear()
                driver.find_element('name','email').send_keys('reviewed@example.test')
                driver.find_element('id','submit').click()
                outer.until(monitor,{'applied':1,'awaiting_manual_submit':2})
                outer.assertEqual(driver.current_window_handle,handles[1],'After closing the confirmed tab, focus should move to a retained review tab')
                for handle in handles[1:]:
                    driver.switch_to.window(handle);driver.find_element('id','submit').click()
                outer.until(monitor,{'applied':3});on_change()
        with patch.dict('sys.modules',{'tkinter':None}):
            result=self.run_jobs(self.jobs('/job/a','/job/b','/native/c'),tab_monitor_factory=Review)
        self.assertEqual(result['counts'],{'applied':3});self.assertEqual(len(Handler.receipts),3)
        self.assertEqual(json.loads((self.root/'run/manual-review.json').read_text())['jobs'],[])
        self.assertEqual(len(self.drivers[-1].window_handles),1,'Confirmed job tabs should close; only the browser starter tab remains')

    def test_unknown_only_hands_off_unconfigured_choices(self):
        outer=self
        class Review(ManualTabs):
            def wait(monitor,on_change):
                outer.assertEqual(Handler.receipts,[ '/receive/job/a' ])
                outer.assertEqual(len(monitor.tabs),1)
                outer.assertEqual(status(monitor.run.directory)['counts'],{'applied':1,'awaiting_manual_submit':1})
                monitor.driver.find_element('id','submit').click()
                outer.until(monitor,{'applied':2})
        result=self.run_jobs(self.jobs('/job/a','/choice/b'),pause='unknown',tab_monitor_factory=Review)
        self.assertEqual(result['counts'],{'applied':2})

    def test_incomplete_tab_stays_for_manual_correction_and_next_job_is_filled(self):
        outer=self
        class Review(ManualTabs):
            def wait(monitor,on_change):
                outer.assertEqual(Handler.receipts,[])
                outer.assertEqual(status(monitor.run.directory)['counts'],{'awaiting_correction':1,'awaiting_manual_submit':1})
                jobs=monitor.run.rows();driver=monitor.driver
                driver.switch_to.window(jobs[0][1]['tab_handle'])
                driver.find_element('name','fact').send_keys('Provided manually')
                driver.find_element('id','submit').click()
                driver.switch_to.window(jobs[1][1]['tab_handle']);driver.find_element('id','submit').click()
                outer.until(monitor,{'applied':2})
        result=self.run_jobs(self.jobs('/required/a','/job/b'),tab_monitor_factory=Review)
        self.assertEqual(result['counts'],{'applied':2})

    def test_frame_confirmation_and_duplicate_are_posting_scoped(self):
        outer=self
        class Review(ManualTabs):
            def wait(monitor,on_change):
                driver=monitor.driver;rows=monitor.run.rows()
                driver.switch_to.window(rows[0][1]['tab_handle']);driver.switch_to.frame(0)
                driver.find_element('id','submit').click();driver.switch_to.default_content()
                driver.switch_to.window(rows[1][1]['tab_handle']);driver.find_element('id','submit').click()
                outer.until(monitor,{'applied':1,'duplicate':1})
        result=self.run_jobs(self.jobs('/frame/a','/portal-duplicate-alert/b'),tab_monitor_factory=Review)
        self.assertEqual(result['counts'],{'applied':1,'duplicate':1});self.assertEqual(len(Handler.receipts),2)

    def test_pause_resume_reconnects_live_tab_without_refill_or_submit(self):
        outer=self
        class Stop(ManualTabs):
            def wait(monitor,on_change):raise KeyboardInterrupt
        first=self.run_jobs(self.jobs('/job/a','/job/b'),tab_monitor_factory=Stop,max_applications=1)
        self.assertEqual(first['counts'],{'awaiting_manual_submit':1,'pending':1})
        self.assertEqual(Handler.receipts,[])
        original_handle=first['jobs'][0]['tab_handle'];driver=self.drivers[-1]
        class Review(ManualTabs):
            def wait(monitor,on_change):
                outer.assertEqual(len(monitor.tabs),1)
                outer.assertEqual(monitor.run.rows()[0][1]['attempts'],1)
                outer.assertEqual(driver.find_element('name','email').get_attribute('value'),'test@example.test')
                driver.find_element('id','submit').click()
                outer.until(monitor,{'applied':1,'pending':1})
        result=run_submissions(resume_dir=self.root/'run',services=self.services,driver_factory=lambda:driver,
            allow_local=True,tab_monitor_factory=Review,confirmation_timeout=.7)
        self.assertEqual(result['counts'],{'applied':1,'pending':1})
        self.assertEqual(result['jobs'][0]['tab_handle'],original_handle);self.assertEqual(len(Handler.receipts),1)

    def test_ten_tabs_are_retained_with_zero_automatic_submissions(self):
        outer=self
        class Stop(ManualTabs):
            def wait(monitor,on_change):
                outer.assertEqual(len(monitor.tabs),10)
                outer.assertEqual(Handler.receipts,[])
                outer.assertEqual(status(monitor.run.directory)['counts'],{'awaiting_manual_submit':10})
                raise KeyboardInterrupt
        result=self.run_jobs(self.jobs(*(f'/job/{i}' for i in range(10))),tab_monitor_factory=Stop)
        self.assertEqual(result['counts'],{'awaiting_manual_submit':10});self.assertEqual(Handler.receipts,[])

    def test_server_rejection_remains_editable_and_manual_retry_confirms(self):
        outer=self
        class Review(ManualTabs):
            def wait(monitor,on_change):
                driver=monitor.driver
                driver.find_element('id','submit').click()
                outer.until(monitor,{'awaiting_correction':1})
                driver.find_element('name','email').clear()
                driver.find_element('name','email').send_keys('corrected@example.test')
                driver.find_element('id','submit').click()
                outer.until(monitor,{'applied':1})
        result=self.run_jobs(self.jobs('/reject-once/a'),tab_monitor_factory=Review)
        self.assertEqual(result['counts'],{'applied':1});self.assertEqual(len(Handler.receipts),2)
        events=[json.loads(line) for line in (self.root/'run/events.jsonl').read_text().splitlines()]
        self.assertTrue(any(e['stage']=='portal_validation_rejected' for e in events))

    def test_manual_frame_alias_is_reserved_once(self):
        outer=self
        class Review(ManualTabs):
            def wait(monitor,on_change):
                outer.assertEqual(len(monitor.tabs),1)
                outer.assertEqual(status(monitor.run.directory)['counts'],{'awaiting_manual_submit':1,'duplicate':1})
                outer.assertEqual(Handler.receipts,[])
                raise KeyboardInterrupt
        result=self.run_jobs(self.jobs('/frame/a','/job/a'),tab_monitor_factory=Review)
        self.assertEqual(result['counts'],{'awaiting_manual_submit':1,'duplicate':1})

    def test_real_detach_and_new_webdriver_reconnect_preserves_form(self):
        outer=self;created=[]
        def browser_factory(profile_path,*,debugger_address=None):
            def create():
                from selenium import webdriver
                options=webdriver.ChromeOptions()
                if not debugger_address:options.add_experimental_option('detach',True)
                if debugger_address:options.debugger_address=debugger_address
                else:
                    options.add_argument('--headless=new')
                    options.add_argument('--user-data-dir='+str(profile_path))
                driver=webdriver.Chrome(options=options);created.append(driver);return driver
            return create
        class Stop(ManualTabs):
            def wait(monitor,on_change):raise KeyboardInterrupt
        class Review(ManualTabs):
            def wait(monitor,on_change):
                outer.assertEqual(len(monitor.tabs),1)
                monitor.driver.switch_to.window(monitor.run.rows()[0][1]['tab_handle'])
                outer.assertEqual(monitor.driver.find_element('name','email').get_attribute('value'),'test@example.test')
                monitor.driver.find_element('id','submit').click()
                outer.until(monitor,{'applied':1})
        try:
            with patch('direct_apply.browser_factory',side_effect=browser_factory):
                first=run_submissions(self.jobs('/job/a'),run_dir=self.root/'detached',config_dir=self.config,
                    output_dir=self.root/'reports',services=self.services,allow_local=True,tab_monitor_factory=Stop)
                self.assertEqual(first['counts'],{'awaiting_manual_submit':1})
                result=run_submissions(resume_dir=first['run_dir'],services=self.services,allow_local=True,tab_monitor_factory=Review)
            self.assertEqual(result['counts'],{'applied':1},result);self.assertEqual(len(created),2)
        finally:
            if created:
                # Explicitly clean up this synthetic detached Chrome, never a user browser.
                from modules.manual_tabs import TargetReader
                address=first['options']['debugger_address'] if 'first' in locals() else None
                if address:
                    try:
                        reader=TargetReader(address,first['jobs'][0]['manual_tab']['target_id'])
                        try:reader.call('Browser.close')
                        except Exception:pass
                        reader.close()
                    except Exception:pass
                for driver in created:
                    try:driver.quit()
                    except Exception:pass

    def test_cross_origin_frame_manual_submit_is_observed_without_focus_change(self):
        outer=self
        class Review(ManualTabs):
            def wait(monitor,on_change):
                driver=monitor.driver;handle=driver.current_window_handle
                outer.assertEqual(status(monitor.run.directory)['counts'],{'awaiting_manual_submit':1})
                driver.switch_to.frame(0);driver.find_element('id','submit').click()
                driver.switch_to.default_content()
                outer.until(monitor,{'applied':1})
                outer.assertEqual(driver.current_window_handle,handle)
        result=self.run_jobs(self.jobs('/cross-frame/a'),tab_monitor_factory=Review)
        self.assertEqual(result['counts'],{'applied':1});self.assertEqual(len(Handler.receipts),1)

    def test_native_submit_while_monitor_stopped_is_recovered_from_tab_record(self):
        outer=self
        class Stop(ManualTabs):
            def wait(monitor,on_change):raise KeyboardInterrupt
        first=self.run_jobs(self.jobs('/native/offline'),tab_monitor_factory=Stop)
        driver=self.drivers[-1]
        driver.find_element('id','submit').click()
        deadline=time.monotonic()+3
        while not driver.current_url.endswith('/thanks') and time.monotonic()<deadline:time.sleep(.05)
        self.assertTrue(driver.current_url.endswith('/thanks'))
        # A disconnected CDP session's document hooks need not survive navigation.
        driver.execute_script('delete window.__jobroboPrepare;delete window.__jobroboManualConfig')
        class Review(ManualTabs):
            def wait(monitor,on_change):outer.until(monitor,{'applied':1})
        result=run_submissions(resume_dir=first['run_dir'],services=self.services,driver_factory=lambda:driver,
            allow_local=True,tab_monitor_factory=Review)
        self.assertEqual(result['counts'],{'applied':1});self.assertEqual(len(Handler.receipts),1)


class ManualTabContracts(TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from modules.generic_inputs import load_jobs
        from modules.submit_state import SubmitRun
        from modules.external_apply import ExternalApplicationLedger,ExternalApplicationResult
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.job=load_jobs(url='https://employer.test/job/one')[0]
        self.run=SubmitRun(self.root/'run',jobs=[self.job]);self.addCleanup(self.run.close)
        self.ledger=ExternalApplicationLedger(self.root/'run/ledger.json')
        self.ledger.record_aliases(ExternalApplicationResult('submitting',self.job['url'],attempt_id='manual-one'),[self.job['url']],self.job['id'])
        self.monitor=ManualTabs(Mock(capabilities={'goog:chromeOptions':{'debuggerAddress':'127.0.0.1:12345'}}),self.run,self.ledger,confirmation_timeout=0)
        self.info={'target_id':'test','token':'manual-one','resolved_url':self.job['url'],'form_url':self.job['url'],
            'baseline':['Staff Engineer'],'aliases':[self.job['url']],'resume_name':'resume.pdf','resume_sha256':'sha',
            'report_path':str(self.root/'report.json'),'activations':0,'initially_complete':True}
        self.reader=Mock()
        self.tab={'job':self.job,'info':self.info,'reader':self.reader,'started':None,'done':False}
        self.monitor.tabs[self.job['key']]=self.tab
        self.run.update(self.job,status='awaiting_manual_submit',stage='manual_tab',manual_tab=self.info,tab_handle='handle-one')

    def snapshot(self,*,heading='Staff Engineer',url=None,count=0,**extra):
        return {'url':url or self.job['url'],'top':True,'headings':[heading],'alerts':[],
            'invalid':False,'challenge':False,'record':{'token':'manual-one','activations':count},**extra}

    def test_success_without_manual_activation_does_not_mark_applied(self):
        self.reader.read.return_value=([self.snapshot(heading='Application submitted successfully')],[])
        self.monitor.poll()
        self.assertEqual(self.run.rows()[0][1]['status'],'awaiting_manual_submit')
        self.monitor.driver.close.assert_not_called()

    def test_wrong_posting_confirmation_stays_uncertain(self):
        self.reader.read.return_value=([self.snapshot(heading='Application submitted successfully',url='https://employer.test/job/two',count=1)],[])
        self.monitor.poll()
        self.assertEqual(self.run.rows()[0][1]['status'],'submission_uncertain')

    def test_late_confirmation_upgrades_uncertain_without_any_click(self):
        self.reader.read.return_value=([self.snapshot(count=1)],[])
        self.monitor.poll();self.assertEqual(self.run.rows()[0][1]['status'],'submission_uncertain')
        self.reader.read.return_value=([self.snapshot(heading='Application submitted successfully',count=1)],[])
        self.monitor.poll();self.assertEqual(self.run.rows()[0][1]['status'],'applied')
        self.monitor.driver.find_element.assert_not_called()

    def test_confirmed_manual_submission_closes_only_its_tab(self):
        class WindowDriver:
            def __init__(self):self.window_handles=['handle-one','manual-two'];self.current_window_handle='manual-two';self.closed=[]
            class Switch:
                def __init__(self,owner):self.owner=owner
                def window(self,handle):self.owner.current_window_handle=handle
            def close(self):
                self.closed.append(self.current_window_handle);self.window_handles.remove(self.current_window_handle)
            switch_to=None
        driver=WindowDriver();driver.switch_to=WindowDriver.Switch(driver);self.monitor.driver=driver
        self.reader.read.return_value=([self.snapshot(heading='Application submitted successfully',count=1)],[])
        self.monitor.poll()
        self.assertEqual(driver.closed,['handle-one'])
        self.assertEqual(driver.current_window_handle,'manual-two')
        self.assertEqual(driver.window_handles,['manual-two'])

    def test_close_browser_tab_does_not_close_unresolved_tab(self):
        driver=Mock(window_handles=['handle-one','manual-two'],current_window_handle='manual-two')
        self.assertFalse(close_browser_tab(driver,'missing'))
        driver.close.assert_not_called()

    def test_closed_tab_never_means_submitted_or_safe_automatic_retry(self):
        self.reader.read.side_effect=ConnectionError('closed')
        self.monitor.poll();state=self.run.rows()[0][1]
        self.assertEqual(state['status'],'submission_uncertain');self.assertFalse(state['retryable'])
        self.assertEqual((self.root/'run/retry.txt').read_text(),'')

    def test_manual_queue_export_separates_review_from_retry(self):
        self.assertEqual(len(json.loads((self.root/'run/manual-review.json').read_text())['jobs']),1)
        self.assertEqual((self.root/'run/manual-review.txt').read_text(),self.job['url']+'\n')
        self.assertEqual((self.root/'run/retry.txt').read_text(),'')

    def test_known_rejection_and_correction_confirm_only_after_second_manual_click(self):
        self.reader.read.return_value=([self.snapshot(count=1,rejected=True)],[])
        self.monitor.poll();self.assertEqual(self.run.rows()[0][1]['status'],'awaiting_correction')
        self.reader.read.return_value=([self.snapshot(heading='Application submitted successfully',count=2)],[])
        self.monitor.poll();self.assertEqual(self.run.rows()[0][1]['status'],'applied')
        self.assertEqual(self.run.rows()[0][1]['manual_tab']['activations'],2)
