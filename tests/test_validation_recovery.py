"""Regressions from the ten-provider validation; all employer actions are fixtures."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from modules.generic_prepare import (PreparationResolver, fill_fields, posting_mismatch,
                                     email_verification_required, prepare_url)
from modules.submit_runner import requeue_failed


class ValidationRecoveryTests(TestCase):
    def field(self, value=''):
        return dict(name='name', id='name', question='Name', label='Name', tag='input',
                    type='text', visible=True, disabled=False, readonly=False, required=True,
                    valid=True, value=value, options=[], checked=False, element=Mock())

    def test_delayed_autofill_during_answer_resolution_is_not_overwritten(self):
        field=self.field();browser=Mock(actions=[])
        browser.read.side_effect=lambda:{'fields':[field]}
        resolver=PreparationResolver({'full_name':'Configured Applicant'}, {})
        original=resolver.resolve
        def resolve(*a,**k):
            result=original(*a,**k);field['value']='Resume parsed applicant';return result
        resolver.resolve=resolve
        with patch('modules.generic_prepare.fill_native') as write:
            result=fill_fields(browser,{'fields':[field]},resolver,'generic',set())
        write.assert_not_called();self.assertEqual(field['value'],'Resume parsed applicant')
        self.assertEqual(result[0]['source'],'existing_browser')

    def test_existing_valid_field_does_not_call_answer_provider(self):
        field=self.field('Existing Applicant');browser=Mock(actions=[])
        browser.read.return_value={'fields':[field]};resolver=PreparationResolver({}, {})
        resolver.resolve=Mock(side_effect=AssertionError('unnecessary AI/config resolution'))
        result=fill_fields(browser,{'fields':[field]},resolver,'generic',set())
        self.assertEqual(result[0]['source'],'existing_browser')

    def test_phone_readback_preserves_digits_and_does_not_relax_other_text(self):
        from modules.generic_prepare import _answers_equal
        q={'candidate_key':'phone','fields':[{'type':'tel'}]}
        self.assertTrue(_answers_equal(q,'(555) 123-4567','+15551234567',country='United States'))
        self.assertFalse(_answers_equal(q,'(555) 123-4568','+15551234567',country='United States'))
        self.assertFalse(_answers_equal(q,'(555) 123-4567 x12','5551234567',country='United States'))
        self.assertFalse(_answers_equal({'fields':[{'type':'text'}]},'555-123-4567','5551234567'))

    def test_custom_choice_populated_during_resolution_is_not_opened_or_typed(self):
        from modules.generic_prepare import _custom_choice
        field={**self.field(),'question':'Location','name':'location','combobox':True,'committed':False}
        browser=Mock();browser.read.side_effect=lambda:{'fields':[field]}
        resolver=PreparationResolver({'city':'Example City'}, {})
        original=resolver.resolve
        def resolve(*args,**kwargs):
            answer=original(*args,**kwargs)
            field.update(committed=True,value='Example City, California, United States')
            return answer
        resolver.resolve=resolve
        self.assertEqual(_custom_choice(browser,field,resolver,'generic'),(True,'existing_browser',''))
        field['element'].click.assert_not_called();field['element'].send_keys.assert_not_called()

    def test_profile_aliases_and_named_referral_fact_guard(self):
        draft=Mock();resolver=PreparationResolver({'github':'https://github.com/example','full_name':'Example Applicant'}, {},draft)
        for label,key in [('GitHub profile','github'),('Please state your full legal name:✱','full_name'),('Your full name','full_name')]:
            q=dict(label=label,name=key,kind='text',required=True,fields=[],options=[])
            self.assertEqual(resolver.resolve(q,'generic').source,'candidate_config:'+key)
        q=dict(label='If someone referred you, please share their name and your connection.',name='referral',kind='text',required=True,fields=[],options=[])
        self.assertFalse(resolver.resolve(q,'generic').resolved);draft.answer.assert_not_called()

    def test_upload_processing_wait_is_bounded_and_does_not_repeat_selection(self):
        from hashlib import sha256
        from itertools import count
        from modules.generic_prepare import attach_resume
        with TemporaryDirectory() as tmp:
            root=Path(tmp);pdf=root/'source.pdf';pdf.write_bytes(b'fixture resume')
            binding={'pdf':str(pdf),'pdf_sha256':sha256(pdf.read_bytes()).hexdigest(),'job_id':'fixture'}
            for complete in (True,False):
                directory=root/str(complete);directory.mkdir()
                field={'element':Mock()};browser=Mock(actions=[])
                browser.driver.resume_upload_errors=[];browser.driver.resume_parsing=True
                reads=[0]
                def read():
                    reads[0]+=1;name=browser.actions[-1]['filename']
                    return {'guard':{'uploads':[{'name':name,'size':pdf.stat().st_size,'sha256':binding['pdf_sha256']}]},
                        'fields':[{'type':'file','name':'resume','label':'Resume','files':[]}],
                        'file_receipts':[name] if complete and reads[0]>=3 else []}
                browser.read.side_effect=read;ticks=count(0,.1)
                with patch('modules.generic_prepare.time.monotonic',side_effect=lambda:next(ticks)),patch('modules.generic_prepare.time.sleep'),patch('modules.generic_prepare.settle_resume_autofill'):
                    if complete:
                        result=attach_resume(browser,field,binding,directory,timeout=.05,processing_timeout=3)
                        self.assertTrue(result['method'].endswith('visible_receipt'))
                    else:
                        with self.assertRaisesRegex(ValueError,'could not be verified'):
                            attach_resume(browser,field,binding,directory,timeout=.05,processing_timeout=.4)
                field['element'].send_keys.assert_called_once();self.assertLess(reads[0],10)

    def test_upload_response_requires_matching_file_and_success_status(self):
        from modules.generic_prepare import _accepted_upload_response
        driver=Mock();driver.resume_upload_receipt={'name':'resume.pdf','sha256':'expected','http_status':200,'request_match':'pdf_bytes'}
        self.assertIsNotNone(_accepted_upload_response(driver,'resume.pdf','expected'))
        self.assertIsNone(_accepted_upload_response(driver,'other.pdf','expected'))
        driver.resume_upload_receipt['http_status']=502
        self.assertIsNone(_accepted_upload_response(driver,'resume.pdf','expected'))
        driver.resume_upload_receipt.update(http_status=200,request_match='multipart_filename')
        self.assertIsNone(_accepted_upload_response(driver,'resume.pdf','expected'))
        self.assertIsNotNone(_accepted_upload_response(driver,'resume.pdf','expected',browser_captured=True))
        driver.resume_upload_receipt['buffer_verified']=True
        self.assertIsNotNone(_accepted_upload_response(driver,'resume.pdf','expected'))

    def test_initial_generic_identity_change_is_blocked(self):
        self.assertTrue(posting_mismatch('https://example.com/jobs/it-12345678','https://example.com/jobs/devops-87654321',
            {'title':'DevOps Engineer'},{'title':'IT Engineer'},initial=True))
        self.assertFalse(posting_mismatch('https://example.com/jobs/it-12345678','https://example.com/jobs/it-12345678',
            {'title':'IT Engineer'},{'title':'IT Engineer'},initial=True))

    def test_submit_email_override_is_private_scoped_and_replaces_old_autofill(self):
        from modules.submit_runner import submit_profile
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'private.json';path.write_text(json.dumps({'email':'new@example.test'}))
            original={'candidate':{'email':'old@example.test'},'question_config':{'candidate':{'email':'other@example.test'}}}
            services=submit_profile(original,path)
            self.assertEqual(original['candidate']['email'],'old@example.test')
            field={**self.field('old@example.test'),'type':'email','name':'email','id':'email','label':'Email','question':'Email'}
            browser=Mock(actions=[]);browser.read.side_effect=lambda:{'fields':[field]}
            resolver=PreparationResolver(services['candidate'],services['question_config'])
            with patch('modules.generic_prepare.fill_native',side_effect=lambda d,q,v:field.update(value=v)) as write:
                result=fill_fields(browser,{'fields':[field]},resolver,'generic',set())
            write.assert_called_once();self.assertEqual(field['value'],'new@example.test')
            self.assertEqual(result[0]['status'],'prepared')

    def test_greenhouse_verification_wording_and_controls(self):
        self.assertTrue(email_verification_required({'text':'A verification code was sent. Enter the 8-character code to confirm you are a human.'}))
        self.assertTrue(email_verification_required({'fields':[{'id':'security-input-0','visible':True}]}))
        self.assertFalse(email_verification_required({'text':'We have received your application.'}))

    def test_declared_application_success_requires_a_fresh_message(self):
        from modules.external_apply import _confirmed
        text="Success\n\nThank you for your interest! We'll get back to you as soon as possible."
        self.assertTrue(_confirmed({'headings':[text],'application_success':[text]}))
        self.assertFalse(_confirmed({'headings':[],'application_success':[text]}))
        self.assertFalse(_confirmed({'headings':['Success']}))

    def test_intermediary_queue_is_not_employer_submission(self):
        from modules.generic_submit import external_dispatch_pending
        from modules.external_apply import _confirmed
        state={'headings':["You're in the queue"], 'text':"We'll submit your application within 24 hours.", 'forms':[]}
        self.assertTrue(external_dispatch_pending(state));self.assertFalse(_confirmed(state))
        self.assertFalse(external_dispatch_pending({**state,'headings':[]}))
        self.assertFalse(external_dispatch_pending({**state,'forms':[{'id':'application'}]}))
        self.assertFalse(external_dispatch_pending({**state,'text':'Your application was submitted successfully.'}))

    def test_generic_completion_stays_bound_to_exact_application_uuid(self):
        from modules.generic_submit import _identity_ok
        root='https://jobrobo.test/apply/abcdefab-cdef-4abc-8abc-abcdefabcdef'
        self.assertTrue(_identity_ok(root+'/done',root+'/confirm'))
        self.assertFalse(_identity_ok(root.replace('abcdefabcdef','abcdefabcdee')+'/done',root+'/confirm'))
        self.assertFalse(_identity_ok('https://other.test'+root.split('jobrobo.test')[1]+'/done',root+'/confirm'))
        self.assertFalse(_identity_ok('https://jobrobo.test/thanks',root+'/confirm'))
        self.assertFalse(_identity_ok(root+'/jobs/other/done',root+'/jobs/original/confirm'))

    def test_retained_preexisting_success_cannot_promote_an_uncertain_attempt(self):
        from modules.submit_runner import recover_verification_tabs
        text="Success: application received"
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'report.json';url='https://example.test/job'
            path.write_text(json.dumps({'resolved_url':url,'steps':[{'headings':[text]}]}))
            job={'url':url};run=Mock();ledger=Mock();driver=Mock()
            run.rows.return_value=[(job,{'status':'submission_uncertain','tab_handle':'target','preparation_report':str(path)})]
            browser=Mock();browser.read.return_value={'url':url,'headings':[text],'application_success':[text]}
            with patch('modules.submit_runner.SubmissionBrowser',return_value=browser):recover_verification_tabs(driver,run,ledger)
            run.update.assert_not_called();ledger.record_aliases.assert_not_called()

    def test_retained_custom_success_recovers_original_attempt_without_replay(self):
        from modules.submit_runner import recover_verification_tabs
        from modules.submit_state import SubmitRun
        from modules.generic_inputs import load_jobs
        from modules.external_apply import ExternalApplicationLedger
        text="Success\n\nThank you for your interest! We'll get back to you as soon as possible."
        with TemporaryDirectory() as tmp,patch('modules.submission_tracking.publish_checkpoint'):
            job=load_jobs(url='https://jobs.ashbyhq.com/example/abcdefab-cdef-4abc-8abc-abcdefabcdef')[0]
            root=Path(tmp);report=root/'report.json'
            report.write_text(json.dumps({'resolved_url':job['url'],'attachment':{'name':'resume.pdf'},'resume':{'pdf_sha256':'a'*64}}))
            run=SubmitRun(root/'run',jobs=[job]);ledger=ExternalApplicationLedger(root/'ledger.json')
            try:
                run.update(job,status='submission_uncertain',attempt_id='original',tab_handle='retained',preparation_report=str(report))
                browser=Mock();browser.read.return_value={'url':job['url'],'headings':[text],'application_success':[text]}
                driver=Mock()
                with patch('modules.submit_runner.SubmissionBrowser',return_value=browser):recover_verification_tabs(driver,run,ledger)
                state=run.rows()[0][1]
                self.assertEqual((state['status'],state['attempt_id']),('applied','original'))
                self.assertTrue(state['confirmation_verified']);driver.get.assert_not_called()
                self.assertEqual(ledger._read()[job['key']]['status'],'applied')
            finally:run.close()

    def test_completion_date_requires_policy_and_signature_context(self):
        from datetime import datetime
        from modules.generic_submit import unknown_answers
        resolver=PreparationResolver({}, {'signature_date_policy':'completion_date'})
        q=dict(label='Date',name='eeo[disabilitySignatureDate]',kind='date',required=True,fields=[],options=[])
        with patch('modules.generic_prepare.datetime') as clock:
            clock.now.return_value=datetime(2026,10,21,23,59)
            answer=resolver.resolve(q,'lever')
            self.assertEqual(answer.value,'2026-10-21')
            self.assertEqual(answer.source,'user_policy:completion_date')
            text=resolver.resolve({**q,'kind':'text','label':'Date signed'},'generic')
            self.assertEqual(text.value,'10/21/2026')
            self.assertFalse(resolver.resolve({**q,'max':'2026-10-20'},'lever').resolved)
            for label in ('Date of birth','Employment start date','Date'):
                self.assertFalse(resolver.resolve({**q,'name':'other','label':label},'generic').resolved)
        self.assertFalse(PreparationResolver({},{}).resolve(q,'lever').resolved)
        self.assertEqual(unknown_answers({'questions':[{'name':q['name'],'question':'Date',
            'status':'prepared','source':answer.source}]}),[])

    def test_private_date_policy_is_scoped_and_validated(self):
        from modules.submit_runner import submit_profile
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'private.json';path.write_text(json.dumps({'signature_date_policy':'completion_date'}))
            original={'candidate':{},'question_config':{}}
            result=submit_profile(original,path)
            self.assertEqual(result['question_config']['signature_date_policy'],'completion_date')
            self.assertEqual(original['question_config'],{})
            path.write_text(json.dumps({'signature_date_policy':'guess'}))
            with self.assertRaisesRegex(ValueError,'Signature date policy'):submit_profile(original,path)

    def test_completion_date_policy_replaces_only_a_stale_signature_date(self):
        from datetime import datetime
        field={**self.field('01/01/2020'),'name':'signatureDate','question':'Date signed','label':'Date signed'}
        browser=Mock(actions=[]);browser.read.side_effect=lambda:{'fields':[field]}
        resolver=PreparationResolver({}, {'signature_date_policy':'completion_date'})
        with patch('modules.generic_prepare.datetime') as clock,patch('modules.generic_prepare.fill_native',side_effect=lambda d,q,v:field.update(value=v)) as write:
            clock.now.return_value=datetime(2026,10,21,23,59)
            result=fill_fields(browser,{'fields':[field]},resolver,'generic',set())
            self.assertEqual(field['value'],'10/21/2026');self.assertTrue(result[0]['authoritative'])
            write.assert_called_once()
            field.update(name='dob',question='Date of birth',label='Date of birth',value='01/01/2020')
            write.reset_mock();fill_fields(browser,{'fields':[field]},resolver,'generic',set())
            write.assert_not_called()

    def test_dei_wording_never_falls_back_to_first_option(self):
        resolver=PreparationResolver({}, {'dei_choice_policy':'prefer_not_to_answer','unanswered_choice_policy':'first_option'})
        for label in ('Are you Hispanic or Latino?','Do you identify as transgender?','Indigenous identity'):
            q=dict(label=label,name='identity',kind='select',required=True,fields=[],options=['Yes','No','Prefer not to answer'])
            answer=resolver.resolve(q,'generic')
            self.assertEqual((answer.value,answer.source),('Prefer not to answer','user_policy:dei_opt_out'))

    def test_explicit_retry_preserves_confirmed_and_uncertain_attempts(self):
        from modules.submit_state import SubmitRun
        from modules.generic_inputs import load_jobs
        with TemporaryDirectory() as tmp,patch('modules.submission_tracking.publish_checkpoint'):
            jobs=[*load_jobs(url='https://example.test/jobs/1'),
                *load_jobs(url='https://example.test/jobs/2'),*load_jobs(url='https://example.test/jobs/3')]
            run=SubmitRun(Path(tmp)/'run',jobs=jobs)
            try:
                run.update(jobs[0],status='applied',attempt_id='confirmed',retryable=False)
                run.update(jobs[1],status='blocked',retryable=True,reason='Old blocker')
                run.update(jobs[2],status='submission_uncertain',attempt_id='uncertain',retryable=False)
                ledger=Mock();ledger.protected.return_value=False
                self.assertEqual(requeue_failed(run,ledger),1)
                states=[s for _,s in run.rows()]
                self.assertEqual([s['status'] for s in states],['applied','pending','submission_uncertain'])
                self.assertEqual(states[0]['attempt_id'],'confirmed');self.assertEqual(states[2]['attempt_id'],'uncertain')
                self.assertEqual(states[1]['reason'],'')
            finally:run.close()

    def test_opaque_cursor_advances_on_filtered_empty_page(self):
        from modules.kernel_challenges import KernelChallenges
        runtime=Mock();page=Mock(items=[]);page.next_page_info.return_value=Mock(params={'offset':90210})
        runtime.client.browsers.telemetry.events.return_value=page
        c=KernelChallenges(runtime,1);c.offset=711;c.telemetry()
        self.assertEqual(c.offset,90210)
        runtime.session_observer.assert_called_once_with({'type':'telemetry_cursor','cursor_offset':90210,'page_correlated':False})

    def test_verified_replacement_preserves_input_history_and_confirmed_job(self):
        from modules.submit_state import SubmitRun
        from modules.generic_inputs import load_jobs
        with TemporaryDirectory() as tmp,patch('modules.submission_tracking.publish_checkpoint'):
            jobs=load_jobs(url='https://example.test/jobs/old')+load_jobs(url='https://example.test/jobs/confirmed')
            run=SubmitRun(Path(tmp)/'run',jobs=jobs)
            try:
                original=(run.directory/'input.json').read_bytes()
                run.update(jobs[0],status='blocked',retryable=False)
                run.update(jobs[1],status='applied',attempt_id='protected')
                replacement=load_jobs(url='https://example.test/jobs/new')[0]
                run.replace_unsubmitted(jobs[0]['key'],replacement,evidence='fixture proof')
                self.assertEqual((run.directory/'input.json').read_bytes(),original)
                self.assertEqual(run.export()['active_total'],2)
                self.assertEqual(run.export()['counts'],{'discarded':1,'applied':1,'pending':1})
                with self.assertRaisesRegex(ValueError,'cannot be replaced'):
                    run.replace_unsubmitted(jobs[1]['key'],load_jobs(url='https://example.test/jobs/other')[0],evidence='fixture')
            finally:run.close()

    def test_kernel_diagnostics_do_not_store_query_body_or_error_messages(self):
        from modules.kernel_browser import KernelBrowser
        runtime=object.__new__(KernelBrowser);runtime.settings={'diagnostics':True};runtime.session_observer=Mock()
        page=Mock();callbacks={}
        page.on.side_effect=lambda name,handler:callbacks.setdefault(name,handler)
        with patch('modules.browser_runtime.PlaywrightActions.register_page',return_value='target'):
            KernelBrowser.register_page(runtime,page)
        request=Mock(url='https://example.test/api/parse?token=PRIVATE',method='POST')
        callbacks['requestfailed'](request);callbacks['pageerror'](RuntimeError('PRIVATE applicant answer'))
        events=[call.args[0] for call in runtime.session_observer.call_args_list]
        self.assertNotIn('PRIVATE',json.dumps(events));self.assertEqual(events[0]['website_path'],'/api/parse')


@skipUnless(os.environ.get('JOBROBO_PLAYWRIGHT_TESTS')=='1','Opt-in local browser fixture')
class ValidationRecoveryBrowserTests(TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        from modules.browser_runtime import PlaywrightActions
        self.pw=sync_playwright().start()
        chrome=self.pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        self.driver=PlaywrightActions(self.pw,chrome);self.addCleanup(self.driver.quit)
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.pdf=Path(self.temp.name)/'resume.pdf';self.pdf.write_bytes(b'fixture resume')
        self.posts=[];self.bodies={};self.response_status={}
        def route(r):
            path=r.request.url.split('jobrobo.test')[-1]
            if r.request.method=='POST':self.posts.append(path)
            body=self.bodies.get((path,r.request.method),self.bodies.get(path,''))
            r.fulfill(status=self.response_status.get(path,200),content_type='text/html',body=body)
        self.driver.context.route('https://jobrobo.test/**',route)

    def html(self, fields):
        job={'@type':'JobPosting','title':'Fixture Engineer','hiringOrganization':{'name':'Fixture'},
             'description':'Build reliable distributed systems with Python and cloud platforms. '*8}
        return '<meta charset="utf-8"><title>Fixture Engineer @ Fixture</title><script type="application/ld+json">'+json.dumps(job)+'</script><h1>Fixture Engineer</h1>'+fields

    def prepare(self,path,**kwargs):
        from modules.direct_careers_apply import digest
        return prepare_url('https://jobrobo.test'+path,driver=self.driver,output_dir=Path(self.temp.name)/'reports',
            candidate=kwargs.pop('candidate',{'full_name':'Fixture Applicant','email':'fixture@example.test','phone':'5550100','city':'San Francisco','state':'California','country':'United States'}),
            question_config={},resume_provider=lambda job,root:{'pdf':str(self.pdf),'pdf_sha256':digest(self.pdf),'job_id':'fixture'},settle=.03,**kwargs)

    def test_intermediary_queue_after_one_submit_keeps_employer_outcome_pending(self):
        from modules.generic_submit import SubmissionBrowser, submit_ready
        from modules.external_apply import ExternalApplicationLedger
        self.bodies['/queue-handoff']=self.html('<form method=post><input type=file name=resume><button type=submit>Submit application</button></form>')
        self.bodies[('/queue-handoff','POST')]=self.html("<h2>You're in the queue</h2><p>We'll submit your application within 24 hours.</p>")
        ledger=ExternalApplicationLedger(Path(self.temp.name)/'queue-ledger.json');run=Mock()
        report=self.prepare('/queue-handoff',browser_class=SubmissionBrowser,on_ready=lambda b,r,root:
            submit_ready(b,r,root,job={'id':'queue','url':'https://jobrobo.test/queue-handoff'},run=run,ledger=ledger,
                         attempt_id='queue',pause='never',confirmation_timeout=2))
        self.assertEqual(report['status'],'submission_uncertain',report['blockers'])
        self.assertTrue(report['external_submission_pending']);self.assertTrue(ledger.protected('https://jobrobo.test/queue-handoff'))
        self.assertEqual(self.posts,['/queue-handoff'])

    def test_formatted_phone_with_e164_proxy_is_prepared_without_submit(self):
        self.bodies['/masked-phone']=self.html('''<form><label>Phone number<input name=phone_display type=tel required></label>
          <input name=phone_e164 type=hidden><input type=file name=resume><button type=submit>Submit application</button></form>
          <script>document.querySelector('[name=phone_display]').oninput=e=>{let n=e.target.value.replace(/\\D/g,'').replace(/^1(?=\\d{10}$)/,'');
          if(n.length===10)e.target.value='('+n.slice(0,3)+') '+n.slice(3,6)+'-'+n.slice(6);
          document.querySelector('[name=phone_e164]').value='+1'+n;};</script>''')
        report=self.prepare('/masked-phone',candidate={'phone':'+15551234567','country':'United States'})
        self.assertEqual(report['status'],'prepared',report['blockers'])
        self.assertEqual(self.driver.page.locator('[name=phone_e164]').input_value(),'+15551234567')
        self.assertEqual(self.posts,[])

    def test_resume_analysis_gateway_error_is_reported_before_submit(self):
        self.response_status['/resume/analyze']=502
        self.bodies['/upload-error']=self.html('''<form><label><span id=receipt>Resume</span>
          <input type=file style="display:none"></label><button type=submit>Submit application</button></form>
          <script>document.querySelector('input').onchange=e=>{const file=e.target.files[0];
          document.getElementById('receipt').textContent='Uploading '+file.name+'…';
          fetch('/resume/analyze',{method:'POST',body:file});e.target.value='';};</script>''')
        report=self.prepare('/upload-error')
        self.assertEqual(report['status'],'failed')
        self.assertIn('HTTP 502',' '.join(report['blockers']))
        self.assertEqual(self.posts,['/resume/analyze'])

    def test_captcha_callback_hidden_submit_continues_once_after_delay(self):
        from modules.generic_submit import SubmissionBrowser
        self.bodies['/captcha-continuation']=self.html('''<form method=post id=application>
          <label>Email<input name=email type=email required></label>
          <textarea name=h-captcha-response style="display:none"></textarea>
          <div class=h-captcha></div><input id=callback type=submit hidden>
          <button id=start type=button>Submit application</button></form>
          <script>window.posts=0;document.querySelector('form').onsubmit=e=>{e.preventDefault();window.posts++};
          document.getElementById('start').onclick=()=>setTimeout(()=>{
            document.querySelector('textarea').value='synthetic-solver-response';document.getElementById('callback').click();
          },1100);</script>''')
        browser=SubmissionBrowser(self.driver,settle=.01)
        browser.navigate('https://jobrobo.test/captcha-continuation')
        self.driver.page.locator('[name=email]').fill('fixture@example.test')
        self.driver.execute_script("return window.__jobroboPrepare.armSubmit(document.getElementById('start'))")
        self.driver.page.locator('#start').click();self.driver.page.wait_for_timeout(1250)
        self.assertEqual(self.driver.execute_script('return window.posts'),1)
        self.driver.page.locator('#callback').evaluate('e=>e.click()')
        self.assertEqual(self.driver.execute_script('return window.posts'),1)
        self.assertEqual(self.driver.execute_script('return window.__jobroboPrepare.actions.filter(x=>x==="final-activation").length'),1)

    def test_captcha_callback_native_submit_continues_after_delay(self):
        from modules.generic_submit import SubmissionBrowser
        self.bodies['/captcha-native']=self.html('''<form method=post id=application>
          <textarea name=h-captcha-response hidden></textarea>
          <button id=start type=button>Submit application</button></form>
          <script>document.getElementById('start').onclick=()=>setTimeout(()=>{
            document.querySelector('textarea').value='synthetic-response';document.querySelector('form').submit();
          },1100);</script>''')
        browser=SubmissionBrowser(self.driver,settle=.01);browser.navigate('https://jobrobo.test/captcha-native')
        self.driver.execute_script("return window.__jobroboPrepare.armSubmit(document.getElementById('start'))")
        self.driver.page.locator('#start').click();self.driver.page.wait_for_timeout(1400)
        self.assertEqual(self.posts,['/captcha-native'])

    def test_captcha_continuation_rejects_changed_answers_other_forms_and_missing_token(self):
        from modules.generic_submit import SubmissionBrowser
        self.bodies['/captcha-negative']=self.html('''<form id=application>
          <label>Email<input name=email type=email required value="fixture@example.test"></label>
          <textarea name=h-captcha-response hidden></textarea><input id=callback type=submit hidden>
          <button id=start type=button>Submit application</button></form>
          <form id=other><input type=submit id=other-submit></form>
          <script>window.posts=0;for(const f of document.forms)f.onsubmit=e=>{e.preventDefault();window.posts++};</script>''')
        for mode in ('changed','changed_action','other','missing','prepare'):
            self.driver.switch_to.new_window('tab')
            browser=SubmissionBrowser(self.driver,settle=.01) if mode!='prepare' else __import__('modules.generic_prepare',fromlist=['PreparationBrowser']).PreparationBrowser(self.driver,settle=.01)
            browser.navigate('https://jobrobo.test/captcha-negative')
            self.driver.execute_script("return window.__jobroboPrepare.armSubmit(document.getElementById('start'))")
            self.driver.page.locator('#start').click();self.driver.page.wait_for_timeout(1050)
            if mode!='missing':self.driver.page.locator('textarea').evaluate("e=>e.value='synthetic-response'")
            if mode=='changed':self.driver.page.locator('[name=email]').fill('changed@example.test')
            if mode=='changed_action':self.driver.page.locator('#application').evaluate("e=>e.action='/another-job'")
            self.driver.page.locator('#other-submit' if mode=='other' else '#callback').evaluate('e=>e.click()')
            self.assertEqual(self.driver.execute_script('return window.posts'),0,mode)

    def test_upload_auto_advance_uses_matching_response_without_final_submit(self):
        self.bodies['/auto-upload']=self.html('''<form><label>Resume<input type=file style="display:none"></label></form>
          <script>document.querySelector('input').onchange=e=>{const data=new FormData();data.append('resume',e.target.files[0]);
          fetch('/resume/analyze',{method:'POST',body:data}).then(r=>{if(r.ok)location.href='/auto-upload/confirm'});e.target.value='';};</script>''')
        self.bodies['/auto-upload/confirm']=self.html('''<form onsubmit="window.finalSubmit=true;return false">
          <label>Name<input name=name required></label><button type=submit>Submit application</button></form>''')
        report=self.prepare('/auto-upload')
        self.assertEqual(report['status'],'prepared',report['blockers'])
        self.assertEqual(report['attachment']['method'],'browser_file_sha256_and_upload_response')
        self.assertIn(report['attachment']['upload_response']['request_match'],{'pdf_bytes','multipart_filename'})
        self.assertTrue(report['resolved_url'].endswith('/confirm'))
        self.assertEqual(self.posts,['/resume/analyze']);self.assertIsNone(self.driver.execute_script('return window.finalSubmit'))

    def test_unrelated_successful_request_does_not_verify_a_resume(self):
        self.bodies['/proof']=self.html('<p>Fixture page</p>')
        self.driver.get('https://jobrobo.test/proof')
        self.driver.begin_resume_upload(b'unique expected file','resume.pdf')
        try:
            self.driver.page.evaluate("async()=>await fetch('/resume/analyze',{method:'POST',body:'a different file'})")
            self.assertIsNone(self.driver.resume_upload_receipt)
        finally:self.driver.end_resume_upload()

    def test_auto_advanced_upload_can_submit_once_with_verified_receipt(self):
        from modules.generic_submit import SubmissionBrowser, submit_ready
        from modules.submit_state import SubmitRun
        from modules.external_apply import ExternalApplicationLedger
        from modules.generic_inputs import load_jobs
        self.bodies['/verified-upload']=self.html('''<form><label>Resume<input type=file style="display:none"></label></form>
          <script>document.querySelector('input').onchange=e=>{const data=new FormData();data.append('resume',e.target.files[0]);
          fetch('/resume/analyze',{method:'POST',body:data}).then(r=>{if(r.ok)location.href='/verified-upload/confirm'});e.target.value='';};</script>''')
        self.bodies['/verified-upload/confirm']=self.html('<form method=post><label>Name<input name=name required></label><button type=submit>Submit application</button></form>')
        self.bodies[('/verified-upload/confirm','POST')]=self.html('<h2>Application received</h2>')
        job=load_jobs(url='https://jobrobo.test/verified-upload')[0]
        with patch('modules.submission_tracking.publish_checkpoint'):
            run=SubmitRun(Path(self.temp.name)/'upload-run',jobs=[job]);self.addCleanup(run.close)
            ledger=ExternalApplicationLedger(Path(self.temp.name)/'upload-ledger.json')
            report=self.prepare('/verified-upload',browser_class=SubmissionBrowser,on_ready=lambda b,r,root:
                submit_ready(b,r,root,job=job,run=run,ledger=ledger,attempt_id='verified-upload',pause='never',confirmation_timeout=2))
        self.assertEqual(report['status'],'applied',report['blockers'])
        self.assertEqual(self.posts,['/resume/analyze','/verified-upload/confirm'])

    def test_location_with_country_eligibility_context_selects_country(self):
        self.bodies['/country-location']=self.html('''<form><input type=file name=resume>
          <div class="ashby-application-form-field-entry"><label id=loclabel for=loc>Location</label>
          <div class="ashby-application-form-question-description">Not all roles are open in all countries. Review eligible remote work locations.</div>
          <input id=loc name=location role=combobox aria-labelledby=loclabel aria-controls=choices required>
          <div id=choices role=listbox style="display:none"></div></div><button type=submit>Submit application</button></form>
          <script>const loc=document.getElementById('loc'),choices=document.getElementById('choices');
          function show(){choices.style.display='block';loc.setAttribute('aria-expanded','true');
          choices.innerHTML=loc.value.toLowerCase().includes('united')?'<div role="option">United States</div>':'No results';
          const option=choices.querySelector('[role=option]');if(option)option.onclick=()=>{loc.value='United States';loc.setAttribute('aria-valuetext','United States');loc.setAttribute('aria-expanded','false');choices.style.display='none';};}
          loc.onfocus=show;loc.onkeyup=show;</script>''')
        report=self.prepare('/country-location')
        self.assertEqual(report['status'],'prepared',report['blockers'])
        location=next(q for q in report['questions'] if q['name']=='location')
        self.assertEqual(location['source'],'candidate_config:country')
        self.assertEqual(self.driver.page.locator('#loc').input_value(),'United States')
        self.assertEqual(self.posts,[])

    def test_native_server_action_continue_posts_once_and_never_final_submits(self):
        self.bodies['/wizard']=self.html('<form method=post><label>Name<input name=name required></label><label>Email<input name=email required></label><input type=hidden name="$ACTION_ID_fixture"><button type=submit>Continue →</button></form>')
        self.bodies[('/wizard','POST')]=self.html('<form onsubmit="window.finalSubmit=true;return false"><label>Resume<input name=resume type=file required></label><label>Phone<input name=phone required></label><button type=submit>Submit application</button></form>')
        result=self.prepare('/wizard')
        self.assertEqual(result['status'],'prepared',result['blockers'])
        self.assertEqual(self.posts,['/wizard']);self.assertIsNone(self.driver.execute_script('return window.finalSubmit'))

    def test_custom_ashby_success_copy_confirms_one_activation(self):
        from modules.generic_submit import SubmissionBrowser, submit_ready
        from modules.submit_state import SubmitRun
        from modules.external_apply import ExternalApplicationLedger
        from modules.generic_inputs import load_jobs
        self.bodies['/custom-success']=self.html('''<form method=post><label>Name<input name=name required></label>
          <label>Resume<input type=file name=resume required></label><button type=submit>Submit application</button></form>''')
        self.bodies[('/custom-success','POST')]=self.html('''<div class="ashby-application-form-success-container">
          <h2>Success</h2><p>Thank you for your interest! We'll get back to you as soon as possible.</p></div>''')
        job=load_jobs(url='https://jobrobo.test/custom-success')[0]
        with patch('modules.submission_tracking.publish_checkpoint'):
            run=SubmitRun(Path(self.temp.name)/'success-run',jobs=[job]);self.addCleanup(run.close)
            ledger=ExternalApplicationLedger(Path(self.temp.name)/'success-ledger.json')
            report=self.prepare('/custom-success',browser_class=SubmissionBrowser,on_ready=lambda b,r,root:
                submit_ready(b,r,root,job=job,run=run,ledger=ledger,attempt_id='custom-copy',pause='never',confirmation_timeout=2))
        self.assertEqual(report['status'],'applied',report['blockers'])
        self.assertEqual(self.posts,['/custom-success'])

    def test_parser_autofill_is_preserved_without_ai_or_clear(self):
        self.bodies['/parse']=self.html('<form onsubmit="return false"><label>Name<input name=name required></label><label>Email<input name=email required></label><label>Resume<input name=resume type=file required onchange="setTimeout(()=>{document.querySelector(\'[name=name]\').value=\'Parsed Applicant\'},200)"></label><button type=submit>Submit application</button></form>')
        result=self.prepare('/parse')
        self.assertEqual(result['status'],'prepared',result['blockers'])
        self.assertEqual(self.driver.find_element('name','name').get_attribute('value'),'Parsed Applicant')
        self.assertFalse(any(a['action']=='fill' and a.get('field')=='Name' for a in result['actions']))

    def test_non_aria_location_requires_typing_and_committed_hidden_proxy(self):
        self.bodies['/location']=self.html('''<form onsubmit="return false"><label>Email<input name=email required></label><label>Resume<input name=resume type=file required></label>
            <label>Current location *<div class=application-field><input name=location id=location-input class=location-input required
              onkeyup="if(this.value.includes('San Francisco'))document.getElementById('results').hidden=false"
              onblur="if(!document.getElementById('selected-location').value)this.value=''">
              <input type=hidden name=selectedLocation id=selected-location><div class=dropdown-results id=results hidden>
              <div onclick="document.getElementById('location-input').value=this.textContent;document.getElementById('selected-location').value='committed';this.parentElement.hidden=true">San Francisco, CA, USA</div></div></div></label>
            <button type=submit>Submit application</button></form>''')
        result=self.prepare('/location')
        self.assertEqual(result['status'],'prepared',result['blockers'])
        self.assertEqual(self.driver.find_element('name','selectedLocation').get_attribute('value'),'committed')

    def test_wrong_initial_posting_stops_before_resume_or_fill(self):
        self.bodies['/different']=self.html('<label>Name<input name=name required></label><label>Resume<input name=resume type=file></label>')
        result=self.prepare('/different',job_hint={'title':'Unrelated Original Role'})
        self.assertEqual(result.get('access_outcome'),'posting_identity_changed')
        self.assertNotIn('resume',result);self.assertFalse(any(a['action']=='fill' for a in result['actions']))

    def test_reconnect_reads_retained_records_without_context_wide_binding(self):
        from modules.browser_runtime import PlaywrightActions
        self.bodies['/retained']=self.html('<p>Retained page</p>')
        self.driver.get('https://jobrobo.test/retained')
        self.driver.execute_script("sessionStorage.setItem('jobrobo.manual.fixture',JSON.stringify({token:'fixture',activations:1}))")
        with patch.object(self.driver.context,'expose_binding',side_effect=AssertionError('must not register across existing frames')):
            restored=PlaywrightActions(self.pw,self.driver.browser,context=self.driver.context)
        reader=restored.target_reader(restored.current_window_handle,token='fixture')
        states,_=reader.read()
        self.assertTrue(any(s.get('record',{}).get('activations')==1 for s in states))

    def test_post_submit_email_verification_is_retained_without_replay(self):
        import html
        from modules.submit_runner import run_submissions
        from modules.generic_inputs import load_jobs
        from modules.direct_careers_apply import digest
        script="event.preventDefault();fetch('/receive',{method:'POST'});document.body.innerHTML='<h1>Fixture Engineer</h1><p>A verification code was sent. Enter the 8-character code.</p><input id=security-input-0 required>';return false"
        self.bodies['/gated']=self.html('<form onsubmit="'+html.escape(script,quote=True)+'"><label>Email<input name=email required></label><label>Resume<input name=resume type=file required></label><button type=submit>Submit application</button></form>')
        config=Path(self.temp.name)/'config';config.mkdir();(config/'search.py').write_text('max_applications_per_run = 10\n')
        with patch('modules.submission_tracking.publish_checkpoint'):
            result=run_submissions(load_jobs(url='https://jobrobo.test/gated'),run_dir=Path(self.temp.name)/'run',
                pause='never',driver_factory=lambda:self.driver,config_dir=config,
                services={'candidate':{'email':'fixture@example.test'},'question_config':{},
                    'resume_provider':lambda job,root:{'pdf':str(self.pdf),'pdf_sha256':digest(self.pdf),'job_id':'fixture'}})
        self.assertEqual(result['counts'],{'awaiting_email_verification':1})
        self.assertEqual(self.posts,['/receive'])
        self.assertTrue(result['jobs'][0]['manual_tab']['verification_after_submit'])
