"""LinkedIn/direct-submit integration contracts; no live employer requests."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from modules.external_apply import ExternalApplicationLedger, ExternalApplicationResult
from modules.generic_inputs import load_jobs
from modules.linkedin_external_submit import finish_browser, import_submission_holds, open_employer_tab, submit_employer_tab, reconcile_confirmed_attempt
from modules.search_planner import application_mode, filters_snapshot
from modules.submit_runner import ApplicationTab, run_submissions


class Tabs:
    def __init__(self):
        self.window_handles=['linkedin','employer','unrelated']
        self.current_window_handle='employer'
        self.current_url='https://example.test/jobs/1'
        self.switch_to=SimpleNamespace(window=self.window, new_window=Mock())
        self.quit=Mock();self.service=SimpleNamespace(stop=Mock())
        self.set_window_size=Mock();self.set_page_load_timeout=Mock()
    def window(self,handle):self.current_window_handle=handle
    def close(self):self.window_handles.remove(self.current_window_handle)


class BorrowedSubmissionTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.config=self.root/'config';self.config.mkdir()
        (self.config/'search.py').write_text('max_applications_per_run=50\n')
        self.driver=Tabs();self.events=[]
        self.services={'candidate':{},'question_config':{},'resume_provider':Mock(return_value={})}
        self.ledger=self.root/'shared.json'

    def run_job(self,job,preparer,**kwargs):
        return run_submissions([job],run_dir=self.root/'attempt',config_dir=self.config,
            services=self.services,pause='never',ledger_path=self.ledger,
            application_tab=ApplicationTab(self.driver,'employer',lambda j,s:self.events.append(s)),
            preparer=preparer,**kwargs)

    def test_confirmed_closes_only_employer_and_checkpoints_before_return(self):
        job=load_jobs(url='https://example.test/jobs/1')[0]
        def prepare(url,**kw):
            claim=ExternalApplicationResult('applied',url,attempt_id=kw['input_metadata']['attempt_id'],submitted_at='2026-10-30T00:00:00+00:00')
            kw['ledger'].record_aliases(claim,[url],job['id'])
            return {'status':'applied','output_dir':str(self.root/'report'),'resume':{}}
        result=self.run_job(job,prepare)
        self.assertEqual(result['counts'],{'applied':1})
        self.assertEqual(self.driver.window_handles,['linkedin','unrelated'])
        self.driver.switch_to.new_window.assert_not_called();self.driver.quit.assert_not_called()
        self.driver.service.stop.assert_not_called()
        self.assertTrue(any(s['status']=='applied' for s in self.events))
        self.assertTrue(all(s['direct_run_id']==result['run_id'] for s in self.events))
        self.assertTrue(all(s['direct_run_dir']==result['run_dir'] for s in self.events))
        self.assertTrue(ExternalApplicationLedger(self.ledger).protected(job['url']))
        self.assertEqual(result['options']['execution_scope'],'linkedin_handoff')

    def test_failure_keeps_tab_browser_and_next_job_can_run(self):
        job=load_jobs(url='https://example.test/jobs/1')[0]
        result=self.run_job(job,Mock(side_effect=RuntimeError('fixture failure')))
        self.assertEqual(result['counts'],{'failed_before_submit':1})
        self.assertIn('employer',self.driver.window_handles)
        self.driver.quit.assert_not_called();self.driver.service.stop.assert_not_called()
        next_job=load_jobs(url='https://example.test/jobs/2')[0]
        prepare=Mock(return_value={'status':'blocked','blockers':['fixture validation'],'output_dir':str(self.root/'report'),'resume':{}})
        result=self.run_job(next_job,prepare)
        prepare.assert_called_once();self.assertEqual(result['counts'],{'blocked':1})

    def test_prior_uncertain_blocks_replay_and_keeps_tab(self):
        job=load_jobs(url='https://example.test/jobs/1')[0]
        ExternalApplicationLedger(self.ledger).record_aliases(ExternalApplicationResult('submitting',job['url']),[job['url']],job['id'])
        prepare=Mock();result=self.run_job(job,prepare)
        prepare.assert_not_called();self.assertEqual(result['counts'],{'submission_uncertain':1})
        self.assertTrue(any(s['status']=='submission_uncertain' for s in self.events))
        self.assertIn('employer',self.driver.window_handles)

    def test_borrowed_review_handoff_never_waits_or_owns_browser_shutdown(self):
        job=load_jobs(url='https://example.test/jobs/1')[0]
        monitor=Mock()
        def factory(driver,run,ledger,**kw):
            monitor.handoff.side_effect=lambda *a,**k:run.update(job,status='awaiting_manual_submit',stage='review')
            return monitor
        def prepare(url,**kw):
            report={'status':'awaiting_review','manual_handoff':True,'output_dir':str(self.root/'report'),'resume':{}}
            kw['on_ready'](Mock(),report,self.root)
            return report
        result=run_submissions([job],run_dir=self.root/'review',config_dir=self.config,services=self.services,
            pause='always',ledger_path=self.ledger,application_tab=ApplicationTab(self.driver,'employer'),
            preparer=prepare,tab_monitor_factory=factory)
        self.assertEqual(result['counts'],{'awaiting_manual_submit':1})
        monitor.wait.assert_not_called();self.driver.quit.assert_not_called()
        self.assertIn('employer',self.driver.window_handles)

    def test_shared_history_import_protects_standalone_claims(self):
        history=self.root/'history'/'run';history.mkdir(parents=True)
        url='https://example.test/jobs/1'
        ExternalApplicationLedger(history/'applications-ledger.json').record_aliases(ExternalApplicationResult('applied',url),[url],'direct-job')
        import_submission_holds(self.ledger,history.parent)
        self.assertTrue(ExternalApplicationLedger(self.ledger).protected(url))

    def test_submit_interruption_preserves_report_pointer_before_return(self):
        job=load_jobs(url='https://example.test/jobs/interrupted')[0]
        report_root=self.root/'report';report_root.mkdir()
        report={'status':'ready','url':job['url'],'resolved_url':job['url'],'resume':{'pdf_sha256':'hash'}}
        def prepare(url,**kw):
            try:kw['on_ready'](Mock(),report,report_root)
            finally:(report_root/'report.json').write_text(json.dumps(report))
        def interrupted(browser,report,root,**kw):
            claim=ExternalApplicationResult('submitting',job['url'],attempt_id=kw['attempt_id'])
            kw['ledger'].record_aliases(claim,[job['url']],job['id'])
            kw['run'].update(job,status='submitting',stage='waiting_for_confirmation')
            raise KeyboardInterrupt()
        with patch('modules.submit_runner.submit_ready',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
            self.run_job(job,prepare)
        state=json.loads((self.root/'attempt'/'progress.json').read_text())['jobs'][0]
        self.assertEqual(state['status'],'submission_uncertain')
        self.assertEqual(state['preparation_report'],str(report_root/'report.json'))
        self.assertTrue(Path(state['preparation_report']).is_file())
        self.assertTrue(ExternalApplicationLedger(self.ledger).protected(job['url']))
        self.driver.quit.assert_not_called()

    def test_adapter_uses_exact_shared_engine_options_and_profile_loader(self):
        result={'run_id':'direct-run','run_dir':str(self.root),'jobs':[{'status':'failed_before_submit','reason':'fixture','retryable':True}]}
        with patch('modules.submit_runner.run_submissions',return_value=result) as runner:
            outcome=submit_employer_tab(self.driver,'employer','https://example.test/jobs/1',job_id='123',title='FDE',company='Example',description='Build systems',
                state_dir=self.root/'search_runs',provenance={'Search Run ID':'search-run'},checkpoint=Mock())
        args=runner.call_args
        self.assertEqual(args.kwargs['pause'],'never');self.assertTrue(args.kwargs['captcha_solver'])
        self.assertEqual(args.kwargs['workers'],1)
        self.assertIs(args.kwargs['application_tab'].driver,self.driver)
        self.assertEqual(args.args[0][0]['provenance']['linkedin_id'],'123')
        self.assertEqual(outcome.direct_run_id,'direct-run');self.assertEqual(outcome.status,'failed')

    def test_finish_retains_unresolved_and_quits_when_clear(self):
        self.assertTrue(finish_browser(self.driver,{'employer'}))
        self.driver.service.stop.assert_called_once();self.driver.quit.assert_not_called()
        other=Tabs();self.assertFalse(finish_browser(other,{'closed'}));other.quit.assert_called_once()


class ApplicationModes(TestCase):
    def test_explicit_modes_override_legacy_and_snapshot(self):
        for mode in ('external_only','both','easy_apply_only'):
            snapshot=filters_snapshot({'application_mode':mode,'easy_apply_only':True})
            self.assertEqual(snapshot['intent']['easy_apply_only'],mode=='easy_apply_only')
        self.assertEqual(application_mode({'easy_apply_only':True}),'easy_apply_only')
        self.assertEqual(application_mode({'easy_apply_only':False}),'both')
        with self.assertRaises(ValueError):application_mode({'application_mode':'unknown'})


class EmployerReconciliationTests(TestCase):
    def setUp(self):
        from test_search_runner import spec
        from modules.search_state import SearchManifest
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.spec=spec('parent')
        self.manifest=SearchManifest.create(self.root/'search_runs',[self.spec])
        self.manifest.record_job(self.spec,'123','submitting','Employer submission awaiting confirmation')
        self.parent=self.manifest.query('parent')['jobs']['123']
        self.parent['external_application']={'direct_run_dir':str(self.root),'direct_run_id':'direct',
            'attempt_id':'attempt','application_link':'https://example.test/jobs/1','status':'submitting'}
        self.proof={'schema':'direct-submit-progress-v1','run_id':'direct','jobs':[{
            'id':'linkedin:123','attempt_id':'attempt','url':'https://example.test/jobs/1','status':'applied'}]}

    def test_matching_confirmation_updates_parent_without_counting_a_new_application(self):
        from modules.application_budget import ApplicationBudget
        (self.root/'progress.json').write_text(json.dumps(self.proof))
        self.assertTrue(reconcile_confirmed_attempt(self.manifest,self.spec,'123'))
        parent=self.manifest.query('parent')['jobs']['123']
        self.assertEqual(parent['status'],'applied')
        self.assertEqual(parent['external_application']['direct_run_id'],'direct')
        budget=ApplicationBudget(3)
        self.assertFalse(budget.stop_if_reached(self.manifest))
        self.assertEqual(budget.count,0)

    def test_other_run_attempt_posting_or_uncertain_state_cannot_confirm_parent(self):
        from copy import deepcopy
        for changes in ({'attempt_id':'other'},{'url':'https://example.test/jobs/2'},{'status':'submission_uncertain'}):
            proof=deepcopy(self.proof);proof['jobs'][0].update(changes)
            (self.root/'progress.json').write_text(json.dumps(proof))
            self.assertFalse(reconcile_confirmed_attempt(self.manifest,self.spec,'123'))
        proof=deepcopy(self.proof);proof['run_id']='other'
        (self.root/'progress.json').write_text(json.dumps(proof))
        self.assertFalse(reconcile_confirmed_attempt(self.manifest,self.spec,'123'))
        self.assertEqual(self.parent['status'],'submitting')


class ExternalHandoffTests(TestCase):
    def driver(self,same_tab=False):
        driver=Tabs();driver.window_handles=['linkedin','unrelated'];driver.current_window_handle='linkedin'
        driver.current_url='https://www.linkedin.com/jobs/search-results/?currentJobId=123'
        original=driver.current_url
        urls={'linkedin':original,'unrelated':'https://unrelated.test/'}
        def window(handle):driver.current_window_handle=handle;driver.current_url=urls[handle]
        def click():
            if same_tab:urls['linkedin']='https://example.test/jobs/1'
            else:driver.window_handles.insert(1,'new-employer');urls['new-employer']='https://example.test/jobs/1'
        def new(_):driver.window_handles.append('copied-employer');urls['copied-employer']='about:blank';window('copied-employer')
        def get(url):urls[driver.current_window_handle]=url;driver.current_url=url
        driver.switch_to=SimpleNamespace(window=window,new_window=Mock(side_effect=new));driver.get=Mock(side_effect=get)
        button=Mock(id='apply',text='Apply',is_displayed=lambda:True,is_enabled=lambda:True,get_attribute=lambda _: 'Apply on company website',click=click)
        root=Mock();root.find_elements.return_value=[button];driver.execute_script=Mock()
        return driver,root,original

    def test_new_tab_ignores_preexisting_unrelated_tab(self):
        driver,root,_=self.driver()
        with patch('modules.linkedin_job_details.modern_details_root',return_value=root):
            handle,url=open_employer_tab(driver,'123',timeout=.1)
        self.assertEqual(handle,'new-employer');self.assertEqual(url,'https://example.test/jobs/1')
        driver.switch_to.new_window.assert_not_called()

    def test_same_tab_restores_search_and_copies_employer(self):
        driver,root,original=self.driver(True)
        with patch('modules.linkedin_job_details.modern_details_root',return_value=root):
            handle,url=open_employer_tab(driver,'123',timeout=.1)
        self.assertEqual(handle,'copied-employer');self.assertEqual(driver.current_window_handle,handle)
        driver.switch_to.window('linkedin');self.assertEqual(driver.current_url,original)
