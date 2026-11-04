"""Personal employer screening uses configuration, never generated biography."""
import re
from pathlib import Path


def employer_screening_answer(question, settings, *, choice=False):
    text = ' '.join(question.casefold().split())
    kind = None
    if re.search(r'\b(?:relatives|personal relationships)\b', text) and re.search(r'employee|contractor|vendor|working|employed', text):
        kind = 'employee_relationships'
    elif re.search(r'\b(?:referred|referral|referrer)\b', text) and re.search(r'employee|name|relationship', text):
        kind = 'employee_referral'
    elif re.search(r'previously applied|applied (?:here|before|previously)|ever applied', text):
        kind = 'previous_application'
    elif re.search(r'ever (?:been )?employed|previously (?:worked|employed)|worked (?:here|for us|for this company) before', text):
        kind = 'previous_employment'
    elif re.search(r'legally eligible.*(?:employment|work)|legally authorized to work', text):
        kind = 'employment_eligibility'
    if kind is None:
        return None

    answer = None
    entries = settings.get('application_employer_screening_answers', {})
    if not isinstance(entries, dict):
        raise ValueError('Employer screening configuration must be an object')
    if any(not isinstance(name, str) or not name.strip() or not isinstance(values, dict)
           for name, values in entries.items()):
        raise ValueError('Each employer screening entry needs a name and answer object')
    current = str(settings.get('_application_employer') or '').casefold().strip()
    matches = [values for employer, values in entries.items()
               if employer.casefold().strip() == current
               or re.search(r'(?<!\w)' + re.escape(employer.casefold()) + r'(?!\w)', text)]
    if len(matches) > 1:
        raise ValueError('Ambiguous employer screening configuration')
    if matches:
        answer = matches[0].get(kind)

    if answer is None and kind == 'employment_eligibility':
        answer = settings.get('application_immediate_employment_eligible') if 'immediately' in text else None
        if answer is None:
            authorized = settings.get('us_citizenship') in {
                'U.S. Citizen/Permanent Resident', 'Non-citizen allowed to work for any employer'}
            immediate = 'immediately' not in text or str(settings.get('available_start_date', '')).casefold() == 'immediate'
            if authorized and immediate:
                answer = True
    if answer is None and kind == 'employee_relationships' and 'personal relationships' not in text:
        # Existing explicit relative-name setting: empty means no relatives.
        if 'application_relative_employee_names' in settings:
            answer = settings['application_relative_employee_names'] or False
    if answer is None:
        from modules.linkedin_easy_apply import MissingApplicationAnswer
        raise MissingApplicationAnswer('Employer screening needs explicit config (' + kind + '): ' + question)
    if type(answer) is bool:
        return 'Yes' if answer else 'No'
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('Employer screening answer must be a boolean or nonempty text')
    if choice:
        if re.match(r'^no\b', answer.strip(), re.I) or answer.strip().casefold() in {'none', 'n/a', 'not applicable'}:
            return 'No'
        return 'Yes'
    return answer.strip()


def draft_evidence_path(selected_resume, uploaded, original_docx, original_pdf):
    """Prepare prose from source evidence before upload; never change upload state."""
    candidates = [selected_resume] if uploaded and selected_resume else [original_docx, original_pdf]
    for value in candidates:
        if value:
            path = Path(value).expanduser().resolve()
            if path.is_file() and path.suffix.lower() in {'.docx', '.pdf'}:
                return path
    from modules.application_drafts import DraftError
    raise DraftError('Readable configured source resume is required for drafting')
