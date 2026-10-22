"""Editable prompt loading and actual shared-adapter dispatch, without network."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch

from modules import resume_all_bullets as m


class GenerationPromptTest(unittest.TestCase):
    def test_prompt_is_packaged_and_resolved_from_app_resources(self):
        import ast,sys
        repository=Path(m.__file__).resolve().parent.parent
        tree=ast.parse((repository/'setup.py').read_text())
        options=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
            and any(isinstance(target,ast.Name) and target.id=='OPTIONS' for target in node.targets))
        self.assertIn(('config/prompts',['config/prompts/resume_bullets.txt']),options['resources'])
        self.assertIn(('config',['config/resume_company_context.json']),options['resources'])
        with TemporaryDirectory() as tmp:
            contents=Path(tmp)/'JobRobo.app/Contents';resource=contents/'Resources/config/prompts/resume_bullets.txt'
            resource.parent.mkdir(parents=True);resource.write_text('Packaged user prompt\n')
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',str(contents/'MacOS/JobRobo')):
                self.assertEqual(m.load_bullet_prompt(),'Packaged user prompt\n')

    def test_prompt_loader_preserves_edited_text_and_fails_on_missing_or_empty(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'prompt.txt'
            text='User-edited JD-first prompt\n\nKeep UTF-8: résumé → role.\n'
            path.write_text(text,encoding='utf-8')
            self.assertEqual(m.load_bullet_prompt(path),text)
            path.write_text(' \n',encoding='utf-8')
            with self.assertRaises(ValueError):m.load_bullet_prompt(path)
            with self.assertRaises(FileNotFoundError):m.load_bullet_prompt(path.with_name('missing.txt'))

    def test_shared_adapter_sends_exact_pinned_prompt_with_complete_jd(self):
        from modules.ai.resume_optimizer import run_resume_optimization
        from test_resume_all_bullets import inv
        inventory=inv(1,1);group=inventory['groups'][0]
        jd='Complete target JD: Python APIs and production reliability.'
        payload=m.compact_payload(inventory,jd,'Engineer','review_draft',group,group['bullets'])
        optimizer=Mock();marker='Exact edited prompt\nJD alignment first.\n'
        def exercise(*args,provider,**kwargs):
            provider('bullets',payload,7)
        with patch.object(m,'SYSTEM',marker),patch.object(m,'run_all_bullets',side_effect=exercise):
            run_resume_optimization(jd,'source.docx','unit-job','Engineer',
                rewrite_all_bullets=True,optimizer_instance=optimizer,
                runtime_config_override={'optimization_mode':'full','rewrite_all_bullets':True},
                content_policy='review_draft')
        call=optimizer.client.with_options.return_value.chat.completions.create.call_args
        self.assertEqual(call.kwargs['messages'][0],{'role':'system','content':marker})
        import json
        self.assertEqual(json.loads(call.kwargs['messages'][1]['content'])['job_description'],jd)
        self.assertEqual(optimizer.client.with_options.call_args.kwargs,{'timeout':7,'max_retries':0})

    def test_review_payload_follows_jd_first_selection_and_alternative_order(self):
        from test_resume_all_bullets import inv
        inventory=inv(1,1);group=inventory['groups'][0]
        payload=m.compact_payload(inventory,'Python API engineer','Engineer','review_draft',group,group['bullets'])
        bullet=payload['requested_bullets'][0]
        self.assertNotIn('source_reordering_reference',bullet)
        self.assertNotIn('source_passive_reference',bullet)
        self.assertNotIn('protected_source_terms',bullet)
        self.assertIn('JD-first',payload['acceptance_criteria']['alternatives'])
        self.assertIn('engineering-first',payload['acceptance_criteria']['alternatives'])
        self.assertIn('impact-first',payload['acceptance_criteria']['alternatives'])
        self.assertFalse(payload['fact_policy']['invented_claims_allowed'])
        grounded=m.compact_payload(inventory,'Python','Engineer','grounded',group,group['bullets'])
        self.assertIn('protected_source_terms',grounded['requested_bullets'][0])


if __name__=='__main__':unittest.main()
