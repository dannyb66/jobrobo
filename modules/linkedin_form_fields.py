"""Field-local constraints and resume-backed checkbox answers for Easy Apply."""
import re

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


TEXT_CONTROLS = './/input[not(@type) or @type="text" or @type="number" or @type="email" or @type="tel" or @type="url" or @type="date"] | .//textarea | .//select | .//*[@role="combobox"]'


def radio_options(group):
    """Read option captions within this group, including empty native labels.

    The input's aria-label can repeat the question for every option, so it
    cannot identify Yes versus No. Use the associated label, an ARIA option,
    or the nearest bounded row that owns exactly one radio input.
    """
    options = group.find_elements(By.XPATH, ".//input[@type='radio']")
    descendants = {node.id for node in group.find_elements(By.XPATH, './/*')}
    result = []
    for option in options:
        identity = option.get_attribute('id')
        labels = [label for label in group.find_elements(By.XPATH, './/label[@for]')
                  if identity and label.get_attribute('for') == identity]
        roles = [node for node in option.find_elements(By.XPATH, './ancestor::*[@role="radio"][1]')
                 if node.id in descendants]
        label = next((node for node in labels if node.is_displayed()), None)
        role = roles[0] if roles else None
        text = next((node.text.strip() for node in labels if node.text.strip()), '')
        if not text and role is not None:
            text = role.text.strip() or role.get_attribute('aria-label') or ''
        if not text:
            text = ' '.join(node.text.strip() for reference in (option.get_attribute('aria-labelledby') or '').split()
                            for node in group.find_elements(By.XPATH, './/*[@id]')
                            if node.get_attribute('id') == reference and node.text.strip())
        if not text:
            rows = option.find_elements(By.XPATH, "./ancestor::*[not(self::fieldset) and not(@role='radiogroup') and count(.//input[@type='radio'])=1 and normalize-space(.)!=''][1]")
            row = next((node for node in rows if node.id in descendants and node.is_displayed()), None)
            if row is not None:
                text = row.text.strip()
        control = role if role is not None and role.is_displayed() else label if label is not None else option
        checked = role.get_attribute('aria-checked') if role is not None else None
        selected = checked == 'true' if checked in {'true', 'false'} else option.is_selected()
        result.append({'input': option, 'control': control, 'text': text,
                       'enabled': option.is_enabled() and (role is None or role.get_attribute('aria-disabled') != 'true'),
                       'selected': selected})
    return result


def availability_answer(question, settings, input_type='text', today=None):
    """Answer personal availability only from explicit config, never AI."""
    from datetime import date
    if re.search(r'\b(?:(?:employment|education)\s+(?:start|end|date)|dates? of employment|previous role|birth|graduation)\b', question, re.I):
        return None
    if not re.search(r'\b(?:start(?:ing)? date|available to (?:start|begin)|availability|(?:when|what date) (?:can|could|would) you (?:start|begin))\b', question, re.I):
        return None
    configured = str(settings.get('available_start_date') or '').strip()
    if configured.casefold() in {'immediate', 'immediately', 'asap'}:
        return (today or date.today()).isoformat() if input_type == 'date' else 'Immediate'
    if configured:
        return date.fromisoformat(configured).isoformat()
    notice = settings.get('notice_period')
    if str(notice).isdigit():
        if int(notice) == 0:
            return (today or date.today()).isoformat() if input_type == 'date' else 'Immediate'
        if input_type != 'date':
            return f'Available with {int(notice)} days of notice'
    from modules.linkedin_easy_apply import MissingApplicationAnswer
    raise MissingApplicationAnswer('Configure available_start_date for this availability question: ' + question)


def sponsorship_question(question):
    return bool(re.search(r'\bsponsor(?:ship|ed|ing)?\b|\bvisa\b', question, re.I))


def application_location_answer(question, choices, posting_location, configured_location=''):
    """Match an application-office choice to the posting before any fallback."""
    location_prompt = (re.search(r'\blocation\b', question, re.I)
        and re.search(r'\b(?:apply|applying|preferred|preference|desired|office|job|position|work)\b', question, re.I))
    if not location_prompt or re.search(r'\b(?:current|home|residen|birth)\w*\b', question, re.I):
        return None
    options = [str(item.get('text') or '').strip() for item in choices
               if item.get('enabled', True) and not item.get('placeholder') and str(item.get('text') or '').strip()]
    if options and all(re.fullmatch(r'yes|no|true|false', text, re.I) for text in options):
        return None  # An ordinary yes/no question about willingness to work there.
    normalize = lambda value: ' '.join(re.sub(r'[^\w\s]', ' ', str(value).casefold()).split())
    posting = re.sub(r'\((?:remote|hybrid|on.site)\)', '', str(posting_location), flags=re.I).strip()
    city = normalize(posting.split(',')[0])
    parts = posting.split(',')
    state = normalize(parts[1]) if len(parts) > 1 else ''
    canonical_state = lambda value: {'california': 'ca'}.get(normalize(value), normalize(value))
    if state:
        options = [text for text in options if ',' not in text
                   or canonical_state(text.split(',')[1]) == canonical_state(state)]
    def unique_match(target):
        exact = [text for text in options if normalize(text) == normalize(target)]
        if len(exact) == 1:
            return exact[0]
        matches = [text for text in options if target and re.search(r'(?<!\w)' + re.escape(target) + r'(?!\w)', normalize(text))]
        return matches[0] if len(matches) == 1 else None
    matched = unique_match(normalize(posting)) if posting else None
    if not matched and city and city not in {'united states', 'usa', 'us', 'california', 'san francisco bay area'}:
        matched = unique_match(city)
    if matched:
        return matched
    configured = normalize(configured_location)
    if 'bay area' in configured:
        from modules.job_pipeline.careers import BAY_AREA_CITIES
        regional = [text for text in options if any(re.search(r'(?<!\w)' + re.escape(city) + r'(?!\w)', normalize(text))
                    for city in BAY_AREA_CITIES)]
        if len(regional) == 1:
            return regional[0]
    elif configured:
        matched = unique_match(configured) or unique_match(normalize(str(configured_location).split(',')[0]))
        if matched:
            return matched
    from modules.linkedin_easy_apply import MissingApplicationAnswer
    raise MissingApplicationAnswer('No unambiguous application location matches the posting/configuration: ' + question)


def is_calendar_date_select(control, inferred_label=''):
    """A duration option mentioning 'year' does not make a calendar selector."""
    options = control.find_elements(By.TAG_NAME, 'option')
    if not options:
        return True  # Non-native date widgets are identified by their caller.
    labels = [inferred_label, control.get_attribute('aria-label'),
              control.get_attribute('title'), control.get_attribute('placeholder')]
    labels.extend(option.text for option in options
                  if option.get_attribute('selected') is not None)
    if not any(option.get_attribute('selected') is not None for option in options):
        labels.append(options[0].text)
    return any(re.fullmatch(r'\s*(?:(?:select|from|to|start|end|employment)\s+)*(?:month|year)\s*\*?\s*',
                            str(label or ''), re.I) for label in labels)


def experience_range_answer(question, choices, years):
    """Match the configured experience to an employer's duration buckets."""
    if not re.search(r'experience|industry role|how long.*work', question, re.I):
        return None
    try:
        years = float(years)
    except (TypeError, ValueError):
        return None
    for choice in choices:
        text = str(choice.get('text') or '')
        if not choice.get('enabled', True) or choice.get('placeholder'):
            continue
        match = re.fullmatch(r'\s*(?:(<)\s*(\d+)|(\d+)\s*[-–]\s*(\d+)|(\d+)\s*(\+))\s*years?\s*', text, re.I)
        if match:
            less, upper, low, high, lower, plus = match.groups()
            if ((less and 0 <= years < float(upper))
                    or (low and float(low) <= years <= float(high))
                    or (plus and years >= float(lower))):
                return text
    return None


def fill_binary_checkbox_groups(modal, answer_for, click, questions, settings=None):
    """Treat SDUI Yes/No checkbox fieldsets as one employer question.

    Empty native labels and a heading outside the fieldset are intentional in
    this UI. Do not let the independent required-checkbox handler select both.
    """
    from modules.application_choices import choose_index
    from modules.linkedin_easy_apply import MissingApplicationAnswer
    handled, count = set(), 0
    for group in modal.find_elements(By.XPATH, './/fieldset[.//input[@type="checkbox"] or .//*[@role="checkbox"]]'):
        controls = group.find_elements(By.XPATH,
            './/input[@type="checkbox"] | .//*[@role="checkbox"][not(.//input[@type="checkbox"])]')
        if len(controls) != 2:
            continue
        options, wrappers = [], []
        for control in controls:
            roles = control.find_elements(By.XPATH, './ancestor::*[@role="checkbox"][1]')
            wrapper = roles[0] if roles else control
            ident = control.get_attribute('id')
            labels = group.find_elements(By.XPATH, './/label[@for="' + ident + '"]') if ident else []
            text = (labels[0].text if labels else '') or wrapper.text or control.get_attribute('aria-label') or ''
            options.append({'text': ' '.join(text.split()), 'enabled': control.is_enabled()
                            and wrapper.get_attribute('aria-disabled') != 'true'})
            wrappers.append(wrapper if roles or control.get_attribute('role') == 'checkbox'
                            else labels[0] if labels and labels[0].is_displayed() else control)
        if {option['text'].casefold() for option in options} != {'yes', 'no'}:
            continue
        headings = group.find_elements(By.XPATH, './legend | ./preceding-sibling::p[1]')
        prompt = group.get_attribute('aria-label') or ' '.join(node.text for node in headings)
        if not prompt.strip():
            continue
        prompt = ' '.join(prompt.split())
        disclosure, disclosure_answer = demographic_request(prompt, options, settings or {})
        if disclosure and disclosure_answer is None:
            raise MissingApplicationAnswer('Checkbox group has no configured demographic opt-out: ' + prompt)
        selected, defaulted = choose_index(options, disclosure_answer if disclosure else answer_for(prompt.casefold(), None))
        if defaulted and re.search(r'visa|sponsor', prompt, re.I):
            raise MissingApplicationAnswer('Sponsorship question requires a configured Yes/No answer: ' + prompt)
        def checked(index):
            return controls[index].is_selected() or wrappers[index].get_attribute('aria-checked') == 'true'
        previous = next((option['text'] for i, option in enumerate(options) if checked(i)), None)
        if (options[selected]['text'].casefold() == 'yes' and not checked(selected)
                and re.search(r'\b(?:agree|consent|certif\w*|attest\w*|terms|signature|sign electronically)\b', prompt, re.I)):
            raise MissingApplicationAnswer('Required agreement needs confirmation for this application: ' + prompt)
        # Clear any conflicting selection before selecting the requested answer.
        for i in [i for i in range(2) if i != selected] + [selected]:
            if checked(i) != (i == selected):
                if not options[i]['enabled']:
                    raise MissingApplicationAnswer('Checkbox group option is disabled: ' + prompt)
                click(wrappers[i])
        if not checked(selected) or any(checked(i) for i in range(2) if i != selected):
            raise MissingApplicationAnswer('Checkbox group selection did not persist: ' + prompt)
        questions.add((prompt, options[selected]['text'], 'checkbox_group', previous))
        handled.update(node.id for node in controls + wrappers)
        count += 1
    return handled, count


def validation_messages(root):
    """Describe rejected questions without recording their entered answers."""
    messages = []
    for error in root.find_elements(By.XPATH,
            ".//*[normalize-space(text())='This field is required' or normalize-space(text())='Invalid input']"):
        if not error.is_displayed():
            continue
        contexts = error.find_elements(By.XPATH,
            './ancestor::*[@componentkey and starts-with(@componentkey,"easyApplyFieldFocus_")][1]')
        if not contexts:
            contexts = error.find_elements(By.XPATH, './parent::*')
        headings = contexts[0].find_elements(By.XPATH, './p[not(.=../p[last()])] | .//legend | .//label') if contexts else []
        prompt = next((' '.join(node.text.split()) for node in headings
                       if node.text.strip() and node.text.strip() not in {'This field is required', 'Invalid input'}), '')
        message = (prompt[:240] + ': ' if prompt else '') + ' '.join(error.text.split())
        if message not in messages:
            messages.append(message)
    return messages


def bounded_text(value, limit):
    """Bound descriptive prose using the browser's UTF-16 character count."""
    value = str(value or '')
    if not isinstance(limit, int) or limit <= 0 or len(value.encode('utf-16-le')) // 2 <= limit:
        return value
    clipped = value.encode('utf-16-le')[:limit * 2].decode('utf-16-le', errors='ignore')
    if not clipped[-1:].isspace() and re.search(r'\s', clipped):
        clipped = re.sub(r'\s+\S*$', '', clipped)
    return clipped.rstrip()


def demographic_request(label, choices, settings):
    """Honor configured disclosure preferences before generic first-option fallback."""
    category = next((name for pattern, name in [
        (r'gender|\bsex\b', 'gender'), (r'race|ethnic|hispanic|latino', 'ethnicity'),
        (r'veteran', 'veteran_status'), (r'disab|handicapped', 'disability_status')]
        if re.search(pattern, label, re.I)), None)
    if category is None:
        return False, None
    requested = settings.get(category)
    if requested is None and settings.get('dei_choice_policy') != 'prefer_not_to_answer':
        return False, None
    if str(requested or '').casefold() != 'decline' and requested:
        return True, requested
    for choice in choices:
        text = choice.get('text') or ''
        if choice.get('enabled', True) and re.search(
                r'declin|prefer not|not wish|not want|choose not|not disclos|not provid|not declared|rather not', text, re.I):
            return True, text
    # Some employers explicitly encode their opt-out as No.
    if re.search(r'(?:not to self.identify|choose not).*\bno\b', label, re.I):
        no = next((c['text'] for c in choices if c.get('enabled', True) and c.get('text', '').strip().casefold() == 'no'), None)
        if no:
            return True, no
    if settings.get('unanswered_choice_policy') == 'first_option':
        return False, None
    return True, None


def clear_optional_choice(driver, control):
    """Clear an optional disclosure with no offered opt-out, verifying React state."""
    driver.execute_script('''/* jobrobo-clear-optional-disclosure */
      const root=arguments[0];
      if(root.tagName==='SELECT') {
        const option=[...root.options].find(o=>!o.value || /^(select|choose)/i.test(o.text));
        if(option) { Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(root,option.value);
          root.dispatchEvent(new Event('input',{bubbles:true})); root.dispatchEvent(new Event('change',{bubbles:true})); }
      } else for(const e of root.querySelectorAll('input[type="radio"]')) {
        if(!e.checked) continue;
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'checked').set.call(e,false);
        e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));
      }
    ''', control)
    if getattr(control, 'tag_name', '').casefold() == 'select':
        from modules.application_choices import dropdown_placeholder
        from selenium.webdriver.support.ui import Select
        cleared = dropdown_placeholder(Select(control).first_selected_option.text)
    else:
        cleared = not any(node.is_selected() or node.get_attribute('aria-checked') == 'true'
                          for node in control.find_elements(By.CSS_SELECTOR, 'input[type="radio"],[role="radio"]'))
    if not cleared:
        from modules.linkedin_easy_apply import MissingApplicationAnswer
        raise MissingApplicationAnswer('Optional demographic answer could not be cleared to honor configured Decline preference')


def is_privacy_notice_choice(label, prompt):
    if re.search(r'\b(?:employment\s+(?:agreement|contract)|non.?compete|arbitration|sign electronically)\b', prompt, re.I):
        return False
    if label == 'i consent' and re.search(r'read and agree to the privacy notice', prompt, re.I):
        return True
    if (label == 'i consent' and re.search(r'privacy notice', prompt, re.I)
            and re.search(r'personal information', prompt, re.I)
            and re.search(r'(?:job application|process your application|recruitment process)', prompt, re.I)):
        return True
    return (re.fullmatch(r'yes,? i have read and consent to the terms and conditions\.?', label) is not None
            and re.search(r'privacy notice', prompt, re.I) is not None
            and re.search(r'when you apply for a position', prompt, re.I) is not None)


def country_checkbox_answers(modal, country):
    """Handle an employer's required job-country checkbox group from config."""
    requested = {}
    if not isinstance(country, str) or not country.strip():
        return requested
    for group in modal.find_elements(By.CSS_SELECTOR, 'fieldset,[role="group"]'):
        boxes = group.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
        if len(boxes) < 2:
            continue
        prompt = group.text
        node = group
        for _ in range(3):
            if re.search(r'country of the position you are applying to', prompt, re.I):
                break
            parents = node.find_elements(By.XPATH, './parent::*')
            if not parents or parents[0].get_attribute('role') == 'dialog':
                break
            node = parents[0]
            prompt = node.text
        if not re.search(r'country of the position you are applying to', prompt, re.I):
            continue
        labels = []
        for box in boxes:
            ident = box.get_attribute('id')
            names = modal.find_elements(By.CSS_SELECTOR, 'label[for="' + ident + '"]') if ident else []
            text = names[0].text.strip() if names else ''
            if not text:
                wrappers = box.find_elements(By.XPATH, './ancestor::*[@role="checkbox"][1]')
                text = wrappers[0].text.strip() if wrappers else box.get_attribute('aria-label') or ''
            labels.append(' '.join(text.casefold().split()))
        target = ' '.join(country.casefold().split())
        if target in labels:
            requested.update({label: label == target for label in labels if label})
    return requested


def checkbox_prompt(driver, control):
    """Read a single checkbox's question, including an external required heading."""
    try:
        state = driver.execute_script('''/* jobrobo-checkbox-prompt */
          const e=arguments[0]; let text='';
          for(let p=e.parentElement,depth=0;p && depth<8;p=p.parentElement,depth++) {
            if(p.matches('dialog,[role="dialog"],form')) break;
            const fields=p.querySelectorAll('input:not([type="hidden"]),textarea,select');
            if(fields.length>1) break;
            const boxes=p.querySelectorAll('[role="checkbox"]');
            if(!fields.length && boxes.length>1) break;
            text=p.innerText||text;
          }
          return {text,required:e.required || e.getAttribute('aria-required')==='true' ||
            /\\*|this field is required/i.test(text)};
        ''', control)
        if isinstance(state, dict) and isinstance(state.get('text'), str):
            return state
    except Exception:
        pass
    text = ''
    for parent in list(reversed(control.find_elements(By.XPATH, './ancestor::*')))[:8]:
        if parent.get_attribute('role') == 'dialog' or getattr(parent, 'tag_name', '') in {'dialog', 'form'}:
            break
        if len(parent.find_elements(By.CSS_SELECTOR, 'input:not([type="hidden"]),textarea,select')) > 1:
            break
        text = parent.text or text
    return {'text': text, 'required': bool(re.search(r'\*|this field is required', text, re.I))}


def field_limit(driver, control, fallback):
    """Use the strictest native limit or counter belonging to this single field.

    SDUI can render a counter without setting maxlength. Never borrow a limit
    from a neighbouring field, even when both share one form-element wrapper.
    """
    limits = []
    for attr in ('maxlength', 'data-maxlength', 'data-max-length'):
        raw = control.get_attribute(attr)
        if isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
            limits.append(int(raw))
    texts = []
    try:
        # Lookup within the owning tree also works for shadow-root form fields.
        state = driver.execute_script('''/* jobrobo-field-constraints */
            const e=arguments[0], root=e.getRootNode();
            const texts=(e.getAttribute('aria-describedby')||'').split(/\\s+/)
              .map(id=>root.getElementById(id)?.textContent||'');
            for(let p=e.parentElement, depth=0;p && depth<8;p=p.parentElement,depth++) {
              if(p.matches('dialog,[role="dialog"]')) break;
              if(p.querySelectorAll('input:not([type]),input[type="text"],input[type="email"],input[type="tel"],input[type="number"],input[type="url"],textarea,select,[role="combobox"]').length>1) break;
              texts.push(p.innerText||'');
            }
            return {texts};
        ''', control)
        if isinstance(state, dict) and isinstance(state.get('texts'), list):
            texts.extend(text for text in state['texts'] if isinstance(text, str))
    except Exception:
        pass
    if not texts:
        for parent in list(reversed(control.find_elements(By.XPATH, './ancestor::*')))[:8]:
            if parent.get_attribute('role') == 'dialog' or getattr(parent, 'tag_name', '') == 'dialog':
                break
            if len(parent.find_elements(By.XPATH, TEXT_CONTROLS)) > 1:
                break
            if isinstance(parent.text, str):
                texts.append(parent.text)
            if parent.get_attribute('role') == 'dialog':
                break
    for text in texts:
        limits.extend(int(match) for match in re.findall(r'^\s*\d[\d,]*\s*/\s*([\d,]+)\s*(?:characters?|chars?)?\s*$', text.replace(',', ''), re.M | re.I)
                      if int(match) > 0)
        limits.extend(int(match) for match in re.findall(r'\b\d+\s+of\s+(\d+)\s+characters?\b', text, re.I)
                      if int(match) > 0)
        limits.extend(int(match) for match in re.findall(
            r'\b(?:maximum|max(?:imum)?\s+(?:of|length)?\s*:?|up to|limit\s*:?)[\s]*(\d+)\s*(?:characters?|chars?)\b', text, re.I))
    return min(limits) if limits else fallback


def invalid_text(control, limit):
    value = control.get_attribute('value')
    return (isinstance(value, str) and len(value.encode('utf-16-le')) // 2 > limit
            or control.get_attribute('aria-invalid') == 'true')


def short_numeric_rejection(driver, control, limit):
    """Recognize SDUI's short numeric screening field after prose is rejected.

    LinkedIn exposes these as type=text without pattern/inputmode. A bounded
    recovery is attempted only after its own field-local validation rejects an
    answer; other short fields retain their normal text behavior.
    """
    if limit != 20:
        return False
    state = driver.execute_script('''/* jobrobo-short-field-rejection */
        const e=arguments[0];
        for(let p=e.parentElement, depth=0;p && depth<6;p=p.parentElement,depth++) {
          if(p.querySelectorAll('input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"]),textarea,select').length>1) break;
          if(/\\binvalid input\\b/i.test(p.innerText||'')) return true;
          if(p.matches('dialog,[role="dialog"]')) break;
        }
        return false;
    ''', control)
    return state is True


def inapplicable_followup(driver, control, question):
    """Skip optional 'If yes' details only when the preceding radio says No."""
    if not re.match(r'^\s*if\s+["“\']?yes\b', question, re.I):
        return False
    if control.get_attribute('required') is not None or control.get_attribute('aria-required') == 'true':
        return False
    state = driver.execute_script('''/* jobrobo-conditional-followup */
        const e=arguments[0], root=e.closest('dialog,[role="dialog"]')||e.getRootNode();
        const groups=new Map();
        for(const r of root.querySelectorAll('input[type="radio"][name]')) {
          if(!(r.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)) continue;
          const name=r.getAttribute('name');
          if(!groups.has(name)) groups.set(name,[]);
          groups.get(name).push(r);
        }
        const group=[...groups.values()].at(-1)||[];
        for(const r of group) {
          const wrapper=r.closest('[role="radio"]');
          if(!(r.checked || wrapper?.getAttribute('aria-checked')==='true')) continue;
          const label=(r.labels?.[0]?.innerText||r.getAttribute('aria-label')||wrapper?.innerText||'').trim();
          return /^no[.\\s*]*$/i.test(label);
        }
        return false;
    ''', control)
    return state is True


def fill_text(driver, control, answer, limit):
    """Type, blur and verify the actual React-controlled value, without logging it."""
    from modules.linkedin_easy_apply import MissingApplicationAnswer
    value = '' if answer is None else str(answer)
    if len(value.encode('utf-16-le')) // 2 > limit:
        label = control.get_attribute('aria-label') or ''
        if not label:
            try:
                label = driver.execute_script("return [...(arguments[0].labels||[])].map(e=>e.innerText).join(' | ')", control)
            except Exception:
                pass
        name = f' for {label}' if isinstance(label, str) and label else ''
        raise MissingApplicationAnswer(f'Answer{name} exceeds this field\'s {limit}-character limit '
                                       f'({len(value.encode("utf-16-le")) // 2} characters)')
    def replace_value():
        driver.execute_script('''/* jobrobo-verified-field-replacement */
            const e=arguments[0], value=arguments[1];
            const proto=e.tagName==='TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            Object.getOwnPropertyDescriptor(proto,'value').set.call(e,value);
            e.dispatchEvent(new Event('input',{bubbles:true,composed:true}));
            e.dispatchEvent(new Event('change',{bubbles:true,composed:true}));
            e.blur();
        ''', control, value)
    control.clear()
    if control.get_attribute('type') == 'date':
        # Calendar keyboard formats depend on browser locale; the native value
        # contract is always ISO YYYY-MM-DD.
        replace_value()
    else:
        control.send_keys(value)
    control.send_keys(Keys.TAB)
    actual = control.get_attribute('value')
    if actual != value:
        # Fast keyboard input can lose characters during SDUI React rerenders.
        replace_value()
        if control.get_attribute('value') != value:
            raise MissingApplicationAnswer('Application field did not retain the intended answer after replacement')
    state = driver.execute_script('''/* jobrobo-field-validity */
        const e=arguments[0]; return e.validity ? {
          valid:e.validity.valid, typeMismatch:e.validity.typeMismatch,
          patternMismatch:e.validity.patternMismatch, rangeOverflow:e.validity.rangeOverflow,
          rangeUnderflow:e.validity.rangeUnderflow, badInput:e.validity.badInput
        } : null;
    ''', control)
    if isinstance(state, dict) and state.get('valid') is False:
        raise MissingApplicationAnswer('Application answer does not match this field\'s format')


def education_checkbox_answers(modal, source_docx, configured):
    """Return required field-of-study selections supported by source education.

    Other checkbox groups, especially personal declarations and agreements,
    retain their existing explicit configuration/confirmation behavior.
    """
    from pathlib import Path
    from modules.linkedin_easy_apply import MissingApplicationAnswer
    groups = modal.find_elements(By.XPATH,
        './/*[count(.//input[@type="checkbox"])>1][not(.//*[count(.//input[@type="checkbox"])>1])]')
    requested = {}
    education = None
    for group in groups:
        text = ' '.join(group.text.split())
        # The options may be in an inner list and the prompt just above it.
        for _ in range(3):
            if re.search(r'field(?:s)? of study|major(?:s)?\b|degree(?:s)?\b', text, re.I):
                break
            parents = group.find_elements(By.XPATH, './parent::*')
            if not parents or parents[0].get_attribute('role') == 'dialog':
                break
            group = parents[0]
            text = ' '.join(group.text.split())
        if not re.search(r'field(?:s)? of study|major(?:s)?\b|degree(?:s)?\b', text, re.I):
            continue
        if not ('*' in text or group.get_attribute('aria-required') == 'true'
                or 'this field is required' in text.casefold()):
            continue
        controls = group.find_elements(By.XPATH, './/input[@type="checkbox"]')
        if any(node.is_selected() for node in controls):
            continue
        if education is None:
            education = ''
            if source_docx and Path(source_docx).is_file():
                from docx import Document
                doc = Document(source_docx)
                body = '\n'.join(p.text for p in doc.paragraphs)
                # Source degrees only; job requirements and skills are not degrees.
                section = re.search(r'\bEDUCATION\b(.*?)(?:\n\s*(?:SKILLS|EXPERIENCE|WORK EXPERIENCE|PROFESSIONAL EXPERIENCE)\b|$)', body, re.S | re.I)
                education = section.group(1).casefold() if section else ''
        matches = []
        configured_selection = False
        for node in controls:
            ident = node.get_attribute('id')
            labels = modal.find_elements(By.XPATH, './/label[@for="' + ident + '"]') if ident else []
            label = (labels[0].text if labels else node.get_attribute('aria-label')) or ''
            if not label.strip():
                wrappers = node.find_elements(By.XPATH, './ancestor::*[@role="checkbox"][1]')
                label = wrappers[0].text if wrappers else ''
            key = ' '.join(label.casefold().split())
            if key in configured:
                requested[key] = configured[key]
                configured_selection |= configured[key] is True
                continue
            # Compound options can contain synonymous degrees; match a phrase,
            # never incidental words such as "science" or "engineering" alone.
            options = [part.strip() for part in re.split(r'[/,;]|\bor\b', key) if part.strip()]
            supported = any(len(part.split()) >= 2 and part in education for part in options)
            supported |= ('business administration' in key and bool(re.search(r'\bmba\b', education)))
            if supported:
                matches.append(key)
        if not matches and not configured_selection:
            raise MissingApplicationAnswer('Required education checkbox group has no resume-backed or configured answer')
        if not configured_selection:
            for key in (matches if re.search(r'select all|check all', text, re.I) else matches[:1]):
                requested[key] = True
    return requested
