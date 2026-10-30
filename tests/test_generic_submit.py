"""No employer/network provider calls: input, state and local HTTP submit tests."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from modules.generic_inputs import load_jobs, posting_key
from modules.generic_submit import unknown_answers, SubmissionBrowser, review_values
from modules.submit_state import SubmitRun, status
from modules.submit_runner import run_submissions
from modules.generic_prepare import prepare_url
from modules.external_apply import ExternalApplicationLedger, ExternalApplicationResult
from modules.direct_careers_apply import digest
from modules.job_pipeline.models import StageResult


def role():
    return {'id':'role:1','career_url':'https://employer.test/jobs/1','title':'Staff Engineer',
        'description':'Build Python systems. '*20,'status':'open','eligible':True,'application_eligible':False,
        'application_exclusion_reasons':['preference_warning'],'verified_at':'2026-10-01T00:00:00+00:00',
        'verification_run_id':'original-verification','company_id':'company:1',
        'company':{'id':'company:1','name':'Synthetic'}}


class SubmitContracts(TestCase):
    def test_redirect_claims_are_atomic_and_owner_checked(self):
        with TemporaryDirectory() as tmp:
            ledger=ExternalApplicationLedger(Path(tmp)/'ledger.json')
            urls=['https://a.test/job/1','https://jobs.lever.co/hive/4df537a1-1c31-4c05-9390-9ce635f03f1d']
            claim=ExternalApplicationResult('submitting',urls[0],attempt_id='owner')
            ledger.record_aliases(claim,urls,'role:1')
            self.assertTrue(all(ledger.protected(u) for u in urls))
            other=ExternalApplicationResult('submitting',urls[1],attempt_id='other')
            with self.assertRaises(RuntimeError):ledger.record_aliases(other,['https://a.test/job/2',urls[1]],'role:2')
            self.assertFalse(ledger.protected('https://a.test/job/2'))
            with self.assertRaises(ValueError):ledger.release_aliases(urls,'other',proof={'disarmed':True,'activated':False})
            ledger.release_aliases(urls,'owner',proof={'disarmed':True,'activated':False})
            self.assertFalse(any(ledger.protected(u) for u in urls))

    def test_review_preview_shows_text_values_and_checkbox_options(self):
        rows=review_values({'fields':[{'name':'email','question':'Email','type':'email','visible':True,'value':'test@example.test','checked':False},
            {'name':'choice','question':'Team','label':'Engineering','type':'checkbox','visible':True,'checked':True}]})
        self.assertEqual(rows,[('Email','test@example.test'),('Team — Engineering',True)])

    def test_direct_and_pipeline_cli_route_to_shared_runner(self):
        import direct_apply,job_pipeline
        from modules.job_pipeline.models import write_artifact
        with TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'ranked.json';write_artifact(StageResult.create('verified_roles','ranked','rank:1',[role()]),p)
            with patch('modules.submit_runner.run_submissions',return_value={'jobs':[{'status':'applied'}]}) as runner:
                self.assertEqual(direct_apply.main(['submit','--input',str(p),'--pause-before-submit','unknown','--workers','3']),0)
                self.assertEqual(runner.call_args.args[0][0]['id'],'role:1')
                self.assertEqual(runner.call_args.kwargs['workers'],3)
            def execute(jobs,**kwargs):
                out=Path(kwargs['export_path']);write_artifact(StageResult.create('applications','test','apply:1',[]),out)
                return {'run_dir':str(root/'run'),'options':{'export_path':str(out)}}
            with patch('modules.submit_runner.run_submissions',side_effect=execute) as runner:
                self.assertEqual(job_pipeline.main(['apply','careers','--input',str(p),'--db',str(root/'pipeline.db'),
                    '--output',str(root/'applications.json'),'--limit','1','--workers','2']),0)
                self.assertEqual(runner.call_args.args[0][0]['verification_run_id'],'original-verification')
                self.assertEqual(runner.call_args.kwargs['workers'],2)
            self.assertFalse((root/'pipeline.db').exists(),'Input routing must not create a DB before execution')
    def test_native_saved_stage_order_and_provenance_not_rank_run(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'ranked.json'; r=role()
            artifact=StageResult.create('verified_roles','ranked','rank:1',[r])
            p.write_text(json.dumps(artifact.to_dict()));before=p.read_bytes()
            jobs=load_jobs([str(p)])
            self.assertEqual(jobs[0]['verification_run_id'],'original-verification')
            self.assertEqual(jobs[0]['provenance']['input_run_id'],'rank:1')
            self.assertEqual(jobs[0]['admission_blockers'],[])
            self.assertEqual(jobs[0]['preference_warnings'],['preference_warning'])
            self.assertEqual(p.read_bytes(),before)

    def test_actual_saved_artifacts_load_without_database(self):
        base=Path.home()/'Library/Application Support/jobrobo/work-programme-20261014'
        paths=[('verification-tiers/90-engineering-ranked.json',90),('verification-tiers/all-174-ranked.json',174),
               ('direct-careers-apply/90-original-queue.json',90),('direct-careers-apply/generation/90-generated-queue.json',90)]
        for rel,count in paths:
            p=base/rel
            if not p.is_file(): continue
            with self.subTest(path=rel):
                original=p.read_bytes();jobs=load_jobs([str(p)])
                self.assertEqual(len(jobs),count);self.assertEqual(p.read_bytes(),original)
                self.assertTrue(all(j.get('verification_run_id') for j in jobs))

    def test_wrong_stage_and_conflicting_ids_fail_before_browser(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'companies.json'
            p.write_text(json.dumps(StageResult.create('companies','c','d',[]).to_dict()))
            with self.assertRaisesRegex(ValueError,'verify careers'):load_jobs([str(p)])
            p.write_text(json.dumps([{'id':'x','url':'https://a.test/job/1'},{'id':'x','url':'https://a.test/job/2'}]))
            with self.assertRaisesRegex(ValueError,'different postings'):load_jobs([str(p)])

    def test_txt_json_aliases_and_role_filter(self):
        with TemporaryDirectory() as tmp:
            a=Path(tmp)/'jobs.txt';a.write_text('# comment\nhttps://a.test/job/1?utm_source=x\n')
            b=Path(tmp)/'jobs.json';b.write_text(json.dumps({'jobs':[{'id':'role:chosen','url':'https://a.test/job/1'},'https://a.test/job/2']}))
            jobs=load_jobs([str(a),str(b)],selected_roles=['role:chosen'])
            self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['url'],'https://a.test/job/1')
            self.assertEqual(posting_key('https://a.test/job/1'),ExternalApplicationLedger.target_key('https://a.test/job/1'))

    def test_retry_exports_exclude_uncertain_and_keep_provenance(self):
        with TemporaryDirectory() as tmp:
            jobs=load_jobs(url='https://a.test/job/1')+load_jobs(url='https://a.test/job/2')
            run=SubmitRun(Path(tmp)/'run',jobs=jobs,options={'pause':'unknown'})
            run.update(jobs[0],status='failed_before_submit',stage='upload',retryable=True,reason='fixture')
            run.update(jobs[1],status='submission_uncertain',stage='confirmation',retryable=False)
            directory=run.directory;run.close()
            self.assertEqual((directory/'retry.txt').read_text(),'https://a.test/job/1\n')
            # retry.json now tracks every non-success URL so a later run can pick
            # it up; only the retryable one is marked safe to replay automatically.
            tracked=load_jobs([str(directory/'retry.json')])
            self.assertEqual(len(tracked),2)
            self.assertEqual((directory/'retry-manual.txt').read_text(),'https://a.test/job/2\n')
            self.assertEqual(len(json.loads((directory/'needs-review.json').read_text())['jobs']),1)
            resumed=SubmitRun(directory);self.assertEqual(resumed.options['pause'],'unknown');resumed.close()
            self.assertEqual(status(directory)['counts']['submission_uncertain'],1)

    def test_unknown_review_is_answer_source_based_not_resume_generation(self):
        q=lambda source: {'name':source,'question':source,'status':'prepared','source':source}
        report={'resume':{'ai_generated':True},'questions':[q('candidate_config:email'),q('user_policy:dei_opt_out'),
            q('ai_draft'),q('user_policy:first_option'),{'name':'blank','question':'Optional','status':'manual_review','source':'manual'}]}
        self.assertEqual(unknown_answers(report),['ai_draft','user_policy:first_option'])
        report['questions'].append({**q('candidate_config:city'), 'label_source':'ai_observed_context'})
        self.assertEqual(unknown_answers(report),['ai_draft','user_policy:first_option','candidate_config:city'])

    def test_confirmation_requires_exact_posting_not_only_shared_host(self):
        from modules.generic_submit import _identity_ok
        url='https://jobs.lever.co/hive/4df537a1-1c31-4c05-9390-9ce635f03f1d'
        self.assertTrue(_identity_ok(url+'/thanks',url))
        self.assertFalse(_identity_ok('https://jobs.lever.co/another/11111111-1111-1111-1111-111111111111/thanks',url))
        self.assertFalse(_identity_ok('https://a.test/job/2/thanks','https://a.test/job/1'))

    def test_application_export_keeps_original_verification_and_ranking_in_store(self):
        from modules.submit_runner import application_export
        from modules.job_pipeline.store import PipelineStore
        with TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'roles.json'
            p.write_text(json.dumps(StageResult.create('verified_roles','ranked','rank:1',[role()]).to_dict()))
            jobs=load_jobs([str(p)]);run=SubmitRun(root/'run',jobs=jobs)
            try:
                run.update(jobs[0],status='applied',stage='confirmed',attempt_id='test-attempt',retryable=False)
                exported=application_export(run,db_path=root/'pipeline.db')
                record=exported['records'][0]
                self.assertEqual(record['role_id'],'role:1')
                self.assertEqual(record['verification_run_id'],'original-verification')
                self.assertEqual(record['ranking_run_id'],'rank:1')
                with PipelineStore(root/'pipeline.db') as store:
                    stored=json.loads(store.connection.execute("SELECT record FROM entities WHERE stage='applications'").fetchone()[0])
                    self.assertEqual(stored,record)
            finally:run.close()

    def test_uncertain_reconciliation_releases_only_inspected_attempt(self):
        from modules.submit_runner import reconcile_run
        for outcome in ('applied','not-submitted'):
            with self.subTest(outcome=outcome), TemporaryDirectory() as tmp:
                root=Path(tmp);jobs=load_jobs(url='https://a.test/job/1');ledger=ExternalApplicationLedger(root/'ledger.json')
                run=SubmitRun(root/'run',jobs=jobs,options={'ledger_path':str(ledger.path)})
                run.update(jobs[0],status='submission_uncertain',stage='confirmation',attempt_id='test-attempt',retryable=False)
                ledger.record_aliases(ExternalApplicationResult('submitting',jobs[0]['url'],attempt_id='test-attempt'),[jobs[0]['url']],'role:1')
                run.close()
                with patch.object(SubmitRun,'update',side_effect=OSError('fixture checkpoint failure')):
                    with self.assertRaises(OSError):
                        reconcile_run(root/'run',jobs[0]['id'],outcome=outcome,reason='Synthetic receipt inspected')
                result=reconcile_run(root/'run',jobs[0]['id'],outcome=outcome,reason='Synthetic receipt inspected')
                expected='applied' if outcome=='applied' else 'failed_before_submit'
                self.assertEqual(result['counts'],{expected:1})
                self.assertEqual(ledger.protected(jobs[0]['url']),outcome=='applied')
                self.assertEqual(bool((root/'run/retry.txt').read_text()),outcome=='not-submitted')
                self.assertEqual(reconcile_run(root/'run',jobs[0]['id'],outcome=outcome,reason='Repeated inspected outcome')['counts'],{expected:1})

    def test_prepare_cannot_accept_a_submit_callback(self):
        with self.assertRaisesRegex(ValueError,'cannot invoke'):
            prepare_url('https://a.test/job',driver=Mock(),output_dir='/tmp/unused',candidate={},question_config={},resume_provider=Mock(),on_ready=Mock())


class Handler(BaseHTTPRequestHandler):
    receipts=[]
    def do_GET(self):
        ident=self.path.rsplit('/',1)[-1]
        if '/thanks' in self.path:
            body='<h1>Thank you for applying</h1>'
        elif self.path.startswith(('/frame/','/cross-frame/')):
            origin=f'http://localhost:{self.server.server_port}' if self.path.startswith('/cross-frame/') else ''
            body=self.header()+'<iframe width="900" height="900" src="'+origin+'/job/'+ident+'"></iframe>'
        else:
            extra='<label>Choose team<select name="team" required><option value="">Select</option><option value="one">One</option><option value="two">Two</option></select></label>' if 'choice' in self.path else ''
            if 'required' in self.path: extra+='<label>Unknown required fact<input name="fact" required></label>'
            action=f'action="{self.path}/thanks" method="post"' if 'native' in self.path else 'onsubmit="event.preventDefault();fetch(\'/receive'+self.path+'\',{method:\'POST\'}).then(()=>{'+('void 0' if 'no-confirm' in self.path else 'document.querySelector(\'h1\').textContent=\'Application submitted successfully\'')+'});"'
            if 'reject-once' in self.path:
                action=action.replace("document.querySelector('h1').textContent='Application submitted successfully'", "if(!window.rejectedOnce){window.rejectedOnce=true;document.querySelector('#feedback').textContent='Your form needs corrections: Missing entry for required field: Current Company'}else{document.querySelector('#feedback').textContent='';document.querySelector('h1').textContent='Application submitted successfully'}")
            if 'portal-duplicate' in self.path:
                if '-alert' in self.path:
                    action=action.replace("document.querySelector('h1').textContent='Application submitted successfully'","document.querySelector('#feedback').textContent='You have already submitted an application for this job'")
                else:action=action.replace('Application submitted successfully','You have already applied for this job')
            body=self.header()+'<form '+action+'><label>Email<input name="email" type="email" required></label><label>Resume<input name="resume" type="file" required></label>'+extra+'<button id="submit" type="submit">Submit application</button></form>'
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(('<!doctype html>'+body).encode())
    def header(self):
        job={'@type':'JobPosting','title':'Staff Engineer','hiringOrganization':{'name':'Synthetic'},'description':'Build reliable Python systems and cloud APIs. '*15}
        return '<title>Staff Engineer @ Synthetic</title><h1>Staff Engineer</h1><div id="feedback" role="alert"></div><script type="application/ld+json">'+json.dumps(job)+'</script>'
    def do_POST(self):
        Handler.receipts.append(self.path)
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(b'<h1>Thank you for applying</h1>')
    def log_message(self,*args):pass



class SubmitActivationTests(TestCase):
    """Pure helpers; no browser needed."""

    def test_rejected_post_submit_captcha_stops_at_three_attempts(self):
        from types import SimpleNamespace
        from modules.generic_submit import submit_ready
        with TemporaryDirectory() as tmp:
            job=load_jobs(url='https://example.test/jobs/bounded-captcha')[0]
            run=SubmitRun(Path(tmp)/'run',jobs=[job])
            self.addCleanup(run.close)
            ledger=ExternalApplicationLedger(Path(tmp)/'ledger.json')
            activated=[False];clock=[0.0]
            driver=Mock(current_url=job['url'],browser_backend='local')
            def script(source,*args):
                if source=='return window.__jobroboPrepare.documentId':return 'document'
                if 'finalActivated' in source:return {'activated':activated[0],'document':'document'}
                return True
            driver.execute_script.side_effect=script
            state=lambda:{'url':job['url'],'headings':['Staff Engineer'],'alerts':[], 'fields':[],
                          'challenge':activated[0]}
            browser=SimpleNamespace(driver=driver,allow_local=False,read=state,actions=[])
            report={'url':job['url'],'resolved_url':job['url'],'resume':{'pdf_sha256':'hash'},
                    'attachment':{'name':'optimized.pdf'},'questions':[],'review_binding_sha256':'binding'}
            def activate(**kw):activated[0]=True
            def sleep(seconds):clock[0]+=seconds
            with patch('modules.generic_submit.validate_final',return_value=(state(),{'element':Mock()},'')), \
                 patch('modules.generic_submit._activate',side_effect=activate) as click, \
                 patch('modules.generic_submit._accept_cookie_banner'), patch('modules.generic_submit._await_painted_challenge'), \
                 patch('modules.kernel_challenges.wait_for_challenge',return_value=True), \
                 patch('modules.captcha_solver.enabled',return_value=True), \
                 patch('modules.captcha_solver.solve',return_value={'status':'rejected','responses':1}) as solve, \
                 patch('modules.generic_submit.time.monotonic',side_effect=lambda:clock[0]), \
                 patch('modules.generic_submit.time.sleep',side_effect=sleep):
                result=submit_ready(browser,report,Path(tmp),job=job,run=run,ledger=ledger,
                    attempt_id='attempt',pause='never',confirmation_timeout=.03,poll_interval=.01)
            # Capped at three total attempts per job, never unbounded.
            self.assertEqual(solve.call_count,3)
            click.assert_called_once()
            self.assertEqual(result['status'],'submission_uncertain')
            self.assertEqual(run.rows()[0][1]['stage'],'captcha_unresolved_after_submit')
            self.assertTrue(ledger.protected(job['url']))
            self.assertLess(clock[0],5)

    def test_intercepted_final_submit_falls_back_to_a_dom_click(self):
        """A footer overlaying Submit must not fail the whole application."""
        from modules.generic_submit import _activate

        class Element:
            def __init__(self, error=None):
                self.error, self.clicks = error, 0
            def is_displayed(self): return True
            def click(self):
                self.clicks += 1
                if self.error: raise self.error

        class Driver:
            def __init__(self): self.scripts = []
            def execute_script(self, script, *a): self.scripts.append(script)

        driver = Driver()
        self.assertEqual(_activate(driver=driver, element=Element()), 'native')
        self.assertEqual(driver.scripts, [])

        class ElementClickInterceptedException(Exception):
            pass

        intercepted = Element(ElementClickInterceptedException('element click intercepted'))
        self.assertEqual(_activate(driver=driver, element=intercepted), 'script')
        self.assertEqual(driver.scripts, ['arguments[0].click()'])

    def test_other_click_errors_are_not_swallowed(self):
        from modules.generic_submit import _activate

        class Element:
            def is_displayed(self): return True
            def click(self): raise RuntimeError('stale element reference')

        class Driver:
            def execute_script(self, *a): raise AssertionError('should not fall back')

        with self.assertRaises(RuntimeError):
            _activate(driver=Driver(), element=Element())
@skipUnless(os.getenv('JOBROBO_BROWSER_TESTS')=='1','Opt-in local real Chrome submissions')
class SubmitBrowserTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config=self.root/'config';self.config.mkdir();(self.config/'search.py').write_text('max_applications_per_run = 50\n')
        self.pdf=self.root/'optimized.pdf';self.pdf.write_bytes(b'synthetic upload')
        self.ledger=self.root/'ledger.json';Handler.receipts=[];self.drivers=[]
        def factory():
            from selenium import webdriver
            opts=webdriver.ChromeOptions();opts.add_argument('--headless=new')
            d=webdriver.Chrome(options=opts);self.drivers.append(d);return d
        self.factory=factory
        self.services={'candidate':{'email':'test@example.test'},'question_config':{'unanswered_choice_policy':'first_option'},
            'resume_provider':lambda job,root:{'pdf':str(self.pdf),'pdf_sha256':digest(self.pdf),'job_id':'synthetic'},
            'ledger_path':self.ledger}
    def jobs(self,*paths):return load_jobs(url=self.base+paths[0],allow_local=True) if len(paths)==1 else sum((load_jobs(url=self.base+p,allow_local=True) for p in paths),[])

    def run_jobs(self,jobs,**kwargs):
        return run_submissions(jobs,run_dir=self.root/'run',config_dir=self.config,output_dir=self.root/'reports',
            services=self.services,driver_factory=self.factory,allow_local=True,confirmation_timeout=.7,**kwargs)
    def test_real_ajax_native_and_frame_submit_once(self):
        result=self.run_jobs(self.jobs('/job/a','/native/b','/frame/c'),pause='never')
        self.assertEqual(result['counts'],{'applied':3});self.assertEqual(len(Handler.receipts),3)
        self.assertEqual(len(json.loads((self.root/'run/applications.json').read_text())['records']),3)

    def test_borrowed_browser_confirms_keeps_uncertain_and_continues(self):
        from modules.submit_runner import ApplicationTab
        driver = self.factory()
        self.addCleanup(driver.quit)
        origin = driver.current_window_handle
        outcomes, handles = [], []
        for path in ('/job/borrowed-a', '/no-confirm/borrowed-b', '/native/borrowed-c'):
            driver.switch_to.new_window('tab')
            handle = driver.current_window_handle
            handles.append(handle)
            result = run_submissions(self.jobs(path), run_dir=self.root/'borrowed', config_dir=self.config,
                output_dir=self.root/'reports', services=self.services, allow_local=True, pause='never',
                ledger_path=self.ledger, application_tab=ApplicationTab(driver, handle), confirmation_timeout=.7)
            outcomes.append(result['jobs'][0]['status'])
            driver.switch_to.window(origin)
        self.assertEqual(outcomes, ['applied', 'submission_uncertain', 'applied'])
        self.assertEqual(len(Handler.receipts), 3)
        self.assertIn(origin, driver.window_handles)
        self.assertNotIn(handles[0], driver.window_handles)
        self.assertIn(handles[1], driver.window_handles)
        self.assertNotIn(handles[2], driver.window_handles)

    def test_borrowed_browser_continues_after_rejected_captcha(self):
        class ChallengedBrowser(SubmissionBrowser):
            def read(self):
                state=super().read()
                if '/no-confirm/borrowed-b' in state['url'] and '/receive/no-confirm/borrowed-b' in Handler.receipts:
                    state['challenge']=True
                return state
        with patch('modules.submit_runner.SubmissionBrowser',ChallengedBrowser), \
             patch('modules.captcha_solver.enabled',return_value=True), \
             patch('modules.captcha_solver.solve',return_value={'status':'rejected','responses':1}) as solve:
            self.test_borrowed_browser_confirms_keeps_uncertain_and_continues()
        self.assertEqual(solve.call_count,2)
    def test_repeated_fresh_runs_allow_same_posting_and_preserve_old_run(self):
        jobs=self.jobs('/job/a');jobs[0]['prior_status']='applied'
        old=ExternalApplicationLedger(self.ledger)
        old.record_aliases(ExternalApplicationResult('submitting',jobs[0]['url'],attempt_id='older-run'),[jobs[0]['url']],'older')
        history=self.ledger.read_bytes()
        first=self.run_jobs(jobs,pause='never')
        before={str(p.relative_to(first['run_dir'])):p.read_bytes() for p in Path(first['run_dir']).rglob('*') if p.is_file()}
        second=self.run_jobs(jobs,pause='never')
        self.assertEqual(first['counts'],{'applied':1});self.assertEqual(second['counts'],{'applied':1})
        self.assertNotEqual(first['run_id'],second['run_id']);self.assertNotEqual(first['run_dir'],second['run_dir'])
        self.assertEqual(len(Handler.receipts),2);self.assertEqual(self.ledger.read_bytes(),history)
        self.assertEqual(before,{str(p.relative_to(first['run_dir'])):p.read_bytes() for p in Path(first['run_dir']).rglob('*') if p.is_file()})
        self.assertNotEqual(first['options']['preparation_dir'],second['options']['preparation_dir'])
    def test_frame_alias_prevents_second_application(self):
        result=self.run_jobs(self.jobs('/frame/c','/job/c'),pause='never')
        self.assertEqual(result['counts'],{'applied':1,'duplicate':1})
        self.assertEqual(len(Handler.receipts),1)
    def test_portal_duplicate_is_recorded_and_next_job_continues(self):
        result=self.run_jobs(self.jobs('/portal-duplicate/a','/portal-duplicate-alert/b','/job/c'),pause='never')
        self.assertEqual(result['counts'],{'duplicate':2,'applied':1})
        self.assertEqual(result['jobs'][0]['stage'],'portal_duplicate')
        self.assertEqual(result['jobs'][1]['stage'],'portal_duplicate')
        self.assertEqual(len(Handler.receipts),3)
    def test_success_heading_without_activation_is_not_application(self):
        outer=self
        class Review:
            def __init__(self,*a):self.changed=False
            def poll(self,state,ready,reason):
                if ready and not self.changed:
                    self.changed=True
                    outer.drivers[-1].execute_script("document.querySelector('h1').textContent='Application submitted successfully'")
                elif self.changed:return 'stop'
            def close(self):pass
        result=self.run_jobs(self.jobs('/job/a'),pause='always',review_factory=Review)
        self.assertEqual(result['counts'],{'awaiting_review':1});self.assertEqual(Handler.receipts,[])
    def test_live_edit_disarms_manual_submit_until_revalidated(self):
        outer=self
        class Review:
            def __init__(self,*a):self.phase=0
            def poll(self,state,ready,reason):
                d=outer.drivers[-1]
                if ready and self.phase==0:
                    self.phase=1;d.find_element('name','email').clear();d.find_element('id','submit').click()
                    self.assert_no_activation(d)
                elif not ready and self.phase==1:
                    self.phase=2;d.find_element('name','email').send_keys('reviewed@example.test')
                elif ready and self.phase==2:return 'submit'
            def assert_no_activation(self,d):
                outer.assertFalse(d.execute_script('return window.__jobroboPrepare.finalActivated'))
                outer.assertEqual(Handler.receipts,[])
            def close(self):pass
        result=self.run_jobs(self.jobs('/job/a'),pause='always',review_factory=Review)
        self.assertEqual(result['counts'],{'applied':1});self.assertEqual(len(Handler.receipts),1)
    def test_changed_structured_jd_requires_new_preparation(self):
        outer=self
        class Review:
            def __init__(self,*a):self.changed=False
            def poll(self,state,ready,reason):
                d=outer.drivers[-1]
                if ready and not self.changed:
                    self.changed=True
                    d.execute_script("const s=document.querySelector('script[type=\"application/ld+json\"]');const j=JSON.parse(s.textContent);j.description='A different job description. '.repeat(20);s.textContent=JSON.stringify(j)")
                    d.find_element('id','submit').click()
                    outer.assertFalse(d.execute_script('return window.__jobroboPrepare.finalActivated'))
                elif self.changed:
                    outer.assertFalse(ready);outer.assertIn('Job description changed',reason)
                    return 'stop'
            def close(self):pass
        result=self.run_jobs(self.jobs('/job/a'),pause='always',review_factory=Review)
        self.assertEqual(result['counts'],{'awaiting_review':1});self.assertEqual(Handler.receipts,[])
    def test_manual_browser_click_advances_to_next_pause(self):
        calls=[]
        outer=self
        class Manual:
            def __init__(self,report,unknown):calls.append(report['url']);self.clicked=False
            def poll(self,state,ready,reason):
                if ready and not self.clicked:
                    self.clicked=True;outer.drivers[-1].find_element('id','submit').click()
            def close(self):pass
        result=self.run_jobs(self.jobs('/job/a','/job/b'),pause='always',review_factory=Manual)
        self.assertEqual(result['counts'],{'applied':2});self.assertEqual(len(calls),2);self.assertEqual(len(Handler.receipts),2)
    def test_unknown_only_pauses_default_choice_not_configured_email(self):
        calls=[]
        class Review:
            def __init__(self,report,unknown):calls.append(unknown)
            def poll(self,state,ready,reason):return 'submit'
            def close(self):pass
        result=self.run_jobs(self.jobs('/job/a','/choice/b'),pause='unknown',review_factory=Review)
        self.assertEqual(result['counts'],{'applied':2});self.assertEqual(len(calls),1)
    def test_stop_save_then_resume_and_duplicate_skip(self):
        class Stop:
            def __init__(self,*a):pass
            def poll(self,*a):return 'stop'
            def close(self):pass
        result=self.run_jobs(self.jobs('/job/a','/job/b'),pause='always',review_factory=Stop)
        self.assertEqual(len(Handler.receipts),0);self.assertEqual(result['counts'],{'awaiting_review':1,'pending':1})
        self.assertFalse(ExternalApplicationLedger(self.root/'run/applications-ledger.json').protected(self.base+'/job/a'))
        result=run_submissions(resume_dir=self.root/'run',pause='never',services=self.services,driver_factory=self.factory,allow_local=True,confirmation_timeout=.7)
        self.assertEqual(result['counts'],{'applied':2})
        result=run_submissions(resume_dir=self.root/'run',services=self.services,driver_factory=Mock(side_effect=AssertionError('duplicate browser')),allow_local=True)
        self.assertEqual(result['counts'],{'applied':2});self.assertEqual(len(Handler.receipts),2)
    def test_missing_confirmation_is_not_retried(self):
        result=self.run_jobs(self.jobs('/no-confirm/a','/job/b'),pause='never')
        self.assertEqual(result['counts'],{'submission_uncertain':1,'applied':1})
        self.assertEqual((self.root/'run/retry.txt').read_text(),'')
        self.assertEqual(len(Handler.receipts),2)
        driver=self.drivers[-1]
        uncertain=next(j for j in result['jobs'] if j['status']=='submission_uncertain')
        applied=next(j for j in result['jobs'] if j['status']=='applied')
        self.assertIn(uncertain['tab_handle'],driver.window_handles,'Uncertain employer page should stay open')
        self.assertNotIn(applied['tab_handle'],driver.window_handles,'Confirmed employer page should close')
        run_submissions(resume_dir=self.root/'run',services=self.services,driver_factory=Mock(side_effect=AssertionError('duplicate browser')),allow_local=True)
        self.assertEqual(len(Handler.receipts),2)
    def test_manual_completion_of_required_fact_then_submit(self):
        outer=self
        class Review:
            def __init__(self,*a):pass
            def poll(self,state,ready,reason):
                if not ready:
                    outer.drivers[-1].find_element('name','fact').send_keys('Supplied manually')
                else:return 'submit'
            def close(self):pass
        result=self.run_jobs(self.jobs('/required/a'),pause='unknown',review_factory=Review)
        self.assertEqual(result['counts'],{'applied':1});self.assertEqual(len(Handler.receipts),1)
    def test_pre_submit_failure_retries_via_export_not_main_resume(self):
        svc=self.services;svc['resume_provider']=Mock(side_effect=ValueError('fixture failure'))
        result=self.run_jobs(self.jobs('/job/a'),pause='never')
        self.assertEqual(result['counts'],{'failed_before_submit':1})
        self.assertIn(self.base+'/job/a',(self.root/'run/retry.txt').read_text())
        jobs=load_jobs([str(self.root/'run/retry.json')],allow_local=True)
        svc['resume_provider']=lambda job,root:{'pdf':str(self.pdf),'pdf_sha256':digest(self.pdf),'job_id':'synthetic'}
        result=run_submissions(jobs,run_dir=self.root/'retry-run',config_dir=self.config,output_dir=self.root/'reports',
            services=svc,driver_factory=self.factory,allow_local=True,pause='never',confirmation_timeout=.7)
        self.assertEqual(result['counts'],{'applied':1})

    def test_claim_write_failure_prevents_any_click(self):
        with patch.object(ExternalApplicationLedger,'record_aliases',side_effect=OSError('fixture disk failure')):
            result=self.run_jobs(self.jobs('/job/a'),pause='never')
        self.assertEqual(Handler.receipts,[])
        self.assertEqual(result['counts'],{'failed_before_submit':1})

    def test_run_checkpoint_failure_after_claim_is_protected(self):
        original=SubmitRun.update
        def update(run,job,**kwargs):
            if kwargs.get('status')=='submitting' and kwargs.get('stage')=='submitting':raise OSError('fixture checkpoint failure')
            return original(run,job,**kwargs)
        with patch.object(SubmitRun,'update',new=update):
            result=self.run_jobs(self.jobs('/job/a'),pause='never')
        self.assertEqual(Handler.receipts,[])
        self.assertEqual(result['counts'],{'submission_uncertain':1})
        self.assertTrue(ExternalApplicationLedger(self.root/'run/applications-ledger.json').protected(self.base+'/job/a'))

    def test_interrupted_preparation_resumes_unfinished_job(self):
        original=self.services['resume_provider'];self.services['resume_provider']=Mock(side_effect=KeyboardInterrupt)
        with self.assertRaises(KeyboardInterrupt):self.run_jobs(self.jobs('/job/a'),pause='never')
        self.assertEqual(status(self.root/'run')['counts'],{'interrupted_before_submit':1})
        self.services['resume_provider']=original
        result=run_submissions(resume_dir=self.root/'run',services=self.services,driver_factory=self.factory,allow_local=True,confirmation_timeout=.7)
        self.assertEqual(result['counts'],{'applied':1});self.assertEqual(len(Handler.receipts),1)

    def test_manual_click_then_review_crash_never_clicks_again(self):
        outer=self
        class Crash:
            def __init__(self,*a):pass
            def poll(self,state,ready,reason):
                if ready:
                    outer.drivers[-1].find_element('id','submit').click()
                    raise RuntimeError('fixture review interruption after click')
            def close(self):pass
        result=self.run_jobs(self.jobs('/job/a'),pause='always',review_factory=Crash)
        self.assertEqual(result['counts'],{'submission_uncertain':1});self.assertEqual(len(Handler.receipts),1)
        run_submissions(resume_dir=self.root/'run',services=self.services,driver_factory=Mock(side_effect=AssertionError('duplicate browser')),allow_local=True)
        self.assertEqual(len(Handler.receipts),1)

    def test_global_cap_survives_resume(self):
        result=self.run_jobs(self.jobs('/job/a','/job/b'),pause='never',max_applications=1)
        self.assertEqual(result['counts'],{'applied':1,'pending':1})
        result=run_submissions(resume_dir=self.root/'run',services=self.services,driver_factory=self.factory,allow_local=True,confirmation_timeout=.7)
        self.assertEqual(result['counts'],{'applied':1,'pending':1});self.assertEqual(len(Handler.receipts),1)
