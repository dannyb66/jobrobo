"""Non-submitting receipt dismissal and bounded, same-job native card clicks."""
from time import monotonic
import re
from selenium.common.exceptions import (ElementClickInterceptedException,
                                        StaleElementReferenceException, TimeoutException)
from selenium.webdriver.support.ui import WebDriverWait
from modules.linkedin_easy_apply import DIALOGS, BUTTONS, dialog_contexts, dialog_structure

HOSTS = '#interop-outlet, [data-testid="interop-shadowdom"]'
CLOSE = {'done', 'dismiss', 'close', 'close dialog', 'dismiss dialog', 'close notification',
         'dismiss application confirmation', 'close application confirmation'}


class PostSubmitUIBlocked(RuntimeError):
    def __init__(self, job_id, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(f"post_submit_cleanup [{job_id}]: blocking UI remains; evidence: {diagnostics.get('report_path', 'not saved')}")


class JobCardBlocked(RuntimeError):
    def __init__(self, job_id, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(f"select_job_card [{job_id}]: {diagnostics.get('cause_type', 'card blocked')}; evidence: {diagnostics.get('report_path', 'not saved')}")


def _visible(nodes):
    return [node for node in nodes if node.is_displayed()]


def _contexts(driver):
    contexts, _ = dialog_contexts(driver)
    # Generic shadow hosts may be the entire app; only known overlay outlets
    # count as blockers in the absence of a visible dialog.
    hosts={node.id:node for context in contexts
           for node in _visible(context.find_elements('css selector', HOSTS))}
    return contexts, list(hosts.values())


def _blocking(driver, host):
    # The outlet may persist while empty or pointer-transparent. Visibility alone
    # cannot tell whether it intercepts the results list.
    value = driver.execute_script('''/* jobrobo-overlay-blocking */
        const e=arguments[0], r=e.getBoundingClientRect();
        if(r.width<=0 || r.height<=0) return false;
        const pts=[[Math.max(0,Math.min(innerWidth-1,r.left+r.width/2)),
                    Math.max(0,Math.min(innerHeight-1,r.top+r.height/2))],
                   [Math.min(380,innerWidth/3), Math.min(280,innerHeight/3)]];
        return pts.some(([x,y])=>{const n=document.elementFromPoint(x,y);return n===e || (n && e.contains(n));});
    ''', host)
    return value is not False


def _dialog_blocks_jobs(driver, dialog, target=None):
    """Require real modality or obstruction; floating chat panels are dialogs too."""
    if (dialog.get_attribute('aria-modal') == 'true'
            or getattr(dialog, 'tag_name', '').lower() == 'dialog'
            or 'jobs-easy-apply-modal' in (dialog.get_attribute('class') or '').split()
            or re.search(r'\bapply\b|\bapplication\b', dialog.get_attribute('aria-label') or '', re.I)):
        return True
    execute=getattr(driver,'execute_script',None)
    if not callable(execute):
        return True
    script='''/* jobrobo-dialog-obstruction */
        const dialog=arguments[0], target=arguments[1];
        if(dialog.matches(':modal') || dialog.getAttribute('aria-modal')==='true')
            return {blocking:true,reason:'modal'};
        const roots=[document], cards=[];
        if(target) cards.push(target);
        else for(let i=0;i<roots.length && i<24;i++) {
            cards.push(...roots[i].querySelectorAll('[data-view-name="job-search-job-card"],'
                +'[componentkey^="job-card-component-ref-"],li[data-occludable-job-id]'));
            for(const node of roots[i].querySelectorAll('*'))
                if(node.shadowRoot && roots.length<24) roots.push(node.shadowRoot);
        }
        let checked=0;
        for(const card of cards.slice(0,200)) {
            if(checked>=3) break;
            const r=card.getBoundingClientRect();
            if(r.width<=0 || r.height<=0 || r.bottom<=0 || r.top>=innerHeight) continue;
            const x=(Math.max(0,r.left)+Math.min(innerWidth,r.right))/2,
                  y=(Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2;
            let hit=document.elementFromPoint(x,y);
            for(let i=0;hit && hit.shadowRoot && i<24;i++) {
                const next=hit.shadowRoot.elementFromPoint(x,y);
                if(!next || next===hit) break; hit=next;
            }
            if(hit===dialog || dialog.contains(hit) || dialog.contains(card))
                return {blocking:true,reason:'covers_job_card'};
            if(hit!==card && !card.contains(hit))
                continue; // Offscreen or clipped virtual-list cards prove nothing.
            checked++;
        }
        return {blocking:checked===0,reason:checked ? 'nonmodal_outside_jobs' : 'no_job_target'};
    '''
    try:
        state=execute(script,dialog,target)
    except (TypeError,AttributeError):
        # Containment-only DOM adapters cannot verify geometry.
        return True
    # Adapters without geometry cannot prove that an unknown dialog is harmless.
    return not (isinstance(state,dict) and state.get('blocking') is False)


def _snapshot(driver, diagnostic, diagnostics_dir):
    if diagnostics_dir is None:
        return
    from pathlib import Path
    import json
    import uuid
    from datetime import datetime, timezone
    try:
        directory=Path(diagnostics_dir);directory.mkdir(parents=True,exist_ok=True)
        base=directory/(str(diagnostic['job_id'])+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
        diagnostic['report_path']=str(base.with_suffix('.json'))
        try:
            diagnostic['dialogs']=dialog_structure(driver)
        except Exception as error:
            diagnostic['structure_error']=type(error).__name__
        try:
            if driver.save_screenshot(str(base.with_suffix('.png'))):
                diagnostic['screenshot_path']=str(base.with_suffix('.png'))
        except Exception as error:
            diagnostic['screenshot_error']=type(error).__name__
        # Structural metadata only: never serialize form values or answers.
        base.with_suffix('.json').write_text(json.dumps(diagnostic,indent=2)+'\n',encoding='utf-8')
    except Exception as error:
        diagnostic['capture_error']=type(error).__name__


def clear_post_submit_ui(driver, job_id, *, timeout=5, quiet_seconds=.5, log=lambda _:None, diagnostics_dir=None, target=None):
    """Dismiss submission receipts or recognized profile promotions, then await clear UI.

    Never Save, Discard, Continue or Submit; unknown dialogs remain untouched.
    The caller records successful submission before invoking this operation.
    """
    diagnostic=dict(stage='post_submit_cleanup',job_id=str(job_id),dismissals=0)
    clicked=set();quiet_since=None

    class ReceiptDismissed(Exception):
        pass

    def clear(browser):
        nonlocal quiet_since
        contexts,hosts=_contexts(browser)
        visible_dialogs={node.id:node for context in contexts for node in _visible(context.find_elements('css selector',DIALOGS))}
        dialogs={identity:node for identity,node in visible_dialogs.items()
                 if _dialog_blocks_jobs(browser,node,target)}
        blockers=[host for host in hosts if _blocking(browser,host)]
        diagnostic['visible_dialogs']=len(visible_dialogs)
        diagnostic['blocking_dialogs']=len(dialogs)
        diagnostic['nonblocking_dialogs']=len(visible_dialogs)-len(dialogs)
        diagnostic['blocking_hosts']=[{'id':host.get_attribute('id'),'testid':host.get_attribute('data-testid')} for host in blockers]
        candidates={}
        for dialog in dialogs.values():
            text=' '.join(dialog.text.split())
            controls=_visible(dialog.find_elements('css selector',BUTTONS))
            labels={' '.join((value or '').lower().split()) for control in controls
                    for value in (control.text,control.get_attribute('aria-label'))}
            profile_promotion=bool(re.search(r'turn your resume into a profile|update profile',text,re.I))
            standalone_promotion=(bool(re.search(r'turn your resume into a profile',text,re.I))
                                  and {'not now','update profile'}.issubset(labels))
            receipt=bool(re.search(r'\b(?:your\s+)?application\s+(?:(?:has been|was)\s+)?(?:sent|submitted)\b',text,re.I))
            if not receipt and not standalone_promotion:
                continue
            fields=_visible(dialog.find_elements('css selector','input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), textarea, select'))
            navigation=any(' '.join((label or '').lower().split()) in
                {'next','review','review your application','submit','submit application','submit your application'}
                for button in _visible(dialog.find_elements('css selector',BUTTONS))
                for label in (button.text,button.get_attribute('aria-label')))
            if any(field.is_enabled() for field in fields) or navigation:
                continue
            allowed=CLOSE|({'not now'} if profile_promotion else set())
            for button in _visible(dialog.find_elements('css selector',BUTTONS)):
                labels={' '.join(value.lower().split()) for value in (button.text,button.get_attribute('aria-label')) if value}
                if (labels & allowed and labels.issubset(allowed|{'x','×','✕'}) and button.is_enabled()
                        and button.get_attribute('aria-disabled')!='true'):
                    candidates[button.id]=button
        # Decline the optional profile update. Classic receipts instead use Done.
        primary={identity:button for identity,button in candidates.items() if any(
            ' '.join((label or '').lower().split())=='not now'
            for label in (button.text,button.get_attribute('aria-label')))}
        if not primary:
            primary={identity:button for identity,button in candidates.items() if any(
                ' '.join((label or '').lower().split())=='done'
                for label in (button.text,button.get_attribute('aria-label')))}
        if primary:
            candidates=primary
        if len(candidates)==1:
            identity,button=next(iter(candidates.items()))
            if identity not in clicked and len(clicked)<3:
                is_not_now=any(' '.join((label or '').lower().split())=='not now'
                               for label in (button.text,button.get_attribute('aria-label')))
                button.click();clicked.add(identity);diagnostic['dismissals']+=1
                if is_not_now:
                    log(f'Application [{job_id}]: optional profile update dismissed with Not now; waiting for clear job list')
                else:
                    log(f'Application confirmed [{job_id}]: receipt dismissed; waiting for clear job list')
                quiet_since=None
                raise ReceiptDismissed()
            quiet_since=None
            return False
        if dialogs or blockers:
            quiet_since=None
            return False
        if quiet_since is None:
            quiet_since=monotonic()
        return monotonic()-quiet_since>=quiet_seconds

    # Each completed native dismissal starts a fresh bounded clearance phase.
    # Slow browser calls must not consume the interval reserved for disappearance.
    # At most three distinct dismissals are allowed, so total phases stay bounded.
    for _ in range(4):
        try:
            WebDriverWait(driver,timeout,poll_frequency=.05,ignored_exceptions=(StaleElementReferenceException,)).until(clear)
            return diagnostic
        except ReceiptDismissed:
            continue
        except TimeoutException as error:
            diagnostic['cause_type']=type(error).__name__
            _snapshot(driver,diagnostic,diagnostics_dir)
            raise PostSubmitUIBlocked(job_id,diagnostic) from error
    raise PostSubmitUIBlocked(job_id,diagnostic)


def select_job_card(driver, job_id, acquire, *, timeout=8, max_attempts=3, log=lambda _:None, diagnostics_dir=None):
    """Acquire (verified_job_id, control) fresh on every bounded click attempt."""
    diagnostic=dict(stage='select_job_card',job_id=str(job_id),attempts=0)
    deadline=monotonic()+timeout
    control=None
    for attempt in range(1,max_attempts+1):
        diagnostic['attempts']=attempt
        try:
            remaining=deadline-monotonic()
            if remaining<=0:
                break
            observed,control=acquire()
            if str(observed)!=str(job_id) or control is None:
                diagnostic['cause_type']='SelectedJobMismatch'
                break
            execute = getattr(driver, 'execute_script', None)
            if execute is not None:
                execute('arguments[0].scrollIntoView({block:"center"});',control)
            clear_post_submit_ui(driver,job_id,timeout=remaining,quiet_seconds=0,
                log=log,diagnostics_dir=diagnostics_dir,target=control)
            def hittable(_):
                return execute('''/* jobrobo-card-hit-test */
                    const e=arguments[0],r=e.getBoundingClientRect(),
                    x=Math.max(0,Math.min(innerWidth-1,r.left+r.width/2)),
                    y=Math.max(0,Math.min(innerHeight-1,r.top+r.height/2));
                    let n=document.elementFromPoint(x,y);
                    for(let i=0;n && n.shadowRoot && i<24;i++) {
                        const inner=n.shadowRoot.elementFromPoint(x,y);
                        if(!inner || inner===n) break; n=inner;
                    }
                    return n===e || (n && e.contains(n));''',control)
            if execute is not None and hittable(driver) is False:
                diagnostic['cause_type']='CardClickPointObscured'
                log(f'Job card [{job_id}]: click point blocked; checking for a delayed confirmation')
                clear_post_submit_ui(driver,job_id,timeout=max(.01,deadline-monotonic()),
                    quiet_seconds=.2,log=log,diagnostics_dir=diagnostics_dir,target=control)
                # The receipt or React may have replaced the target; reacquire.
                continue
            control.click()
            return
        except (StaleElementReferenceException,ElementClickInterceptedException) as error:
            diagnostic['cause_type']=type(error).__name__
            log(f'Job card [{job_id}]: {type(error).__name__}; reacquiring same job ({attempt}/{max_attempts})')
        except PostSubmitUIBlocked as error:
            diagnostic['overlay']=error.diagnostics
            diagnostic['cause_type']='OverlayRemainsVisible'
            break
    if control is not None and callable(getattr(driver,'execute_script',None)):
        try:
            point=driver.execute_script('''/* jobrobo-card-obstruction */
                const e=arguments[0],r=e.getBoundingClientRect(),
                    x=Math.max(0,Math.min(innerWidth-1,r.left+r.width/2)),
                    y=Math.max(0,Math.min(innerHeight-1,r.top+r.height/2));
                const describe=n=>n ? {tag:n.tagName,role:n.getAttribute('role'),
                    testid:n.getAttribute('data-testid'),id:n.id} : null;
                const path=[]; let n=document.elementFromPoint(x,y);
                for(let i=0;n && i<24;i++) {
                    path.push(describe(n)); if(!n.shadowRoot) break;
                    const inner=n.shadowRoot.elementFromPoint(x,y);
                    if(!inner || inner===n) break; n=inner;
                }
                return {x,y,target:describe(e),hit_path:path};
            ''',control)
            if isinstance(point,dict):diagnostic['click_point']=point
        except Exception as error:
            diagnostic['click_point_error']=type(error).__name__
    _snapshot(driver,diagnostic,diagnostics_dir)
    raise JobCardBlocked(job_id,diagnostic)
