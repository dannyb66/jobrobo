"""Read-only validator fixtures: no employer, model, credentials or CAPTCHA calls."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock,patch

import pytest
import direct_apply
from modules.generic_inputs import load_jobs
from modules.external_apply import identify_ats
from modules.job_url_validation import (BrowserChecks, HTTPChecks, check_http, fetch_board,
                                       html_snapshot, inspect_snapshot, validate_jobs)


FORM='<h1>Software Engineer</h1><form><input type="email" name="email"><input type="file" name="resume"></form>'
UUIDS=[f'00000000-0000-0000-0000-{i:012d}' for i in range(12)]


def response(url,text,status=200):
    return SimpleNamespace(url=url,text=text if isinstance(text,str) else json.dumps(text),status_code=status,headers={})


def source(tmp_path,count=1,ats=False):
    rows=[{'id':str(i),'url':f'https://jobs.ashbyhq.com/fixture/{UUIDS[i]}' if ats else f'https://fixture{i}.test/jobs/{i}',
           'company':'Fixture','title':'Software Engineer','source_tasks':[44]} for i in range(count)]
    path=tmp_path/'source.json';path.write_text(json.dumps({'jobs':rows}))
    return path,load_jobs([path])


@pytest.mark.parametrize('message',['Job not found','This position is no longer available','No longer accepting applications','Role has been filled','Page not found','404'])
def test_soft_404_and_closed_messages_are_invalid(message):
    job={'url':'https://fixture.test/job','title':'Engineer'}
    result=inspect_snapshot(html_snapshot('<h1>'+message+'</h1>',job['url']),job)
    assert result['status']=='invalid'


def test_hidden_closed_template_does_not_drop_live_form():
    job={'url':'https://fixture.test/job','title':'Software Engineer'}
    html=FORM+'<div hidden><h1>Job not found</h1></div><script>"job is closed"</script>'
    result=inspect_snapshot(html_snapshot(html,job['url']),job)
    assert result['status']=='apply_ready'


def test_200_shell_and_newsletter_are_not_verified_application_forms():
    job={'url':'https://fixture.test/job','title':'Software Engineer'}
    for html in ['<p>Enable JavaScript</p>','<h1>Newsletter</h1><input type="email">']:
        assert inspect_snapshot(html_snapshot(html,job['url']),job)['status']=='needs_review'
    shell=inspect_snapshot(html_snapshot('<p>Enable JavaScript</p>',job['url']),job,known_open=True)
    assert shell['status']=='open' and not shell['form']['verified']


def test_disabled_fieldset_is_not_a_usable_application_form():
    job={'url':'https://fixture.test/job','title':'Software Engineer'}
    result=inspect_snapshot(html_snapshot('<fieldset disabled>'+FORM+'</fieldset>',job['url']),job)
    assert result['status']=='needs_review' and not result['form']['verified']


def test_wrong_posting_and_board_redirect_never_pass():
    original='https://jobs.ashbyhq.com/fixture/'+UUIDS[0]
    for target,reason in [('https://jobs.ashbyhq.com/fixture/'+UUIDS[1],'different_posting'),
                          ('https://jobs.ashbyhq.com/fixture','board_redirect')]:
        assert inspect_snapshot(html_snapshot(FORM,target),{'url':original})['reason']==reason


@pytest.mark.parametrize('code',[403,429,503])
def test_access_and_transient_failures_are_review_not_closed(code):
    url='https://fixture.test/jobs/1'
    http=HTTPChecks(retries=0,client_factory=lambda:SimpleNamespace(get=lambda u,**kw:response(u,'blocked',code)))
    assert check_http({'url':url},None,http,False)['status']=='needs_review'


def test_unsafe_url_is_not_requested():
    client=Mock()
    http=HTTPChecks(client_factory=lambda:client)
    assert http.get('http://127.0.0.1/private')['reason']=='unsafe_url'
    client.get.assert_not_called()


def test_bad_url_is_filtered_without_aborting_good_rows(tmp_path):
    path,_=source(tmp_path)
    data=json.loads(path.read_text());data['jobs'].append({'id':'bad','url':'not a URL','company':'Fixture'})
    path.write_text(json.dumps(data))
    jobs=load_jobs([path],allow_invalid_urls=True)
    calls=[]
    def get(url,**kw):calls.append(url);return response(url,FORM)
    with redirect_stdout(StringIO()):
        result=validate_jobs(jobs,output_dir=tmp_path/'out',client_factory=lambda:SimpleNamespace(get=get))
    assert result['status_counts']=={'apply_ready':1,'invalid':1}
    assert calls==[jobs[0]['url']]
    assert len(load_jobs([tmp_path/'out/jobs-apply-ready.json']))==1
    with pytest.raises(ValueError):load_jobs([path])


def test_unlisted_posting_and_incomplete_board_do_not_mean_closed(tmp_path):
    _,jobs=source(tmp_path,ats=True);url=jobs[0]['url']
    http=Mock()
    http.get.return_value={'status':200,'url':url,'text':json.dumps({'jobs':[
        {'id':UUIDS[0],'jobUrl':url,'applyUrl':url+'/application','isListed':False,'title':'Engineer'}]})}
    board=fetch_board(('ashby','jobs.ashbyhq.com','fixture'),http)
    assert len(board['jobs'])==1
    http.get.return_value={'status':200,'url':url,'text':FORM}
    assert check_http(jobs[0],{'jobs':{},'complete':False},http,True)['status']=='apply_ready'


def test_stale_api_application_url_falls_back_to_original_posting(tmp_path):
    _,jobs=source(tmp_path,ats=True);job=jobs[0];identity=identify_ats(job['url'])
    board={'jobs':{identity.key:{'apply_url':job['url']+'/application','api_url':'https://api.ashbyhq.com/fixture'}},'complete':True}
    def get(url):return {'url':url,'status':404 if url.endswith('/application') else 200,'text':FORM}
    result=check_http(job,board,SimpleNamespace(get=get),True)
    assert result['status']=='apply_ready' and result['failed_apply_http_status']==404
    assert result['checked_url']==job['url']


def test_published_api_with_http_404_requires_browser_review(tmp_path):
    _,jobs=source(tmp_path,ats=True);job=jobs[0];identity=identify_ats(job['url'])
    board={'jobs':{identity.key:{'apply_url':job['url'],'api_url':'https://api.ashbyhq.com/fixture'}}}
    http=SimpleNamespace(get=lambda url:{'url':url,'status':404,'text':'not found'})
    result=check_http(job,board,http,True)
    assert result['status']=='needs_review' and result['reason']=='api_http_conflict'


def test_validation_does_not_launder_uncertain_retry_restrictions(tmp_path):
    _,jobs=source(tmp_path)
    jobs[0]['admission_blockers']=['retry_requires_manual_resolution']
    with redirect_stdout(StringIO()):
        validate_jobs(jobs,output_dir=tmp_path/'out',check_inputs=True,
                      client_factory=lambda:SimpleNamespace(get=lambda u,**k:response(u,FORM)))
    loaded=load_jobs([tmp_path/'out/jobs-apply-ready.json'])
    assert loaded[0]['admission_blockers']==['retry_requires_manual_resolution']
    assert loaded[0]['validation']['input_provenance']==jobs[0]['provenance']


def test_board_fetch_is_shared_and_preserves_input_metadata(tmp_path):
    path,jobs=source(tmp_path,count=4,ats=True);before=path.read_bytes();calls=[]
    def get(url,**kwargs):
        calls.append(url)
        if '/posting-api/' in url:
            return response(url,{'jobs':[{'jobUrl':j['url'],'applyUrl':j['url']+'/application','isListed':False} for j in jobs]})
        return response(url,'<p>Enable JavaScript</p>')
    with redirect_stdout(StringIO()):
        report=validate_jobs(jobs,output_dir=tmp_path/'out',client_factory=lambda:SimpleNamespace(get=get))
    assert sum('/posting-api/' in url for url in calls)==1
    assert report['status_counts']=={'open':4}
    retained=json.loads((tmp_path/'out/jobs-open.json').read_text())['jobs']
    assert [j['id'] for j in retained]==[j['id'] for j in jobs]
    assert all(j['source_tasks']==[44] for j in retained)
    assert path.read_bytes()==before


def test_eight_http_and_two_browser_workers_use_separate_bounded_pools(tmp_path):
    _,jobs=source(tmp_path,count=8)
    http_barrier=threading.Barrier(8);browser_barrier=threading.Barrier(2)
    lock=threading.Lock();active={'http':0,'browser':0};peak={'http':0,'browser':0};closed=[]
    def get(url,**kw):
        with lock:active['http']+=1;peak['http']=max(peak['http'],active['http'])
        try:http_barrier.wait(timeout=10);return response(url,'<p>Enable JavaScript</p>')
        finally:
            with lock:active['http']-=1
    class Browser:
        def __init__(self):self.owner=threading.get_ident()
        def check(self,job,previous):
            assert threading.get_ident()==self.owner
            with lock:active['browser']+=1;peak['browser']=max(peak['browser'],active['browser'])
            try:
                browser_barrier.wait(timeout=10)
                return {'status':'apply_ready','reason':'fixture','open_verified':True,'form':{'verified':True}}
            finally:
                with lock:active['browser']-=1
        def close(self):closed.append((self.owner,threading.get_ident()))
    with redirect_stdout(StringIO()):
        report=validate_jobs(jobs,output_dir=tmp_path/'out',check_inputs=True,workers=8,browser_workers=2,
                             client_factory=lambda:SimpleNamespace(get=get),browser_factory=Browser)
    assert report['status_counts']=={'apply_ready':8}
    assert peak=={'http':8,'browser':2}
    assert len(closed)==2 and all(a==b for a,b in closed)
    with redirect_stdout(StringIO()):
        resumed=validate_jobs(jobs,output_dir=tmp_path/'out',check_inputs=True,resume=True,
                             client_factory=lambda:pytest.fail('should reuse completed checkpoints'),
                             browser_factory=lambda:pytest.fail('should reuse completed browser checks'))
    assert resumed['status_counts']==report['status_counts']


def test_interrupted_form_scan_resumes_unfinished_browser_checks(tmp_path):
    _,jobs=source(tmp_path)
    client=lambda:SimpleNamespace(get=lambda url,**kw:response(url,'<p>JavaScript app</p>'))
    checker=Mock();checker.check.side_effect=KeyboardInterrupt()
    with redirect_stdout(StringIO()):
        interrupted=validate_jobs(jobs,output_dir=tmp_path/'out',check_inputs=True,client_factory=client,browser_factory=lambda:checker)
    assert not interrupted['complete'] and interrupted['pending_browser_pages']==1
    checker.check.side_effect=None
    checker.check.return_value={'status':'apply_ready','reason':'fixture','form':{'verified':True}}
    with redirect_stdout(StringIO()):
        resumed=validate_jobs(jobs,output_dir=tmp_path/'out',check_inputs=True,resume=True,
                              client_factory=client,browser_factory=lambda:checker)
    assert resumed['complete'] and resumed['status_counts']=={'apply_ready':1}
    assert checker.close.call_count==2


def test_resume_rejects_changed_selection(tmp_path):
    _,jobs=source(tmp_path)
    client=lambda:SimpleNamespace(get=lambda url,**kw:response(url,FORM))
    with redirect_stdout(StringIO()):validate_jobs(jobs,output_dir=tmp_path/'out',client_factory=client)
    with pytest.raises(ValueError,match='same input selection'):
        validate_jobs([{**jobs[0],'title':'Changed'}],output_dir=tmp_path/'out',resume=True,client_factory=client)


def test_cli_validation_never_routes_to_submit_or_preparation(tmp_path):
    path,_=source(tmp_path)
    with patch('modules.job_url_validation.validate_jobs',return_value={'complete':True}) as validator, \
         patch('modules.submit_runner.run_submissions') as submit, \
         patch('modules.generic_prepare.run_preparations') as prepare,redirect_stdout(StringIO()):
        assert direct_apply.main(['validate','--urls-file',str(path),'--check-inputs','--workers','8','--browser-workers','2'])==0
    assert validator.call_args.kwargs['check_inputs']
    submit.assert_not_called();prepare.assert_not_called()


@pytest.mark.skipif(os.getenv('JOBROBO_BROWSER_TESTS')!='1',reason='Opt-in local Chrome form validation')
def test_real_chrome_reads_dynamic_form_and_never_submits(tmp_path):
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    receipts=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
            self.wfile.write(b'''<h1>Software Engineer</h1><form action="/submit" method="post"><input type="email" name="email"><input type="file" name="resume"><button>Submit</button></form><script>setTimeout(()=>document.forms[0].requestSubmit(),100)</script>''')
        def do_POST(self):receipts.append(self.path);self.send_response(200);self.end_headers()
        def log_message(self,*a):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/job/1'
    checker=BrowserChecks(timeout=3,allow_local=True)
    try:
        result=checker.check({'url':url,'key':url},{'checked_url':url})
        assert result['status']=='apply_ready'
        with pytest.raises(Exception,match='Validation cannot submit'):
            checker.driver.execute_script('document.forms[0].requestSubmit()')
        assert checker.driver.execute_script('return document.querySelector("input[type=email]").value')==''
        assert receipts==[]
    finally:checker.close();server.shutdown();server.server_close()
