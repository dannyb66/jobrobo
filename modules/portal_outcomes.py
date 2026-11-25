"""Pure classification of explicit employer refusals, shared by all runners."""
import re


def portal_messages(state):
    return list(dict.fromkeys(str(value) for field in ('headings', 'alerts')
                             for value in state.get(field, []) if value))


def explicit_portal_rejection(state):
    text = '\n'.join(portal_messages(state))
    if (re.search(r"we couldn['’]t submit your application", text, re.I)
            and re.search(r'flagged as possible spam', text, re.I)):
        return 'Employer explicitly rejected the application as possible spam'
    if re.search(r'error verifying your application', text, re.I):
        return 'Employer could not verify the submitted application'
    if re.search(r'problem verifying this submission with CAPTCHA', text, re.I):
        return 'Employer rejected CAPTCHA verification for this submission'
    return ''
