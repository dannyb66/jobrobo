"""Shared URL/verified-role application runner. Real submit is explicit."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import shlex
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid

from .direct_careers_apply import literal_config, write_json
from .external_apply import ExternalApplicationLedger
from .generic_inputs import job_hint
from .generic_prepare import prepare_url, preparation_services, fingerprint
from .generic_submit import SubmissionBrowser, submit_ready, unknown_answers
from .manual_tabs import ManualTabs
from .manual_tabs import close_browser_tab
from .search_history import file_lock
from .submit_state import SubmitRun, build_run_summary, now


@dataclass
class ApplicationTab:
    """An employer tab borrowed from another runner; its browser is never owned here."""
    driver: object
    handle: str
    on_update: object = None


def explicit_portal_rejection(state):
    """Return evidence only for a visible employer denial of the submitted form."""
    messages = [str(x) for x in state.get('alerts', []) + state.get('headings', [])]
    text = '\n'.join(messages + [str(state.get('text', ''))])
    if (re.search(r"we couldn['’]t submit your application", text, re.I) and
        re.search(r'flagged as possible spam', text, re.I)):
        return 'Employer explicitly rejected the application as possible spam'
    return ''


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
    """Apply private overrides to employer submissions from either entry point."""
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


def recover_verification_tabs(driver, run, ledger, job_keys=None):
    """Inspect an existing uncertain tab without repeating any employer action."""
    from .generic_prepare import email_verification_required
    from .generic_submit import _identity_ok, external_dispatch_pending
    from .external_apply import _confirmed, ExternalApplicationResult
    selected=set(job_keys) if job_keys is not None else None
    for job,state in run.rows():
        if selected is not None and job['key'] not in selected:continue
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
            rejection = explicit_portal_rejection(fresh)
            if rejection and not live.get('challenge'):
                ledger.reconcile(job['url'], state['attempt_id'], applied=False, reason=rejection)
                run.update(job,status='failed_before_submit',stage='portal_rejected_as_spam',retryable=True,
                    reason=rejection,reconciliation={'source':'retained_portal_message','at':now()})
                report.update(status='failed',portal_rejection=rejection,blockers=[rejection])
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
                if close_browser_tab(driver,state.get('tab_handle')):
                    print('[Submit] Closed confirmed application tab: '+job.get('title',job['url']),flush=True)
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


def _parallel_submit_job(job, saved, *, attempt, index, total, run, options, services,
                         ledger, worker_context, preparer, review_factory, allow_local,
                         confirmation_timeout, tab_monitor_factory):
    """Prepare one URL in a worker-owned browser session and tab."""
    driver=worker_context['driver'];monitor=worker_context.get('monitor');started=time.monotonic()
    try:
        if getattr(driver,'browser_backend',None)=='kernel':
            run.update(job,kernel_session_id=driver.session_id)
            def observe(event):
                run.browser_event(driver.session_id,event)
                offset=event.get('cursor_offset') if isinstance(event,dict) else None
                if type(offset) is int and offset>=0:run.update(job,kernel_telemetry_offset=offset)
            driver.session_observer=observe
            driver.challenge_observer=lambda event:run.update(job,stage='captcha_solver',captcha_event=event)
        else:
            address=driver.capabilities.get('goog:chromeOptions',{}).get('debuggerAddress')
            if address:
                run.update(job,debugger_address=address)
                # Run-level too: resume reattaches once for the whole session.
                run.set_options({**run.options,'debugger_address':address})
        run.update(job,worker_id=worker_context['worker_id'])
        driver.switch_to.new_window('tab')
        run.update(job,tab_handle=str(driver.current_window_handle))

        candidate=deepcopy(services['candidate']);question_config=deepcopy(services['question_config'])
        if job.get('discovery_source'):
            candidate['application_source']=job['discovery_source']
            question_config.setdefault('candidate',{})['application_source']=job['discovery_source']
        def stage(name, report):
            run.update(job,stage=name)
            print(f'[{index}/{total} | {time.monotonic()-started:.0f}s] {name}',flush=True)
        def ready(browser, report, root):
            nonlocal monitor
            needs_review=options['pause']=='always' or options['pause']=='unknown' and (unknown_answers(report) or report.get('blockers'))
            if review_factory is None and needs_review:
                if monitor is None:
                    monitor=tab_monitor_factory(driver,run,ledger,allow_local=allow_local,
                        confirmation_timeout=confirmation_timeout,job_keys={job['key']},persist_run_options=False)
                    worker_context['monitor']=monitor
                return monitor.handoff(browser,report,root,job=job,attempt_id=attempt)
            return submit_ready(browser,report,root,job=job,run=run,ledger=ledger,
                attempt_id=attempt,pause=options['pause'],review_factory=review_factory,
                confirmation_timeout=confirmation_timeout)
        def cached_resume(job_context, _report_resume_dir):
            return services['resume_provider'](job_context,
                Path(options['output_dir'])/fingerprint(job['url'])[:20]/'resume')
        print(f"[{index}/{total}] {job.get('company','')} {job.get('title') or job['url']}",flush=True)
        report=preparer(job['url'],driver=driver,output_dir=options['preparation_dir'],
            candidate=candidate,question_config=question_config,resume_provider=cached_resume,
            drafting_factory=services.get('drafting_factory'),question_mapper=services.get('question_mapper'),
            ledger=ledger,job_hint=job_hint(job),browser_class=SubmissionBrowser,on_ready=ready,on_stage=stage,
            allow_local=allow_local,input_metadata={'run_id':run.manifest['id'],'attempt_id':attempt,
                'role_id':job['id'],'company_id':job.get('company_id'),'profile_hash':services.get('profile_hash'),
                'settings_hash':services.get('settings_hash'),'verification_run_id':job.get('verification_run_id'),
                'source':job.get('provenance',{})})
        snapshot=ledger._read()
        aliases=report.get('posting_aliases',[job['url'],report.get('resolved_url',job['url'])])
        states=[snapshot.get(ledger.target_key(url),{}) for url in aliases]
        stored=next((s for s in states if s.get('status')=='applied'),
                    next((s for s in states if s.get('status')=='submitting'),{}))
        if report['status']=='awaiting_email_verification':
            state=next(s for row,s in run.rows() if row['key']==job['key'])
            if not state.get('manual_tab'):
                final=report.get('final_state') or {};resolved=report.get('resolved_url',job['url'])
                info={'target_id':driver.current_window_handle,'token':attempt,
                    'aliases':list(dict.fromkeys([job['url'],resolved])),'resolved_url':resolved,
                    'form_url':final.get('url',resolved),'baseline':final.get('headings',[]),
                    'resume_name':report.get('attachment',{}).get('name',''),
                    'resume_sha256':report.get('resume',{}).get('pdf_sha256',''),
                    'report_path':str(Path(report['output_dir'])/'report.json'),'activations':0,
                    'initially_complete':False,'verification_after_submit':False}
                run.update(job,status='awaiting_email_verification',stage='email_verification',manual_tab=info,retryable=False)
            if monitor is None:
                monitor=tab_monitor_factory(driver,run,ledger,allow_local=allow_local,
                    confirmation_timeout=confirmation_timeout,job_keys={job['key']},persist_run_options=False)
                worker_context['monitor']=monitor
            monitor.restore(job_keys={job['key']})
        elif report.get('manual_handoff'):
            pass
        elif stored.get('status')=='applied':
            run.update(job,status='applied' if stored.get('attempt_id')==attempt else 'duplicate',
                stage='confirmed',submitted_at=stored.get('submitted_at'),retryable=False)
        elif stored.get('status')=='submitting' and stored.get('attempt_id')!=attempt and any(
                s.get('attempt_id')==stored.get('attempt_id') and s['status'] in {'awaiting_manual_submit','awaiting_correction'}
                for _,s in run.rows()):
            run.update(job,status='duplicate',stage='reserved_manual_tab',retryable=False,duplicate_source='run_ledger')
        elif stored.get('status')=='submitting':
            run.update(job,status='submission_uncertain',stage='external_submission_pending' if report.get('external_submission_pending') else 'confirmation_required',
                retryable=False,**({'external_submission_pending':True,'reason':'; '.join(report.get('blockers',[]))} if report.get('external_submission_pending') else {}))
        elif report['status']=='duplicate':
            run.update(job,status='duplicate',stage='portal_duplicate' if report.get('portal_duplicate_verified') else 'protected_posting',
                duplicate_source='portal' if report.get('portal_duplicate_verified') else 'run_ledger',retryable=False)
        elif report['status'] not in {'applied','awaiting_review','deferred'}:
            retryable=bool(report.get('pre_submit_retryable')) or report['status'] in {'failed','blocked','interrupted'} and not any(
                phrase in ' '.join(report.get('blockers',[])).lower() for phrase in ('captcha','manual access','closed','unsupported','login'))
            if report.get('access_outcome')=='posting_identity_changed':retryable=False
            run.update(job,status='failed_before_submit' if report['status']=='failed' else 'blocked',
                stage='portal_validation_rejected' if report.get('portal_validation_rejected') else 'captcha_timeout_before_submit' if report.get('pre_submit_retryable') and any('CAPTCHA timeout' in b for b in report.get('blockers',[])) else 'preparation_finished',
                reason='; '.join(report.get('blockers',[])),retryable=retryable)
        run.update(job,preparation_report=str(Path(report['output_dir'])/'report.json'),
            jd_sha256=report.get('jd_sha256'),resume_sha256=report.get('resume',{}).get('pdf_sha256'))
        if stored.get('status')=='applied' and stored.get('attempt_id')==attempt:
            state=next((s for row,s in run.rows() if row['key']==job['key']),{})
            if close_browser_tab(driver,state.get('tab_handle')):print('[Submit] Closed confirmed application tab: '+job.get('title',job['url']),flush=True)
        if monitor:monitor.poll()
        print('Progress: '+json.dumps(run.export()['counts']),flush=True)
        final_state=next(s for row,s in run.rows() if row['key']==job['key'])
        worker_context.setdefault('job_keys',set()).add(job['key'])
        worker_context.setdefault('retain_keys',set())
        if final_state['status'] not in {'applied','duplicate','discarded','pending'}:
            worker_context['retain_keys'].add(job['key'])
        return worker_context
    except BaseException as error:
        snapshot=ledger._read();claimed=snapshot.get(ledger.target_key(job['url']),{})
        status='applied' if claimed.get('status')=='applied' else 'submission_uncertain' if claimed.get('status')=='submitting' else 'interrupted_before_submit' if not isinstance(error,Exception) else 'failed_before_submit'
        run.update(job,status=status,stage='interrupted',reason=type(error).__name__,retryable=status in {'interrupted_before_submit','failed_before_submit'})
        if not isinstance(error,Exception):
            worker_context.setdefault('job_keys',set()).add(job['key'])
            worker_context.setdefault('retain_keys',set()).add(job['key'])
            return worker_context
        print('Job stopped: '+type(error).__name__,flush=True)
        worker_context.setdefault('job_keys',set()).add(job['key'])
        if options['pause']!='never':worker_context.setdefault('retain_keys',set()).add(job['key'])
        return worker_context


def _run_parallel_submissions(run, *, options, services, ledger, driver_factory,
                              driver_factory_is_default, kernel_settings, backend,
                              preparer, review_factory, allow_local, confirmation_timeout,
                              tab_monitor_factory, retry_failed=False):
    """Run bounded URL workers; each worker owns one isolated session and tabs."""
    workers=options['workers']
    if backend!='kernel' and driver_factory_is_default:
        raise ValueError('Parallel workers require --browser kernel; one local Chrome profile cannot be safely shared.')
    if retry_failed:print('[Resume] Requeued '+str(requeue_failed(run,ledger))+' eligible failures; confirmed jobs remain skipped.',flush=True)
    import threading
    from collections import defaultdict, deque
    stop=threading.Event();startup_failed=threading.Event();dispatch_lock=threading.Lock()
    startup_failure_reason=[];startup_probe=threading.Event();startup_probe_lock=threading.Lock();startup_probe_claimed=False

    def create_context(worker_id, session_id=None, telemetry_offset=0):
        if backend=='kernel':
            from .kernel_browser import KernelBrowser
            driver=KernelBrowser(settings=kernel_settings,run_id=run.manifest['id']+'-'+worker_id,
                session_id=session_id,telemetry_offset=telemetry_offset)
        else:driver=driver_factory()
        try:
            driver.set_window_size(1440,1000);driver.set_page_load_timeout(40)
        except BaseException:
            try:
                if getattr(driver,'browser_backend',None)=='kernel':driver.finish(retain=True)
                else:driver.quit()
            except Exception:pass
            raise
        return {'driver':driver,'monitor':None,'worker_id':worker_id,'job_keys':set(),'retain_keys':set()}

    def restore_session(worker_id,session_id,items):
        keys={job['key'] for job,state in items}
        offsets=[state.get('kernel_telemetry_offset',0) for _,state in items]
        context=create_context(worker_id,session_id,max(offsets or [0]))
        driver=context['driver']
        def observe(event):run.browser_event(driver.session_id,event)
        driver.session_observer=observe
        driver.challenge_observer=lambda event:run.browser_event(driver.session_id,{'type':'challenge','event':event})
        for job,state in items:
            if state.get('tab_handle'):
                try:driver.switch_to.window(state['tab_handle'])
                except Exception:pass
        recover_verification_tabs(driver,run,ledger,job_keys=keys)
        monitor=tab_monitor_factory(driver,run,ledger,allow_local=allow_local,
            confirmation_timeout=confirmation_timeout,job_keys=keys,persist_run_options=False)
        monitor.restore(job_keys=keys);context['monitor']=monitor;context['job_keys']=keys
        return context

    # Group retained jobs by their owning browser session. New runs write one
    # shared session id per bounded worker, while older parallel runs may have
    # one session per job; both layouts resume without refilling those forms.
    saved_groups=defaultdict(list)
    for job,state in run.rows():
        if state['status'] not in {'awaiting_manual_submit','awaiting_correction','submitting','awaiting_email_verification','submission_uncertain'}:continue
        session=state.get('kernel_session_id')
        if not session:
            if state['status'] in {'awaiting_manual_submit','awaiting_correction','submitting','awaiting_email_verification'}:
                run.update(job,status='submission_uncertain',stage='worker_session_missing',retryable=False,
                    reason='The per-job browser session is missing; inspect the employer outcome before retrying')
            continue
        saved_groups[session].append((job,state))

    def monitor_saved_session(worker_id,session,items):
        context=None;keys={job['key'] for job,_ in items}
        try:
            context=restore_session(worker_id,session,items)
            if options['pause']!='never' and context['monitor'].tabs:
                context['driver'].show_live_view()
                while not stop.is_set() and any(not tab['done'] for tab in context['monitor'].tabs.values()):
                    if context['monitor'].poll():application_export(run,set_name=options['set_name'],output=options['export_path'],db_path=options['db_path'])
                    time.sleep(.4)
        except KeyboardInterrupt:stop.set()
        except Exception as error:
            print('[Worker] Could not restore prior session: '+type(error).__name__,flush=True)
        finally:
            if context:
                try:context['monitor'].close()
                except Exception:pass
                retain=any(state['status'] not in {'applied','duplicate','discarded','pending'}
                    for job,state in run.rows() if job['key'] in keys)
                try:context['driver'].finish(retain=retain)
                except Exception:pass

    def eligible_rows():
        result=[]
        for job,state in run.rows():
            if state['status']!='pending':continue
            if ledger.protected(job['url']):
                prior=ledger._read().get(ledger.target_key(job['url']),{})
                run.update(job,status='duplicate' if prior.get('status') in {'applied','duplicate'} else 'submission_uncertain',
                    stage='protected_in_run_ledger',retryable=False)
                continue
            blockers=[b for b in job.get('admission_blockers',[]) if b!='retry_requires_manual_resolution']
            if blockers:
                run.update(job,status='blocked',stage='input_admission',reason='; '.join(blockers),retryable=False)
                continue
            result.append((job,state))
        return deque(result)

    queue=eligible_rows();total=len(run.rows());cap=options['max_applications']
    positions={job['key']:i for i,(job,_) in enumerate(run.rows(),1)}

    def count_toward_cap(state):
        return state['status'] in {'preparing','ready','awaiting_review','submitting','submission_uncertain','awaiting_manual_submit','awaiting_correction','awaiting_email_verification','applied'}

    def take_work():
        with dispatch_lock:
            if stop.is_set() or startup_failed.is_set() or not queue:return None
            used=sum(count_toward_cap(state) for _,state in run.rows())
            if cap is not None and used>=cap:return None
            job,state=queue.popleft();attempt=str(uuid.uuid4())
            reserved=run.update(job,status='preparing',stage='worker_reserved',attempt_id=attempt,
                attempts=state.get('attempts',0)+1,reason='')
            return job,reserved,attempt

    def worker_loop(worker_index):
        nonlocal startup_probe_claimed
        worker_id=f'worker-{worker_index:02d}';context=None
        try:
            while not stop.is_set():
                task=take_work()
                if task is None:break
                job,saved,attempt=task
                if context is None:
                    with startup_probe_lock:
                        is_probe=not startup_probe_claimed
                        if is_probe:startup_probe_claimed=True
                    if not is_probe:
                        while not startup_probe.wait(.1):
                            if stop.is_set():break
                        if stop.is_set():
                            run.update(job,status='pending',stage='pending',attempt_id=None,
                                attempts=saved.get('attempts',0),reason='')
                            break
                    if startup_failed.is_set():
                        run.update(job,status='pending',stage='pending',attempt_id=None,
                            attempts=saved.get('attempts',0),reason='')
                        break
                    try:context=create_context(worker_id)
                    except Exception as error:
                        if backend=='kernel':
                            safe_reason=(str(error).strip().replace('\n',' ')[:350]
                                if type(error) is ValueError and 'Kernel browser setup failed' in str(error)
                                else 'Kernel browser startup failed ('+type(error).__name__+')')
                        else:safe_reason=type(error).__name__
                        with dispatch_lock:
                            if not startup_failure_reason:startup_failure_reason.append(safe_reason)
                            startup_failed.set()
                        startup_probe.set()
                        run.update(job,status='failed_before_submit',stage='worker_browser_start_failed',
                            reason=safe_reason,retryable=True)
                        print(f'[Worker {worker_index}/{workers}] Browser startup failed: {safe_reason}',flush=True)
                        break
                    if is_probe:startup_probe.set()
                    if getattr(context['driver'],'browser_backend',None)=='kernel':
                        print(f"[Worker {worker_index}/{workers}] Kernel session {context['driver'].session_id}",flush=True)
                context=_parallel_submit_job(job,saved,attempt=attempt,index=positions.get(job['key'],0),total=total,
                    run=run,options=options,services=services,ledger=ledger,worker_context=context,
                    preparer=preparer,review_factory=review_factory,allow_local=allow_local,
                    confirmation_timeout=confirmation_timeout,tab_monitor_factory=tab_monitor_factory)
            if context and context.get('monitor') and options['pause']!='never' and context['monitor'].tabs:
                driver=context['driver'];driver.show_live_view()
                while not stop.is_set() and any(not tab['done'] for tab in context['monitor'].tabs.values()):
                    if context['monitor'].poll():application_export(run,set_name=options['set_name'],output=options['export_path'],db_path=options['db_path'])
                    time.sleep(.4)
            return context
        except KeyboardInterrupt:
            stop.set();return context
        finally:
            if context:
                if stop.is_set():context.setdefault('retain_keys',set()).update(context.get('job_keys',set()))
                if context.get('monitor'):
                    try:context['monitor'].close()
                    except Exception:pass
                retain=stop.is_set() or any(s['status'] not in {'applied','duplicate','discarded','pending'} for job,s in run.rows() if job['key'] in context.get('job_keys',set()))
                try:
                    if getattr(context['driver'],'browser_backend',None)=='kernel':context['driver'].finish(retain=retain)
                    elif retain and driver_factory_is_default:
                        try:context['driver'].service.stop()
                        except Exception:pass
                    elif not retain:context['driver'].quit()
                except Exception:pass

    from concurrent.futures import ThreadPoolExecutor, as_completed
    parallel_workers=min(workers,max(1,len(queue)))
    with ThreadPoolExecutor(max_workers=max(1,parallel_workers+len(saved_groups)),thread_name_prefix='jobrobo-apply') as pool:
        futures=[]
        for slot,(session,items) in enumerate(saved_groups.items(),1):
            worker_id=items[0][1].get('worker_id') or f'restored-{slot:02d}'
            futures.append(pool.submit(monitor_saved_session,worker_id,session,items))
        futures.extend(pool.submit(worker_loop,index) for index in range(1,parallel_workers+1))
        try:
            for future in as_completed(futures):future.result()
        except KeyboardInterrupt:
            stop.set();print('[Submit] Stop requested; workers are checkpointing and retaining unresolved sessions.',flush=True)
            for future in futures:
                try:future.result()
                except Exception:pass
        except Exception as error:
            stop.set();print('[Submit] Parallel worker stopped: '+type(error).__name__,flush=True)
            for future in futures:
                try:future.result()
                except Exception:pass
    application_export(run,set_name=options['set_name'],output=options['export_path'],db_path=options['db_path'])
    return run.export()


def run_submissions(jobs=None, *, run_dir=None, resume_dir=None, config_dir=None, output_dir=None,
                    chrome_profile=None, questions_path=None, discovery_source=None, pause=None,
                    max_applications=None, workers=None, driver_factory=None, services=None, ledger_path=None,
                    review_factory=None, allow_local=False, confirmation_timeout=30,
                    tab_monitor_factory=ManualTabs,
                    preparer=prepare_url, set_name=None, export_path=None, db_path=None,
                    browser_backend=None,browser_config=None,retry_failed=False,captcha_solver=False,
                    application_tab=None):
    """Each normal invocation is independent; explicit resume retains its own state."""
    if pause is not None and pause not in {'always', 'unknown', 'never'}:
        raise ValueError('Invalid pause mode')
    if application_tab is not None:
        if resume_dir or not jobs or len(jobs) != 1 or workers not in (None, 1) or not ledger_path:
            raise ValueError('A borrowed application tab needs one job, one worker, and a shared ledger')
        if application_tab.handle not in application_tab.driver.window_handles:
            raise ValueError('Employer application tab is no longer available')
        browser_backend = 'local'
    if captcha_solver:
        from modules import captcha_solver as solver
        solver.enable()
        ready, why = solver.available()
        if not ready:
            raise ValueError(f'--captcha-solver is unavailable: {why}')
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
                    'workers': workers,
                    'ledger_path': str(ledger_path) if ledger_path else None,
                    'set_name': set_name, 'export_path': str(export_path) if export_path else None,
                    'db_path': str(db_path) if db_path else None,
                    'execution_scope': None if resume_dir else 'independent',
                    'browser_backend':browser_backend,'browser_config':str(browser_config) if browser_config else None}
        run = SubmitRun(directory, jobs=None if resume_dir else jobs, options=supplied, run_id=run_id)
        if application_tab is not None:
            run.on_update = application_tab.on_update
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
            options['workers'] = options['workers'] or (run.options.get('workers') if resume_dir else None) or 1
            if type(options['workers']) is not int or not 1 <= options['workers'] <= 4:
                raise ValueError('Parallel worker count must be between 1 and 4')
            options['set_name'] = options['set_name'] or 'direct-submissions'
            for key in ('config_dir','output_dir','chrome_profile','questions_path','ledger_path','export_path','db_path','browser_config'):
                if options.get(key):
                    options[key] = str(Path(options[key]).expanduser().resolve())
            if not resume_dir and options.get('export_path') and Path(options['export_path']).exists():
                path = Path(options['export_path'])
                options['export_path'] = str(path.with_name(path.stem+'-'+run.manifest['id']+path.suffix))
            # New runs never read the shared history. Legacy explicit resumes
            # migrate only owned attempts without changing the shared ledger.
            options['ledger_path'] = str(Path(ledger_path).expanduser().resolve()) if application_tab is not None else local_ledger(run)
            options['execution_scope'] = 'linkedin_handoff' if application_tab is not None else 'independent'
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
            if ledger_path and application_tab is None:
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
            if application_tab is not None:
                driver_factory = lambda: application_tab.driver
            if driver_factory is None:
                if backend=='kernel':
                    driver_factory=lambda:KernelBrowser(settings=kernel_settings,run_id=run.manifest['id'],session_id=options.get('kernel_session_id') if resume_dir else None,
                        telemetry_offset=options.get('kernel_telemetry_offset',0) if resume_dir else 0)
                else:
                    from direct_apply import browser_factory
                    profile = options['chrome_profile'] or directory/'chrome-profile'
                    driver_factory = browser_factory(profile, debugger_address=options.get('debugger_address'))
            if options['workers'] > 1:
                return _run_parallel_submissions(run,options=options,services=svc,ledger=ledger,
                    driver_factory=driver_factory,driver_factory_is_default=driver_factory_is_default,
                    kernel_settings=kernel_settings,backend=backend,preparer=preparer,
                    review_factory=review_factory,allow_local=allow_local,
                    confirmation_timeout=confirmation_timeout,tab_monitor_factory=tab_monitor_factory,
                    retry_failed=retry_failed)
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
                    if application_tab is not None:
                        driver.switch_to.window(application_tab.handle)
                    else:
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
                    if stored.get('status')=='applied' and stored.get('attempt_id')==attempt:
                        saved_state=next((saved for row,saved in run.rows() if row['key']==job['key']),{})
                        if close_browser_tab(driver,saved_state.get('tab_handle')):
                            print('[Submit] Closed confirmed application tab: '+job.get('title',job['url']),flush=True)
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
                    if driver and not manual_tabs and not keep_browser and application_tab is None:
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
            if manual_tabs and options['pause']!='never' and application_tab is None:
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
                try:
                    if manual_tabs:
                        manual_tabs.close()
                    retain_browser=any(s['status'] not in {'applied','duplicate','discarded','pending'} for _,s in run.rows())
                    if application_tab is not None:
                        pass  # The search runner owns browser lifetime and retained employer tabs.
                    elif driver and getattr(driver,'browser_backend',None)=='kernel':
                        driver.finish(retain=retain_browser)
                    elif manual_tabs or keep_browser or retain_browser:
                        # Leave unresolved employer pages open for manual review.
                        if driver and driver_factory_is_default:
                            try:driver.service.stop()
                            except Exception:pass
                    elif driver:
                        try: driver.quit()
                        except Exception: pass
                finally:
                    try:
                        final_progress=run.export()
                        summary=build_run_summary(final_progress)
                        write_json(directory/'summary.json', summary)
                        elapsed=summary.get('elapsed_seconds')
                        print('[Run summary] Confirmed {confirmed_submissions}/{total_jobs} '
                              '({confirmed_rate_percent:.1f}%); uncertain {unresolved_submission_count}; '
                              'email verification pending {email_verification_pending_count}; '
                              'blocked {blocked_count}; failed before submit {failed_before_submit_count}; '
                              'retryable before submit {retryable_before_submit_count}; '
                              'unattempted {unattempted_count}; elapsed {elapsed}. Summary: {path}'.format(
                                  **summary, elapsed=(f'{elapsed}s' if elapsed is not None else 'unknown'),
                                  path=str(directory/'summary.json')), flush=True)
                    finally:
                        run.close()
