"""Regression coverage for the saved-run audit, without employer actions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
import json
import multiprocessing
from pathlib import Path
import shlex
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import direct_apply
from modules.direct_careers_apply import write_json
from modules.external_apply import ExternalApplicationResult
from modules.generic_inputs import load_jobs
from modules.portal_outcomes import explicit_portal_rejection
from modules.submit_history import SubmissionHistory
from modules.submit_runner import run_submissions
from modules.submit_state import SubmitRun, retry_command


def _reserve_process(directory, scope, barrier, queue):
    jobs = load_jobs(url='https://example.test/same-posting')
    run = SubmitRun(directory,jobs=jobs)
    try:
        barrier.wait(timeout=10)
        SubmissionHistory(scope).reserve(run)
        queue.put(run.rows()[0][1]['status'])
    finally:run.close()


@pytest.fixture
def config(tmp_path):
    directory = tmp_path/'config'
    directory.mkdir()
    (directory/'search.py').write_text('max_applications_per_run = 50\n')
    return directory


def test_two_processes_cannot_claim_same_posting(tmp_path):
    scope = tmp_path/'runs'
    scope.mkdir()
    ctx = multiprocessing.get_context('spawn')
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    processes = [ctx.Process(target=_reserve_process,args=(scope/str(i),scope,barrier,queue)) for i in range(2)]
    try:
        for process in processes:process.start()
        results = [queue.get(timeout=20) for _ in processes]
        assert sorted(results) == ['blocked','pending']
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():process.terminate();process.join()
        queue.close()


def test_history_guard_protects_confirmed_and_uncertain_by_posting_identity(tmp_path,config):
    scope = tmp_path/'runs'
    jobs = (load_jobs(url='https://example.test/confirmed') + load_jobs(url='https://example.test/uncertain')
            + load_jobs(url='https://example.test/preparing'))
    prior = SubmitRun(scope/'prior',jobs=jobs)
    prior.update(jobs[0],status='applied')
    prior.update(jobs[1],status='submission_uncertain')
    prior.update(jobs[2],status='preparing')
    prior.close()
    for job in jobs:job['id'] = 'fresh-'+job['id']
    factory = Mock()
    with redirect_stdout(StringIO()):
        result = run_submissions(jobs,config_dir=config,run_dir=scope/'new',history_root=scope,driver_factory=factory)
    factory.assert_not_called()
    assert result['counts'] == {'duplicate':1,'blocked':2}
    assert result['jobs'][1]['stage'] == 'history_requires_reconciliation'
    assert not result['jobs'][1]['retryable']


def test_history_releases_safe_failures_but_preserves_crash_claims(tmp_path):
    jobs = load_jobs(url='https://example.test/job')
    guard = SubmissionHistory(tmp_path/'scope')
    original = SubmitRun(tmp_path/'first',jobs=jobs)
    guard.reserve(original)
    original.update(jobs[0],status='failed_before_submit',retryable=True)
    guard.finish(original)
    second = SubmitRun(tmp_path/'second',jobs=jobs)
    guard.reserve(second)
    assert second.rows()[0][1]['status'] == 'pending'
    # Simulate a killed process: no finish call. Only its own explicit resume
    # can reuse the active claim, even if time has passed.
    second.close()
    third = SubmitRun(tmp_path/'third',jobs=jobs)
    guard.reserve(third)
    assert third.rows()[0][1]['status'] == 'blocked'
    resumed = SubmitRun(tmp_path/'second')
    guard.reserve(resumed)
    assert resumed.rows()[0][1]['status'] == 'pending'
    resumed.close();third.close();original.close()


def test_corrupt_history_fails_closed_before_browser(tmp_path,config):
    scope=tmp_path/'runs'
    (scope/'bad').mkdir(parents=True)
    (scope/'bad/progress.json').write_text('{')
    browser=Mock()
    with redirect_stdout(StringIO()),pytest.raises(ValueError,match='Cannot verify submission history'):
        run_submissions(load_jobs(url='https://example.test/job'),config_dir=config,
                        run_dir=scope/'new',history_root=scope,driver_factory=browser)
    browser.assert_not_called()


def test_diagnostics_do_not_record_url_credentials_or_config_secrets(tmp_path):
    from modules.submit_diagnostics import runtime_metadata
    (tmp_path/'secrets.py').write_text("llm_api_url = 'https://user:do-not-record@provider.test/v1?key=do-not-record'\n"
                                     "llm_api_key = 'do-not-record'\nllm_model = 'fixture-model'\n")
    metadata=runtime_metadata(tmp_path)
    assert metadata['draft_provider_host']=='provider.test'
    assert metadata['draft_model']=='fixture-model'
    assert 'do-not-record' not in json.dumps(metadata)
    assert metadata['source_sha256']['modules/submit_runner.py']


@pytest.mark.parametrize('suffix',['retry-uncertain.json','retry-submission-uncertain.txt'])
def test_uncertain_retry_file_never_starts_browser(tmp_path,config,suffix):
    jobs = load_jobs(url='https://example.test/uncertain')
    parent = SubmitRun(tmp_path/'parent',jobs=jobs)
    parent.update(jobs[0],status='submission_uncertain',retryable=False)
    parent.close()
    retry = load_jobs([tmp_path/'parent'/suffix])
    assert 'retry_requires_manual_resolution' in retry[0]['admission_blockers']
    factory = Mock()
    with redirect_stdout(StringIO()):
        result = run_submissions(retry,run_dir=tmp_path/'child',config_dir=config,driver_factory=factory)
    factory.assert_not_called()
    assert result['counts'] == {'blocked':1}


def test_retry_command_round_trips_effective_settings(tmp_path):
    jobs = load_jobs(url='https://example.test/job')
    options = {'workers':4,'pause':'never','captcha_solver':True,'max_applications':500,
               'captcha_max_requests':36,'config_dir':str(tmp_path/'config with spaces'),
               'browser_backend':'local','history_root':str(tmp_path/'history with spaces'),
               'chrome_profile':'old-retained-profile'}
    run = SubmitRun(tmp_path/'run',jobs=jobs,options=options)
    try:
        run.update(jobs[0],status='failed_before_submit',retryable=True)
        command = retry_command(run.export())
        with patch('modules.submit_runner.run_submissions',return_value={'jobs':[{'status':'applied'}]}) as runner,redirect_stdout(StringIO()):
            assert direct_apply.main(shlex.split(command)[2:]) == 0
    finally:run.close()
    for name in ['workers','pause','captcha_solver','max_applications','captcha_max_requests','config_dir','history_root']:
        assert runner.call_args.kwargs[name] == options[name]
    assert runner.call_args.kwargs['chrome_profile'] is None


@pytest.mark.parametrize('outcome',['refusal','late_confirmation'])
def test_four_workers_reconcile_retained_outcomes_on_own_thread(tmp_path,config,outcome):
    jobs = sum((load_jobs(url=f'https://example.test/job/{i}') for i in range(4)),[])
    for job in jobs:job['company']='Fixture Company';job['title']='Fixture Engineer'
    barrier = threading.Barrier(4)
    reads = []
    def factory():
        driver = Mock(browser_backend='local',capabilities={})
        driver.owner = threading.get_ident()
        driver.current_window_handle = 'tab'
        driver.current_url = 'about:blank'
        driver.live = {}
        def select(handle):driver.current_window_handle=handle
        driver.switch_to.window.side_effect=select
        return driver
    def prepare(url,**kwargs):
        driver = kwargs['driver']
        driver.current_url=url
        metadata = kwargs['input_metadata']
        kwargs['ledger'].record_aliases(ExternalApplicationResult('submitting',url,
            attempt_id=metadata['attempt_id']),[url],metadata['role_id'])
        final = {'url':url,'headings':['ERROR'],'alerts':[
            'There was a problem verifying this submission with CAPTCHA. Please try again later.'],'challenge':False}
        if outcome=='late_confirmation':
            final.update(headings=['Application submitted successfully'],alerts=[])
        driver.live[driver.current_window_handle]=final
        output = Path(kwargs['output_dir'])/url.rsplit('/',1)[-1]
        report = {'url':url,'resolved_url':url,'status':'submission_uncertain',
                  'resume':{'pdf_sha256':'fixture-hash'},'attachment':{'name':'fixture.pdf'},
                  'output_dir':str(output),'final_state':final,'confirmation_baseline':[]}
        write_json(output/'report.json',report)
        barrier.wait(timeout=10)
        return report
    def browser(driver):
        def read():
            reads.append((driver.owner,threading.get_ident()))
            return driver.live[driver.current_window_handle]
        return SimpleNamespace(read=read)
    with patch('modules.submit_runner.SubmissionBrowser',side_effect=browser),redirect_stdout(StringIO()):
        result = run_submissions(jobs,config_dir=config,run_dir=tmp_path/'run',workers=4,pause='never',
            driver_factory=factory,preparer=prepare,
            services={'candidate':{},'question_config':{},'resume_provider':Mock()})
    assert result['counts']=={('failed_before_submit' if outcome=='refusal' else 'applied'):4}
    assert len(reads)==4 and all(owner==actual for owner,actual in reads)
    artifacts=json.loads((tmp_path/'run/applications.json').read_text())['records']
    assert all(row['company']=='Fixture Company' and row['title']=='Fixture Engineer' for row in artifacts)
    events=[json.loads(line) for line in (tmp_path/'run/events.jsonl').read_text().splitlines()]
    reservations=[e for e in events if e['event_type']=='reservation']
    assert len(reservations)==4
    assert len({e['reservation_id'] for e in reservations})==4


def test_generic_error_and_stale_or_missing_detail_are_not_rejections():
    assert not explicit_portal_rejection({'headings':['ERROR'],'alerts':[]})
    assert not explicit_portal_rejection({'text':'There was a problem verifying this submission with CAPTCHA.'})
    assert explicit_portal_rejection({'alerts':['There was a problem verifying this submission with CAPTCHA.']})


def test_interrupted_preparation_retains_report_pointer(tmp_path,config):
    jobs = load_jobs(url='https://example.test/interrupted')
    def prepare(url,**kwargs):
        from modules.generic_prepare import fingerprint
        output=Path(kwargs['output_dir'])/fingerprint(url)[:20]
        write_json(output/'report.json',{'status':'interrupted','url':url})
        raise KeyboardInterrupt()
    with redirect_stdout(StringIO()),pytest.raises(KeyboardInterrupt):
        run_submissions(jobs,config_dir=config,run_dir=tmp_path/'run',driver_factory=Mock(return_value=Mock()),
            preparer=prepare,services={'candidate':{},'question_config':{},'resume_provider':Mock()})
    progress=json.loads((tmp_path/'run/progress.json').read_text())
    assert progress['jobs'][0]['status']=='interrupted_before_submit'
    assert Path(progress['jobs'][0]['preparation_report']).is_file()
