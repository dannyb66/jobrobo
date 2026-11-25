"""Hard model request caps and worker-local accounting; no vendor calls."""
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import Mock

import pytest
from modules import captcha_solver
from scripts.captcha_solve import RequestBudget, RequestBudgetExceeded


def test_budget_blocks_seventh_model_request_but_separates_outcome_posts():
    budget=RequestBudget(6)
    post=Mock()
    for _ in range(6):budget.post(post,None,'https://fixture.test/v1/chat/completions')
    budget.post(post,None,'https://fixture.test/v1/solve-outcome')
    with pytest.raises(RequestBudgetExceeded):
        budget.post(post,None,'https://fixture.test/v1/chat/completions')
    assert post.call_count==7
    assert budget.model_requests==6 and budget.post_requests==7


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(captcha_solver,'enabled',lambda:True)
    monkeypatch.setattr(captcha_solver,'available',lambda:(True,''))
    monkeypatch.setattr(captcha_solver,'cdp_url',lambda driver:'ws://fixture')
    monkeypatch.setattr(captcha_solver,'_env',lambda name:'')
    monkeypatch.setattr(captcha_solver,'_base_url',lambda:'https://fixture.test')
    calls=[]
    real_run=captcha_solver.subprocess.run
    def child(command,**kwargs):
        if '--max-responses' not in command:return real_run(command,**kwargs)
        allowance=int(command[command.index('--max-responses')+1])
        calls.append(allowance)
        return Mock(stdout=json.dumps({'status':'no_challenge','model_requests':allowance}),stderr='')
    monkeypatch.setattr(captcha_solver.subprocess,'run',child)
    return calls


def test_concurrent_vendor_calls_cannot_race_past_request_budget():
    budget=RequestBudget(6)
    original=Mock()
    def request(_):
        try:budget.post(original,None,'https://fixture.test/chat/completions')
        except RequestBudgetExceeded:return False
        return True
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(request,range(32)))==6
    assert original.call_count==budget.model_requests==6


def test_four_workers_have_separate_budgets_across_multiple_solves(bridge):
    def worker(_):
        checkpoints=[]
        with captcha_solver.job_budget(limit=7,checkpoint=checkpoints.append) as budget:
            for _ in range(2):captcha_solver.solve(Mock(current_url='https://fixture.test'))
            assert captcha_solver.solve(Mock())['status']=='budget_exhausted'
            return budget['used'],max(checkpoints)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(worker,range(4)))==[(7,7)]*4
    assert sorted(bridge)==[1]*4+[6]*4


def test_unknown_timeout_reserves_usage_and_resume_keeps_it(bridge,monkeypatch):
    def timeout(command,**kwargs):raise captcha_solver.subprocess.TimeoutExpired(command,200)
    with monkeypatch.context() as m:
        m.setattr(captcha_solver.subprocess,'run',timeout)
        with captcha_solver.job_budget(limit=7) as budget:
            assert captcha_solver.solve(Mock())['status']=='timeout'
            assert budget['used']==6
    with captcha_solver.job_budget(limit=7,used=6) as resumed:
        captcha_solver.solve(Mock())
        assert resumed['used']==7
    assert bridge==[1]


def test_failed_launch_releases_unused_reservation(bridge,monkeypatch):
    def fail(*args,**kwargs):raise FileNotFoundError()
    monkeypatch.setattr(captcha_solver.subprocess,'run',fail)
    with captcha_solver.job_budget(limit=6) as budget:
        result=captcha_solver.solve(Mock())
        assert result['terminal'] and result['model_requests']==0
        assert budget['used']==0


def test_real_runner_checkpoints_budget_and_resume_cannot_reset_it(tmp_path,bridge,monkeypatch):
    from contextlib import redirect_stdout
    from io import StringIO
    from modules.generic_inputs import load_jobs
    from modules.submit_runner import run_submissions
    monkeypatch.setenv('CAPTCHA_SOLVER','1')
    config=tmp_path/'config';config.mkdir()
    (config/'search.py').write_text('max_applications_per_run = 50\n')
    jobs=load_jobs(url='https://fixture.test/job')
    services={'candidate':{},'question_config':{},'resume_provider':Mock()}
    def interrupted(url,**kwargs):
        captcha_solver.solve(kwargs['driver'])
        captcha_solver.solve(kwargs['driver'])
        raise KeyboardInterrupt()
    with redirect_stdout(StringIO()),pytest.raises(KeyboardInterrupt):
        run_submissions(jobs,config_dir=config,run_dir=tmp_path/'run',captcha_max_requests=7,
            services=services,driver_factory=Mock(return_value=Mock()),preparer=interrupted)
    state=json.loads((tmp_path/'run/progress.json').read_text())['jobs'][0]
    assert state['captcha_model_requests']==7
    def resumed(url,**kwargs):
        assert captcha_solver.solve(kwargs['driver'])['status']=='budget_exhausted'
        return {'status':'blocked','blockers':['CAPTCHA request budget exhausted'],
                'output_dir':str(tmp_path/'report'),'resume':{}}
    with redirect_stdout(StringIO()):
        result=run_submissions(resume_dir=tmp_path/'run',retry_failed=True,services=services,
            driver_factory=Mock(return_value=Mock()),preparer=resumed)
    assert result['jobs'][0]['captcha_model_requests']==7
    assert bridge==[6,1]
