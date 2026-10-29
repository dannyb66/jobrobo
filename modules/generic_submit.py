"""Single-activation submission, guarded review, and posting-scoped confirmation."""
import hashlib
import json
from pathlib import Path
import re
import time

from .generic_prepare import PreparationBrowser, GUARD_JS, FINAL, NEXT, canonical_url, fingerprint, _resume_field, extract_job, email_verification_required, _accepted_upload_response
from .external_apply import missing_required, identify_ats, confirmation_identity, _confirmed, ExternalApplicationResult
from .submit_state import now


class SubmissionBrowser(PreparationBrowser):
    submission_enabled = True
    guard_script = GUARD_JS.replace('const submissionMode = false;', 'const submissionMode = true;')


def external_dispatch_pending(state):
    """An intermediary's queued handoff is not an employer confirmation."""
    queued=any(re.search(r"you['’]re in (?:the )?queue|application (?:is )?(?:queued|pending dispatch)",h,re.I)
               for h in state.get('headings',[]))
    promised=re.search(r"\b(?:we['’]ll|we will) submit your application\b",state.get('text',''),re.I)
    return bool(queued and promised and not state.get('forms'))


def unknown_answers(report):
    """Classify evidence sources, never the model's own confidence score."""
    latest = {(q['name'], q['question']): q for q in report['questions']}
    known = ('candidate_config:', 'question_config', 'resume_profile:', 'application_context:', 'user_policy:dei_opt_out', 'user_policy:completion_date')
    return [q['question'] for q in latest.values() if q['status'] == 'prepared' and
            (q.get('label_source') == 'ai_observed_context' or not q['source'].startswith(known))]


def review_values(state):
    values=[]
    for field in state['fields']:
        if not field.get('visible') or field['type'] in {'file','hidden','button','submit'}: continue
        label=field.get('question') or field.get('label')
        if field['type'] in {'radio','checkbox'}:
            label += ' — '+str(field.get('label') or field.get('value') or '')
            value=bool(field.get('checked'))
        else:
            value=field.get('value')
            if field.get('options'):
                value=next((o['label'] for o in field['options'] if o.get('value')==value),value)
        values.append((label,value))
    return values



CHALLENGE_PROBE = (
    "(function(){const f=[...document.querySelectorAll('iframe[src*=hcaptcha],iframe[src*=recaptcha],iframe[src*=turnstile]')];"
    "return f.some(e=>{const r=e.getBoundingClientRect();"
    "return r.height>150&&getComputedStyle(e).visibility!=='hidden';});})()"
)


def _await_painted_challenge(browser, timeout=12.0):
    """Block until a challenge paints, or the window closes.

    An invisible widget only draws its frame once Submit runs it, so asking the
    moment we click finds nothing and reads as "no CAPTCHA". Poll instead, and
    stop early when it appears so a real one is never waited out.
    """
    runtime = getattr(browser, 'driver', None)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if runtime.execute_script(CHALLENGE_PROBE):
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


CONSENT_JS = r"""
const want=/^(accept|accept all|allow all|got it|agree|ok)$/i;
const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
const hit=[...document.querySelectorAll('button,a[role=button]')]
  .filter(e=>visible(e)&&want.test((e.textContent||'').trim()))
  .filter(e=>/cookie|consent|privacy|gdpr/i.test(
      (e.closest('[class*=cookie],[id*=cookie],[class*=consent],[id*=consent],[class*=banner]')||{}).className||'') ||
      /accept/i.test((e.textContent||'').trim()));
if(!hit.length)return null;
hit[0].click();
return (hit[0].textContent||'').trim();
"""


def _accept_cookie_banner(browser):
    """Dismiss a consent banner if one is up; it overlays the submit button."""
    try:
        return browser.driver.execute_script(CONSENT_JS)
    except Exception:
        return None


CODE_FIELD_JS = r"""
const f=[...document.querySelectorAll('input')].find(e=>{
 const id=(e.id||'')+' '+(e.name||'');
 return (id.includes('security-input')||id.includes('verification')||id.includes('code'))
   && e.getClientRects().length;});
return f||null;
"""


def complete_email_verification(browser, *, timeout=120, wait=time.sleep):
    """Fill an emailed verification code into the retained form.

    Returns the code on success, else None. Off unless a mailbox is configured;
    the caller keeps the tab open either way.
    """
    from . import email_codes
    if not email_codes.configured():
        return None
    driver = browser.driver
    try:
        field = driver.execute_script(CODE_FIELD_JS)
    except Exception:
        field = None
    if field is None:
        return None
    started = time.time()
    code = email_codes.await_code(timeout=timeout, after=started)
    if not code:
        return None
    try:
        field.clear()
        field.send_keys(code)
    except Exception:
        return None
    # Submitting the code is the site's own button, never the application Submit.
    try:
        button = driver.execute_script(
            "const f=arguments[0];const s=f.closest('form')||document;"
            "return [...s.querySelectorAll('button,input[type=submit]')]"
            ".find(b=>/verify|continue|submit|confirm/i.test((b.textContent||b.value||'')));", field)
        if button is not None:
            button.click()
    except Exception:
        pass
    wait(2)
    return code


def _activate(*, driver, element):
    """Click the final Submit, falling back to a DOM click.

    Sites raise ElementClickInterceptedException over sticky footers/cookie
    banners that paint above the button. A DOM click still runs the page's own
    handler, and the caller has already armed the submit guard.
    """
    try:
        element.click()
        return 'native'
    except Exception as error:
        if type(error).__name__ != 'ElementClickInterceptedException' or not element.is_displayed():
            raise
        driver.execute_script('arguments[0].click()', element)
        return 'script'


def _identity_ok(current_url, expected_url, *, allow_local=False):
    expected = identify_ats(expected_url)
    if expected:
        actual = confirmation_identity(current_url)
        return actual is not None and actual.key == expected.key
    try:
        actual = canonical_url(current_url, allow_local=allow_local, normalize_posting=False)
        initial = canonical_url(expected_url, allow_local=allow_local, normalize_posting=False)
        if actual == initial or actual.startswith(initial.rstrip('/')+'/'):return True
        # UUID application wizards commonly redirect from /confirm to /done.
        # Bind only that final path segment, never an organization UUID above
        # another job path or a shared, identifier-free success page.
        from urllib.parse import urlsplit
        first,second=urlsplit(initial),urlsplit(actual)
        match=re.fullmatch(r'(.*/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/(?:confirm|review|application|apply)',first.path,re.I)
        completion=re.fullmatch(r'(.*/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/(?:success|thanks|thank-you|confirmation|submitted|done|complete|completed|sent)',second.path,re.I)
        return bool(match and completion and (first.scheme,first.netloc)==(second.scheme,second.netloc)
                    and match.group(1)==completion.group(1))
    except ValueError:
        return False


def validate_final(browser, report):
    """Refresh everything immediately before enabling the one final action."""
    context=browser.context
    try:
        browser.top()
        top=browser.read()
    finally:
        browser.enter(context)
    state = browser.read()
    if not _identity_ok(browser.driver.current_url, report['resolved_url'], allow_local=browser.allow_local):
        return state, None, 'Posting identity changed'
    # Structured JDs remain available even when their application lives in a
    # frame. A changed JD requires preparation of a newly bound resume.
    if (top.get('job') or {}).get('description'):
        current=extract_job(top)['description']
        if hashlib.sha256(current.encode('utf-8')).hexdigest()!=report['jd_sha256']:
            return state,None,'Job description changed; restart preparation before submitting'
    required = missing_required([f for f in state['fields'] if not f.get('upload_satisfied')])
    if required or state.get('challenge'):
        reasons=list(dict.fromkeys([*report.get('blockers', []), *required,
                                   *(['Access challenge remains'] if state.get('challenge') else [])]))
        return state, None, '; '.join(reasons)
    pdf = Path(report['resume']['pdf'])
    expected = report['resume']['pdf_sha256']
    if not pdf.is_file() or hashlib.sha256(pdf.read_bytes()).hexdigest() != expected:
        return state, None, 'Resume changed since preparation'
    attachment = report['attachment']
    capture = (state.get('guard') or {}).get('uploads', [])
    upload = _resume_field(state['fields'])
    native = upload and any(f['name'] == attachment['name'] and f['size'] == attachment['size'] for f in upload['files'])
    receipt = attachment['name'] in state.get('file_receipts', [])
    hashed = any(f.get('sha256') == expected and f.get('name') == attachment['name'] and not f.get('pending') for f in capture)
    response=_accepted_upload_response(browser.driver,attachment['name'],expected,
                                      browser_captured=attachment.get('browser_capture_verified',False))
    network_verified=attachment.get('method')=='browser_file_sha256_and_upload_response' and response is not None
    if upload and upload.get('files') and not native:
        return state,None,'A different resume is selected'
    if not (hashed and (native or receipt) or network_verified):
        return state, None, 'Exact resume attachment is no longer verified'
    buttons = [b for b in state['buttons'] if FINAL.search(b['text']) and not NEXT.fullmatch(b['text']) and
               (b.get('type') == 'submit' or re.search(r'submit|send application|finish|complete application', b['text'], re.I))]
    if len(buttons) != 1 or not buttons[0]['element'].is_enabled():
        return state, None, 'One enabled final Submit control is required'
    report['review_binding_sha256']=fingerprint({'posting':report['resolved_url'],'jd':report['jd_sha256'],
        'pdf':expected,'profile':report.get('input_provenance',{}).get('profile_hash'),
        'settings':report.get('input_provenance',{}).get('settings_hash'),
        'fields':[{k:f.get(k) for k in ('name','type','question','required','value','checked','options')}
                  for f in state['fields'] if f.get('visible')]})
    return state, buttons[0], ''


def submit_ready(browser, report, root, *, job, run, ledger, attempt_id, pause='always',
                 review_factory=None, confirmation_timeout=30, poll_interval=.2):
    """Called inside preparation's final context; no other path can submit."""
    unknown = unknown_answers(report)
    incomplete = bool(report.get('blockers'))
    needs_review = pause != 'never' and (pause == 'always' or bool(unknown) or incomplete)
    run.update(job, status='awaiting_review' if needs_review else 'ready', stage='review' if needs_review else 'ready',
               review_reasons=unknown, resume_sha256=report['resume']['pdf_sha256'])
    if needs_review and review_factory is None:
        raise ValueError('Manual review requires a retained-tab handoff')
    review = review_factory(report, unknown) if needs_review else None
    claimed = False; activated = False; started = None; document_id = None; waited_after_submit=False
    expected_urls = [report['resolved_url'], browser.read()['url']]
    aliases = list(dict.fromkeys([report['url'], *expected_urls]))
    top_identity, form_identity = identify_ats(expected_urls[0]), identify_ats(expected_urls[1])
    if top_identity and form_identity and top_identity.key != form_identity.key:
        raise ValueError('Embedded application belongs to a different ATS posting')
    report['posting_aliases'] = aliases
    initial_state=browser.read()
    baseline = set(initial_state.get('headings', [])+initial_state.get('alerts', []))
    report['confirmation_baseline']=sorted(baseline)
    outcome = ExternalApplicationResult('submitting', report['url'], attempt_id=attempt_id,
        resume_name=report['attachment']['name'], resume_sha256=report['resume']['pdf_sha256'])

    def claim():
        nonlocal claimed, document_id
        if not claimed:
            # Ledger first: if the following run-state write fails, the claim
            # remains protected and no second worker can make a duplicate click.
            ledger.record_aliases(outcome, aliases, job['id'])
            claimed = True
            run.update(job, status='awaiting_review' if review else 'submitting', stage='review_armed' if review else 'submitting', attempt_id=attempt_id)
            document_id = browser.driver.execute_script('return window.__jobroboPrepare.documentId')

    def release():
        nonlocal claimed
        if not claimed:
            return True
        proof = browser.driver.execute_script('const s=window.__jobroboPrepare;return s.documentId===arguments[0]?s.disarmSubmit():null', document_id)
        if proof == {'disarmed': True, 'activated': False}:
            ledger.release_aliases(aliases, attempt_id, proof=proof)
            claimed = False
            return True
        return False

    heartbeat = time.monotonic()
    try:
        while True:
            if time.monotonic()-heartbeat >= 15:
                label = 'waiting for employer confirmation' if activated else 'paused for review/manual Submit' if review else 'validating Submit'
                print('[Submit] Still '+label, flush=True)
                run.update(job, stage='waiting_for_confirmation' if activated else 'review_armed' if claimed else 'review')
                heartbeat = time.monotonic()
            # Probe the active context first, then top/frame documents after a
            # navigation; success must be new and remain posting-scoped.
            try:
                state = browser.read()
            except Exception:
                browser.top(); state = browser.read()
            if getattr(browser.driver,'browser_backend',None)=='kernel':
                state['challenge']=state.get('challenge') or browser.driver.challenges.page_active(browser.driver.page)
            current_url = browser.driver.current_url
            fresh = {**state, 'headings': [h for h in state.get('headings', []) if h not in baseline]}
            scoped = (_identity_ok(current_url, report['resolved_url'], allow_local=browser.allow_local) and
                      any(_identity_ok(state['url'], u, allow_local=browser.allow_local) for u in expected_urls))
            guard = browser.driver.execute_script('return window.__jobroboPrepare?{activated:window.__jobroboPrepare.finalActivated,document:window.__jobroboPrepare.documentId}:null')
            possible_activation = activated or claimed and (not guard or guard['document'] != document_id or guard['activated'])
            fresh_messages=[h for h in state.get('headings', [])+state.get('alerts', []) if h not in baseline]
            portal_duplicate = any(re.search(r'\byou (?:have )?(?:already|previously) (?:applied|submitted an application) (?:for|to) (?:this|the) (?:job|role|position)\b',h,re.I) for h in fresh_messages)
            if claimed and possible_activation and scoped and external_dispatch_pending(fresh):
                reason='Application service accepted the request; employer submission is still pending'
                run.update(job,status='submission_uncertain',stage='external_submission_pending',retryable=False,
                           external_submission_pending=True,reason=reason)
                return {'status':'submission_uncertain','external_submission_pending':True,'blockers':[reason]}
            if claimed and possible_activation and scoped and not state.get('challenge') and portal_duplicate:
                outcome.status='duplicate';outcome.reason='Portal reports an existing application'
                ledger.record_aliases(outcome,aliases,job['id'])
                run.update(job,status='duplicate',stage='portal_duplicate',retryable=False,duplicate_source='portal')
                return {'status':'duplicate','portal_duplicate_verified':True,'blockers':[]}
            if claimed and possible_activation and scoped and not state.get('challenge') and _confirmed(fresh):
                outcome.status='applied'; outcome.submitted_at=now(); outcome.reason='Employer submission confirmed'
                ledger.record_aliases(outcome, aliases, job['id'])
                run.update(job, status='applied', stage='confirmed', submitted_at=outcome.submitted_at,
                           retryable=False, attempt_id=attempt_id)
                return {'status': 'applied', 'submitted_at': outcome.submitted_at, 'confirmation_verified': True,
                        'final_review_verified': True, 'blockers': []}
            if (claimed and scoped and state.get('challenge') and not solved_after_submit
                    and getattr(browser.driver, 'browser_backend', None) != 'kernel'):
                # An invisible widget only appears after Submit; solve it here and
                # let the loop re-judge, rather than timing out on the prompt.
                from . import captcha_solver
                if captcha_solver.enabled():
                    run.update(job, status='submitting', stage='captcha_after_submit')
                    if captcha_solver.cleared(captcha_solver.solve(browser.driver)):
                        solved_after_submit = True
                        continue
            if scoped and email_verification_required(state):
                if complete_email_verification(browser):
                    # The code was entered; give the page a beat, then let the
                    # normal confirmation loop judge the result.
                    continue
                target=browser.driver.execute_cdp_cmd('Target.getTargetInfo',{})['targetInfo']['targetId']
                continuation={'target_id':target,'token':attempt_id,'aliases':aliases,
                    'resolved_url':report['resolved_url'],'form_url':state['url'],
                    'baseline':baseline and sorted(baseline) or [],'resume_name':report['attachment']['name'],
                    'resume_sha256':report['resume']['pdf_sha256'],'report_path':str(Path(root)/'report.json'),
                    'activations':1 if possible_activation else 0,'initially_complete':True,
                    'verification_after_submit':bool(possible_activation)}
                run.update(job,status='awaiting_email_verification',stage='email_verification',retryable=False,
                    manual_tab=continuation,verification_after_submit=bool(possible_activation),attempt_id=attempt_id)
                return {'status':'awaiting_email_verification','verification_after_submit':bool(possible_activation),
                    'blockers':['Complete email verification in the retained employer tab; original Submit will not be replayed']}
            if possible_activation:
                if scoped and not state.get('challenge') and any(re.search(r'your form needs corrections|missing entry for required field|field is required|invalid (?:email|phone)',message,re.I) for message in fresh_messages):
                    outcome.status='validation_rejected';outcome.reason='Portal explicitly rejected the application form'
                    ledger.record_aliases(outcome,aliases,job['id'])
                    run.update(job,status='blocked',stage='portal_validation_rejected',retryable=True,reason=outcome.reason)
                    return {'status':'blocked','blockers':['Portal rejected required fields; correct before retrying'],'pre_submit_retryable':True,'portal_validation_rejected':True}
                if state.get('challenge') and not waited_after_submit and getattr(browser.driver,'browser_backend',None)=='kernel':
                    from .kernel_challenges import wait_for_challenge
                    waited_after_submit=True
                    run.update(job,status='submitting',stage='waiting_for_captcha_after_submit')
                    if wait_for_challenge(browser,stage='after_submit') is False:
                        run.update(job,status='submission_uncertain',stage='captcha_timeout_after_submit',retryable=False)
                        return {'status':'submission_uncertain','blockers':['CAPTCHA timeout after possible Submit; inspect employer outcome']}
                    activated=True;started=time.monotonic()
                    continue
                if not activated:
                    activated=True; started=time.monotonic()
                    browser.actions.append({'action':'submit','source':'review_or_explicit_submit_mode','at':now()})
                    run.update(job, status='submitting', stage='waiting_for_confirmation')
                if time.monotonic()-started >= confirmation_timeout:
                    run.update(job, status='submission_uncertain', stage='confirmation_timeout', retryable=False)
                    return {'status':'submission_uncertain','blockers':['Submit may have occurred; inspect needs-review.json before retrying']}
                time.sleep(poll_interval)
                continue
            from .kernel_challenges import wait_for_challenge
            if wait_for_challenge(browser,stage='before_submit') is False:
                if not release():
                    return {'status':'submission_uncertain','blockers':['CAPTCHA timeout after possible activation']}
                run.update(job,status='blocked',stage='captcha_timeout_before_submit',retryable=True)
                return {'status':'blocked','blockers':['CAPTCHA timeout before final activation'],'pre_submit_retryable':True}
            _accept_cookie_banner(browser)
            if getattr(browser.driver, 'browser_backend', None) != 'kernel':
                # Local Chrome has no challenge runtime, so wait for a late
                # widget here rather than letting the click land underneath it.
                _await_painted_challenge(browser)
            state, button, reason = validate_final(browser, report)
            if review and incomplete and not missing_required(state['fields']) and any(NEXT.fullmatch(b['text']) for b in state['buttons']) and not button:
                return {'status':'preparing','blockers':[],'resume_preparation':True}
            if button:
                binding=report['review_binding_sha256']
                if binding!=report.get('last_recorded_review_binding'):
                    run.update(job,review_binding_sha256=binding)
                    report['last_recorded_review_binding']=binding
                claim()
                armed = browser.driver.execute_script('return window.__jobroboPrepare.armSubmit(arguments[0])', button['element'])
                if not armed:
                    raise ValueError('Submission guard could not arm the validated final control')
            else:
                browser.driver.execute_script('window.__jobroboPrepare.disarmSubmit()')
            action = review.poll(state, bool(button), reason) if review else 'submit'
            if action in {'skip', 'stop'}:
                if not release():
                    run.update(job, status='submission_uncertain', stage='review_interrupted_after_possible_submit', retryable=False)
                    return {'status':'submission_uncertain','blockers':['A final activation may have occurred']}
                status = 'deferred' if action == 'skip' else 'awaiting_review'
                run.update(job, status=status, stage='saved_review', retryable=action=='skip')
                return {'status':status,'stop_run':action=='stop'}
            if action == 'submit' and button:
                # Reacquire/revalidate after the review callback; never click
                # a stored reference after the user has edited the form.
                _, button, reason = validate_final(browser, report)
                if not button:
                    if review: continue
                    raise ValueError(reason)
                browser.driver.execute_script('return window.__jobroboPrepare.armSubmit(arguments[0])', button['element'])
                activated=True; started=time.monotonic()
                _accept_cookie_banner(browser)
                run.update(job, status='submitting', stage='waiting_for_confirmation')
                browser.actions.append({'action':'submit','source':'explicit_submit_or_review','at':now()})
                _activate(driver=browser.driver, element=button['element'])
            elif not review and not button:
                if not release():
                    raise ValueError('Cannot establish that no submission occurred')
                run.update(job, status='blocked', stage='final_validation', retryable=True, reason=reason)
                return {'status':'blocked','blockers':[reason]}
            time.sleep(poll_interval)
    except BaseException as error:
        if claimed:
            try: released = release()
            except Exception: released = False
            if not released:
                run.update(job,status='submission_uncertain',stage='submission_interrupted',retryable=False,reason=type(error).__name__)
                if not isinstance(error, Exception): raise
                return {'status':'submission_uncertain','blockers':['Submission outcome requires inspection: '+type(error).__name__]}
        raise
    finally:
        if review:
            review.close()
