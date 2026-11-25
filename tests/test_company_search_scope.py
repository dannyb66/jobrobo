import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from modules.company_search_scope import load_scope, expand_specs, employer_allowed
from modules.search_planner import SearchSpec
from modules.search_state import SearchManifest, plan_fingerprint


def base():
    return SearchSpec('manual:ai', 'Find AI Engineer roles.', 'manual', 'ai', 'test', '1', {}, None, 'AI Engineer')


class CompanyScopeTests(unittest.TestCase):
    def test_catalog_and_partial_batch(self):
        scope=load_scope('data/company_names.json', strict=True)
        specs=expand_specs([base()],scope)
        self.assertEqual(len(specs),(len(scope['companies'])+9)//10)
        self.assertEqual(len(specs),30)
        self.assertEqual(specs[-1].company_scope['batch_names'],[c['name'] for c in scope['companies'][290:]])
        for s in specs:
            for n in s.company_scope['batch_names']:
                self.assertIn(n,s.query_text)
                self.assertIn(n.replace('"',' '),s.classic_query)

    def test_inputs_aliases_union_and_normalization(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'companies.json'
            p.write_text(json.dumps({'companies':[{'name':'ByteDance','aliases':['Byte Dance']},'Rive']}))
            scope=load_scope(p,['BYTEDANCE','Griting'],batch_size=2,strict=True)
            self.assertEqual([c['name'] for c in scope['companies']],['ByteDance','Rive','Griting'])
            s=expand_specs([base()],scope)[0]
            for name in ('Byte Dance','BYTEDANCE Inc.',' Rive ','Griting'):
                self.assertTrue(employer_allowed(s,name))
            for name in ('ByteDance Staffing','River','TikTok','',None):
                self.assertFalse(employer_allowed(s,name))
            p.write_text('["Rive", "ByteDance"]')
            self.assertEqual(len(load_scope(p)['companies']),2)

    def test_invalid_inputs(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'bad.json'
            for text in ('{','[]','{}','null','[null]','[""]','{"companies":[{"name":"X","aliases":"bad"}]}','["X\\nY"]'):
                p.write_text(text)
                with self.subTest(text=text),self.assertRaises(ValueError):load_scope(p)
            with self.assertRaises(OSError):load_scope(Path(d)/'missing')
        for size in (0,-1,True):
            with self.assertRaises(ValueError):load_scope(companies=['X'],batch_size=size)
        with self.assertRaises(ValueError):load_scope()

    def test_ambiguous_alias_rejected_and_prompt_only_accepts(self):
        scope=load_scope(companies=['A','B'],strict=True)
        scope['companies'][0]['aliases']=['Shared']
        scope['companies'][1]['aliases']=['Shared']
        self.assertFalse(employer_allowed(expand_specs([base()],scope)[0],'Shared'))
        scope['strict']=False
        self.assertTrue(employer_allowed(expand_specs([base()],scope)[0],None))

    def test_scope_fingerprint_roundtrip_and_legacy_compatibility(self):
        original=base()
        self.assertNotIn('company_scope',original.to_dict())
        self.assertIs(expand_specs([original],None)[0],original)
        scope=load_scope(companies=['A','B'],strict=True,batch_size=1)
        specs=expand_specs([original],scope);fingerprint=plan_fingerprint(specs)
        for key,value in (('strict',False),('batch_size',2),('companies',[{'name':'C','aliases':[]}])):
            modified={**scope,key:value}
            self.assertNotEqual(fingerprint,plan_fingerprint(expand_specs([original],modified)))
        with TemporaryDirectory() as d:
            manifest=SearchManifest.create(d,specs)
            manifest.record_job(specs[0],'1','applied','Confirmed')
            restored=SearchManifest.find_resume(d,manifest.data['configuration_id'])
            self.assertEqual(restored.queries()[0].company_scope,specs[0].company_scope)
            self.assertIn('1',SearchManifest.applied_ids(d))

    def test_cli_validation_and_restores_scope(self):
        import runAiBot as bot
        with patch.object(bot,'run_bot') as run:
            for argv in (['--company','A'],['--configured-search-and-apply','--strict-company-filter'],['--configured-search-and-apply','--company','A','--company-batch-size','0']):
                with self.assertRaises(SystemExit):bot.cli_main(argv)
            run.assert_not_called()
            previous=getattr(bot,'company_search_scope',None)
            def inspect():
                self.assertEqual(bot.company_search_scope['batch_size'],2)
                self.assertEqual(len(bot.company_search_scope['companies']),2)
                self.assertTrue(bot.company_search_scope['strict'])
                self.assertEqual(bot.single_search_run,2)
            run.side_effect=inspect
            self.assertEqual(bot.cli_main(['--configured-search-and-apply','--single-search','2','--company','A','--company','B','--company-batch-size','2','--strict-company-filter']),0)
            self.assertEqual(getattr(bot,'company_search_scope',None),previous)
            run.side_effect=RuntimeError('synthetic')
            with self.assertRaises(RuntimeError):bot.cli_main(['--configured-search-and-apply','--company','C'])
            self.assertEqual(getattr(bot,'company_search_scope',None),previous)

    def test_runner_strict_gate_precedes_preparation(self):
        from test_search_runner import SearchRunnerTests, spec
        case=SearchRunnerTests();case.setUp()
        try:
            s=expand_specs([spec('scoped')],load_scope(companies=['Never Matches'],strict=True))[0]
            manifest=case.manifest([s],{s.query_id:[['1','2']]})
            prepare=case.namespace['open_easy_apply']=Mock()
            external=case.namespace['external_apply']=Mock()
            case.execute(manifest)
            prepare.assert_not_called();external.assert_not_called()
            self.assertEqual(manifest.query(s.query_id)['jobs']['1']['status'],'skipped')
            self.assertIn('outside CLI company list',manifest.query(s.query_id)['jobs']['1']['reason'])
            self.assertNotIn('Submit application',case.events)
        finally:case.doCleanups()

    def test_selected_base_prompt_expands_after_selection(self):
        import runAiBot as bot
        from types import SimpleNamespace
        with TemporaryDirectory() as d:
            profile=SimpleNamespace(search_state_dir=d,resume_search_enabled=True,ai_query_refinement_enabled=False)
            scope=load_scope(companies=['A','B','C'],batch_size=2,strict=True)
            second=base();second.query_id='manual:second';second.query_text='Find second role';second.classic_query='second'
            with patch.object(bot,'search_profile',profile),patch.object(bot,'single_search_run',2,create=True), \
                 patch.object(bot,'company_search_scope',scope,create=True),patch.object(bot,'randomize_search_order',False,create=True), \
                 patch.object(bot,'print_lg',Mock(),create=True),patch.object(bot,'execute_search_plan') as execute:
                manifest=bot.apply_to_jobs([],prepared_specs=[base(),second],fresh_manifest=True)
                self.assertEqual(len(manifest.data['queries']),2)
                for q in manifest.data['queries']:
                    self.assertTrue(q['spec']['query_text'].startswith('Find second role'))
                    self.assertIsNone(q['spec']['quota'])
                execute.assert_called_once()

    def test_cli_file_and_inline_scope(self):
        import runAiBot as bot
        with TemporaryDirectory() as d:
            path=Path(d)/'names.json'
            path.write_text('{"companies":[{"name":"ByteDance","aliases":["Byte Dance"]},"Rive"]}')
            def inspect():
                self.assertEqual([c['name'] for c in bot.company_search_scope['companies']],['ByteDance','Rive','Griting'])
                self.assertEqual(bot.company_search_scope['companies'][0]['aliases'],['Byte Dance'])
            with patch.object(bot,'run_bot',side_effect=inspect):
                bot.cli_main(['--configured-search-and-apply','--companies-file',str(path),
                    '--company','BYTEDANCE','--company','Griting','--prepare-only','--limit','1'])

    def test_company_batches_share_application_budget(self):
        from test_search_runner import SearchRunnerTests, spec
        from modules.application_budget import ApplicationBudget
        case=SearchRunnerTests();case.setUp()
        try:
            specs=expand_specs([spec('batches',quota=10)],load_scope(companies=['A','B','C'],batch_size=1))
            manifest=case.manifest(specs,{s.query_id:[[str(i)]] for i,s in enumerate(specs,1)})
            budget=ApplicationBudget(2)
            case.execute(manifest,application_budget=budget)
            self.assertEqual(budget.count,2)
            self.assertEqual(len(case.visited),2)
            self.assertEqual(case.events.count('Submit application'),2)
        finally:case.doCleanups()

    def test_preparation_batches_never_submit(self):
        from test_search_runner import SearchRunnerTests, spec
        case=SearchRunnerTests();case.setUp()
        try:
            specs=expand_specs([spec('prep',quota=10)],load_scope(companies=['A','B','C'],batch_size=1))
            manifest=case.manifest(specs,{s.query_id:[[str(i)]] for i,s in enumerate(specs,1)})
            with patch('modules.linkedin_form_cleanup.discard_application'):
                case.namespace['execute_search_plan'](manifest,prepare_only=True,preparation_limit=2)
            self.assertNotIn('Submit application',case.events)
            self.assertFalse(any(j['status'] in ('applied','submitting') for q in manifest.data['queries'] for j in q['jobs'].values()))
            self.assertLessEqual(len(case.visited),2)
        finally:case.doCleanups()

    def test_strict_alias_match_reaches_enabled_submit_in_prepare_only(self):
        from test_search_runner import SearchRunnerTests, spec
        case=SearchRunnerTests();case.setUp()
        try:
            scope=load_scope(companies=['Canonical Employer'],strict=True)
            scope['companies'][0]['aliases']=['Example']
            s=expand_specs([spec('accepted')],scope)[0]
            manifest=case.manifest([s],{s.query_id:[['1']]})
            with patch('modules.linkedin_form_cleanup.discard_application'):
                case.namespace['execute_search_plan'](manifest,prepare_only=True,preparation_limit=1)
            report=json.loads(next((case.directory/'form_validations').glob('*.json')).read_text())
            self.assertEqual((report['attempted'],report['ready'],report['failed']),(1,1,0))
            self.assertTrue(report['records'][0]['submit_enabled'])
            self.assertTrue(report['submission_disabled'])
            self.assertEqual(manifest.query(s.query_id)['jobs']['1']['status'],'prepared')
            self.assertNotIn('Submit application',case.events)
            self.assertFalse((case.directory/'applied.csv').exists())
        finally:case.doCleanups()
