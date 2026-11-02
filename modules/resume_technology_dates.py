"""Reject catalogued technology claims made before the product existed.

Release dates are eligibility bounds, never proof of personal use. Unknown
technology names remain allowed so the guard does not become an allowlist.
"""
from __future__ import annotations
from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import re

MONTHS = {name.casefold(): index for index, name in enumerate(
    "January February March April May June July August September October November December".split(), 1)}
MONTHS.update({name[:3].casefold(): index for name, index in list(MONTHS.items())})


@lru_cache(maxsize=4)
def catalogue(path="config/technology_timeline.json"):
    from modules.config_loader import resource_path
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = resource_path(str(raw))
    data = json.loads(raw.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("technologies"), list):
        raise ValueError("Technology timeline requires schema_version 1 and technologies")
    rows = []
    for item in data["technologies"]:
        if not isinstance(item, dict) or not isinstance(item.get("names"), list):
            raise ValueError("Each technology needs names")
        names = [name for name in item["names"] if isinstance(name, str) and name.strip()]
        if not names:
            raise ValueError("Technology names must be nonempty strings")
        try:
            released = date.fromisoformat(item["first_public"])
        except (KeyError, ValueError) as exc:
            raise ValueError("Technology first_public must be an ISO date") from exc
        rows.append((tuple(names), released, item.get("source", "")))
    return tuple(rows)


def role_period(group) -> tuple[date, date] | None:
    """Read the first explicit start/end dates from the group's title line."""
    contexts = group.get("historical_title_dates") or group.get("context") or []
    text = " ".join(str(value) for value in contexts[:2])
    match = re.search(
        r"\b(?P<sm>[A-Za-z]{3,9})\s+(?P<sy>\d{4})\s*[-–—]\s*"
        r"(?:(?P<em>[A-Za-z]{3,9})\s+(?P<ey>\d{4})|(?P<present>present|current))\b",
        text, re.I)
    if not match:
        return None
    start_month = MONTHS.get(match.group("sm").casefold())
    end_month = MONTHS.get((match.group("em") or "").casefold())
    if not start_month:
        return None
    try:
        start = date(int(match.group("sy")), start_month, 1)
        if match.group("present"):
            end = date.today()
        elif end_month:
            year, month = int(match.group("ey")), end_month
            # Treat the named month as included and use its final day.
            end = date(year + (month == 12), month % 12 + 1, 1)
            end = date.fromordinal(end.toordinal() - 1)
        else:
            return None
    except ValueError:
        return None
    return (start, end) if start <= end else None


def mentioned(text, names):
    text = text or ""
    for name in names:
        pattern = r"(?<![\w])" + re.escape(name) + r"(?![\w])"
        if re.search(pattern, text, re.I):
            return True
    return False


def late_technologies(text, period, rows=None):
    """Return catalogued names in text whose public release postdates the role end."""
    if period is None:
        return []
    _, ended = period
    return [
        {"technology": names[0], "first_public": released.isoformat(), "source": source}
        for names, released, source in (rows or catalogue())
        if released > ended and mentioned(text, names)
    ]


def audit_inventory(inventory, rows=None):
    """Attach a deterministic technology-date audit to every experience group."""
    report = []
    for group in inventory.get("groups", []):
        period = role_period(group)
        late = late_technologies(group.get("company", ""), period, rows)
        group["technology_period"] = {
            "start": period[0].isoformat() if period else None,
            "end": period[1].isoformat() if period else None,
            "late": late,
        }
        report.append({"experience_id": group["experience_id"], "company": group.get("company"),
                       "period": group["technology_period"], "late": late})
    return report


def claim_issue(text, group, rows=None):
    period = role_period(group)
    if period is None:
        return None
    late = late_technologies(text, period, rows)
    if not late:
        return None
    detail = ", ".join(f"{item['technology']} ({item['first_public']})" for item in late)
    return f"technology predates role end {period[1].isoformat()}: {detail}"
