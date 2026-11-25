"""Read-only posting and application-input checks, separate from application runs."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import queue
import sqlite3
import threading
import time
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from .direct_careers_apply import write_json
from .external_apply import identify_ats
from .generic_prepare import canonical_url, fingerprint
from .job_pipeline.http import Document, PublicHTTPClient, embedded_json, objects, public_url
from .search_history import file_lock

POLICY_VERSION = 1
CLOSED = re.compile(r"\b(?:job (?:was |is )?not found|(?:job|position|role) (?:is |was )?no longer (?:available|open)|"
                    r"(?:job|position|role) (?:has (?:been )?|is |was )?(?:closed|filled|expired)|"
                    r"no longer accepting applications|could(?:n['’]t| not) find (?:this|the) (?:job|position))\b", re.I)
APPLY = re.compile(r'^(?:apply(?: now| for (?:this|the) (?:job|role|position))?|application|apply for this job)$',re.I)
CHALLENGE = re.compile(r'verify you are human|checking your browser|enable javascript and cookies to continue|access denied',re.I)
READ_ONLY = """document.addEventListener('submit',e=>{e.preventDefault();e.stopImmediatePropagation()},true);
HTMLFormElement.prototype.submit=function(){throw Error('Validation cannot submit')};
HTMLFormElement.prototype.requestSubmit=function(){throw Error('Validation cannot submit')};"""


def now():
    return datetime.now(timezone.utc).isoformat()


def _visible(node):
    while node:
        attrs=node.attrs
        if 'hidden' in attrs or attrs.get('aria-hidden')=='true' or re.search(
                r'display\s*:\s*none|visibility\s*:\s*hidden',attrs.get('style') or '',re.I):return False
        node=node.parent
    return True


def html_snapshot(text, url):
    document=Document(text)
    controls=[]
    for node in document.nodes():
        if node.tag not in {'input','textarea','select'} or 'disabled' in node.attrs or 'readonly' in node.attrs:continue
        parent=node.parent
        disabled=False
        while parent:
            if parent.tag=='fieldset' and 'disabled' in parent.attrs:disabled=True;break
            parent=parent.parent
        if disabled:continue
        kind=(node.attrs.get('type') or 'text').lower()
        if kind in {'hidden','submit','button','search','reset'}:continue
        if not _visible(node) and kind!='file':continue
        controls.append({'type':kind,'name':node.attrs.get('name') or node.attrs.get('id') or ''})
    roles=[]
    for data in embedded_json(document):
        for item in objects(data):
            types=item.get('@type') or []
            if 'JobPosting' in ([types] if isinstance(types,str) else types):roles.append(item)
    headings=[n.text().strip() for n in document.nodes() if n.tag in {'h1','h2','h3'} and _visible(n)]
    alerts=[n.text().strip() for n in document.nodes() if n.attrs.get('role') in {'alert','status'} and _visible(n)]
    links=[{'url':urljoin(url,n.attrs['href']),'label':n.text().strip()} for n in document.nodes('a')
           if n.attrs.get('href') and _visible(n) and APPLY.fullmatch(n.text().strip())]
    return {'url':url,'headings':headings,'alerts':alerts,'controls':controls,'roles':roles,'links':links,
            'text':' '.join(n.text() for n in document.root.children if not isinstance(n,str) and _visible(n))[:70000]}


def _form_evidence(snapshot):
    controls=snapshot.get('controls') or []
    files=sum(c.get('type')=='file' for c in controls)
    candidate=sum(c.get('type')=='email' or bool(re.search(r'email|first.?name|last.?name|full.?name|^name$',
                  c.get('name',''),re.I)) for c in controls if c.get('type')!='file')
    return {'candidate_inputs':candidate,'file_inputs':files,
            'input_types':dict(Counter(c.get('type','unknown') for c in controls)),
            'verified':bool(files and candidate)}


def _identity(expected, actual):
    left,right=identify_ats(expected),identify_ats(actual)
    if left:
        if right:return 'same' if left.key==right.key else 'different_posting'
        query=parse_qs(urlsplit(actual).query)
        if left.provider=='greenhouse' and (query.get('gh_jid')==[left.job_id] or
                query.get('token')==[left.job_id] and query.get('for')==[left.board]):return 'same'
        return 'board_redirect' if urlsplit(actual).path.rstrip('/') in {'','/'+left.board} else 'unknown'
    if canonical_url(expected,allow_local=True)==canonical_url(actual,allow_local=True):return 'same'
    a,b=urlsplit(expected),urlsplit(actual)
    ident=re.search(r'(?:^|/)(\d{6,})(?:[-/]|$)',a.path)
    if a.hostname==b.hostname and ident and ident.group(1) in b.path:return 'same'
    if b.path.rstrip('/').lower() in {'','/careers','/jobs','/careers/jobs'}:return 'board_redirect'
    return 'unknown'


def inspect_snapshot(snapshot, job, *, known_open=False):
    """A page reaching HTTP 200 is not sufficient evidence of an open job."""
    identity=_identity(job['url'],snapshot['url'])
    base={'final_url':snapshot['url'],'form':_form_evidence(snapshot),'open_verified':False}
    if identity in {'different_posting','board_redirect'}:
        return {**base,'status':'invalid','reason':identity}
    messages=[s for s in snapshot.get('headings',[])+snapshot.get('alerts',[]) if CLOSED.search(s)]
    if not messages and not snapshot.get('roles') and not base['form']['verified']:
        text=snapshot.get('text','')
        if len(text)<1500 and CLOSED.search(text):messages=[text[:500]]
    if not messages:
        messages=[h for h in snapshot.get('headings',[]) if re.fullmatch(r'\s*(?:404|page not found|404\s*[-:–]?\s*(?:page )?not found)[.!]?\s*',h,re.I)]
    if messages:return {**base,'status':'invalid','reason':'posting_closed_or_not_found','messages':messages[:3]}
    visible=snapshot.get('text','')
    if CHALLENGE.search(' '.join(snapshot.get('headings',[]))+' '+visible[:1500]):
        return {**base,'status':'needs_review','reason':'access_challenge'}
    if any(c.get('type')=='password' for c in snapshot.get('controls',[])):
        return {**base,'status':'needs_review','reason':'login_required'}
    if identity!='same':return {**base,'status':'needs_review','reason':'posting_identity_unverified'}
    roles=snapshot.get('roles',[])
    for role in roles:
        try:
            until=datetime.fromisoformat(role.get('validThrough','').replace('Z','+00:00'))
            if until.tzinfo is None:until=until.replace(tzinfo=timezone.utc)
            if until<datetime.now(timezone.utc):
                return {**base,'status':'needs_review' if base['form']['verified'] or known_open else 'invalid',
                        'reason':'expiry_metadata_conflict' if base['form']['verified'] or known_open else 'posting_expired',
                        'valid_through':role['validThrough']}
        except (ValueError,TypeError,AttributeError):pass
    title=' '.join(str(job.get('title','')).casefold().split())
    title_match=bool(title and any(title in ' '.join(h.casefold().split()) for h in snapshot.get('headings',[])))
    opened=known_open or bool(roles) or base['form']['verified'] or bool(title_match and len(visible)>120 and snapshot.get('links'))
    base['open_verified']=opened
    if opened and base['form']['verified']:return {**base,'status':'apply_ready','reason':'application_inputs_verified'}
    return {**base,'status':'open' if opened else 'needs_review',
            'reason':'published_posting_form_unverified' if opened else 'posting_not_verified'}


class HTTPChecks:
    """Thread-local sessions and shared per-host pacing/concurrency."""
    def __init__(self, timeout=12, retries=1, client_factory=None,stop=None):
        self.timeout,self.retries=timeout,retries
        self.client_factory=client_factory or (lambda:PublicHTTPClient(timeout=timeout))
        self.local=threading.local();self.lock=threading.Lock();self.hosts={};self.next_request={}
        self.stop=stop or threading.Event()

    def get(self,url):
        if not public_url(url):return {'status':0,'reason':'unsafe_url','url':url,'text':''}
        host=urlsplit(url).hostname
        with self.lock:slot=self.hosts.setdefault(host,threading.BoundedSemaphore(2))
        with slot:
            if self.stop.is_set():return {'status':0,'reason':'interrupted','url':url,'text':''}
            if not hasattr(self.local,'client'):self.local.client=self.client_factory()
            for attempt in range(self.retries+1):
                if self.stop.is_set():return {'status':0,'reason':'interrupted','url':url,'text':''}
                with self.lock:
                    delay=max(0,self.next_request.get(host,0)-time.monotonic())
                    self.next_request[host]=time.monotonic()+delay+.25
                if delay and self.stop.wait(delay):return {'status':0,'reason':'interrupted','url':url,'text':''}
                try:
                    response=self.local.client.get(url,timeout=self.timeout)
                    code=response.status_code
                    result={'status':code,'url':response.url or url,'text':response.text}
                    if code not in {429,500,502,503,504} or attempt==self.retries:return result
                    try:wait=min(15,max(0,float(response.headers.get('Retry-After',1))))
                    except (ValueError,TypeError,AttributeError):wait=1
                except Exception as error:
                    result={'status':0,'url':url,'text':'','reason':getattr(error,'code','network'),
                            'error_kind':type(error).__name__}
                    if attempt==self.retries or result['reason']=='unsafe_url':return result
                    wait=1
                self.stop.wait(wait)


def _board_key(job):
    if job.get('input_url_error'):return None
    identity=identify_ats(job['url'])
    return (identity.provider,identity.host,identity.board) if identity else None


def fetch_board(key,http):
    provider,host,board=key
    slug=quote(board,safe='')
    if provider=='ashby':url=f'https://api.ashbyhq.com/posting-api/job-board/{slug}'
    elif provider=='greenhouse':
        if host!='greenhouse_us':return {'jobs':{},'complete':False,'reason':'unsupported_region'}
        url=f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'
    else:url=f'https://{"api.eu.lever.co" if host=="jobs.eu.lever.co" else "api.lever.co"}/v0/postings/{slug}?mode=json&limit=100&skip=0'
    jobs={}
    for page in range(20):
        response=http.get(url)
        if response['status']!=200:return {'jobs':jobs,'complete':False,'reason':'board_http_'+str(response['status'])}
        try:
            data=json.loads(response['text']);rows=data if provider=='lever' else data['jobs']
            if not isinstance(rows,list):raise ValueError()
            for row in rows:
                if not isinstance(row,dict):raise ValueError()
                link=row.get('jobUrl') or row.get('hostedUrl') or row.get('absolute_url')
                if provider=='greenhouse':link=f'https://job-boards.greenhouse.io/{board}/jobs/{row["id"]}'
                identity=identify_ats(link)
                if not identity:continue
                # Direct-link/unlisted postings are still valid candidates.
                jobs[identity.key]={'url':link,'apply_url':row.get('applyUrl') or row.get('apply_url') or link,
                                    'title':row.get('title') or row.get('text'), 'api_url':url}
        except (ValueError,KeyError,TypeError):return {'jobs':jobs,'complete':False,'reason':'board_schema_unverified'}
        if provider!='lever' or len(rows)<100:return {'jobs':jobs,'complete':True}
        url=re.sub(r'skip=\d+',f'skip={(page+1)*100}',url)
    return {'jobs':jobs,'complete':False,'reason':'board_pagination_limit'}


def check_http(job,board,http,check_inputs):
    if job.get('input_url_error'):
        return {'status':'invalid','reason':'invalid_url','open_verified':False,'form':{'verified':False}}
    identity=identify_ats(job['url'])
    published=(board or {}).get('jobs',{}).get(identity.key) if identity else None
    target=published['apply_url'] if published and check_inputs else job['url']
    if not public_url(target) or _identity(job['url'],target)!='same':target=job['url']
    response=http.get(target)
    fallback={}
    if target!=job['url'] and response['status'] in {404,410}:
        # An ATS can publish a stale application URL while the posting still
        # offers a working application route. Check the supplied URL too.
        fallback={'failed_apply_url':target,'failed_apply_http_status':response['status']}
        response=http.get(job['url'])
        target=job['url']
    evidence={'http_status':response['status'],'checked_url':target,'final_url':response['url'],
              'api_verified':bool(published),'api_url':published.get('api_url') if published else None,
              'board_complete':(board or {}).get('complete'),'open_verified':bool(published),'form':{'verified':False},**fallback}
    code=response['status']
    if code in {404,410}:
        return {**evidence,'status':'needs_review' if published else 'invalid',
                'reason':'api_http_conflict' if published else 'http_'+str(code)}
    if code!=200:
        return {**evidence,'status':'invalid' if response.get('reason')=='unsafe_url' else 'needs_review',
                'reason':response.get('reason') or 'http_'+str(code)}
    snapshot=html_snapshot(response['text'],response['url'])
    result=inspect_snapshot(snapshot,job,known_open=bool(published))
    if published and result['reason']=='posting_closed_or_not_found':
        result.update(status='needs_review',reason='conflicting_closed_message')
    return {**evidence,**result,'links':snapshot['links']}


DOM_SNAPSHOT = r"""return (()=>{
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&getComputedStyle(e).display!=='none';
 const all=s=>[...document.querySelectorAll(s)];
 const controls=all('input,textarea,select').filter(e=>!e.matches(':disabled')&&!e.readOnly&&(visible(e)||e.type==='file')&&!['hidden','submit','button','search','reset'].includes(e.type)).map(e=>({type:e.type||'text',name:e.name||e.id||''}));
 const roles=[];const walk=x=>{if(!x||typeof x!=='object')return;if((Array.isArray(x['@type'])?x['@type']:[x['@type']]).includes('JobPosting'))roles.push(x);for(const v of Object.values(x)){if(v&&typeof v==='object'){if(Array.isArray(v))v.forEach(walk);else walk(v)}}};
 for(const e of all('script[type="application/ld+json"]')){try{walk(JSON.parse(e.textContent))}catch{}}
 return {url:location.href,text:(document.body?.innerText||'').slice(0,70000),controls,roles,
 headings:all('h1,h2,h3').filter(visible).map(e=>e.innerText.trim()),
 alerts:all('[role=alert],[role=status]').filter(visible).map(e=>e.innerText.trim()),
 links:all('a[href]').filter(e=>visible(e)&&/^(apply( now| for (this|the) (job|role|position))?|application)$/i.test(e.innerText.trim())).map(e=>({url:e.href,label:e.innerText.trim()}))};
})()"""


class BrowserChecks:
    """One fresh, read-only Chrome per owning worker; never use application profiles."""
    def __init__(self, timeout=12, screenshot_dir=None, driver_factory=None, allow_local=False):
        self.timeout,self.screenshot_dir,self.allow_local=timeout,screenshot_dir,allow_local
        if driver_factory:self.driver=driver_factory()
        else:
            from selenium import webdriver
            options=webdriver.ChromeOptions();options.add_argument('--headless=new')
            options.page_load_strategy='eager'
            self.driver=webdriver.Chrome(options=options)
        try:
            self.driver.set_page_load_timeout(timeout)
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':READ_ONLY})
        except Exception:
            self.driver.quit()
            raise

    def _safe(self,url):
        return bool(public_url(url) or self.allow_local and urlsplit(url).hostname in {'127.0.0.1','localhost'})

    def _finish(self,result,job):
        result={**result,'browser_checked':True}
        if self.screenshot_dir:
            path=Path(self.screenshot_dir)/(fingerprint(job['key'])[:24]+'.png')
            path.parent.mkdir(parents=True,exist_ok=True)
            try:
                self.driver.save_screenshot(str(path))
                result['screenshot']=str(path.resolve())
            except Exception:pass
        return result

    def check(self,job,previous):
        url=previous.get('checked_url') or job['url']
        if not self._safe(url):return {'status':'needs_review','reason':'unsafe_browser_target'}
        visited=set();last=previous
        for navigation in range(2):
            visited.add(url)
            try:
                self.driver.get(url)
                deadline=time.monotonic()+self.timeout
                while True:
                    self.driver.switch_to.default_content()
                    snapshot=self.driver.execute_script(DOM_SNAPSHOT)
                    if not self._safe(snapshot['url']):
                        return self._finish({'status':'needs_review','reason':'unsafe_browser_redirect'},job)
                    last=inspect_snapshot(snapshot,job,known_open=previous.get('api_verified',False))
                    if last['status']=='apply_ready' or last['status']=='invalid' or last['reason'] in {'access_challenge','login_required'}:
                        return self._finish(last,job)
                    # Only inspect posting-bound application frames, never CAPTCHA/advertising frames.
                    for frame in self.driver.find_elements('css selector','iframe')[:4]:
                        src=frame.get_attribute('src')
                        if not src or not self._safe(src) or _identity(job['url'],src)!='same':continue
                        try:
                            self.driver.switch_to.frame(frame)
                            embedded=self.driver.execute_script(DOM_SNAPSHOT)
                            result=inspect_snapshot(embedded,job,known_open=last.get('open_verified',False))
                            if result['status'] in {'apply_ready','invalid'}:return self._finish(result,job)
                        finally:self.driver.switch_to.default_content()
                    link=next((link['url'] for link in snapshot.get('links',[]) if link['url'] not in visited
                               and self._safe(link['url']) and _identity(job['url'],link['url'])=='same'),None)
                    if link:
                        url=link
                        break
                    if time.monotonic()>=deadline:
                        return self._finish({**last,'status':'needs_review','reason':'application_inputs_unverified'},job)
                    time.sleep(.35)
            except Exception as error:
                return self._finish({'status':'needs_review','reason':'browser_error','error_kind':type(error).__name__},job)
        return self._finish({**last,'status':'needs_review','reason':'application_navigation_limit'},job)

    def close(self):
        self.driver.quit()


def _browser_needed(result):
    return result['status']=='open' or (result['status']=='needs_review' and result['reason'] in {
        'posting_not_verified','posting_identity_unverified','conflicting_closed_message','api_http_conflict'})


def validate_jobs(jobs, *, output_dir, check_inputs=False, workers=8, browser_workers=2,
                  timeout=12, resume=False, refresh=False, client_factory=None, browser_factory=None,
                  screenshots=False):
    """Check public pages without credentials, filling, uploads or submission."""
    if type(workers) is not int or not 1<=workers<=64:raise ValueError('HTTP workers must be between 1 and 64')
    if type(browser_workers) is not int or not 1<=browser_workers<=16:raise ValueError('Browser workers must be between 1 and 16')
    if timeout<=0:raise ValueError('Validation timeout must be positive')
    if not jobs:raise ValueError('At least one job is required')
    if refresh and not resume:raise ValueError('--refresh requires --resume')
    directory=Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    controlled={directory/name for name in ['input.json','validation-report.json','jobs-open.json','jobs-apply-ready.json']}
    if any(Path(j.get('provenance',{}).get('source','')).resolve() in controlled for j in jobs):
        raise ValueError('Validation output must not overwrite its input')
    selection=fingerprint({'policy':POLICY_VERSION,'jobs':jobs,'check_inputs':check_inputs})
    with file_lock(directory/'validation.lock'):
        database=directory/'validation.sqlite3'
        existed=database.exists()
        if existed and not resume:raise ValueError('Validation exists; use --resume or a new output directory')
        if resume and not existed:raise ValueError('No validation checkpoint exists to resume')
        conn=sqlite3.connect(database,check_same_thread=False)
        database.chmod(0o600)
        lock=threading.RLock();results={};started=now();stop=threading.Event()
        try:
            conn.execute('PRAGMA synchronous=FULL')
            conn.executescript('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);'
                               'CREATE TABLE IF NOT EXISTS checks(key TEXT PRIMARY KEY,result TEXT NOT NULL);')
            old=conn.execute("SELECT value FROM meta WHERE key='selection'").fetchone()
            if old and old[0]!=selection:raise ValueError('Resume requires the same input selection and --check-inputs setting')
            if not old:
                with conn:
                    conn.execute('INSERT INTO meta VALUES (?,?)',('selection',selection))
                    conn.execute('INSERT INTO meta VALUES (?,?)',('started_at',started))
                write_json(directory/'input.json',{'jobs':jobs})
            else:started=conn.execute("SELECT value FROM meta WHERE key='started_at'").fetchone()[0]
            if refresh:
                with conn:conn.execute('DELETE FROM checks')
            if not refresh:
                for key,value in conn.execute('SELECT key,result FROM checks'):
                    result=json.loads(value)
                    age=(datetime.now(timezone.utc)-datetime.fromisoformat(result['checked_at'])).total_seconds()
                    if (result['status'] in {'apply_ready','invalid'} or result['status']=='open' and not check_inputs) and age<6*3600:
                        results[key]=result

            def export(complete=False,full=False):
                counts=Counter(r['status'] for r in results.values())
                summary={'schema':'job-url-validation-v1','started_at':started,'observed_at':now(),
                         'selection_sha256':selection,'check_inputs':check_inputs,'total_jobs':len(jobs),
                         'checked_jobs':len(results),'pending_jobs':len(jobs)-len(results),
                         'pending_browser_pages':sum(bool(r.get('browser_pending')) for r in results.values()),
                         'status_counts':dict(counts),'complete':complete,'read_only':True,
                         'workers':workers,'browser_workers':browser_workers}
                write_json(directory/'progress.json',summary)
                if full:
                    report=[{'id':j['id'],'url':j['url'],'company':j.get('company'),'title':j.get('title'),
                             **results.get(j['key'],{'status':'pending'})} for j in jobs]
                    write_json(directory/'validation-report.json',{**summary,'results':report})
                    for filename,states in [('jobs-open.json',{'open','apply_ready'}),('jobs-apply-ready.json',{'apply_ready'})]:
                        retained=[{**j,'validation':{**results[j['key']],
                                      'input_provenance':j.get('provenance',{}),
                                      'admission_blockers':j.get('admission_blockers',[])}} for j in jobs
                                  if results.get(j['key'],{}).get('status') in states]
                        write_json(directory/filename,{'jobs':retained})
                return summary

            saves=0
            def save(job,result):
                nonlocal saves
                result={**result,'checked_at':now()}
                result.pop('links',None)
                with lock:
                    results[job['key']]=result
                    with conn:conn.execute('INSERT OR REPLACE INTO checks VALUES (?,?)',(job['key'],json.dumps(result)))
                    saves+=1
                    export(full=saves%25==0)

            export(full=True)
            pending=[j for j in jobs if j['key'] not in results]
            http=HTTPChecks(timeout=timeout,client_factory=client_factory,stop=stop)
            board_keys=set(filter(None,(_board_key(j) for j in pending)))
            boards={}
            print(f'[Validate] {len(jobs)} jobs; {len(pending)} to check; {len(board_keys)} ATS boards',flush=True)
            finished=False
            try:
                with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='job-url-http') as pool:
                    futures={pool.submit(fetch_board,key,http):key for key in board_keys}
                    try:
                        for future in as_completed(futures):boards[futures[future]]=future.result()
                        futures={pool.submit(check_http,j,boards.get(_board_key(j)),http,check_inputs):j for j in pending}
                        browser_queue=queue.Queue()
                        for future in as_completed(futures):
                            job=futures[future]
                            try:result=future.result()
                            except Exception as error:result={'status':'needs_review','reason':'http_check_error','error_kind':type(error).__name__}
                            needs_browser=check_inputs and _browser_needed(result)
                            save(job,{**result,'browser_pending':bool(needs_browser)})
                            if needs_browser:browser_queue.put((job,result))
                    except KeyboardInterrupt:
                        stop.set()
                        for future in futures:future.cancel()
                        raise
                if check_inputs and not browser_queue.empty():
                    print(f'[Validate] {browser_queue.qsize()} application pages need browser inspection',flush=True)
                    def browser_loop():
                        checker=None;startup_error=None
                        try:
                            while not stop.is_set():
                                try:job,previous=browser_queue.get_nowait()
                                except queue.Empty:break
                                try:
                                    if startup_error:raise RuntimeError(startup_error)
                                    if checker is None:
                                        checker=browser_factory() if browser_factory else BrowserChecks(
                                            timeout=timeout,screenshot_dir=directory/'screenshots' if screenshots else None)
                                    result=checker.check(job,previous)
                                except Exception as error:
                                    if checker is None:startup_error=type(error).__name__
                                    result={'status':'needs_review','reason':'browser_start_or_check_error','error_kind':startup_error or type(error).__name__}
                                save(job,{**previous,**result,'browser_pending':False})
                        finally:
                            if checker:
                                try:checker.close()
                                except Exception:pass
                    with ThreadPoolExecutor(max_workers=browser_workers,thread_name_prefix='job-url-browser') as pool:
                        futures=[pool.submit(browser_loop) for _ in range(min(browser_workers,browser_queue.qsize()))]
                        try:
                            for future in as_completed(futures):future.result()
                        except KeyboardInterrupt:
                            stop.set()
                            raise
                finished=True
            except KeyboardInterrupt:
                stop.set()
                print('[Validate] Interrupted; completed checks are saved. Repeat with --resume.',flush=True)
            finally:
                with lock:summary=export(complete=finished,full=True)
            print('[Validate] '+json.dumps(summary['status_counts'])+' | '+str(directory/'validation-report.json'),flush=True)
            return summary
        finally:conn.close()
