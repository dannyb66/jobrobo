"""Optional Kernel lifecycle. Secrets and signed connection URLs stay in memory."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re

from .browser_runtime import PlaywrightActions

DEFAULTS={'stealth':True,'headless':False,'timeout_seconds':1800,
          'challenge_timeout_seconds':120,'failed_session_retention_seconds':900,
          'profile_id':None,'proxy':None,'locale':None,'timezone':None}


def browser_configuration(config_dir=None, *, backend=None, path=None):
    file=Path(path).expanduser() if path else Path(config_dir or Path(__file__).resolve().parents[1]/'config')/'browser_runtime.json'
    if path and not file.is_file():raise ValueError('Browser runtime configuration file not found')
    raw=json.loads(file.read_text()) if file.is_file() else {}
    if not isinstance(raw,dict) or set(raw)-{'default_backend','kernel'}:raise ValueError('Invalid browser runtime configuration')
    selected=backend or raw.get('default_backend','local')
    if selected not in {'local','kernel'}:raise ValueError('Browser must be local or kernel')
    extra=raw.get('kernel',{})
    if not isinstance(extra,dict) or set(extra)-set(DEFAULTS):raise ValueError('Unknown Kernel runtime setting')
    settings={**deepcopy(DEFAULTS),**extra}
    for name in ('stealth','headless'):
        if type(settings[name]) is not bool:raise ValueError('Kernel '+name+' must be boolean')
    for name,low,high in [('timeout_seconds',10,259200),('challenge_timeout_seconds',1,600),('failed_session_retention_seconds',10,259200)]:
        if type(settings[name]) is not int or not low<=settings[name]<=high:raise ValueError('Invalid Kernel '+name)
    for name in ('locale','timezone'):
        if settings[name] is not None and (not isinstance(settings[name],str) or not settings[name].strip()):raise ValueError('Invalid Kernel '+name)
    if settings['profile_id'] is not None and (not isinstance(settings['profile_id'],str) or not settings['profile_id'].strip()):raise ValueError('Invalid Kernel profile_id')
    proxy=settings['proxy']
    if proxy is not None and (not isinstance(proxy,dict) or len(proxy)!=1 or not set(proxy)<= {'mode','id','name'}):raise ValueError('Invalid Kernel proxy selection')
    if proxy is not None:
        value=next(iter(proxy.values()))
        if not isinstance(value,str) or not value.strip() or 'mode' in proxy and value not in {'direct','default'}:raise ValueError('Invalid Kernel proxy selection')
    return selected,settings


def kernel_key():
    from dotenv import dotenv_values
    return os.getenv('KERNEL_API_KEY') or dotenv_values(Path(__file__).resolve().parents[1]/'.env').get('KERNEL_API_KEY')


def kernel_preflight():
    try:
        import kernel
        import playwright.sync_api
    except ImportError:raise ValueError('Install optional browser dependencies: python3 -m pip install -r requirements-kernel.txt') from None
    if not kernel_key():raise ValueError('Set KERNEL_API_KEY in the environment or ignored local .env')


class KernelBrowser(PlaywrightActions):
    browser_backend='kernel'
    def __init__(self, *, settings, run_id, session_id=None, client=None, telemetry_offset=0):
        kernel_preflight()
        from kernel import Kernel
        from playwright.sync_api import sync_playwright
        self.client=client or Kernel(api_key=kernel_key(),max_retries=0,timeout=30)
        self.settings=settings;self.session_id=session_id;self.finished=False
        self.challenge_observer=None;self.session_observer=None
        created=False;pw=None
        try:
            if session_id:
                remote=self.client.browsers.retrieve(session_id)
            else:
                name='jobrobo-'+re.sub('[^a-zA-Z0-9_-]','_',run_id)[:100]
                request={'name':name,'stealth':settings['stealth'],'headless':settings['headless'],
                    'kiosk_mode':False,
                    'timeout_seconds':min(settings['timeout_seconds'],settings['failed_session_retention_seconds']),
                    'tags':{'application':'jobrobo','run_id':run_id},
                    'telemetry':{'enabled':True,'browser':{'captcha':{'enabled':True},'system':{'enabled':True}},'storage':{'enabled':True}}}
                if settings['profile_id']:request['profile']={'id':settings['profile_id'],'save_changes':False}
                if settings['proxy']:request['proxy']=settings['proxy']
                location={k:settings[k] for k in ('locale','timezone') if settings[k]}
                if location:request['location']=location
                try:remote=self.client.browsers.create(**request)
                except Exception as create_error:
                    # A lost create response must not create another paid browser.
                    if getattr(create_error,'status_code',500)<500 and getattr(create_error,'status_code',None)!=409:raise
                    try:remote=self.client.browsers.retrieve(name)
                    except Exception:raise create_error from None
                created=True;self.session_id=remote.session_id
            pw=sync_playwright().start()
            browser=pw.chromium.connect_over_cdp(remote.cdp_ws_url,timeout=30000)
            super().__init__(pw,browser)
            self.capabilities['goog:chromeOptions']['debuggerAddress']='kernel'
            from .kernel_challenges import KernelChallenges
            self.challenges=KernelChallenges(self,settings['challenge_timeout_seconds'])
            self.challenges.offset=telemetry_offset if session_id else 0
        except Exception as error:
            if pw:
                try:pw.stop()
                except Exception:pass
            if created and self.session_id:
                try:self.client.browsers.delete_by_id(self.session_id)
                except Exception:pass
            self.client.close()
            body=getattr(error,'body',None)
            code=body.get('code') if isinstance(body,dict) else None
            safe_code='; '+code if isinstance(code,str) and re.fullmatch('[a-z_]{1,80}',code) else ''
            raise ValueError('Kernel browser setup failed ('+type(error).__name__+safe_code+'); check credentials, connectivity and account limits') from None

    @property
    def runtime_metadata(self):
        return {'browser_backend':'kernel','kernel_session_id':self.session_id,'kernel_settings':self.settings,
                'kernel_telemetry_offset':self.challenges.offset or 0}

    def show_live_view(self):
        import webbrowser
        try:
            remote=self.client.browsers.retrieve(self.session_id)
            if remote.browser_live_view_url:
                webbrowser.open(remote.browser_live_view_url)
                print('[Kernel] Opened private live view for session '+self.session_id,flush=True)
        except Exception:print('[Kernel] Live view unavailable; inspect the session in your Kernel dashboard.',flush=True)

    def finish(self, *, retain=False):
        if self.finished:return
        self.finished=True
        try:
            if retain:
                print('[Kernel] Session retained: '+self.session_id+'; expires after configured inactivity unless reconnected.',flush=True)
            else:
                self.client.browsers.delete_by_id(self.session_id)
        except Exception:print('[Kernel] Session cleanup could not be confirmed; check your Kernel dashboard.',flush=True)
        finally:
            # Stop the connection, rather than Browser.close, when retaining.
            self.playwright.stop()
            self.client.close()

    def quit(self):self.finish(retain=False)
