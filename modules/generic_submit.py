"""Single-activation submission, guarded review, and posting-scoped confirmation."""
import hashlib
import json
from pathlib import Path
import re
import time

from .generic_prepare import PreparationBrowser, GUARD_JS, FINAL, NEXT, canonical_url, fingerprint, _resume_field, extract_job
from .external_apply import missing_required, identify_ats, confirmation_identity, _confirmed, ExternalApplicationResult
from .submit_state import now


class SubmissionBrowser(PreparationBrowser):
    submission_enabled = True
    guard_script = GUARD_JS.replace('const submissionMode = false;', 'const submissionMode = true;')


def unknown_answers(report):
    """Classify evidence sources, never the model's own confidence score."""
    latest = {(q['name'], q['question']): q for q in report['questions']}
    known = ('candidate_config:', 'question_config', 'resume_profile:', 'application_context:', 'user_policy:dei_opt_out')
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



def _identity_ok(current_url, expected_url, *, allow_local=False):
    expected = identify_ats(expected_url)
    if expected:
        actual = confirmation_identity(current_url)
        return actual is not None and actual.key == expected.key
    try:
        actual = canonical_url(current_url, allow_local=allow_local, normalize_posting=False)
        initial = canonical_url(expected_url, allow_local=allow_local, normalize_posting=False)
        return actual == initial or actual.startswith(initial.rstrip('/')+'/')
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
        return state, None, 'Required answers or access challenge remain'
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
    if not hashed or not (native or receipt):
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
                run.update(job, status='submitting', stage='waiting_for_confirmation')
                browser.actions.append({'action':'submit','source':'explicit_submit_or_review','at':now()})
                button['element'].click()
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
