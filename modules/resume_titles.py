"""Keep posting metadata out of resume role lines."""
import re


def normalized_role_title(value):
    title = ' '.join(str(value or '').split())
    title = re.split(r'\s*\|\s*', title, maxsplit=1)[0]
    # Skill lists following a real role are posting descriptors, not its title.
    if ':' in title:
        role, detail = title.split(':', 1)
        if re.search(r'engineer|architect|developer|technical staff|scientist|manager|director', role, re.I):
            title = role
    title = re.split(r'\s+[-–—]\s+(?=remote\b|hybrid\b|on.site\b|san francisco\b|\$|up to\b)', title, maxsplit=1, flags=re.I)[0]
    title = re.sub(r'\s*\((?:remote|hybrid|on.site|san francisco|sf bay area)\)\s*$', '', title, flags=re.I)
    return title.strip()
