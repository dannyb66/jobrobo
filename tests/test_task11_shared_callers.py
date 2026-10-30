"""Synthetic caller integration; no live browser, resume uploads or provider calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock,patch
from test_search_runner import extract_functions

class SharedCallerTests(unittest.TestCase):
    def test_cli_override_reaches_selected_local_generator(self):
        import direct_apply
        import modules.direct_careers_apply as module
        with patch.object(module,'literal_config',return_value={}),patch.object(module,'local_candidate',return_value={}),patch.object(module,'summarize',return_value={}),patch.object(module,'run_queue',return_value={}) as run,patch.object(module,'generate_local_resume',return_value='synthetic.pdf') as generate,patch('modules.external_questions.load_question_config',return_value={}):
            status=direct_apply.main(['run','--queue','synthetic.json','--execute','--generate-resume','--role','role:1','--rewrite-all-bullets','--rewrite-experience-concurrency','3'])
            self.assertEqual(status,0)
            callback=run.call_args.kwargs['generate']
            self.assertEqual(callback(job_description='Exact JD',job_id='job'),'synthetic.pdf')
            generate.assert_called_once_with(job_description='Exact JD',job_id='job',rewrite_all_bullets=True,rewrite_experience_concurrency=3)

    def test_hosted_route_uses_shared_submit_engine_without_a_second_optimizer(self):
        from modules.external_apply import ExternalApplicationResult
        ns={'search_profile':SimpleNamespace(search_state_dir='logs/search_runs'),
            'driver':SimpleNamespace(current_window_handle='employer'),
            'active_manifest':None,'active_search':None,'search_metadata':Mock(return_value={'Search Run ID':'search-run'}),
            'checkpoint_job':Mock(),'run_resume_optimization':Mock(),
            'external_apply_pause_before_submit':'never','external_apply_captcha_solver':True}
        extract_functions(ns,'prepare_external_application')
        outcome=ExternalApplicationResult('failed','https://example.test/apply',
            reason='No verified optimized resume available',direct_status='blocked')
        with patch('modules.linkedin_external_submit.submit_employer_tab',return_value=outcome) as submit, patch('modules.external_apply.apply_hosted_application') as legacy:
            result=ns['prepare_external_application']('https://example.test/apply','123','Engineer','Exact JD','Example')
        self.assertIs(result,outcome)
        self.assertEqual(submit.call_args.args,(ns['driver'],'employer','https://example.test/apply'))
        self.assertEqual(submit.call_args.kwargs['description'],'Exact JD')
        self.assertEqual(submit.call_args.kwargs['pause'],'never')
        self.assertTrue(submit.call_args.kwargs['captcha_solver'])
        submit.call_args.kwargs['checkpoint']('submitting','pending employer receipt')
        ns['checkpoint_job'].assert_called_once_with('123','submitting','pending employer receipt')
        ns['run_resume_optimization'].assert_not_called()
        legacy.assert_not_called()

    def test_strict_generated_reports_need_independent_attachment_verification(self):
        import test_direct_careers_apply as harness
        runner=harness.DirectQueueTests(methodName='test_generated_planning_is_zero_api_and_contains_no_fake_selected_pdf')
        runner.setUp();self.addCleanup(runner.doCleanups)
        runner.plan(resume_mode='generated')
        def generate(**kwargs):
            output=runner.generated_output(**kwargs)
            report=Path(output).with_suffix('.match_report.json')
            data=json.loads(report.read_text());data.update(status='complete',rewrite_all_bullets=True,strict_attachment_eligible=True)
            report.write_text(json.dumps(data))
            return output
        with patch('modules.resume_all_bullets.verify_strict_attachment',return_value=False) as verify:
            queue=runner.run_queue(generate_resumes=True,selected_role_ids=['role:1'],generate=generate)
        verify.assert_called_once()
        self.assertEqual(queue['records'][0]['status'],'manual_handoff')
        self.assertIsNone(queue['records'][0]['resume']['pdf'])
        runner.browser.get.assert_not_called()
