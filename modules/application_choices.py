"""Choose a configured radio/select answer, or the first usable option."""
import re


def choose_index(options, requested=None):
    """Return (original index, defaulted), preserving UI order and placeholders."""
    available = [(i, str(option.get('text') or '').strip()) for i, option in enumerate(options)
                 if option.get('enabled', True) and not option.get('placeholder', False)
                 and str(option.get('text') or '').strip()]
    if not available:
        raise ValueError('The application question has no enabled non-placeholder choices')
    target = str(requested or '').strip().casefold()
    if target:
        for i, label in available:
            if label.casefold() == target:
                return i, False
        phrases = ('decline', 'not wish', "don't wish", 'prefer not', 'not want') if target == 'decline' else (target,)
        for phrase in phrases:
            for i, label in available:
                if re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', label.casefold()):
                    return i, False
    return available[0][0], True


def dropdown_placeholder(text):
    text = str(text or '').strip()
    return not text or bool(re.match(r'^(?:please\s+)?(?:select|choose)(?:\s+(?:an?|one|option)\b|\s*[.\u2026]|$)', text, re.I))
