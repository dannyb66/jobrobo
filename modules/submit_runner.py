"""Shared URL/verified-role application runner. Real submit is explicit."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import shlex
from pathlib import Path
import time
import uuid

from .direct_careers_apply import literal_config, write_json
from .external_apply import ExternalApplicationLedger
from .generic_inputs import job_hint
from .generic_prepare import prepare_url, preparation_services, fingerprint
from .generic_submit import SubmissionBrowser, submit_ready, unknown_answers
from .manual_tabs import ManualTabs
from .search_history import file_lock
from .submit_state import SubmitRun, now


def requeue_failed(run, ledger):
    """Explicitly retry only failures with durable evidence of no submission."""
    count=0
    for job,state in run.rows():
        if (state['status'] in {'blocked','failed_before_submit','interrupted_before_submit','deferred'}
                and state.get('retryable') and not ledger.protected(job['url'])):
            run.update(job,status='pending',stage='explicit_retry_before_submit',retryable=False,reason='',
                       previous_failure={'status':state['status'],'stage':state['stage'],'reason':state.get('reason')})
            count+=1
    return count


def submit_profile(services, path):
    """Apply private profile overrides to URL submissions only, never LinkedIn."""
    if not path or not Path(path).expanduser().is_file():return services
    import re
    private=json.loads(Path(path).expanduser().read_text())
    if not isinstance(private,dict) or set(private)-{'email','signature_date_policy'}:
        raise ValueError('Unsupported direct submit profile setting')
    email=private.get('email')
    if email is not None and (not isinstance(email,str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email)):
        raise ValueError('Direct submit profile needs a valid email address')
    policy=private.get('signature_date_policy')
    if policy not in {None,'completion_date'}:
        raise ValueError('Signature date policy must be completion_date')
    result={**services,'candidate':deepcopy(services['candidate']),'question_config':deepcopy(services['question_config'])}
    if email is not None:
        result['candidate']['email']=email
        result['question_config'].setdefault('candidate',{})['email']=email
        result['question_config']['replace_prefilled_candidate_keys']=['email']
    if policy is not None:
        result['question_config']['signature_date_policy']=policy
    result['profile_hash']=fingerprint({'candidate':result['candidate'],'questions':result['question_config']})
    return result


def recover_verification_tabs(driver, run, ledger):
    """Inspect an existing uncertain tab without repeating any employer action."""
    from .generic_prepare import email_verification_required
    from .generic_submit import _identity_ok, external_dispatch_pending
    from .external_apply import _confirmed, ExternalApplicationResult
    for job,state in run.rows():
        if state['status']!='submission_uncertain' or not state.get('tab_handle') or not state.get('preparation_report'):
            continue
        try:
            driver.switch_to.window(state['tab_handle'])
            browser=SubmissionBrowser(driver)
            live=browser.read()
            report=json.loads(Path(state['preparation_report']).read_text())
            if not _identity_ok(live['url'],report['resolved_url']):continue
            baseline=report.get('confirmation_baseline')
            if baseline is None:baseline=[h for step in report.get('steps',[]) for h in step.get('headings',[])]
            fresh={**live,'headings':[h for h in live.get('headings',[]) if h not in baseline]}
            if external_dispatch_pending(fresh):
                reason='Application service accepted the request; employer submission is still pending'
                run.update(job,status='submission_uncertain',stage='external_submission_pending',retryable=False,
                    external_submission_pending=True,reason=reason)
                report.update(status='submission_uncertain',external_submission_pending=True,blockers=[reason])
                write_json(Path(state['preparation_report']),report)
                continue
            if _confirmed(fresh) and not live.get('challenge'):
                outcome=ExternalApplicationResult('applied',job['url'],attempt_id=state['attempt_id'],
                    resume_name=report['attachment']['name'],resume_sha256=report['resume']['pdf_sha256'],
                    submitted_at=now(),reason='Employer confirmation observed on retained attempt tab')
                ledger.record_aliases(outcome,report.get('posting_aliases',[job['url'],report['resolved_url']]),job['id'])
                run.update(job,status='applied',stage='retained_confirmation',confirmation_verified=True,
                    submitted_at=outcome.submitted_at,retryable=False)
                report.update(status='applied',confirmation_verified=True,confirmation_observed_at=now())
                write_json(Path(state['preparation_report']),report)
                continue
            if not email_verification_required(live):continue
            info={'target_id':state['tab_handle'],'token':state['attempt_id'],
                'aliases':report.get('posting_aliases',[job['url'],report['resolved_url']]),
                'resolved_url':report['resolved_url'],'form_url':live['url'],
                'baseline':live.get('headings',[])+live.get('alerts',[]),
                'resume_name':report['attachment']['name'],'resume_sha256':report['resume']['pdf_sha256'],
                'report_path':state['preparation_report'],'activations':1,'initially_complete':True,
                'verification_after_submit':True}
            run.update(job,status='awaiting_email_verification',stage='email_verification',manual_tab=info,
                verification_after_submit=True,retryable=False,reason='Retained tab requires email verification; original Submit is not replayed')
            report.update(status='awaiting_email_verification',verification_after_submit=True)
            write_json(Path(state['preparation_report']),report)
        except Exception:
            # Unavailable tabs stay protected uncertain; never create a new one.
            continue


def reconcile_run(directory, job_id, *, outcome, reason):
    """An explicit operator attestation resolves uncertainty without a browser."""
    if outcome not in {'applied','not-submitted'} or not reason or not reason.strip():
        raise ValueError('Choose applied/not-submitted and supply an inspection reason')
    directory = Path(directory).expanduser().resolve()
    if not (directory/'state.sqlite3').is_file():
        raise ValueError('Not a submission run directory')
    with file_lock(directory/'run.lock'):
        run=SubmitRun(directory)
        try:
            matches=[(j,s) for j,s in run.rows() if j['id']==job_id]
            if len(matches)!=1:
                raise ValueError('Select one exact job ID from progress.json')
            job,state=matches[0]
            resolved='applied' if outcome=='applied' else 'failed_before_submit'
            if state['stage']=='operator_reconciliation' and state['status']==resolved:
                return run.export()
            if state['status'] not in {'submission_uncertain','submitting','awaiting_review'}:
                raise ValueError('Only a protected uncertain submission can be reconciled')
            ledger=ExternalApplicationLedger(run.options['ledger_path'])
            entry=ledger.reconcile(job['url'],state.get('attempt_id'),applied=outcome=='applied',reason=reason.strip())
            run.update(job,status='applied' if outcome=='applied' else 'failed_before_submit',
                stage='operator_reconciliation',retryable=outcome=='not-submitted',
                reason='Operator verified '+outcome,reconciliation=entry['reconciliation'],
                submitted_at=entry.get('submitted_at'))
            application_export(run,set_name=run.options.get('set_name'),output=run.options.get('export_path'),db_path=run.options.get('db_path'))
            return run.export()
        finally:run.close()


def new_run_directory(requested=None):
    """Reserve a fresh directory atomically; never reuse existing run state."""
    base = Path(requested).expanduser().resolve() if requested else None
    if base and base.exists() and not base.is_dir():
        raise ValueError('Run destination must be a directory')
    for _ in range(5):
        run_id = str(uuid.uuid4())
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+run_id
        directory = base or Path('logs/direct_submit').resolve()/name
        if base and base.exists():
            directory = base.with_name(base.name+'-'+name)
        directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            directory.mkdir(mode=0o700)
            return directory, run_id
        except FileExistsError:
            continue
    raise ValueError('Could not allocate a unique submission run directory')


def local_ledger(run):
    """On explicit legacy resume, copy only this run's owned claims."""
    target = run.directory/'applications-ledger.json'
    source = run.options.get('ledger_path')
    if (run.options.get('execution_scope') != 'independent' and source and
        Path(source).resolve() != target and not target.exists()):
        attempts = {s.get('attempt_id') for _,s in run.rows() if s.get('attempt_id')}
        previous = ExternalApplicationLedger(source)._read()
        write_json(target, {k:v for k,v in previous.items() if v.get('attempt_id') in attempts})
        for job,state in run.rows():
            if state['status']=='submission_uncertain' and not state.get('attempt_id') and not state.get('attempts'):
                # The older global gate marked untouched jobs uncertain. No
                # attempt belonged to this run, so they remain pending work.
                run.update(job,status='pending',stage='prior_run_block_ignored',retryable=False)
    return str(target)


def application_export(run, *, set_name='direct-submissions', output=None, db_path=None):
    set_name = set_name or 'direct-submissions'
    from .job_pipeline.models import StageResult, write_artifact
    records = []; errors = []
    for job, state in run.rows():
        if state['status'] not in {'applied','duplicate','discarded'}:
            errors.append({'source': job['url'], 'code': state['status'], 'message': state.get('reason', state['stage']), 'retryable': bool(state.get('retryable'))})
        if state['status'] == 'pending':
            continue
        records.append({'id': 'direct-application:'+fingerprint([run.manifest['id'],job['key']]), 'role_id': job['id'],
            'company_id': job.get('company_id'), 'company': (job.get('role') or {}).get('company'),
            'career_url': job['url'], 'ats_identity': job['key'], 'direct_run_id': run.manifest['id'],
            'verification_run_id': job.get('verification_run_id'),
            'verified_at':job.get('verified_at'), 'preference_warnings':job.get('preference_warnings',[]),
            'ranking_run_id': job.get('provenance', {}).get('input_run_id'),
            'source_provenance': job.get('provenance', {}), **state})
    artifact = StageResult.create('applications', set_name, run.manifest['id'], records, errors=errors,
        input_set_ids=list(dict.fromkeys('verified_roles:'+j['provenance']['set_name'] for j, _ in run.rows() if j.get('provenance', {}).get('set_name'))))
    canonical = run.directory/'applications.json'
    write_artifact(artifact, canonical)
    if output and Path(output).resolve() != canonical:
        write_artifact(artifact, output)
    if db_path:
        from .job_pipeline.store import PipelineStore
        with PipelineStore(db_path) as store:
            store.import_artifact(artifact, 'applications')
    return artifact.to_dict()


def run_submissions(jobs=None, *, run_dir=None, resume_dir=None, config_dir=None, output_dir=None,
                    chrome_profile=None, questions_path=None, discovery_source=None, pause=None,
                    max_applications=None, driver_factory=None, services=None, ledger_path=None,
                    review_factory=None, allow_local=False, confirmation_timeout=30,
                    tab_monitor_factory=ManualTabs,
                    preparer=prepare_url, set_name=None, export_path=None, db_path=None,
                    browser_backend=None,browser_config=None,retry_failed=False):
    """Each normal invocation is independent; explicit resume retains its own state."""
    if pause is not None and pause not in {'always', 'unknown', 'never'}:
        raise ValueError('Invalid pause mode')
    if resume_dir and (jobs is not None or run_dir):
        raise ValueError('Resume takes its jobs and run directory from saved state')
    if retry_failed and not resume_dir:
        raise ValueError('Retrying failures requires an explicit saved run')
    if resume_dir:
        directory, run_id = Path(resume_dir).expanduser().resolve(), None
    else:
        directory, run_id = new_run_directory(run_dir)
    if resume_dir and not (directory/'state.sqlite3').is_file():
        raise ValueError('No saved run exists at '+str(directory))
    with file_lock(directory/'run.lock'):
        supplied = {'config_dir': str(config_dir) if config_dir else None, 'output_dir': str(output_dir) if output_dir else None,
                    'chrome_profile': str(chrome_profile) if chrome_profile else None, 'questions_path': questions_path,
                    'discovery_source': discovery_source, 'pause': pause, 'max_applications': max_applications,
                    'ledger_path': str(ledger_path) if ledger_path else None,
                    'set_name': set_name, 'export_path': str(export_path) if export_path else None,
                    'db_path': str(db_path) if db_path else None,
                    'execution_scope': None if resume_dir else 'independent',
                    'browser_backend':browser_backend,'browser_config':str(browser_config) if browser_config else None}
        run = SubmitRun(directory, jobs=None if resume_dir else jobs, options=supplied, run_id=run_id)
        driver = None; manual_tabs = None; driver_factory_is_default=False; keep_browser=False
        try:
            options = {k: (v if v is not None else run.options.get(k)) for k, v in supplied.items()}
            if resume_dir:
                for key in ('kernel_session_id','kernel_settings','kernel_telemetry_offset'):
                    if key in run.options:options[key]=run.options[key]
            if resume_dir and run.options.get('debugger_address'):
                options['debugger_address']=run.options['debugger_address']
            options['config_dir'] = options['config_dir'] or str(Path(__file__).resolve().parents[1]/'config')
            options['output_dir'] = options['output_dir'] or 'logs/url_preparations'
            options['pause'] = options['pause'] or 'always'
            options['set_name'] = options['set_name'] or 'direct-submissions'
            for key in ('config_dir','output_dir','chrome_profile','questions_path','ledger_path','export_path','db_path','browser_config'):
                if options.get(key):
                    options[key] = str(Path(options[key]).expanduser().resolve())
            if not resume_dir and options.get('export_path') and Path(options['export_path']).exists():
                path = Path(options['export_path'])
                options['export_path'] = str(path.with_name(path.stem+'-'+run.manifest['id']+path.suffix))
            # New runs never read the shared history. Legacy explicit resumes
            # migrate only owned attempts without changing the shared ledger.
            options['ledger_path'] = local_ledger(run)
            options['execution_scope'] = 'independent'
            options['preparation_dir'] = str(directory/'preparations')
            set_name, export_path, db_path = (options[k] for k in ('set_name','export_path','db_path'))
            configured = literal_config(Path(options['config_dir'])/'search.py').get('max_applications_per_run', 1)
            cap = options['max_applications']
            if configured is not None and (type(configured) is not int or configured < 1):
                raise ValueError('Configured application cap must be positive or None')
            if cap is not None and (type(cap) is not int or cap < 1):
                raise ValueError('Application cap must be positive')
            options['max_applications'] = min(c for c in (configured, cap) if c is not None) if any(c is not None for c in (configured, cap)) else None
            from .kernel_browser import browser_configuration, kernel_preflight, KernelBrowser
            if resume_dir and not options.get('browser_backend'):options['browser_backend']='local'
            backend,kernel_settings=browser_configuration(options['config_dir'],backend=options.get('browser_backend'),path=options.get('browser_config'))
            if resume_dir and run.options.get('browser_backend','local')!=backend:
                raise ValueError('Resume must use the saved browser backend')
            if backend=='kernel':
                if options.get('chrome_profile'):raise ValueError('Kernel uses profile_id in browser_runtime.json, not --chrome-profile')
                kernel_preflight()
                kernel_settings=options.get('kernel_settings') or kernel_settings
                options['kernel_settings']=kernel_settings
            options['browser_backend']=backend
            run.set_options(options)
            print('Run ID: '+run.manifest['id'], flush=True)
            print('Submission run: '+str(directory), flush=True)
            if ledger_path:
                print('Submit uses its run-owned ledger; the supplied --ledger is not used for cross-run blocking.', flush=True)
            print('Optional resume: python3 direct_apply.py submit --resume '+shlex.quote(str(directory)), flush=True)
            print('Pause before submit: '+options['pause'], flush=True)
            ledger = ExternalApplicationLedger(options['ledger_path'])
            if retry_failed:
                print('[Resume] Requeued '+str(requeue_failed(run,ledger))+' eligible failures; confirmed jobs remain skipped.',flush=True)
            if all(state['status'] in {'applied','discarded','duplicate','blocked','failed_before_submit','deferred'} for _,state in run.rows()):
                return run.export()
            svc = services or preparation_services(config_dir=options['config_dir'], questions_path=options['questions_path'], discovery_source=options['discovery_source'])
            if services is None:
                private=literal_config(Path(options['config_dir'])/'settings.py').get('direct_submit_profile_path')
                svc=submit_profile(svc,private)
            ledger = ExternalApplicationLedger(options['ledger_path'])
            driver_factory_is_default = driver_factory is None
            if driver_factory is None:
                if backend=='kernel':
                    driver_factory=lambda:KernelBrowser(settings=kernel_settings,run_id=run.manifest['id'],session_id=options.get('kernel_session_id') if resume_dir else None,
                        telemetry_offset=options.get('kernel_telemetry_offset',0) if resume_dir else 0)
                else:
                    from direct_apply import browser_factory
                    profile = options['chrome_profile'] or directory/'chrome-profile'
                    driver_factory = browser_factory(profile, debugger_address=options.get('debugger_address'))
            if resume_dir and any(s['status'] in {'awaiting_manual_submit','awaiting_correction','submitting','awaiting_email_verification','submission_uncertain'} for _,s in run.rows()):
                try:
                    driver=driver_factory()
                    recover_verification_tabs(driver,run,ledger)
                    manual_tabs=tab_monitor_factory(driver,run,ledger,allow_local=allow_local,confirmation_timeout=confirmation_timeout)
                    manual_tabs.restore()
                except Exception:
                    for job,state in run.rows():
                        if state.get('manual_tab') and state['status'] in {'awaiting_manual_submit','awaiting_correction','submitting','awaiting_email_verification'}:
                            run.update(job,status='submission_uncertain',stage='manual_browser_unavailable',retryable=False,
                                reason='Prior browser unavailable; inspect manual employer outcome before retrying')
                    if driver:
                        try:
                            if getattr(driver,'browser_backend',None)=='kernel':driver.finish(retain=True)
                            else:driver.quit()
                        except Exception:pass
                        driver=None
                    if driver_factory_is_default:
                        driver_factory=(lambda:KernelBrowser(settings=kernel_settings,run_id=run.manifest['id'])) if backend=='kernel' else browser_factory(profile)
                        options.pop('debugger_address',None)
                        run.set_options(options)
            total = len(run.rows())
            for index, (job, saved) in enumerate(run.rows(), 1):
                if manual_tabs and job['key'] in manual_tabs.tabs:
                    continue
                if saved['status'] in {'applied', 'discarded', 'duplicate', 'blocked', 'failed_before_submit', 'deferred'}:
                    continue
                if saved['status'] in {'submission_uncertain', 'submitting'}:
                    run.update(job, status='submission_uncertain', stage='external_submission_pending' if saved.get('external_submission_pending') else 'resume_reconciliation', retryable=False)
                    continue
                if ledger.protected(job['url']):
                    prior = ledger._read().get(job['key'], {})
                    reserved_manual=any(s.get('attempt_id')==prior.get('attempt_id') and s['status'] in {'awaiting_manual_submit','awaiting_correction'} for _,s in run.rows())
                    run.update(job, status='duplicate' if prior.get('status') in {'applied','duplicate'} or reserved_manual else 'submission_uncertain', stage='protected_in_this_run', retryable=False)
                    continue
                # A retry export's old execution restriction is provenance in
                # a fresh run. Verified inventory admission still applies.
                blockers = [b for b in job.get('admission_blockers', []) if b != 'retry_requires_manual_resolution']
                if blockers:
                    run.update(job, status='blocked', stage='input_admission', reason='; '.join(blockers), retryable=False)
                    continue
                cap = options['max_applications']
                if cap is not None and sum(s['status'] in {'applied','submitting','submission_uncertain','awaiting_manual_submit','awaiting_correction','awaiting_email_verification'} for _, s in run.rows()) >= cap:
                    print('Configured submission cap reached; remaining jobs saved.', flush=True)
                    break
                attempt = str(uuid.uuid4())
                started = time.monotonic()
                run.update(job, status='preparing', stage='starting', attempt_id=attempt, attempts=saved.get('attempts', 0)+1,reason='')
                print(f"[{index}/{total}] {job.get('company','')} {job.get('title') or job['url']}", flush=True)
                if job.get('preference_warnings'):
                    print('[Input] Candidate preference warnings: '+', '.join(map(str,job['preference_warnings'])),flush=True)
                try:
                    if driver is None:
                        driver = driver_factory(); driver.set_window_size(1440,1000); driver.set_page_load_timeout(40)
                        if getattr(driver,'browser_backend',None)=='kernel':
                            run.set_options({**run.options,**driver.runtime_metadata})
                            print('[Kernel] Browser session: '+driver.session_id,flush=True)
                    if getattr(driver,'browser_backend',None)=='kernel':
                        run.update(job,kernel_session_id=driver.session_id)
                        driver.session_observer=lambda event:run.browser_event(driver.session_id,event)
                        driver.challenge_observer=lambda event:run.update(job,stage='captcha_solver',captcha_event=event)
                    driver.switch_to.new_window('tab')
                    keep_browser=review_factory is None and options['pause']!='never'
                    run.update(job,tab_handle=str(driver.current_window_handle))
                    candidate = deepcopy(svc['candidate']); question_config = deepcopy(svc['question_config'])
                    if job.get('discovery_source'):
                        candidate['application_source'] = job['discovery_source']
                        question_config.setdefault('candidate', {})['application_source'] = job['discovery_source']
                    def stage(name, report):
                        run.update(job, stage=name)
                        print(f'[{index}/{total} | {time.monotonic()-started:.0f}s] {name}', flush=True)
                    def ready(browser, report, root):
                        nonlocal manual_tabs
                        needs_review=options['pause']=='always' or options['pause']=='unknown' and (unknown_answers(report) or report.get('blockers'))
                        if review_factory is None and needs_review:
                            if manual_tabs is None:
                                manual_tabs=tab_monitor_factory(driver,run,ledger,allow_local=allow_local,confirmation_timeout=confirmation_timeout)
                            return manual_tabs.handoff(browser,report,root,job=job,attempt_id=attempt)
                        return submit_ready(browser, report, root, job=job, run=run, ledger=ledger,
                            attempt_id=attempt, pause=options['pause'], review_factory=review_factory,
                            confirmation_timeout=confirmation_timeout)
                    def cached_resume(job_context, _report_resume_dir):
                        return svc['resume_provider'](job_context,Path(options['output_dir'])/fingerprint(job['url'])[:20]/'resume')
                    report = preparer(job['url'], driver=driver, output_dir=options['preparation_dir'],
                        candidate=candidate, question_config=question_config,
                        resume_provider=cached_resume, drafting_factory=svc.get('drafting_factory'),
                        question_mapper=svc.get('question_mapper'), ledger=ledger, job_hint=job_hint(job),
                        browser_class=SubmissionBrowser, on_ready=ready, on_stage=stage, allow_local=allow_local,
                        input_metadata={'run_id':run.manifest['id'],'attempt_id':attempt,'role_id':job['id'],'company_id':job.get('company_id'),
                            'profile_hash':svc.get('profile_hash'),'settings_hash':svc.get('settings_hash'),
                            'verification_run_id':job.get('verification_run_id'),'source':job.get('provenance',{})})
                    snapshot = ledger._read()
                    aliases = report.get('posting_aliases', [job['url'],report.get('resolved_url',job['url'])])
                    states = [snapshot.get(ledger.target_key(u),{}) for u in aliases]
                    stored = next((s for s in states if s.get('status')=='applied'), next((s for s in states if s.get('status')=='submitting'),{}))
                    if report['status']=='awaiting_email_verification':
                        saved_verification=next(s for j,s in run.rows() if j['key']==job['key'])
                        if not saved_verification.get('manual_tab'):
                            final=report.get('final_state') or {}
                            resolved=report.get('resolved_url',job['url'])
                            info={'target_id':driver.current_window_handle,'token':attempt,'aliases':list(dict.fromkeys([job['url'],resolved])),
                                'resolved_url':resolved,'form_url':final.get('url',resolved),'baseline':final.get('headings',[]),
                                'resume_name':report.get('attachment',{}).get('name',''),'resume_sha256':report.get('resume',{}).get('pdf_sha256',''),
                                'report_path':str(Path(report['output_dir'])/'report.json'),'activations':0,'initially_complete':False,
                                'verification_after_submit':False}
                            run.update(job,status='awaiting_email_verification',stage='email_verification',manual_tab=info,retryable=False)
                        if manual_tabs is None:
                            manual_tabs=tab_monitor_factory(driver,run,ledger,allow_local=allow_local,confirmation_timeout=confirmation_timeout)
                        manual_tabs.restore()
                    elif report.get('manual_handoff'):
                        pass  # Its reserved claim is awaiting a human, not an uncertain automatic click.
                    elif stored.get('status') == 'applied':
                        run.update(job,status='applied' if stored.get('attempt_id')==attempt else 'duplicate',stage='confirmed',submitted_at=stored.get('submitted_at'),retryable=False)
                    elif stored.get('status') == 'submitting' and stored.get('attempt_id')!=attempt and any(s.get('attempt_id')==stored.get('attempt_id') and s['status'] in {'awaiting_manual_submit','awaiting_correction'} for _,s in run.rows()):
                        run.update(job,status='duplicate',stage='reserved_manual_tab',retryable=False,duplicate_source='run_ledger')
                    elif stored.get('status') == 'submitting':
                        run.update(job,status='submission_uncertain',stage='external_submission_pending' if report.get('external_submission_pending') else 'confirmation_required',retryable=False,
                                   **({'external_submission_pending':True,'reason':'; '.join(report.get('blockers',[]))} if report.get('external_submission_pending') else {}))
                    elif report['status']=='duplicate':
                        run.update(job,status='duplicate',stage='portal_duplicate' if report.get('portal_duplicate_verified') else 'protected_posting',
                            duplicate_source='portal' if report.get('portal_duplicate_verified') else 'run_ledger',retryable=False)
                    elif report['status'] not in {'applied', 'awaiting_review', 'deferred'}:
                        retryable = bool(report.get('pre_submit_retryable')) or report['status'] in {'failed','blocked','interrupted'} and not any(
                            phrase in ' '.join(report.get('blockers',[])).lower() for phrase in ('captcha','manual access','closed','unsupported','login'))
                        if report.get('access_outcome')=='posting_identity_changed':retryable=False
                        run.update(job, status='failed_before_submit' if report['status']=='failed' else 'blocked',
                            stage='portal_validation_rejected' if report.get('portal_validation_rejected') else 'captcha_timeout_before_submit' if report.get('pre_submit_retryable') and any('CAPTCHA timeout' in b for b in report.get('blockers',[])) else 'preparation_finished',
                            reason='; '.join(report.get('blockers',[])), retryable=retryable)
                    run.update(job, preparation_report=str(Path(report['output_dir'])/'report.json'),
                        jd_sha256=report.get('jd_sha256'), resume_sha256=report.get('resume',{}).get('pdf_sha256'))
                    if manual_tabs:manual_tabs.poll()
                    summary=run.export()
                    print('Progress: '+json.dumps(summary['counts']), flush=True)
                    if report.get('stop_run'):
                        break
                except BaseException as error:
                    claimed = ledger._read().get(job['key'], {})
                    status = 'applied' if claimed.get('status')=='applied' else 'submission_uncertain' if claimed.get('status')=='submitting' else 'interrupted_before_submit' if not isinstance(error,Exception) else 'failed_before_submit'
                    run.update(job,status=status,stage='interrupted',reason=type(error).__name__,retryable=status in {'interrupted_before_submit','failed_before_submit'})
                    if not isinstance(error, Exception):
                        raise
                    print('Job stopped: '+type(error).__name__, flush=True)
                    if driver and not manual_tabs and not keep_browser:
                        try:
                            if getattr(driver,'browser_backend',None)=='kernel':driver.finish(retain=True)
                            else:driver.quit()
                        except Exception: pass
                        driver=None
                finally:
                    application_export(run, set_name=set_name, output=export_path, db_path=db_path)
            if driver is not None:
                # Late employer responses may arrive while later jobs fill.
                # Inspect retained attempts once more; never replay Submit.
                recover_verification_tabs(driver,run,ledger)
            if manual_tabs and options['pause']!='never':
                def checkpoint():
                    application_export(run,set_name=set_name,output=export_path,db_path=db_path)
                try:manual_tabs.wait(checkpoint)
                except KeyboardInterrupt:
                    manual_tabs.poll()
                    print('[Submit] Saved. Chrome tabs remain open; use the printed resume command to reconnect.',flush=True)
            elif manual_tabs:
                manual_tabs.poll()
                print('[Submit] Verification tabs retained. Complete email verification there, then resume this run; no original Submit is replayed.',flush=True)
            return run.export()
        finally:
            try:
                application_export(run, set_name=set_name, output=export_path, db_path=db_path)
            finally:
                if manual_tabs:
                    manual_tabs.close()
                if driver and getattr(driver,'browser_backend',None)=='kernel':
                    retain=any(s['status'] not in {'applied','duplicate','discarded','pending'} for _,s in run.rows())
                    driver.finish(retain=retain)
                elif manual_tabs or keep_browser:
                    # Chrome was launched detached. Keep all review tabs available.
                    if driver and driver_factory_is_default:
                        try:driver.service.stop()
                        except Exception:pass
                elif driver:
                    try: driver.quit()
                    except Exception: pass
                run.close()
