"""Retained employer tabs and background, posting-scoped manual-submit monitoring.

CDP reads individual targets without activating them. WebDriver remains on the
tab being prepared; no polling loop steals focus from the user's review tab.
"""
import json
from pathlib import Path
import re
import time
from urllib.request import urlopen

from .direct_careers_apply import write_json
from .external_apply import CONFIRMATION_SELECTOR, APPLICATION_SUCCESS_SELECTOR, ExternalApplicationResult, _confirmed
from .generic_submit import _identity_ok, unknown_answers, validate_final
from .submit_state import now


PROBE = r"""(() => {
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const texts=q=>[...document.querySelectorAll(q)].filter(visible).map(e=>e.innerText.trim()).filter(Boolean);
 const guard=window.__jobroboPrepare, config=guard?.manualHandoff||window.__jobroboManualConfig;
 let record=guard?.manualRecord||null;
 try {if(config)record=JSON.parse(sessionStorage.getItem('jobrobo.manual.'+config.token)||'null')||record;}catch{}
 return {url:location.href,top:window===window.top,headings:texts('__JOBROBO_CONFIRMATION_SELECTOR__'),
   application_success:texts('__JOBROBO_APPLICATION_SUCCESS_SELECTOR__'),
   alerts:texts('[role=alert],[aria-live=assertive],.ashby-application-form-error-container'),
   rejected:/your form needs corrections|missing entry for required field|unable to submit|could not submit|submission failed/i.test(document.body?.innerText||''),
   invalid:[...document.querySelectorAll('input,textarea,select,[aria-invalid=true]')].filter(visible)
     .some(e=>e.getAttribute('aria-invalid')==='true'||e.validity&&!e.validity.valid),
   email_verification:/verification code was sent|8.character code|verify your email|enter (?:the |your )?(?:verification|one.time|security) code/i.test(document.body?.innerText||'')||[...document.querySelectorAll('input[id^="security-input-"]')].some(visible),
   challenge:[...document.querySelectorAll('iframe')].some(e=>visible(e)&&e.getBoundingClientRect().height>100&&/captcha|challenge/i.test(e.src+' '+e.title)),
   record};
})()""".replace('__JOBROBO_CONFIRMATION_SELECTOR__', CONFIRMATION_SELECTOR).replace('__JOBROBO_APPLICATION_SUCCESS_SELECTOR__', APPLICATION_SUCCESS_SELECTOR)
DUPLICATE = re.compile(r'\byou (?:have )?(?:already|previously) (?:applied|submitted an application) (?:for|to) (?:this|the) (?:job|role|position)\b', re.I)
REJECTED = re.compile(r'form needs corrections|missing entry for required|please (?:complete|correct|fill)|required field|field is required|invalid (?:email|phone)|unable to submit|could not submit|submission failed', re.I)


def close_browser_tab(driver, handle):
    """Close one known-complete job tab without disturbing retained review tabs."""
    if not handle:
        return False
    try:
        handles=list(driver.window_handles)
        if handle not in handles:
            return False
        try: current=driver.current_window_handle
        except Exception: current=None
        driver.switch_to.window(handle)
        driver.close()
        remaining=list(driver.window_handles)
        if current in remaining:
            driver.switch_to.window(current)
        elif remaining:
            index=handles.index(handle)
            following=next((candidate for candidate in handles[index+1:] if candidate in remaining),None)
            preceding=next((candidate for candidate in reversed(handles[:index]) if candidate in remaining),None)
            driver.switch_to.window(following or preceding or remaining[0])
        return True
    except Exception:
        # Tab cleanup is best-effort; never replace a confirmed application
        # outcome with a browser-cleanup failure.
        return False


class TargetReader:
    """Read main/child frame contexts and trusted-click events on one target."""
    def __init__(self, address, target, *, token=None):
        import websocket
        # The address comes only from local Chrome capabilities/saved run state.
        if not re.fullmatch(r'(?:localhost|127\.0\.0\.1|\[::1\]):\d+', address):
            raise ValueError('Manual tab monitoring needs a local Chrome debugger')
        with urlopen('http://'+address+'/json/list', timeout=3) as response:
            targets=json.load(response)
        entry=next((t for t in targets if t['id']==target), None)
        if entry is None: raise LookupError('Employer tab is no longer open')
        self.ws=websocket.create_connection(entry['webSocketDebuggerUrl'], suppress_origin=True, timeout=3)
        self.sequence=0; self.contexts={}; self.events=[]; self.pending=[]; self.token=token
        self.call('Runtime.enable')
        self.call('Runtime.addBinding', {'name':'jobroboManualEvent'})
        self.call('Target.setAutoAttach', {'autoAttach':True,'waitForDebuggerOnStart':False,'flatten':True,'filter':[{'type':'iframe'},{'exclude':True}]})
        self.children()

    def event(self, packet):
        method=packet.get('method'); params=packet.get('params',{}); session=packet.get('sessionId')
        if method=='Runtime.executionContextCreated':
            context=params['context']
            if context.get('auxData',{}).get('isDefault'):
                self.contexts[(session,context['id'])]=True
        elif method=='Runtime.executionContextDestroyed':
            self.contexts.pop((session,params['executionContextId']),None)
        elif method=='Runtime.executionContextsCleared':
            self.contexts={k:v for k,v in self.contexts.items() if k[0]!=session}
        elif method=='Runtime.bindingCalled' and params.get('name')=='jobroboManualEvent':
            try:
                event=json.loads(params['payload'])
                if isinstance(event,dict):self.events.append(event)
            except (ValueError,TypeError):pass
        elif method=='Target.attachedToTarget': self.pending.append(params['sessionId'])
        elif method=='Target.detachedFromTarget':
            self.contexts={k:v for k,v in self.contexts.items() if k[0]!=params['sessionId']}

    def call(self, method, params=None, session=None):
        self.sequence+=1; ident=self.sequence
        packet={'id':ident,'method':method,'params':params or {}}
        if session:packet['sessionId']=session
        self.ws.settimeout(3); self.ws.send(json.dumps(packet))
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            message=json.loads(self.ws.recv())
            if message.get('id')==ident:
                if 'error' in message:raise RuntimeError('Chrome target command failed')
                return message.get('result',{})
            self.event(message)
        raise TimeoutError('Chrome target did not respond')

    def children(self):
        while self.pending:
            session=self.pending.pop(0)
            self.call('Runtime.enable',session=session)
            self.call('Runtime.addBinding',{'name':'jobroboManualEvent'},session=session)
            self.call('Target.setAutoAttach',{'autoAttach':True,'waitForDebuggerOnStart':False,'flatten':True,'filter':[{'type':'iframe'},{'exclude':True}]},session=session)

    def read(self):
        import websocket
        self.ws.settimeout(.01)
        while True:
            try:
                raw=self.ws.recv()
                if not raw:raise ConnectionError('Employer tab closed')
                self.event(json.loads(raw))
            except websocket.WebSocketTimeoutException:break
        self.children()
        states=[]
        for session,context in list(self.contexts):
            try:
                expression=PROBE.replace('window.__jobroboManualConfig;', 'window.__jobroboManualConfig||'+json.dumps({'token':self.token})+';') if self.token else PROBE
                result=self.call('Runtime.evaluate',{'expression':expression,'contextId':context,'returnByValue':True},session)
                value=result.get('result',{}).get('value')
                if isinstance(value,dict):states.append(value)
            except RuntimeError:continue  # An execution context can disappear during navigation.
        events,self.events=self.events,[]
        return states,events

    def close(self):
        try:self.ws.close()
        except Exception:pass


class ManualTabs:
    def __init__(self, driver, run, ledger, *, allow_local=False, confirmation_timeout=30,
                 job_keys=None, persist_run_options=True):
        self.driver=driver; self.run=run; self.ledger=ledger
        self.allow_local=allow_local; self.timeout=confirmation_timeout
        self.job_keys=set(job_keys) if job_keys is not None else None
        self.address=driver.capabilities['goog:chromeOptions']['debuggerAddress']
        self.tabs={}; self.last_heartbeat=time.monotonic()
        if persist_run_options:
            if getattr(driver,'browser_backend',None)=='kernel':
                run.set_options({**run.options,**driver.runtime_metadata})
            else:run.set_options({**run.options,'debugger_address':self.address})

    def reader(self,target,token):
        if getattr(self.driver,'browser_backend',None) in {'kernel','playwright'}:
            return self.driver.target_reader(target,token=token)
        return TargetReader(self.address,target,token=token)

    def handoff(self, browser, report, root, *, job, attempt_id):
        state,button,reason=validate_final(browser,report)
        unknown=unknown_answers(report)
        target=browser.driver.execute_cdp_cmd('Target.getTargetInfo',{})['targetInfo']['targetId']
        reader=self.reader(target,attempt_id)  # Monitoring must exist before final clicks are enabled.
        config={'token':attempt_id}
        context=browser.context
        aliases=list(dict.fromkeys([report['url'],report['resolved_url'],state['url']]))
        if not _identity_ok(state['url'],report['resolved_url'],allow_local=self.allow_local):
            # Hosted same-posting embeds can have an explicitly different URL;
            # preparation already verifies both posting identities.
            from .external_apply import identify_ats
            first,second=identify_ats(state['url']),identify_ats(report['resolved_url'])
            if first and second and first.key!=second.key:
                reader.close();raise ValueError('Manual tab belongs to a different posting')
        outcome=ExternalApplicationResult('submitting',report['url'],attempt_id=attempt_id,
            resume_name=report['attachment']['name'],resume_sha256=report['resume']['pdf_sha256'])
        self.ledger.record_aliases(outcome,aliases,job['id'])
        info={'target_id':target,'token':attempt_id,'aliases':aliases,'resolved_url':report['resolved_url'],
            'form_url':state['url'],'baseline':state.get('headings',[])+state.get('alerts',[]),
            'resume_name':report['attachment']['name'],'resume_sha256':report['resume']['pdf_sha256'],
            'report_path':str(Path(root)/'report.json'),'activations':0,'review_reasons':unknown,
            'initially_complete':bool(button) and not report.get('blockers')}
        # Checkpoint ownership before allowing any trusted manual activation.
        self.run.update(job,status='awaiting_manual_submit' if info['initially_complete'] else 'awaiting_correction',
            stage='manual_tab',manual_tab=info,attempt_id=attempt_id,review_reasons=unknown,
            resume_sha256=info['resume_sha256'],retryable=False,
            reason='' if info['initially_complete'] else reason or '; '.join(report.get('blockers',[])))
        self.tabs[job['key']]={'job':job,'info':info,'reader':reader,'started':None,'done':False}
        # Reinstall on subsequent same-tab navigations, including form frames.
        source='window.__jobroboManualConfig='+json.dumps(config)+';'
        source+=browser.guard_script+'\nwindow.__jobroboPrepare.handoffManual(window.__jobroboManualConfig);'
        browser.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':source})
        for frame_state in browser.contexts():
            browser.enter(frame_state['context'])
            browser.driver.execute_script('return window.__jobroboPrepare.handoffManual(arguments[0])',config)
        browser.enter(context)
        print('[Submit] Tab ready for manual '+('Submit' if info['initially_complete'] else 'correction')+'; preparing the next job.',flush=True)
        return {'status':'awaiting_manual_submit' if info['initially_complete'] else 'awaiting_correction',
            'manual_handoff':True,'posting_aliases':aliases}

    def restore(self, job_keys=None):
        """Reconnect live handed-off tabs; never re-fill a possibly submitted tab."""
        selected=set(job_keys) if job_keys is not None else self.job_keys
        for job,state in self.run.rows():
            if selected is not None and job['key'] not in selected:continue
            info=state.get('manual_tab')
            if not info or state['status'] not in {'awaiting_manual_submit','awaiting_correction','submitting','awaiting_email_verification'}:continue
            if job['key'] in self.tabs:continue
            try:reader=self.reader(info['target_id'],info['token'])
            except Exception:
                self.run.update(job,status='submission_uncertain',stage='manual_tab_unavailable',retryable=False,
                    reason='Manual tab unavailable; inspect employer outcome before retrying')
                continue
            self.tabs[job['key']]={'job':job,'info':info,'reader':reader,'started':None,'done':False}
            if state['status']=='awaiting_email_verification':
                # Enable only trusted human continuation on this retained tab;
                # do not fill, navigate, upload or repeat automated Submit.
                try:
                    self.driver.switch_to.window(info['target_id'])
                    self.driver.execute_script('return window.__jobroboPrepare?.handoffManual(arguments[0])',{'token':info['token']})
                except Exception:
                    self.update(self.tabs[job['key']],'submission_uncertain','verification_tab_unavailable',retryable=False)
                    self.tabs[job['key']]['done']=True

    def update(self, tab, status, stage, **fields):
        self.run.update(tab['job'],status=status,stage=stage,manual_tab=tab['info'],**fields)
        path=Path(tab['info']['report_path'])
        if path.is_file():
            report=json.loads(path.read_text());report.update(status=status,manual_outcome_at=now())
            if status=='applied':report['confirmation_verified']=True
            if status=='duplicate':report['portal_duplicate_verified']=True
            write_json(path,report)

    def poll(self):
        changed=False
        for tab in self.tabs.values():
            if tab['done']:continue
            info=tab['info'];previous=next(s for j,s in self.run.rows() if j['key']==tab['job']['key'])
            try:states,events=tab['reader'].read()
            except Exception:
                self.update(tab,'submission_uncertain','manual_tab_unavailable',retryable=False,
                    reason='Tab closed or disconnected; employer outcome not confirmed')
                tab['done']=True;changed=True;continue
            records=[s.get('record') for s in states if s.get('record')]+events
            count=max([info.get('activations',0)]+[r.get('activations',0) for r in records if r.get('token')==info['token']])
            activated=count>0
            new_activation=count>info.get('activations',0)
            if new_activation:
                info['activations']=count;tab['started']=time.monotonic()
                self.update(tab,'submitting','manual_submit_observed',retryable=False);changed=True
            tops=[s for s in states if s.get('top')]
            scoped_top=any(_identity_ok(s['url'],info['resolved_url'],allow_local=self.allow_local) for s in tops)
            scoped=[s for s in states if _identity_ok(s['url'],info['form_url'],allow_local=self.allow_local) or
                    _identity_ok(s['url'],info['resolved_url'],allow_local=self.allow_local)] if scoped_top else []
            fresh=[{**s,'headings':[h for h in s['headings'] if h not in info['baseline']]} for s in scoped]
            messages=[h for s in scoped for h in s['headings']+s['alerts'] if h not in info['baseline']]
            clean=not any(s.get('challenge') for s in scoped)
            result='duplicate' if any(DUPLICATE.search(h) for h in messages) else 'applied' if any(_confirmed(s) for s in fresh) else None
            if activated and scoped and clean and result:
                outcome=ExternalApplicationResult(result,tab['job']['url'],attempt_id=info['token'],
                    resume_name=info['resume_name'],resume_sha256=info['resume_sha256'],
                    reason='Employer confirmed manual application' if result=='applied' else 'Portal reports an existing application')
                if result=='applied':outcome.submitted_at=now()
                self.ledger.record_aliases(outcome,info['aliases'],tab['job']['id'])
                self.update(tab,result,'confirmed' if result=='applied' else 'portal_duplicate',retryable=False,
                    submitted_at=outcome.submitted_at,**({'duplicate_source':'portal'} if result=='duplicate' else {}))
                tab['done']=True;changed=True
                if result=='applied':
                    tab['reader'].close()
                    state=next((saved for job,saved in self.run.rows() if job['key']==tab['job']['key']),{})
                    if close_browser_tab(self.driver,state.get('tab_handle')):
                        print('[Submit] Closed confirmed application tab: '+tab['job'].get('title',tab['job']['url']),flush=True)
                print('[Submit] '+tab['job'].get('title',tab['job']['url'])+': '+result,flush=True)
            elif scoped and any(s.get('email_verification') for s in scoped):
                if previous['status']!='awaiting_email_verification':
                    self.update(tab,'awaiting_email_verification','email_verification',retryable=False,
                        verification_after_submit=activated,reason='Complete email verification in the retained tab; original Submit is not replayed');changed=True
                tab['started']=None
            elif activated and scoped and (any(REJECTED.search(h) for h in messages) or any(s.get('invalid') or s.get('rejected') for s in scoped)):
                if previous['status']!='awaiting_correction' or new_activation:
                    self.update(tab,'awaiting_correction','portal_validation_rejected',retryable=False,
                        reason='Employer form needs correction; edit and manually Submit again');changed=True
                tab['started']=None
            elif not activated and previous['status']=='awaiting_correction' and scoped and clean and not any(s.get('invalid') or s.get('rejected') for s in scoped) and info['initially_complete']:
                self.update(tab,'awaiting_manual_submit','manual_tab',retryable=False);changed=True
            elif activated and previous['status'] not in {'awaiting_correction','submission_uncertain','awaiting_email_verification'}:
                tab['started']=tab['started'] or time.monotonic()
                if time.monotonic()-tab['started']>=self.timeout:
                    self.update(tab,'submission_uncertain','manual_confirmation_timeout',retryable=False,
                        reason='Manual activation observed; employer confirmation not seen');changed=True
                    # Keep observing: a delayed confirmation may still arrive.
        if time.monotonic()-self.last_heartbeat>=15:
            print('[Submit] Manual tabs remain open; review and Submit on the employer pages. Ctrl-C saves and leaves Chrome open.',flush=True)
            self.last_heartbeat=time.monotonic()
        return changed

    def wait(self, on_change):
        if getattr(self.driver,'browser_backend',None)=='kernel':self.driver.show_live_view()
        print('[Submit] Batch filling complete. Review the open tabs and click Submit manually.',flush=True)
        while any(not tab['done'] for tab in self.tabs.values()):
            if self.poll():on_change()
            time.sleep(.4)

    def close(self):
        for tab in self.tabs.values():tab['reader'].close()
