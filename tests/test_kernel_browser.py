"""Optional transport contracts and opt-in local Playwright fixture validation."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch
from contextlib import ExitStack
from importlib.util import find_spec

from modules.kernel_browser import browser_configuration, kernel_preflight
from modules.kernel_challenges import KernelChallenges


@skipUnless(find_spec('kernel') and find_spec('playwright'),'Optional SDK lifecycle contracts')
class KernelLifecycleContracts(TestCase):
    def fixture(self):
        from modules.kernel_browser import KernelBrowser,DEFAULTS
        stack=ExitStack();self.addCleanup(stack.close)
        client=Mock();remote=Mock(session_id='session-id',cdp_ws_url='SIGNED-URL-PRIVATE')
        client.browsers.create.return_value=remote;client.browsers.retrieve.return_value=remote
        pw=Mock()
        stack.enter_context(patch('modules.kernel_browser.kernel_preflight'))
        stack.enter_context(patch('kernel.Kernel',return_value=client))
        stack.enter_context(patch('playwright.sync_api.sync_playwright',return_value=Mock(start=lambda:pw)))
        def initialize(self,playwright,browser):
            self.playwright=playwright;self.capabilities={'goog:chromeOptions':{}}
        stack.enter_context(patch('modules.browser_runtime.PlaywrightActions.__init__',initialize))
        return KernelBrowser,dict(DEFAULTS),client,pw

    def test_create_omits_account_location_and_cleanup_is_once(self):
        constructor,settings,client,pw=self.fixture()
        runtime=constructor(settings=settings,run_id='test')
        params=client.browsers.create.call_args.kwargs
        self.assertNotIn('location',params);self.assertEqual(params['timeout_seconds'],900)
        self.assertNotIn('SIGNED',json.dumps(runtime.runtime_metadata))
        runtime.finish();runtime.finish();client.browsers.delete_by_id.assert_called_once_with('session-id')

    def test_resume_retrieves_fresh_url_without_allocating(self):
        constructor,settings,client,pw=self.fixture()
        runtime=constructor(settings=settings,run_id='test',session_id='session-id',telemetry_offset=17)
        client.browsers.create.assert_not_called();client.browsers.retrieve.assert_called_once_with('session-id')
        self.assertEqual(runtime.challenges.offset,17)
        runtime.finish(retain=True);client.browsers.delete_by_id.assert_not_called()

    def test_ambiguous_create_looks_up_name_without_second_allocation(self):
        constructor,settings,client,pw=self.fixture();client.browsers.create.side_effect=TimeoutError()
        runtime=constructor(settings=settings,run_id='test')
        self.assertEqual(client.browsers.create.call_count,1);client.browsers.retrieve.assert_called_once_with('jobrobo-test')
        runtime.finish()

    def test_setup_error_redacts_and_existing_session_is_preserved(self):
        constructor,settings,client,pw=self.fixture();pw.chromium.connect_over_cdp.side_effect=RuntimeError('SIGNED-URL-PRIVATE')
        with self.assertRaisesRegex(ValueError,'RuntimeError') as caught:constructor(settings=settings,run_id='test',session_id='session-id')
        self.assertNotIn('SIGNED',str(caught.exception));client.browsers.delete_by_id.assert_not_called();client.close.assert_called_once()


class KernelContracts(TestCase):
    def test_ambiguous_gpa_is_not_a_prose_draft_and_explicit_value_is_supported(self):
        from modules.generic_prepare import PreparationResolver
        question={'label':'What is/was your GPA?','name':'grade','kind':'text','required':True,'fields':[]}
        draft=Mock()
        self.assertFalse(PreparationResolver({}, {},draft).resolve(question,'lever').resolved)
        draft.answer.assert_not_called()
        answer=PreparationResolver({'gpa':'3.5'}, {},draft).resolve(question,'lever')
        self.assertTrue(answer.resolved);self.assertEqual(answer.source,'candidate_config:gpa')
    def test_known_rejection_and_pre_click_captcha_keep_retry_stage(self):
        from modules.submit_runner import run_submissions
        from modules.generic_inputs import load_jobs
        with TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config';config.mkdir();(config/'search.py').write_text('max_applications_per_run = 50\n')
            for name,blocker,extra in [('portal_validation_rejected','Portal rejected required fields',{'portal_validation_rejected':True}),
                    ('captcha_timeout_before_submit','CAPTCHA timeout before final activation',{})]:
                report={'status':'blocked','blockers':[blocker],'pre_submit_retryable':True,'output_dir':str(root/'report'),**extra}
                result=run_submissions(load_jobs(url='https://jobrobo.test/job/1'),run_dir=root/name,config_dir=config,pause='never',driver_factory=Mock(),
                    services={'candidate':{},'question_config':{},'resume_provider':Mock()},preparer=Mock(return_value=report))
                self.assertEqual(result['jobs'][0]['stage'],name)
                self.assertEqual((Path(result['run_dir'])/'retry.txt').read_text(),'https://jobrobo.test/job/1\n')

    def test_captcha_demo_main_document_is_never_skipped(self):
        from types import SimpleNamespace
        from modules.browser_runtime import PlaywrightActions
        self.assertFalse(PlaywrightActions.is_solver_frame(SimpleNamespace(url='https://www.google.com/recaptcha/api2/demo',parent_frame=None)))
        self.assertTrue(PlaywrightActions.is_solver_frame(SimpleNamespace(url='https://www.google.com/recaptcha/api2/bframe',parent_frame=object())))

    def test_default_local_and_typed_settings(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(browser_configuration(tmp)[0],'local')
            file=Path(tmp)/'browser_runtime.json'
            for value in ({'kernel':{'stealth':'yes'}},{'kernel':{'challenge_timeout_seconds':0}},
                          {'kernel':{'api_key':'must-not-be-config'}},{'kernel':{'proxy':{'id':'x','mode':'datacenter'}}}):
                file.write_text(json.dumps(value))
                with self.assertRaises(ValueError):browser_configuration(tmp)

    def test_missing_key_fails_without_creating_browser(self):
        with patch.dict('sys.modules',{'kernel':Mock(),'playwright':Mock(),'playwright.sync_api':Mock()}),patch('modules.kernel_browser.kernel_key',return_value=None):
            with self.assertRaisesRegex(ValueError,'KERNEL_API_KEY'):kernel_preflight()

    def test_cli_forwards_backend(self):
        import direct_apply
        with patch('modules.submit_runner.run_submissions',return_value={'jobs':[],'counts':{}}) as run:
            direct_apply.main(['submit','--url','https://example.test/job/1','--browser','kernel'])
            self.assertEqual(run.call_args.kwargs['browser_backend'],'kernel')

    def test_telemetry_is_diagnostic_redacted_and_paginated(self):
        runtime=Mock();runtime.challenge_observer=Mock()
        row=Mock();row.model_dump.return_value={'seq':7,'event':{'type':'captcha_solve_result','data':{'status':'success','token':'SECRET','captcha_provider':'recaptcha'}}}
        page=Mock(items=[row]);page.next_page_info.return_value=Mock(params={'offset':100})
        runtime.client.browsers.telemetry.events.return_value=page
        challenges=KernelChallenges(runtime,1);challenges.telemetry()
        self.assertEqual(challenges.offset,100)
        self.assertNotIn('SECRET',json.dumps(challenges.events))
        self.assertEqual(challenges.events[0]['status'],'success')
        runtime.challenge_observer.assert_not_called()
        runtime.session_observer.assert_called_once()

    def test_unscoped_telemetry_is_durable_without_changing_job_status(self):
        from modules.submit_state import SubmitRun
        from modules.generic_inputs import load_jobs
        with TemporaryDirectory() as tmp:
            run=SubmitRun(Path(tmp)/'run',jobs=load_jobs(url='https://jobrobo.test/job/1'),options={'kernel_session_id':'session'})
            try:
                run.browser_event('session',{'type':'captcha_solve_result','status':'success','page_correlated':False,'cursor_offset':9})
                self.assertEqual(run.export()['counts'],{'pending':1})
                event=json.loads((run.directory/'events.jsonl').read_text().splitlines()[-1])
                self.assertIsNone(event['job_key']);self.assertFalse(event['captcha_event']['page_correlated'])
                self.assertEqual(run.options['kernel_telemetry_offset'],9)
            finally:run.close()

    def test_solver_success_cannot_override_active_page(self):
        runtime=Mock();runtime.is_solver_frame.return_value=False
        frame=Mock();frame.evaluate.return_value={'active':True};page=Mock(frames=[frame])
        challenges=KernelChallenges(runtime,0)
        self.assertFalse(challenges.wait(page))


@skipUnless(os.getenv('JOBROBO_PLAYWRIGHT_TESTS')=='1','Opt-in local Playwright browser')
class PlaywrightPreparationTests(TestCase):
    def test_invisible_badge_is_not_an_active_challenge_but_overlay_is(self):
        from playwright.sync_api import sync_playwright
        from modules.kernel_challenges import CHALLENGE_PROBE
        with sync_playwright() as pw:
            chrome=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
            page=chrome.new_page();page.route('**/*',lambda r:r.fulfill(body=''))
            page.set_content('<iframe title="reCAPTCHA" src="https://www.recaptcha.net/recaptcha/enterprise/anchor?size=invisible" width="256" height="60"></iframe>')
            self.assertFalse(page.evaluate(CHALLENGE_PROBE)['active'])
            page.locator('iframe').evaluate("e=>{e.src='https://www.recaptcha.net/recaptcha/api2/bframe';e.height='400'}")
            self.assertTrue(page.evaluate(CHALLENGE_PROBE)['active'])
            page.locator('iframe').evaluate("e=>{e.src='https://www.recaptcha.net/recaptcha/api2/anchor?size=normal';e.height='78';e.width='304'}")
            self.assertTrue(page.evaluate(CHALLENGE_PROBE)['active'])
            chrome.close()

    def test_stale_reference_cannot_resolve_to_new_document_control(self):
        from playwright.sync_api import sync_playwright
        from modules.browser_runtime import PlaywrightActions,BrowserOperationError
        pw=sync_playwright().start();chrome=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        driver=PlaywrightActions(pw,chrome)
        driver.context.route('https://jobrobo.test/**',lambda r:r.fulfill(content_type='text/html',body='<input name=email>'))
        try:
            driver.get('https://jobrobo.test/one');old=driver.find_element('name','email')
            driver.get('https://jobrobo.test/two');driver.find_element('name','email')
            with self.assertRaises(BrowserOperationError):old.get_attribute('value')
        finally:driver.quit()

    def test_captcha_before_after_activation_and_timeout_do_not_repeat_submit(self):
        from playwright.sync_api import sync_playwright
        from modules.browser_runtime import PlaywrightActions
        from modules.kernel_challenges import KernelChallenges
        from modules.generic_prepare import prepare_url
        from modules.generic_submit import SubmissionBrowser,submit_ready
        from modules.external_apply import ExternalApplicationLedger
        from modules.direct_careers_apply import digest
        from tests.test_generic_prepare_browser import page
        pw=sync_playwright().start();chrome=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        driver=PlaywrightActions(pw,chrome);driver.browser_backend='kernel'
        driver.client=Mock();driver.client.browsers.telemetry.events.return_value=Mock(items=[],next_page_info=lambda:None)
        driver.challenge_observer=None
        posts=[]
        def route(r):
            path=r.request.url.split('jobrobo.test')[-1]
            if r.request.method=='POST':posts.append(path);r.fulfill(status=200,body='ok');return
            if path=='/widget':r.fulfill(status=200,body='<p>CAPTCHA fixture</p>');return
            widget='<iframe title="captcha" src="/widget" width="300" height="78"></iframe>'
            html=page('/native')
            if path=='/before':html+=widget+'<script>setTimeout(()=>document.querySelector("iframe").remove(),700)</script>'
            if path=='/before-timeout':html+=widget
            after=path in {'/after','/after-timeout'}
            script="window.submits++;event.preventDefault();fetch(location.pathname+'/receive',{method:'POST'});"
            if after:script+="document.body.insertAdjacentHTML('beforeend',"+json.dumps(widget)+");"
            if path=='/reject':script+="document.body.insertAdjacentHTML('beforeend','<div role=alert>Your form needs corrections: Missing entry for required field: Current Company</div>');"
            elif path=='/duplicate':script+="document.querySelector('h1').textContent='You have already applied for this job';"
            elif path!='/after-timeout':script+="setTimeout(()=>{document.querySelector('iframe')?.remove();document.querySelector('h1').textContent='Application submitted successfully'},500);"
            import html as html_module
            html=html.replace('window.submits++;return false',html_module.escape(script+'return false',quote=True))
            r.fulfill(status=200,content_type='text/html',body='<!doctype html>'+html)
        driver.context.route('https://jobrobo.test/**',route)
        try:
            with TemporaryDirectory() as tmp:
                root=Path(tmp);pdf=root/'resume.pdf';pdf.write_bytes(b'synthetic upload')
                for mode,expected,expected_posts in [('before','applied',1),('after','applied',1),('before-timeout','blocked',0),('after-timeout','submission_uncertain',1),('reject','blocked',1),('duplicate','duplicate',1)]:
                    with self.subTest(mode=mode):
                        before=len(posts);driver.challenges=KernelChallenges(driver,1);driver.switch_to.new_window('tab')
                        run=Mock();ledger=ExternalApplicationLedger(root/(mode+'.json'));url='https://jobrobo.test/'+mode
                        def ready(browser,report,out):return submit_ready(browser,report,out,job={'id':mode,'url':url},run=run,ledger=ledger,attempt_id=mode,pause='never',confirmation_timeout=1)
                        report=prepare_url(url,driver=driver,output_dir=root/'reports',candidate={'email':'test@example.test'},question_config={},
                            resume_provider=lambda job,out:{'pdf':str(pdf),'pdf_sha256':digest(pdf),'job_id':'fixture'},browser_class=SubmissionBrowser,on_ready=ready,settle=.05)
                        self.assertEqual(report['status'],expected,report['blockers'])
                        self.assertEqual(len(posts)-before,expected_posts)
                        self.assertLessEqual(driver.execute_script('return window.submits'),1)
                        if mode=='reject':
                            self.assertTrue(report['pre_submit_retryable']);self.assertFalse(ledger.protected(url))
                        if mode=='after-timeout':self.assertTrue(ledger.protected(url))
        finally:driver.quit()

    def test_shared_fixture_matrix_and_prepare_guard(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from tests.test_generic_prepare_browser import Handler
        from playwright.sync_api import sync_playwright
        from modules.browser_runtime import PlaywrightActions
        from modules.generic_prepare import prepare_url
        from modules.direct_careers_apply import digest
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        Thread(target=server.serve_forever,daemon=True).start()
        pw=sync_playwright().start()
        browser=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        driver=PlaywrightActions(pw,browser)
        try:
            with TemporaryDirectory() as tmp:
                pdf=Path(tmp)/'optimized.pdf';pdf.write_bytes(b'synthetic fixture attachment')
                for path in ('/native','/frame','/shadow','/choice','/custom','/conditional','/multi','/multi-submit','/receipt','/city-autocomplete'):
                    with self.subTest(path=path):
                        report=prepare_url(f'http://127.0.0.1:{server.server_port}'+path,driver=driver,output_dir=Path(tmp)/'reports',
                            candidate={'email':'test@example.test','phone':'5550100','current_employer':'Synthetic','country':'United States','city':'San Francisco','state':'California'},
                            question_config={},resume_provider=lambda job,root:{'pdf':str(pdf),'pdf_sha256':digest(pdf),'job_id':'fixture'},allow_local=True,settle=.05)
                        self.assertEqual(report['status'],'prepared',report['blockers'])
                        self.assertTrue(report['attachment_verified'])
                        driver.execute_script('document.querySelector("form")?.requestSubmit()')
                        self.assertEqual(driver.execute_script('return window.submits'),0)
        finally:
            driver.quit();server.shutdown();server.server_close()

    def test_single_automatic_submit_and_manual_retained_tabs(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from tests.test_generic_submit import Handler
        from playwright.sync_api import sync_playwright
        from modules.browser_runtime import PlaywrightActions
        from modules.generic_inputs import load_jobs
        from modules.submit_runner import run_submissions
        from modules.direct_careers_apply import digest
        from modules.manual_tabs import ManualTabs
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
        Handler.receipts=[]
        with TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config';config.mkdir();(config/'search.py').write_text('max_applications_per_run = 50\n')
            pdf=root/'resume.pdf';pdf.write_bytes(b'synthetic fixture attachment')
            services={'candidate':{'email':'test@example.test'},'question_config':{'unanswered_choice_policy':'first_option'},
                'resume_provider':lambda job,out:{'pdf':str(pdf),'pdf_sha256':digest(pdf),'job_id':'synthetic'}}
            pw=sync_playwright().start();browser=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
            driver=PlaywrightActions(pw,browser)
            def jobs(*paths):return sum((load_jobs(url=f'http://127.0.0.1:{server.server_port}'+p,allow_local=True) for p in paths),[])
            try:
                result=run_submissions(jobs('/job/a','/native/b','/frame/c','/choice/d'),run_dir=root/'auto',config_dir=config,output_dir=root/'reports',services=services,
                    driver_factory=lambda:driver,allow_local=True,pause='never',confirmation_timeout=2)
                self.assertEqual(result['counts'],{'applied':4});self.assertEqual(len(Handler.receipts),4)
                # Runner closes an automatic session; use a new adapter for manual tabs.
                pw=sync_playwright().start();browser=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
                driver=PlaywrightActions(pw,browser)
                class Review(ManualTabs):
                    def wait(self,on_change):
                        self.poll()
                        assert len(Handler.receipts)==4
                        for target in self.driver.window_handles:
                            page=self.driver.pages[target]
                            if page.query_selector('button#submit'):page.click('button#submit');page.wait_for_timeout(150)
                        self.poll();on_change()
                result=run_submissions(jobs('/job/e','/native/f'),run_dir=root/'manual',config_dir=config,output_dir=root/'reports',services=services,
                    driver_factory=lambda:driver,allow_local=True,pause='always',tab_monitor_factory=Review,confirmation_timeout=2)
                self.assertEqual(result['counts'],{'applied':2});self.assertEqual(len(Handler.receipts),6)
            finally:
                try:driver.quit()
                except Exception:pass
                server.shutdown();server.server_close()
