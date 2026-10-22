"""Independent-run contracts; no network, credentials or employer actions."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from modules.external_apply import ExternalApplicationLedger, ExternalApplicationResult
from modules.generic_inputs import load_jobs
from modules.job_pipeline.store import PipelineStore
from modules.submit_runner import run_submissions
from modules.submit_state import SubmitRun


class IndependentRunsTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.config=self.root/'config';self.config.mkdir()
        (self.config/'search.py').write_text('max_applications_per_run = 50\n')
        self.history=self.root/'shared-ledger.json'
        self.cache=self.root/'cache';self.cache_calls=[];self.visited=[]
        def resume(job,root):
            self.cache_calls.append(root)
            return {'pdf_sha256':'synthetic-sha'}
        self.services={'candidate':{},'question_config':{},'ledger_path':self.history,'resume_provider':resume}

    @staticmethod
    def snapshot(directory):
        directory=Path(directory)
        return {str(p.relative_to(directory)):p.read_bytes() for p in directory.rglob('*') if p.is_file()}

    def prepared(self,url,**kwargs):
        self.visited.append(url)
        kwargs['resume_provider']({'description':'Synthetic'},Path(kwargs['output_dir'])/'resume')
        metadata=kwargs['input_metadata']
        ledger=kwargs['ledger']
        status='submitting' if 'uncertain' in url else 'applied'
        ledger.record_aliases(ExternalApplicationResult(status,url,attempt_id=metadata['attempt_id']),[url],metadata['role_id'])
        return {'status':'submission_uncertain' if status=='submitting' else 'applied',
                'output_dir':str(Path(kwargs['output_dir'])/'synthetic'),
                'resume':{'pdf_sha256':'synthetic-sha'},'jd_sha256':'synthetic-jd'}

    def execute(self,jobs=None,**kwargs):
        return run_submissions(jobs,config_dir=self.config,output_dir=self.cache,
            services=self.services,driver_factory=Mock(return_value=Mock()),preparer=self.prepared,**kwargs)

    def test_default_invocations_generate_distinct_ids_and_directories(self):
        jobs=load_jobs(url='https://example.test/job/1')
        cwd=Path.cwd()
        try:
            os.chdir(self.root)
            first=self.execute(jobs)
            before=self.snapshot(first['run_dir'])
            second=self.execute(jobs)
        finally:os.chdir(cwd)
        self.assertNotEqual(first['run_id'],second['run_id'])
        self.assertIn(first['run_id'],Path(first['run_dir']).name)
        self.assertEqual(Path(first['run_dir']).parent,self.root/'logs/direct_submit')
        self.assertEqual(first['counts'],{'applied':1});self.assertEqual(second['counts'],{'applied':1})
        self.assertEqual(before,self.snapshot(first['run_dir']))
        self.assertEqual(self.cache_calls[0],self.cache_calls[1])

    def test_reused_destination_ignores_global_history_and_old_input_statuses(self):
        jobs=sum((load_jobs(url=f'https://example.test/job/{i}') for i in range(4)),[])
        for job,prior in zip(jobs,['applied','submitting','submission_uncertain','discarded']):job['prior_status']=prior
        ledger=ExternalApplicationLedger(self.history)
        for i,job in enumerate(jobs):
            ledger.record_aliases(ExternalApplicationResult('applied' if i%2 else 'submitting',job['url'],attempt_id=str(i)),[job['url']],job['id'])
        historical=self.history.read_bytes()
        first=self.execute(jobs,run_dir=self.root/'run',ledger_path=self.history)
        before=self.snapshot(first['run_dir'])
        second=self.execute(jobs,run_dir=self.root/'run',ledger_path=self.history)
        self.assertEqual(first['counts'],{'applied':4});self.assertEqual(second['counts'],{'applied':4})
        self.assertEqual(len(self.visited),8);self.assertNotEqual(first['run_dir'],second['run_dir'])
        self.assertEqual(self.history.read_bytes(),historical)
        self.assertEqual(before,self.snapshot(first['run_dir']))
        self.assertNotEqual(first['options']['ledger_path'],second['options']['ledger_path'])
        self.assertTrue(Path(second['options']['ledger_path']).is_relative_to(Path(second['run_dir'])))

    def test_uncertain_job_does_not_block_next_job_or_new_run(self):
        jobs=load_jobs(url='https://example.test/job/uncertain')+load_jobs(url='https://example.test/job/2')
        first=self.execute(jobs,run_dir=self.root/'run')
        self.assertEqual(first['counts'],{'submission_uncertain':1,'applied':1})
        self.assertEqual(len(self.visited),2)
        resumed=self.execute(resume_dir=first['run_dir'])
        self.assertEqual(resumed['counts'],first['counts']);self.assertEqual(len(self.visited),2)
        second=self.execute(jobs,run_dir=self.root/'run')
        self.assertEqual(second['counts'],first['counts']);self.assertEqual(len(self.visited),4)

    def test_retry_execution_preserves_parent_files(self):
        jobs=load_jobs(url='https://example.test/job/1')
        parent=SubmitRun(self.root/'parent',jobs=jobs)
        parent.update(jobs[0],status='failed_before_submit',stage='upload',retryable=True)
        parent.close();before=self.snapshot(self.root/'parent')
        retry=load_jobs([str(self.root/'parent/retry.json')])
        self.assertEqual(self.execute(retry,run_dir=self.root/'child')['counts'],{'applied':1})
        self.assertEqual(before,self.snapshot(self.root/'parent'))

    def test_old_nonretryable_flag_does_not_gate_fresh_run_but_inventory_does(self):
        jobs=load_jobs(url='https://example.test/job/1')+load_jobs(url='https://example.test/job/2')
        parent=SubmitRun(self.root/'parent',jobs=jobs)
        for job in jobs:parent.update(job,status='blocked',stage='previous_run',retryable=False)
        parent.close()
        retry=load_jobs([str(self.root/'parent/retry.json')])
        retry[1]['admission_blockers'].append('not_in_verified_engineering_inventory')
        result=self.execute(retry,run_dir=self.root/'new')
        self.assertEqual(result['counts'],{'applied':1,'blocked':1})
        self.assertEqual(self.visited,[jobs[0]['url']])

    def test_pipeline_and_custom_export_keep_both_run_outcomes(self):
        jobs=load_jobs(url='https://example.test/job/1');output=self.root/'export.json';db=self.root/'pipeline.db'
        first=self.execute(jobs,run_dir=self.root/'run',export_path=output,db_path=db)
        original=output.read_bytes()
        second=self.execute(jobs,run_dir=self.root/'run',export_path=output,db_path=db)
        self.assertEqual(output.read_bytes(),original)
        self.assertNotEqual(first['options']['export_path'],second['options']['export_path'])
        a=json.loads((Path(first['run_dir'])/'applications.json').read_text())
        b=json.loads((Path(second['run_dir'])/'applications.json').read_text())
        self.assertNotEqual(a['records'][0]['id'],b['records'][0]['id'])
        with PipelineStore(db) as store:
            self.assertEqual(store.connection.execute("SELECT count(*) FROM entities WHERE stage='applications'").fetchone()[0],2)

    def test_explicit_legacy_resume_copies_owned_claim_only(self):
        jobs=load_jobs(url='https://example.test/job/1')+load_jobs(url='https://example.test/job/2')
        ledger=ExternalApplicationLedger(self.history)
        ledger.record_aliases(ExternalApplicationResult('submitting',jobs[0]['url'],attempt_id='owned'),[jobs[0]['url']],jobs[0]['id'])
        ledger.record_aliases(ExternalApplicationResult('submitting',jobs[1]['url'],attempt_id='foreign'),[jobs[1]['url']],jobs[1]['id'])
        run=SubmitRun(self.root/'legacy',jobs=jobs,options={'ledger_path':str(self.history)})
        run.update(jobs[0],status='submitting',stage='submitting',attempt_id='owned')
        run.update(jobs[1],status='submission_uncertain',stage='resume_reconciliation',retryable=False)
        run.close()
        historical=self.history.read_bytes()
        resumed=self.execute(resume_dir=self.root/'legacy')
        self.assertEqual(resumed['counts'],{'submission_uncertain':1,'applied':1})
        self.assertEqual(self.visited,[jobs[1]['url']]);self.assertEqual(self.history.read_bytes(),historical)
        self.assertEqual(Path(resumed['options']['ledger_path']),self.root/'legacy/applications-ledger.json')
