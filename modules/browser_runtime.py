"""Browser-action boundary for the generic form engine.

Local Selenium remains native. The Playwright adapter implements only the
operations used by this engine; it is not a general WebDriver implementation.
DOM references are scoped to their original frame and never serialized to disk.
"""
from pathlib import Path
from types import SimpleNamespace
import uuid


class BrowserOperationError(ValueError):
    pass


BRIDGE_JS = r"""payload => {
 const registry=window.__jobroboElements ||= {nodes:new Map(),ids:new WeakMap(),seq:0,prefix:crypto.randomUUID?.()||String(Math.random())};
 const unpack=x=>{
   if(x&&typeof x==='object'&&Object.keys(x).length===1&&x.__jobroboRef)return registry.nodes.get(x.__jobroboRef);
   if(Array.isArray(x))return x.map(unpack);
   if(x&&typeof x==='object')return Object.fromEntries(Object.entries(x).map(([k,v])=>[k,unpack(v)]));
   return x;
 };
 const pack=x=>{
   if(x instanceof Element){let id=registry.ids.get(x);if(!id){id=registry.prefix+'-'+(++registry.seq);registry.ids.set(x,id);registry.nodes.set(id,x)}return {__jobroboRef:id};}
   if(Array.isArray(x))return x.map(pack);
   if(x&&typeof x==='object')return Object.fromEntries(Object.entries(x).map(([k,v])=>[k,pack(v)]));
   return x===undefined?null:x;
 };
 const result=(new Function(payload.script)).apply(null,unpack(payload.args));
 return pack(result);
}"""


class FormControl:
    def __init__(self, runtime, frame, reference):
        self.runtime,self.frame,self.reference=runtime,frame,reference

    def handle(self):
        handle=self.frame.evaluate_handle('(id)=>window.__jobroboElements?.nodes.get(id)',self.reference).as_element()
        if handle is None:raise BrowserOperationError('Form control changed; read the page again')
        return handle

    def click(self):
        # Playwright actionability retries precede the one dispatched click.
        # The submission guard and durable claim still own final activation.
        try:self.handle().click(timeout=5000)
        except Exception as error:
            from selenium.common.exceptions import ElementClickInterceptedException
            raise ElementClickInterceptedException('Browser control could not be clicked') from None

    def clear(self):
        self.handle().fill('')

    def send_keys(self,*values):
        handle=self.handle()
        if handle.get_attribute('type')=='file':
            path=Path(str(values[0])).resolve()
            data=path.read_bytes()
            handle.set_input_files({'name':path.name,'mimeType':'application/pdf','buffer':data})
            import hashlib
            self.runtime.save_states[self.runtime.selected].update(selected_upload_name=path.name,
                selected_upload_sha256=hashlib.sha256(data).hexdigest())
            return
        keys={'\ue003':'Backspace','\ue004':'Tab','\ue006':'Enter','\ue007':'Enter',
              '\ue00c':'Escape','\ue010':'End','\ue011':'Home','\ue012':'ArrowLeft',
              '\ue013':'ArrowUp','\ue014':'ArrowRight','\ue015':'ArrowDown','\ue017':'Delete'}
        modifier=None; buffer=''
        def flush():
            nonlocal buffer
            if not buffer:return
            if modifier:handle.press(modifier+'+'+buffer)
            elif handle.get_attribute('type') in {'date','time','datetime-local','month','week','number'}:handle.fill(buffer)
            elif (handle.get_attribute('role')=='combobox' or handle.get_attribute('aria-autocomplete')=='list'
                  or handle.evaluate("e=>e.matches('.location-input')")):handle.type(buffer)
            else:
                # Native fill dispatches input events without one CDP round trip
                # per character. The shared engine blurs before readback.
                previous=handle.evaluate("e=>e.isContentEditable?e.textContent:(e.value||'')")
                handle.fill(previous+buffer)
            buffer=''
        for char in ''.join(str(v) for v in values):
            if char in {'\ue009','\ue03d','\ue008','\ue00a','\ue000'}:
                flush();modifier={'\ue009':'Control','\ue03d':'Meta','\ue008':'Shift','\ue00a':'Alt'}.get(char)
            elif char in keys:flush();handle.press(keys[char])
            else:buffer+=char
        flush()

    def is_enabled(self):return self.handle().is_enabled()
    def is_displayed(self):return self.handle().is_visible()
    def is_selected(self):return self.handle().evaluate("e=>!!e.checked||e.getAttribute('aria-checked')==='true'")
    def get_attribute(self,name):
        return self.handle().evaluate("(e,n)=>{const v=e[n]??e.getAttribute(n);return v==null?null:String(v)}",name)


class PageSelection:
    def __init__(self,runtime):self.runtime=runtime
    def default_content(self):self.runtime.frame=self.runtime.page.main_frame
    def frame(self,element):
        frame=element.handle().content_frame()
        if frame is None:raise BrowserOperationError('Application frame is unavailable')
        self.runtime.frame=frame
    def window(self,handle):self.runtime.select_page(handle)
    def new_window(self,kind):
        if kind!='tab':raise BrowserOperationError('Only application tabs are supported')
        self.runtime.select_page(self.runtime.register_page(self.runtime.context.new_page()))


class PlaywrightActions:
    browser_backend='playwright'
    def __init__(self, playwright, browser, *, context=None):
        self.playwright,self.browser=playwright,browser
        self.page_timeout=40000
        self.context=context or (browser.contexts[0] if browser.contexts else browser.new_context())
        self.pages={};self.cdp={};self.events={};self.save_states={}
        self.switch_to=PageSelection(self)
        self.capabilities={'platformName':'linux','goog:chromeOptions':{'debuggerAddress':'playwright'}}
        self.service=SimpleNamespace(stop=lambda:None)
        def binding(source,payload):
            import json
            try:
                event=json.loads(payload)
                if isinstance(event,dict) and isinstance(event.get('token'),str):
                    rows=self.events.setdefault(event['token'],[]);rows.append(event);del rows[:-100]
            except (TypeError,ValueError):pass
        # Context-wide registration can stall a CDP reconnect across retained
        # employer/CAPTCHA frames. Existing tabs already persist manual events
        # in sessionStorage; expose a fresh callback only on newly created tabs.
        self.manual_binding=binding
        pages=self.context.pages or [self.context.new_page()]
        for page in pages:self.register_page(page)
        self.select_page(next(iter(self.pages)))

    def register_page(self,page):
        if page.url in {'','about:blank'}:
            page.expose_binding('jobroboManualEvent',self.manual_binding)
        session=self.context.new_cdp_session(page)
        ident=session.send('Target.getTargetInfo')['targetInfo']['targetId']
        self.pages[ident]=page;self.cdp[ident]=session
        saves={'pending':set(),'failed':False,'parser_pending':set(),'resume_errors':[],
               'upload_data':None,'upload_requests':{},'upload_receipt':None};self.save_states[ident]=saves
        def relevant(request):
            import re
            return request.method in {'POST','PUT','PATCH'} and re.search('ApiSetFormValue|autosave|/draft',request.url,re.I)
        page.on('request',lambda r:saves['pending'].add(r) if relevant(r) else None)
        import re
        resume_request=lambda r:bool(re.search(r'(?:pars|analy[sz]).*resume|resume.*(?:pars|analy[sz])|autofill',r.url,re.I))
        page.on('request',lambda r:saves['parser_pending'].add(r) if resume_request(r) else None)
        def upload_request(request):
            data=saves['upload_data']
            if not data or request.method not in {'POST','PUT','PATCH'}:return
            try:body=request.post_data_buffer or b''
            except Exception:return
            import base64
            match=('pdf_bytes' if data in body else 'pdf_base64' if base64.b64encode(data) in body
                   else 'multipart_filename' if b'filename="'+saves['upload_name'].encode()+b'"' in body else None)
            if match or resume_request(request):
                saves.setdefault('upload_trace',[]).append({'body_bytes':len(body),
                    'body_kind':'json' if body.lstrip().startswith(b'{') else 'multipart' if body.startswith(b'--') else 'binary',
                    'filename_present':saves['upload_name'].encode() in body,'pdf_marker_present':b'%PDF-' in body,
                    'request_match':match})
                saves['upload_trace']=saves['upload_trace'][-20:]
            if match:saves['upload_requests'][request]=match
        page.on('request',upload_request)
        # Chromium can omit multipart File bodies from passive CDP events.
        # A temporary pass-through Fetch interception supplies those entries;
        # fallback preserves other routes and never rewrites the request.
        def upload_route(route):
            upload_request(route.request)
            route.fallback()
        saves['upload_route']=upload_route
        def finished(request):
            saves['pending'].discard(request);saves['parser_pending'].discard(request)
            saves['upload_requests'].pop(request,None)
        def failed(request):
            if relevant(request):saves['failed']=True
            if resume_request(request) or request in saves['upload_requests']:saves['resume_errors'].append('network_error')
            finished(request)
        page.on('requestfinished',finished);page.on('requestfailed',failed)
        page.on('response',lambda response:saves.update(failed=True) if relevant(response.request) and response.status>=400 else None)
        def upload_response(response):
            match=saves['upload_requests'].get(response.request)
            if (resume_request(response.request) or match) and response.status>=400:saves['resume_errors'].append(response.status)
            if match and 200<=response.status<300:
                saves['upload_receipt']={'name':saves['upload_name'],'sha256':saves['upload_sha256'],
                                         'http_status':response.status,'request_match':match}
        page.on('response',upload_response)
        return ident

    def select_page(self,ident):
        page=self.pages.get(ident)
        if page is None or page.is_closed():raise BrowserOperationError('Application tab is unavailable')
        self.page=page;self.frame=page.main_frame;self.selected=ident

    @property
    def current_window_handle(self):return self.selected
    @property
    def resume_parsing(self):return bool(self.save_states.get(self.selected,{}).get('parser_pending'))
    @property
    def resume_upload_errors(self):return list(self.save_states.get(self.selected,{}).get('resume_errors',[]))
    @property
    def resume_upload_receipt(self):
        state=self.save_states.get(self.selected,{})
        value=state.get('upload_receipt')
        return {**value,'buffer_verified':state.get('selected_upload_name')==value['name'] and
                state.get('selected_upload_sha256')==value['sha256']} if value else None
    @property
    def resume_upload_trace(self):return list(self.save_states.get(self.selected,{}).get('upload_trace',[]))
    def begin_resume_upload(self,data,name):
        import hashlib
        self.save_states[self.selected].update(resume_errors=[],upload_data=data,upload_name=name,
            upload_sha256=hashlib.sha256(data).hexdigest(),upload_requests={},upload_receipt=None,
            selected_upload_name=None,selected_upload_sha256=None,upload_trace=[])
        self.page.route('**/*',self.save_states[self.selected]['upload_route'])
    def end_resume_upload(self):
        state=self.save_states[self.selected]
        state['upload_data']=None
        self.page.unroute('**/*',state['upload_route'])
    @property
    def window_handles(self):return [k for k,p in self.pages.items() if not p.is_closed()]
    @property
    def current_url(self):return self.page.url

    def execute_script(self,script,*args):
        frame=self.frame
        def encode(value):
            if isinstance(value,FormControl):
                if value.frame!=frame:raise BrowserOperationError('Control belongs to a different frame')
                return {'__jobroboRef':value.reference}
            if isinstance(value,(tuple,list)):return [encode(x) for x in value]
            if isinstance(value,dict):return {k:encode(v) for k,v in value.items()}
            return value
        def decode(value):
            if isinstance(value,dict):
                if set(value)=={'__jobroboRef'}:return FormControl(self,frame,value['__jobroboRef'])
                return {k:decode(v) for k,v in value.items()}
            if isinstance(value,list):return [decode(v) for v in value]
            return value
        try:return decode(frame.evaluate(BRIDGE_JS,{'script':script,'args':encode(args)}))
        except BrowserOperationError:raise
        except Exception:raise BrowserOperationError('Browser page operation failed; read the page again') from None

    def execute_cdp_cmd(self,method,params):
        if method=='Page.addScriptToEvaluateOnNewDocument':
            self.page.add_init_script(params['source']);return {'identifier':str(uuid.uuid4())}
        return self.cdp[self.selected].send(method,params)

    def get(self,url):
        try:self.page.goto(url,wait_until='domcontentloaded',timeout=self.page_timeout)
        except Exception as error:
            if type(error).__name__=='TimeoutError':
                from selenium.common.exceptions import TimeoutException
                raise TimeoutException('Browser navigation timed out') from None
            raise BrowserOperationError('Browser navigation failed') from None
        self.frame=self.page.main_frame

    def find_elements(self,by,value):
        import json
        selector={'id':'[id='+json.dumps(value)+']','name':'[name='+json.dumps(value)+']',
                  'tag name':value,'css selector':value,'xpath':'xpath='+value}.get(by)
        if selector is None:raise BrowserOperationError('Unsupported control selector')
        if by=='xpath':
            handles=self.frame.query_selector_all(selector)
            return [self.execute_script('return arguments[0]',self.wrap_handle(h)) for h in handles]
        return self.execute_script('return [...document.querySelectorAll(arguments[0])]',selector)

    def wrap_handle(self,handle):
        reference=handle.evaluate("e=>{const s=window.__jobroboElements ||= {nodes:new Map(),ids:new WeakMap(),seq:0,prefix:crypto.randomUUID?.()||String(Math.random())};let id=s.ids.get(e);if(!id){id=s.prefix+'-'+(++s.seq);s.ids.set(e,id);s.nodes.set(id,e)}return id}")
        return FormControl(self,self.frame,reference)

    def find_element(self,by,value):
        found=self.find_elements(by,value)
        if not found:raise BrowserOperationError('Form control not found')
        return found[0]

    def settle_fields(self):
        import time
        self.frame.evaluate('document.activeElement?.blur()')
        self.page.wait_for_timeout(300)
        deadline=time.monotonic()+8
        saves=self.save_states[self.selected]
        while saves['pending'] and time.monotonic()<deadline:self.page.wait_for_timeout(100)
        if saves['pending'] or saves['failed']:raise BrowserOperationError('Application field save did not complete successfully')

    @staticmethod
    def is_solver_frame(frame):
        import re
        from urllib.parse import urlsplit
        if frame.parent_frame is None:return False
        url=urlsplit(frame.url);host=url.hostname or ''
        return bool(re.search(r'(^|\.)(hcaptcha\.com|challenges\.cloudflare\.com|arkoselabs\.com|funcaptcha\.com|geetest\.com)$',host) or
                    re.search(r'(^|\.)(google\.com|recaptcha\.net)$',host) and url.path.startswith('/recaptcha/'))

    def set_window_size(self,width,height):self.page.set_viewport_size({'width':width,'height':height})
    def set_page_load_timeout(self,seconds):self.page_timeout=int(seconds*1000)
    def save_screenshot(self,path):self.page.screenshot(path=str(path));return True
    def close(self):self.page.close()
    def quit(self):
        try:self.browser.close()
        finally:self.playwright.stop()

    def target_reader(self,target,*,token=None):return PlaywrightTargetReader(self,target,token)


class PlaywrightTargetReader:
    def __init__(self,runtime,target,token):
        self.runtime,self.token=runtime,token
        self.page=runtime.pages.get(target)
        if self.page is None or self.page.is_closed():raise BrowserOperationError('Application tab is unavailable')
    def read(self):
        from .manual_tabs import PROBE
        import json
        if self.page.is_closed():raise BrowserOperationError('Application tab closed')
        script=PROBE.replace('window.__jobroboManualConfig;','window.__jobroboManualConfig||'+json.dumps({'token':self.token})+';')
        states=[]
        for frame in self.page.frames:
            if self.runtime.browser_backend=='kernel' and self.runtime.is_solver_frame(frame):continue
            try:
                state=frame.evaluate(script)
                if self.runtime.browser_backend=='kernel':
                    from .kernel_challenges import CHALLENGE_PROBE
                    state['challenge']=bool(frame.evaluate(CHALLENGE_PROBE)['active'])
                states.append(state)
            except Exception:continue
        events=self.runtime.events.pop(self.token,[])
        return states,events
    def close(self):pass
