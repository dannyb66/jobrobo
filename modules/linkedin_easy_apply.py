"""Scoped Easy Apply navigation for classic and semantic LinkedIn dialogs.

Navigation stops at the final Submit screen. Only the caller may authorize Submit.
Logs contain step/action names, never field values or application answers.
"""
from __future__ import annotations

import re
from selenium.common.exceptions import (
    ElementClickInterceptedException, NoSuchShadowRootException,
    StaleElementReferenceException, TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


class EasyApplyError(RuntimeError):
    pass


class EasyApplyLimitReached(EasyApplyError):
    """LinkedIn blocked opening the form; leave this job pending for a later run."""
    stop_reason = 'daily_easy_apply_limit'

    def __init__(self):
        super().__init__("LinkedIn's daily Easy Apply limit reached; no further applications will be attempted")


class MissingApplicationAnswer(EasyApplyError):
    """A required personal answer is absent; never invent free-text answers."""


DIALOGS = 'dialog[open], .jobs-easy-apply-modal, .artdeco-modal, [role="dialog"], [aria-modal="true"], [data-testid="dialog"]'
BUTTONS = 'button, [role="button"]'
CONTINUATION_CONTROLS = BUTTONS + ', a'
ERRORS = '.artdeco-inline-feedback--error, [aria-invalid="true"], [role="alert"]'
OVERLAY_HOSTS = '#interop-outlet, [data-testid="interop-shadowdom"]'


def dialog_contexts(driver):
    """Document plus bounded open shadow roots, including unmarked SDUI hosts.

    No page mutation or private form values are read. Closed roots remain
    inaccessible and therefore require a diagnostic rather than a blind click.
    """
    contexts, hosts, seen = [driver], [], set()
    execute = getattr(driver, 'execute_script', None)
    discovery_script = '''/* jobrobo-dialog-contexts */
        const roots=[document], hosts=[]; let visited=0;
        for(let i=0;i<roots.length && i<24;i++) {
            for(const e of roots[i].querySelectorAll('*')) {
                if(++visited>12000) return hosts;
                if(e.shadowRoot && hosts.length<23) {
                    hosts.push(e); roots.push(e.shadowRoot);
                }
            }
        }
        return hosts;
    '''
    try:
        discovered=execute(discovery_script) if callable(execute) else []
    except TypeError:
        # Some read-only DOM adapters expose only execute_script(script,
        # parent, child) for containment checks, with no discovery support.
        discovered=[]
    # Lightweight DOM adapters need not implement JavaScript discovery.
    pending = list(discovered) if isinstance(discovered, (list, tuple)) else []
    for context in contexts:
        pending.extend(_visible(context.find_elements(By.CSS_SELECTOR, OVERLAY_HOSTS)))
        while pending and len(contexts)<24:
            host=pending.pop(0)
            if host.id in seen:
                continue
            seen.add(host.id)
            if not hasattr(host, 'is_displayed') or host.is_displayed():
                hosts.append(host)
            try:
                contexts.append(host.shadow_root)
            except (AttributeError, NoSuchShadowRootException):
                pass
    return contexts, hosts


def dialog_elements(driver, selector=DIALOGS):
    contexts, _ = dialog_contexts(driver)
    return list({node.id:node for context in contexts
                 for node in _visible(context.find_elements(By.CSS_SELECTOR, selector))}.values())


def dialog_structure(driver):
    """Structural diagnostics only; never serialize field values or answers."""
    nodes=dialog_elements(driver)
    return [{'tag':getattr(node, 'tag_name', None), 'role':node.get_attribute('role'),
             'testid':node.get_attribute('data-testid'),
             'navigation':sorted({_kind(button) for button in _visible(
                 node.find_elements(By.CSS_SELECTOR, BUTTONS)) if _kind(button)}),
             'field_count':len(node.find_elements(By.CSS_SELECTOR, 'input, textarea, select'))}
            for node in nodes]


def _visible(nodes):
    return [node for node in nodes if node.is_displayed()]


def _kind(button):
    kinds = set()
    # Overflow-clipped footer text can be empty in WebElement.text. The scoped
    # navigation probe already rejects CSS-hidden controls before using this.
    for label in (button.get_attribute('aria-label'), button.text or button.get_attribute('textContent')):
        label = ' '.join((label or '').lower().split())
        if label in {'next', 'continue', 'continue to next step'}:
            kinds.add('next')
        if label in {'review', 'review your application', 'review application'}:
            kinds.add('review')
        if label in {'submit', 'submit application', 'submit your application'}:
            kinds.add('submit')
    if len(kinds) > 1:
        raise EasyApplyError('navigation: button has conflicting action labels')
    return next(iter(kinds), None)


def _enabled(button):
    return (button.is_enabled() and button.get_attribute('aria-disabled') != 'true'
            and button.get_attribute('disabled') is None)


def _navigation_buttons(driver, root):
    """Read only exact navigation actions in one pass, even below a long list.

    Resume history can contain hundreds of buttons. Reading every button over
    WebDriver exhausts the readiness timeout before a second stable poll.
    Overflow clipping is recoverable by scrolling; CSS-hidden controls are not.
    """
    execute = getattr(driver, 'execute_script', None)
    if callable(execute):
        try:
            result = execute('''/* jobrobo-navigation-buttons */
              const root=arguments[0], labels=new Set(['next','continue','continue to next step',
                'review','review your application','review application',
                'submit','submit application','submit your application']);
              const normalize=s=>(s||'').replace(/\\s+/g,' ').trim().toLowerCase();
              return [...root.querySelectorAll('button,[role="button"]')].filter(e=>{
                if (![e.textContent,e.getAttribute('aria-label')].some(s=>labels.has(normalize(s)))) return false;
                if (!e.getClientRects().length) return false;
                for(let p=e;p;p=p.parentElement) {
                  const s=getComputedStyle(p);
                  if(p.hidden || s.display==='none' || s.visibility==='hidden' || s.visibility==='collapse') return false;
                  if(p===root) break;
                }
                return true;
              });
            ''', root)
        except TypeError:
            result = None  # Read-only adapters can expose containment scripts only.
        if isinstance(result, (list, tuple)):
            return list(result)
    return [b for b in _visible(root.find_elements(By.CSS_SELECTOR, BUTTONS)) if _kind(b)]


def _modal(driver):
    candidates = []
    for node in dialog_elements(driver):
        classic = 'jobs-easy-apply-modal' in (node.get_attribute('class') or '').split()
        heading = (node.get_attribute('aria-label') or '') + ' ' + ' '.join(
            n.text for n in node.find_elements(By.CSS_SELECTOR, 'h1, h2, h3, [role="heading"]'))
        if re.search(r'\bdiscard\b|\bleave application\b|\bsave.*application\b', heading, re.I):
            continue
        actions = bool(_navigation_buttons(driver, node))
        # Discard/leave dialogs must never be mistaken for application forms.
        application = bool(re.search(r'\bapply\b|\bapplication\b',
                                    (node.get_attribute('aria-label') or '') + ' ' + node.text, re.I))
        fields = node.find_elements(By.CSS_SELECTOR, 'form, input, textarea, select')
        if classic:
            return node
        if actions and (application or fields):
            candidates.append(node)
    if len(candidates) > 1:
        # Prefer the innermost dialog when semantic wrappers are nested.
        candidates = [node for node in candidates if not any(
            child.id != node.id and driver.execute_script('return arguments[0].contains(arguments[1]);', node, child)
            for child in candidates)]
        if len(candidates) > 1:
            raise EasyApplyError('open: multiple visible application dialogs')
    return candidates[0] if candidates else False


def _wait(driver, condition, timeout):
    return WebDriverWait(driver, timeout, poll_frequency=min(.1, max(.001, timeout/4)),
                         ignored_exceptions=(StaleElementReferenceException,)).until(condition)


def _fit_warning(driver):
    """Identify LinkedIn's fit/safety interstitials (legacy helper name)."""
    execute = getattr(driver, 'execute_script', None)
    if callable(execute):
        try:
            result = execute(r'''
              const dialogs = Array.from(document.querySelectorAll(
                'dialog[open], .jobs-easy-apply-modal, .artdeco-modal, [role="dialog"], [aria-modal="true"], [data-testid="dialog"]'
              ));
              const visible = e => { const r=e.getBoundingClientRect(), s=getComputedStyle(e);
                return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden'; };
              const normalize = s => (s||'').toLowerCase().replace(/\s+/g,' ').trim();
              for (const node of dialogs) {
                if (!visible(node)) continue;
                const text = node.textContent || '';
                const fit = /job may not be the best fit|position yourself to stand out/i.test(text);
                const safety = /job search safety reminder/i.test(text);
                if (!fit && !safety) continue;
                const buttons = Array.from(node.querySelectorAll('button,[role="button"],a'))
                  .filter(b => visible(b) && (normalize(b.innerText || b.textContent)==='continue applying' ||
                    normalize(b.getAttribute('aria-label'))==='continue applying'));
                if (safety && (node.querySelector('form,input,textarea,select') || buttons.length===0)) continue;
                return [node, buttons];
              }
              return false;
            ''')
            if result is False:
                return False
            if isinstance(result, (list, tuple)) and len(result) == 2:
                dialog, buttons = result
                return dialog, list(buttons or [])
        except Exception:
            # Preserve adapters that cannot return WebElements from a script.
            pass
    dialogs=[]
    for node in dialog_elements(driver):
        heading=(node.get_attribute('aria-label') or '')+' '+' '.join(
            h.text for h in node.find_elements(By.CSS_SELECTOR,'h1, h2, h3, [role="heading"]'))
        heading=' '.join(heading.split())
        # Some warning variants render their title as a paragraph, not a heading.
        # Require the specific warning text and exact continuation action there.
        plain_warning=re.search(r'job may not be the best fit',' '.join(node.text.split()),re.I)
        continuation=any(any(' '.join((label or '').lower().split())=='continue applying'
            for label in (button.text,button.get_attribute('aria-label')))
            for button in _visible(node.find_elements(By.CSS_SELECTOR,CONTINUATION_CONTROLS)))
        safety_reminder=re.search(r'\bjob search safety reminder\b',heading+' '+node.text,re.I)
        # The safety reminder is informational, not a form or Review/Submit page.
        safety_reminder=(safety_reminder and continuation
            and not node.find_elements(By.CSS_SELECTOR,'form, input, textarea, select'))
        if re.search(r'job may not be the best fit|position yourself to stand out',heading,re.I) or (plain_warning and continuation) or safety_reminder:
            dialogs.append(node)
    dialogs=[node for node in dialogs if not any(child.id!=node.id and
        driver.execute_script('return arguments[0].contains(arguments[1]);',node,child) for child in dialogs)]
    if len(dialogs)>1:
        raise EasyApplyError('open: multiple visible fit-warning dialogs')
    if not dialogs:return False
    buttons=[b for b in _visible(dialogs[0].find_elements(By.CSS_SELECTOR,CONTINUATION_CONTROLS))
        if any(' '.join((label or '').lower().split())=='continue applying'
            for label in (b.text,b.get_attribute('aria-label')))]
    return dialogs[0],buttons


def check_easy_apply_limit(driver):
    # SDUI's internal screen marker can disappear. The visible, specific message
    # in a dialog (or classic inline feedback) remains authoritative. Read
    # bounded text in one browser-side pass: WebElement.text for every large
    # LinkedIn dialog can serialize the full job description on every wait
    # poll and stall the upload/form transition for minutes.
    execute = getattr(driver, 'execute_script', None)
    if callable(execute):
        try:
            hit = execute('''
              const pattern = /you (?:have )?reached today's easy apply limit|exceeded the daily application limit/i;
              const selector = "dialog[open], .jobs-easy-apply-modal, .artdeco-modal, [role=dialog], [aria-modal=true], [data-testid=dialog], .artdeco-inline-feedback__message, .artdeco-inline-feedback--error, [role=alert]";
              return Array.from(document.querySelectorAll(selector)).some(node => {
                const style = getComputedStyle(node), rect = node.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' &&
                  style.display !== 'none' && pattern.test((node.textContent || '').slice(0, 50000).replace(/’/g, "'"));
              });
            ''')
            if hit is True:
                raise EasyApplyLimitReached()
            if hit is False:
                return
        except EasyApplyLimitReached:
            raise
        except Exception:
            # Keep a conservative Selenium fallback for adapters that do not
            # support the one-pass DOM query.
            pass
    for node in dialog_elements(driver, DIALOGS + ', .artdeco-inline-feedback__message'):
        text = ' '.join(node.text.lower().replace('’', "'").split())
        if re.search(r"\byou (?:have )?reached today's easy apply limit\b|"
                     r"\bexceeded the daily application limit\b", text):
            raise EasyApplyLimitReached()


def open_easy_apply(driver, expected_job_id, *, timeout=10, log=lambda _: None, diagnostics_dir=None, inspect_only=False):
    """Click one job-bound button/link and await the form; never click Submit.

    False means a confirmed external Apply control. Missing, disabled or failed
    entry controls are errors, not evidence that a job requires external apply.
    inspect_only classifies the selected CTA without opening an Easy Apply form.
    Reacquire controls only before a successful click; never click entry twice
    while waiting for a form or the existing Continue applying interstitial.
    """
    from modules.linkedin_job_details import modern_details_root, modern_easy_apply_button, _url_job_id
    expected_job_id = str(expected_job_id)
    if not expected_job_id.isdigit():
        raise EasyApplyError('entry: expected a numeric LinkedIn job ID')
    attempts, last_issue = 0, 'no enabled Easy Apply or external Apply control'

    def click_entry(browser):
        nonlocal attempts, last_issue
        check_easy_apply_limit(browser)
        if _url_job_id(browser.current_url) != expected_job_id:
            last_issue = 'URL does not match selected job'
            return False
        try:
            root = modern_details_root(browser, expected_job_id)
            if root is not None:
                button = modern_easy_apply_button(browser, expected_job_id)
                roots = [root]
            else:
                roots = _visible(browser.find_elements(By.CSS_SELECTOR,
                    '.jobs-details__main-content, .jobs-unified-top-card, .job-details-jobs-unified-top-card'))
                controls = {node.id: node for root in roots for node in root.find_elements(
                    By.CSS_SELECTOR, '.jobs-apply-button[aria-label*="Easy"]') if node.is_displayed() and _enabled(node)}
                if len(controls) > 1:
                    raise EasyApplyError('entry: multiple classic Easy Apply controls')
                button = next(iter(controls.values()), None)
            if button is None:
                # Do not classify a loading/disabled Easy Apply link as external.
                for root in roots:
                    for node in _visible(root.find_elements(By.CSS_SELECTOR, 'a[href], button')):
                        labels = [node.text, node.get_attribute('aria-label')]
                        if _enabled(node) and any(' '.join((label or '').lower().split()) in
                                {'apply', 'apply to this job', 'apply on company website'} for label in labels):
                            return 'external'
                return False
            if inspect_only:
                return 'easy'
            href = button.get_attribute('href')
            if href and _url_job_id(href) != expected_job_id:
                raise EasyApplyError('entry: Easy Apply link does not match selected job')
            if attempts >= 3:
                raise EasyApplyError(f'entry: click failed after 3 attempts ({last_issue})')
            attempts += 1
            browser.execute_script('arguments[0].scrollIntoView({block: "center"});', button)
            button.click()
            return 'clicked'
        except (StaleElementReferenceException, ElementClickInterceptedException) as error:
            last_issue = type(error).__name__
            log(f'Easy Apply entry: {last_issue}; reacquiring selected-job control')
            return False
        except ValueError as error:
            last_issue = str(error)
            return False

    try:
        try:
            result = _wait(driver, click_entry, timeout)
        except TimeoutException as error:
            raise EasyApplyError(f'entry: {last_issue} (waited {timeout}s)') from error
        if result == 'external':
            log('Easy Apply entry: confirmed external Apply control')
            return False
        if result == 'easy':
            return True
        log('Easy Apply entry clicked; waiting for application form')
        wait_for_application_modal(driver, timeout=timeout, log=log)
        return True
    except EasyApplyLimitReached:
        raise
    except EasyApplyError as error:
        from modules.linkedin_post_submit import _snapshot
        diagnostic=dict(stage='easy_apply_entry', job_id=expected_job_id,
                        attempts=attempts, cause_type=type(error).__name__)
        try:
            diagnostic['dialogs']=dialog_structure(driver)
        except Exception as capture_error:
            diagnostic['structure_error']=type(capture_error).__name__
        _snapshot(driver, diagnostic, diagnostics_dir)
        error.diagnostics=diagnostic
        raise


def wait_for_application_modal(driver, *, timeout=10, continue_fit_warning=True, log=lambda _: None):
    continued=set()
    def opened(browser):
        while True:
            check_easy_apply_limit(browser)
            warning=_fit_warning(browser)
            if not warning:
                return _modal(browser)
            if not continue_fit_warning:return False
            dialog,buttons=warning
            kind='safety reminder' if re.search(r'\bjob search safety reminder\b',dialog.text,re.I) else 'fit warning'
            identity=(dialog.id,kind)
            if identity in continued:return False
            if len(continued)>=3:
                raise EasyApplyError('open: too many pre-application continuation dialogs')
            if len(buttons)!=1:
                raise EasyApplyError('open: fit warning lacks one Continue applying button')
            button=buttons[0]
            if _kind(button) is not None or not _enabled(button):
                raise EasyApplyError('open: fit-warning Continue applying is disabled or ambiguous')
            browser.execute_script('arguments[0].scrollIntoView({block: "center"});',button)
            # Remember before clicking: a rerender can stale the successful
            # click's response. Never send a second click to the same warning.
            continued.add(identity)
            button.click()
            log(f'Easy Apply: Continue applying clicked ({kind}); waiting for the application form')
    try:
        return _wait(driver, opened, timeout)
    except TimeoutException as error:
        if continued:
            raise EasyApplyError('open: Continue applying did not open the application form') from error
        raise EasyApplyError('open: visible Easy Apply dialog not found (classic or semantic UI)') from error


def _state(driver):
    check_easy_apply_limit(driver)
    modal = _modal(driver)
    if not modal:
        return False
    buttons = [(b, _kind(b)) for b in _navigation_buttons(driver, modal)]
    # Next takes precedence: never jump to Review while there are more form pages.
    for kind in ('next', 'review', 'submit'):
        found = [b for b, action in buttons if action == kind]
        if len(found) > 1:
            raise EasyApplyError(f'{kind}: ambiguous visible navigation controls')
        if found:
            if not found[0].is_displayed():
                # Reacquired, scoped action only: never click to recover visibility.
                driver.execute_script('arguments[0].scrollIntoView({block: "center"});', found[0])
                if not found[0].is_displayed():
                    return False
            return modal, kind, found[0]
    return False


def _signature(modal, kind):
    # Compare structural identity and visible text, not DOM instance identity:
    # React may replace a dialog without advancing to the next page.
    execute = getattr(getattr(modal, 'parent', None), 'execute_script', None)
    if callable(execute):
        try:
            result = execute(r'''
              const root = arguments[0];
              const text = e => (e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 300);
              const pdf = e => e.matches('input[type="radio"]') && /\.(pdf|docx?)$/i.test(e.getAttribute('aria-label')||'');
              const ignored = e => {
                if(e.closest('[role="status"],[role="alert"]') || pdf(e)) return true;
                // Exclude one resume option's filename/date, never the form or
                // its page counter, headings, questions or navigation footer.
                for(let p=e.parentElement;p && p!==root;p=p.parentElement) {
                  const inputs=[...p.querySelectorAll('input,textarea,select')];
                  if(inputs.length===1 && pdf(inputs[0]) && !p.querySelector('h1,h2,h3,footer,button')) return true;
                }
                return false;
              };
              const stable = s => /_r_[\w-]+_|^[\da-f]{8}-[\da-f-]{27,}$/i.test(s||'') ? null : s;
              const fields = Array.from(root.querySelectorAll('input,textarea,select')).filter(e=>!ignored(e)).slice(0, 100)
                .map(e => [stable(e.getAttribute('id')), stable(e.getAttribute('name')), e.getAttribute('type')]);
              const sections = Array.from(root.querySelectorAll('h1,h2,h3,legend,label,[role="heading"],[role="progressbar"]'))
                .filter(e=>!ignored(e)).slice(0, 100).map(e=>text(e)+(e.getAttribute('aria-valuenow')||''));
              const content = Array.from(root.querySelectorAll('[data-testid="dialog-content"] p'))
                .filter(e => !ignored(e)).slice(0, 100).map(text);
              const progress=[...root.querySelectorAll('p,[role="progressbar"]')]
                .filter(e=>!ignored(e)).map(text).find(t=>/^\d+\s*\/\s*\d+\s+pages$/i.test(t));
              if(progress && !content.includes(progress)) content.push(progress);
              return [sections, fields, content];
            ''', modal)
            if isinstance(result, (list, tuple)) and len(result) == 3:
                sections, fields, content = result
                return kind, tuple(sections), tuple(tuple(field) for field in fields), tuple(content)
        except Exception:
            # Retain compatibility with lightweight DOM adapters and older
            # drivers that cannot serialize the bounded structural snapshot.
            pass
    def ignored(node):
        if node.find_elements(By.XPATH, './ancestor::*[@role="status" or @role="alert"]'):
            return True
        if node.get_attribute('type') == 'radio' and re.search(r'\.(?:pdf|docx?)$', node.get_attribute('aria-label') or '', re.I):
            return True
        return bool(node.find_elements(By.XPATH, './ancestor::*[count(.//input | .//textarea | .//select)=1 '
            'and .//input[@type="radio" and (contains(@aria-label,".pdf") or contains(@aria-label,".doc"))] '
            'and not(.//h1 | .//h2 | .//h3 | .//footer | .//button)]'))
    def stable(value):
        return None if re.search(r'_r_[\w-]+_|^[\da-f]{8}-[\da-f-]{27,}$', value or '', re.I) else value
    fields = tuple((stable(n.get_attribute('id')), stable(n.get_attribute('name')), n.get_attribute('type'))
                   for n in modal.find_elements(By.CSS_SELECTOR, 'input, textarea, select') if not ignored(n))
    sections = tuple(n.text + (n.get_attribute('aria-valuenow') or '') for n in modal.find_elements(
        By.CSS_SELECTOR, 'h1, h2, h3, legend, label, [role="heading"], [role="progressbar"]') if not ignored(n))
    # SDUI education/work-history steps can contain only paragraph cards:
    # identical Next controls and no editable fields or semantic headings.
    content = [n.text for n in modal.find_elements(
        By.XPATH, ".//*[@data-testid='dialog-content']//p") if not ignored(n)]
    progress = next((n.text for n in modal.find_elements(By.CSS_SELECTOR, 'p, [role="progressbar"]')
                     if re.fullmatch(r'\d+\s*/\s*\d+\s+pages', n.text.strip(), re.I) and not ignored(n)), None)
    if progress and progress not in content:
        content.append(progress)
    return kind, sections, fields, tuple(content)


def _application_owner(modal):
    """Read the employer heading, never input values or form answers."""
    labels = [modal.get_attribute('aria-label') or '']
    labels.extend(node.text for node in modal.find_elements(By.CSS_SELECTOR, 'h1,h2,h3,[role="heading"]'))
    for label in labels:
        if re.match(r'^\s*apply to\b', label, re.I):
            return ' '.join(label.split()).casefold()
    return None


def _bound_state(driver, job_id, owner):
    from modules.linkedin_job_details import _url_job_id
    if job_id and _url_job_id(getattr(driver, 'current_url', '')) != job_id:
        raise EasyApplyError('navigation: selected job changed while filling; no action taken')
    state = _state(driver)
    if state and owner and _application_owner(state[0]) != owner:
        raise EasyApplyError('navigation: application employer changed while filling; no action taken')
    return state


def _settled_state(driver, timeout, job_id, owner):
    previous = None
    def stable(browser):
        nonlocal previous
        try:
            state = _bound_state(browser, job_id, owner)
            signature = _signature(state[0], state[1]) if state else None
        except StaleElementReferenceException:
            previous = None
            return False
        same = signature is not None and signature == previous
        previous = signature
        return state if same else False
    return _wait(driver, stable, timeout)


def _navigation_snapshot(modal, action):
    """Bounded before/after evidence with labels, not entered values."""
    try:
        return _read_navigation_snapshot(modal, action)
    except Exception as error:
        return {'action': action, 'page': None, 'questions': [], 'capture_error': type(error).__name__}


def _read_navigation_snapshot(modal, action):
    execute = getattr(getattr(modal, 'parent', None), 'execute_script', None)
    if callable(execute):
        result = execute(r'''/* jobrobo-navigation-evidence */
          const root=arguments[0], action=arguments[1];
          const prompts=[...root.querySelectorAll('legend,label[for],input[aria-label],textarea[aria-label],select[aria-label]')]
            .slice(0,20).map(e=>(e.getAttribute('aria-label')||e.textContent||'').replace(/\s+/g,' ').trim().slice(0,240)).filter(Boolean);
          const progress=(root.textContent||'').match(/\b\d+\s*\/\s*\d+\s+pages\b/i);
          const navigation=[...root.querySelectorAll('footer button,footer [role="button"],.jobs-easy-apply-footer button')]
            .slice(0,8).map(e=>{ const r=e.getBoundingClientRect();
              return {label:(e.getAttribute('aria-label')||e.textContent||'').trim().slice(0,80),
                disabled:e.disabled||e.getAttribute('aria-disabled')==='true',
                rect:{x:Math.round(r.x),y:Math.round(r.y),width:Math.round(r.width),height:Math.round(r.height)}}; });
          return {action, page:progress ? progress[0] : null, questions:prompts, navigation};
        ''', modal, action)
        if isinstance(result, dict) and isinstance(result.get('questions'), list):
            return result
    labels = modal.find_elements(By.CSS_SELECTOR,
        'legend,label[for],input[aria-label],textarea[aria-label],select[aria-label]')
    prompts = [node.get_attribute('aria-label') or node.text for node in labels[:20]]
    progress = re.search(r'\b\d+\s*/\s*\d+\s+pages\b', modal.text, re.I)
    return {'action': action, 'page': progress.group() if progress else None,
            'questions': [' '.join(text.split())[:240] for text in prompts if text.strip()]}


def advance_to_review(driver, fill_step, *, timeout=10, max_steps=15, on_blocked=None, log=lambda _: None):
    """Fill every form page, await each transition, and return at final Submit.

    fill_step receives a freshly acquired modal, including for one-page forms.
    on_blocked may invite manual field correction; it must not click navigation.
    """
    from modules.linkedin_job_details import _url_job_id
    initial = wait_for_application_modal(driver, timeout=timeout, log=log)
    job_id = _url_job_id(getattr(driver, 'current_url', ''))
    owner = _application_owner(initial)
    recoveries, transitions = 0, []
    for step in range(1, max_steps + 1):
        try:
            state = _settled_state(driver, timeout, job_id, owner)
        except TimeoutException as error:
            raise EasyApplyError(f'step {step}: no Next, Review or Submit control in application dialog') from error
        modal, kind, button = state
        before_fill = _navigation_snapshot(modal, kind)
        log(f'Easy Apply step {step}: {kind}')
        # Exceptions from answering/uploading must propagate without any final action.
        try:
            fill_step(modal)
        except MissingApplicationAnswer as error:
            if on_blocked and on_blocked(str(error)):
                continue
            raise
        # Answering or uploading may rerender the dialog; always reacquire controls.
        try:
            modal, current_kind, button = _settled_state(driver, timeout, job_id, owner)
        except TimeoutException as error:
            failure = EasyApplyError(f'step {step}: form controls disappeared after filling')
            failure.navigation_evidence = [{'before': before_fill, 'after': _navigation_snapshot(modal, kind)}]
            raise failure from error
        if current_kind != kind:
            recoveries += 1
            after_fill = _navigation_snapshot(modal, current_kind)
            transitions.append({'before': before_fill, 'after': after_fill})
            if not (job_id or owner) or recoveries > 3:
                error = EasyApplyError(f'step {step}: form kept changing while filling; recovery limit reached')
                error.navigation_evidence = transitions
                raise error
            log(f'Easy Apply step {step}: form changed {kind} -> {current_kind}; '
                f'reacquiring and refilling the same application ({recoveries}/3); '
                f'page {before_fill["page"]} -> {after_fill["page"]}; '
                f'questions {after_fill["questions"]}')
            continue
        if kind == 'submit':
            if not _enabled(button):
                raise EasyApplyError('review: Submit application is disabled')
            return modal
        if not _enabled(button):
            reason = f'step {step}: {kind} is disabled; correct required fields'
            if on_blocked and on_blocked(reason):
                continue
            raise EasyApplyError(reason)
        before = _signature(modal, kind)
        driver.execute_script('arguments[0].scrollIntoView({block: "center"});', button)
        try:
            button.click()
        except Exception as error:
            raise EasyApplyError(f'step {step}: {kind} click failed ({type(error).__name__})') from error

        def changed(browser):
            nonlocal last_transition
            current = _bound_state(browser, job_id, owner)
            if not current:
                last_transition = None
                return False
            root, action, _ = current
            invalid = _visible(root.find_elements(By.CSS_SELECTOR, ERRORS))
            # Alerts can contain unrelated status text; aria-invalid/error class
            # remain authoritative, alert text must indicate a form error.
            invalid = [n for n in invalid if n.get_attribute('aria-invalid') == 'true'
                       or 'error' in (n.get_attribute('class') or '')
                       or re.search(r'required|invalid|please enter|please select|error', n.text, re.I)]
            if not invalid:
                # New profile/work-history forms render red validation copy as
                # plain text with no alert role or stable LinkedIn error class.
                try:
                    invalid = _visible(root.find_elements(By.XPATH,
                        ".//*[normalize-space(text())='This field is required' or normalize-space(text())='Invalid input']"))
                except Exception:
                    invalid = []
            if invalid:
                return 'validation'
            signature = _signature(root, action)
            advanced = signature != before and signature == last_transition
            last_transition = signature
            return 'advanced' if advanced else False

        try:
            last_transition = None
            transition = _wait(driver, changed, timeout)
            recoveries = 0
            reason = None
            if transition == 'validation':
                details = []
                try:
                    current = _state(driver)
                    if current:
                        from modules.linkedin_form_fields import validation_messages
                        details = validation_messages(current[0])
                except Exception:
                    details = []
                suffix = f" ({'; '.join(details[:3])})" if details else ''
                reason = f'step {step}: {kind} blocked by form validation{suffix}'
        except TimeoutException:
            reason = f'step {step}: {kind} did not advance the form'
        if reason:
            log(reason)
            if on_blocked and on_blocked(reason):
                continue
            failure = EasyApplyError(reason)
            failure.navigation_evidence = [{'before': before_fill, 'after': _navigation_snapshot(modal, kind)}]
            raise failure
    raise EasyApplyError(f'navigation: exceeded {max_steps} form steps without reaching review')


def current_submit_button(driver, *, timeout=10):
    """Recheck final state after the user's review; never advance on their behalf."""
    try:
        modal, kind, button = _wait(driver, _state, timeout)
    except TimeoutException as error:
        raise EasyApplyError('review: final application screen unavailable') from error
    if kind != 'submit' or not _enabled(button):
        raise EasyApplyError('review: application is not on an enabled final Submit screen')
    return modal, button


def job_submission_receipts(driver, job_id):
    """Read applied state only inside the pane bound to this exact posting.

    Modern LinkedIn renders a persistent Application status panel outside any
    dialog or live region. Stable tokens omit elapsed time so an old receipt
    cannot become new merely because its timestamp changed.
    """
    from modules.linkedin_job_details import modern_details_root
    try:
        root = modern_details_root(driver, job_id)
        if root is None:
            return set()
        labels = [' '.join(node.text.split()) for node in _visible(root.find_elements(
            By.CSS_SELECTOR, 'p, h2, h3, [role="heading"]'))]
        result = set()
        if any(label.lower() == 'application status' for label in labels):
            if any(re.fullmatch(r'(?:your\s+)?application\s+(?:(?:has been|was)\s+)?(?:sent|submitted)(?:\s+successfully)?',
                                label, re.I) for label in labels):
                result.add(f'job:{job_id}:application-submitted')
        if re.search(r'\bApplied\s+(?:just now|\d+\s+(?:second|minute)s?\s+ago)\b', root.text, re.I):
            result.add(f'job:{job_id}:applied-badge')
        return result
    except (ValueError, StaleElementReferenceException):
        return set()


def submission_receipts(driver, job_id=None):
    """Snapshot receipts before Submit, including the selected job's status."""
    result = set()
    for node in dialog_elements(driver, DIALOGS + ', [role="alert"], [role="status"]'):
        text = node.text.strip()
        if re.search(r'(?:^|\n)(?:your\s+)?application\s+(?:(?:has been|was)\s+)?(?:sent|submitted)\b', text, re.I):
            result.add(text)
    if job_id is not None:
        result.update(job_submission_receipts(driver, job_id))
    return result


def wait_for_submission_confirmation(driver, job_id, *, baseline, timeout=15):
    """Require a new explicit receipt; a successful click alone is not proof."""
    def confirmed(browser):
        return bool(submission_receipts(browser, job_id=job_id) - baseline)
    try:
        return bool(_wait(driver, confirmed, timeout))
    except TimeoutException as error:
        raise EasyApplyError('submit: no LinkedIn confirmation received; submission is uncertain, do not retry automatically') from error
