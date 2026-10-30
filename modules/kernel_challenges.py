"""Bounded Kernel solver observation; page readiness remains authoritative."""
import time
from urllib.parse import urlsplit

CHALLENGE_PROBE=r"""(() => {
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const frames=[...document.querySelectorAll('iframe')].filter(visible);
 const response=[...document.querySelectorAll('[name="g-recaptcha-response"],[name="h-captcha-response"],[name="cf-turnstile-response"]')].some(e=>!!e.value);
 const provider=frames.some(e=>/hcaptcha/i.test(e.src+' '+e.title))?'hcaptcha':
   frames.some(e=>/recaptcha/i.test(e.src+' '+e.title))?'recaptcha':
   frames.some(e=>/turnstile|cloudflare/i.test(e.src+' '+e.title))?'turnstile':null;
 const overlay=frames.some(e=>/bframe|challenge|hcaptcha/i.test(e.src+' '+e.title)&&e.getBoundingClientRect().height>100);
 const invisible=e=>new URL(e.src||'about:blank',location.href).searchParams.get('size')==='invisible';
 const widget=frames.some(e=>!invisible(e)&&/captcha|turnstile|challenge/i.test(e.src+' '+e.title)&&e.getBoundingClientRect().height>=40&&e.getBoundingClientRect().width>=150);
 const text=(document.body?.innerText||'').slice(0,12000);
 return {active:!response&&(overlay||widget||/verify you are human|performing security verification|checking your browser|just a moment/i.test(text)),has_response:response,provider};
})()"""


class KernelChallenges:
    def __init__(self,runtime,timeout):
        self.runtime=runtime;self.timeout=timeout;self.last_telemetry=0;self.offset=None
        self.seen=set();self.events=[]

    def page_state(self,page):
        observed=[]
        for frame in page.frames:
            if self.runtime.is_solver_frame(frame):continue
            try:
                state=frame.evaluate(CHALLENGE_PROBE)
                if isinstance(state,dict):
                    observed.append(state)
                    if state.get('active'):return state
            except Exception:continue
        return observed[-1] if observed else {'active':True,'has_response':False,'provider':None}

    def page_active(self,page):
        return bool(self.page_state(page).get('active'))

    def _solver_reported_success(self,provider):
        aliases={'recaptcha':('recaptcha','recaptcha_v2','recaptcha_v3'),
                 'hcaptcha':('hcaptcha',), 'turnstile':('turnstile','cloudflare_turnstile')}
        expected=aliases.get(provider,(provider,))
        return any(event.get('page_correlated') is True and
                   event.get('captcha_provider') in expected and
                   event.get('type') in {'captcha_solve_result','captcha_challenge_result','captcha_solved','challenge_solved'} and
                   str(event.get('status','')).lower() in {'success','solved','passed'}
                   for event in self.events)

    def telemetry(self,page=None):
        if time.monotonic()-self.last_telemetry<3:return
        self.last_telemetry=time.monotonic()
        try:
            request={'category':['captcha'],'limit':100,'order':'asc','timeout':5}
            if self.offset is not None:request['offset']=self.offset
            events_page=self.runtime.client.browsers.telemetry.events(self.runtime.session_id,**request)
            info=events_page.next_page_info()
            # The API's X-Next-Offset cursor is opaque. A filtered empty page
            # may still advance it; sequence numbers/counts are not offsets.
            next_offset=info.params.get('offset') if info else self.offset
            for index,row in enumerate(events_page.items):
                raw=row.model_dump();seq=raw.get('seq')
                if seq in self.seen:continue
                self.seen.add(seq)
                event=raw.get('event') or {};data=event.get('data') or {}
                safe={'seq':seq,'type':event.get('type'),**{k:data.get(k) for k in ('captcha_provider','status','duration_ms','error_code','website_host','website_path','inferred') if k in data}}
                if type(next_offset) is int and next_offset>=0:
                    safe['cursor_offset']=next_offset
                target=urlsplit(page.url) if page else None
                target_id=next((ident for ident,candidate in getattr(self.runtime,'pages',{}).items()
                                if candidate is page),None) if page else None
                if target_id is None and page is getattr(self.runtime,'page',None):
                    target_id=getattr(self.runtime,'selected',None)
                event_target=data.get('target_id')
                safe['page_correlated']=bool(
                    target_id and event_target==target_id or
                    target and data.get('website_host')==target.hostname and data.get('website_path') in (None,target.path)
                )
                self.events.append(safe)
                observer=getattr(self.runtime,'session_observer',None)
                if observer:observer(safe)
                if safe['page_correlated'] and self.runtime.challenge_observer:self.runtime.challenge_observer(safe)
            self.offset=next_offset
            if not events_page.items and info:
                observer=getattr(self.runtime,'session_observer',None)
                if observer:observer({'type':'telemetry_cursor','cursor_offset':next_offset,'page_correlated':False})
        except Exception:pass  # Telemetry is best-effort; never infer readiness from silence.

    def wait(self, page, *, stage='before_submit', timeout=None):
        deadline=time.monotonic()+(self.timeout if timeout is None else timeout)
        initial=self.page_state(page)
        if not initial.get('active'):return True
        provider=initial.get('provider')
        original_url=getattr(page,'url',None)
        print('[Kernel] CAPTCHA detected; waiting for solver ('+stage+').',flush=True)
        heartbeat=time.monotonic()
        while time.monotonic()<deadline:
            self.telemetry(page)
            state=self.page_state(page)
            if not state.get('active'):
                changed_url=getattr(page,'url',None)!=original_url
                token=bool(state.get('has_response'))
                reported=self._solver_reported_success(provider) if provider else False
                needs_token=provider in {'hcaptcha','recaptcha','turnstile'}
                if not needs_token or token or reported or changed_url:
                    print('[Kernel] Challenge cleared on page; rechecking application.',flush=True)
                    return True
                # A hidden/removed CAPTCHA widget without a response is not proof
                # that the employer challenge was solved. Keep waiting so a
                # post-submit click is never treated as completed on DOM silence.
            if time.monotonic()-heartbeat>=15:
                print('[Kernel] Still waiting for CAPTCHA; no additional Submit click.',flush=True);heartbeat=time.monotonic()
            page.wait_for_timeout(400)
        detail='; response token missing' if provider in {'hcaptcha','recaptcha','turnstile'} else ''
        print('[Kernel] CAPTCHA wait budget exhausted ('+stage+detail+').',flush=True)
        return False


def wait_for_challenge(browser, *, stage='before_submit'):
    runtime=browser.driver
    if getattr(runtime,'browser_backend',None)!='kernel':return None
    return runtime.challenges.wait(runtime.page,stage=stage)
