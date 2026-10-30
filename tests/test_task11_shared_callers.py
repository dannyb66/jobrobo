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

    def test_hosted_strict_failure_does_not_reach_form_or_source_upload(self):
        from modules.external_apply import ExternalApplicationResult
        for failure in (None,RuntimeError('Synthetic failure')):
            with self.subTest(failure=type(failure).__name__),TemporaryDirectory() as temp:
                root=Path(temp);source=root/'source.docx';source.write_bytes(b'synthetic')
                source.with_suffix('.pdf').write_bytes(b'synthetic')
                optimize=Mock(side_effect=failure) if isinstance(failure,Exception) else Mock(return_value=None)
                ns={'search_profile':SimpleNamespace(search_state_dir=str(root/'state')),'default_resume_docx_path':str(source),'default_resume_path':str(source.with_suffix('.pdf')),'use_AI_for_resume':True,'run_resume_optimization':optimize,'print_lg':Mock(),'first_name':'Danny','last_name':'Basavaraju','full_name':'Danny Basavaraju','active_search':None,'driver':Mock(),'checkpoint_external_application':Mock()}
                extract_functions(ns,'prepare_external_application')
                with patch('modules.config_loader.load_runtime_config',return_value={'expected_page_count':2,'rewrite_all_bullets':True}),patch('modules.external_apply.ExternalApplicationLedger') as ledger,patch('modules.ai.resume_optimizer.ResumeOptimizer.verify_format',return_value={'passed':True}),patch('modules.external_questions.load_question_config',return_value={}),patch('modules.external_questions.make_local_ai_answerer',return_value=None),patch('modules.external_apply.apply_hosted_application',return_value=ExternalApplicationResult('awaiting_review','https://example.test/apply')) as hosted:
                    ledger.return_value.protected.return_value=False
                    result=ns['prepare_external_application']('https://example.test/apply','job','Engineer','Exact JD','Example')
                self.assertEqual(result.status,'manual_handoff')
                self.assertIn('fallback is disabled',result.reason)
                hosted.assert_not_called()
                ns['checkpoint_external_application'].assert_not_called()

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
