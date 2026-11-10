import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.parser import parse

from ..contracts import EventInput

CATEGORIES = (
    ("exam", r"\b(?:exam(?:ination)?s?|end[- ]semester|midterms?|finals?)\b"),
    ("quiz", r"\b(?:quiz(?:zes)?|assessment)\b"),
    ("assignment", r"\b(?:assignment|homework|problem set)\b"),
    ("project", r"\b(?:project|submission)\b"),
    ("registration", r"\b(?:registration|enrolment|enrollment)\b"),
    ("meeting", r"\b(?:meeting|office hours)\b"),
    ("milestone", r"\b(?:study milestone|study session|important milestone|deadline)\b"),
)
MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY = "(?:" + "|".join(WEEKDAYS) + ")"
DATE = re.compile(
    rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?|{MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}(?:,?\s+\d{{4}})?|(?:next |this |coming )?{WEEKDAY}|day after tomorrow|tomorrow|today|in \d{{1,3}} days?|next week|later this month)\b",
    re.I,
)
CLOCK = re.compile(
    r"\b(?:at\s+)?(midnight|noon|(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[ap]\.?m\.?)?|(?:1[0-2]|0?[1-9])\s*[ap]\.?m\.?)\b",
    re.I,
)
UPDATE = re.compile(
    r"\b(?:moved|extended|postponed|rescheduled|pushed|changed|instead|extension)\b", re.I
)
COMMAND = re.compile(r"^(?:please\s+)?(?:add|schedule|put|remind me|mark|record)\b", re.I)


def classify(text):
    return next((key for key, pattern in CATEGORIES if re.search(pattern, text, re.I)), None)


def local_instant(day, clock, tz):
    wall = datetime.combine(day, clock.replace(tzinfo=None))
    zone = ZoneInfo(tz)
    a, b = wall.replace(tzinfo=zone, fold=0), wall.replace(tzinfo=zone, fold=1)
    if a.utcoffset() != b.utcoffset() or a.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != wall:
        raise ValueError("Local time is ambiguous or does not exist at this timezone transition")
    return a.astimezone(UTC)


def normalized(text, timestamp, tz):
    base = timestamp.astimezone(ZoneInfo(tz)).date()
    matches = list(DATE.finditer(text))
    if not matches:
        return None
    term = matches[-1].group().lower()
    result = {
        "date": None,
        "time": None,
        "original": text[matches[-1].start() :].strip(" ."),
        "review": "",
        "base_date": base.isoformat(),
        "prior": matches[0].group() if len(matches) > 1 and UPDATE.search(text) else None,
    }
    try:
        if term in ("next week", "later this month"):
            raise ValueError("Choose an exact date")
        if "/" in term:
            parts = term.split("/")
            if int(parts[0]) <= 12 and int(parts[1]) <= 12 and parts[0] != parts[1]:
                raise ValueError("Numeric date order is ambiguous")
            day = parse(term, dayfirst=int(parts[0]) > 12, default=datetime.combine(base, time())).date()
        elif term in ("tomorrow", "today", "day after tomorrow"):
            day = base + timedelta(days={"today": 0, "tomorrow": 1, "day after tomorrow": 2}[term])
        elif term.startswith("in "):
            day = base + timedelta(days=int(term.split()[1]))
        elif term.split()[-1] in WEEKDAYS:
            delta = (WEEKDAYS.index(term.split()[-1]) - base.weekday()) % 7
            day = base + timedelta(days=delta or 7)
        else:
            raw = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", term)
            day = parse(raw, default=datetime.combine(base.replace(day=1), time())).date()
            if (
                not re.search(r"\d{4}", raw)
                and day < base
                and not re.search(r"\b(?:was|had|last|yesterday)\b", text, re.I)
            ):
                day = day.replace(year=day.year + 1)
        result["date"] = day.isoformat()
        c = CLOCK.search(text, matches[-1].end()) or CLOCK.search(text[: matches[0].start()])
        if c:
            clock = c.group(1).lower().replace(".", "")
            t = time(0) if clock == "midnight" else time(12) if clock == "noon" else parse(clock).time()
            result["time"] = t.isoformat(timespec="minutes")
            local_instant(day, t, tz)
            if clock == "midnight":
                result["review"] = "Confirm which day begins at midnight"
        if day < base:
            result["review"] = "The stated date is in the past"
    except (ValueError, OverflowError) as exc:
        result["review"] = (
            str(exc)
            if "Choose" in str(exc) or "ambiguous" in str(exc)
            else "Choose a valid date and time"
        )
    return result


def title_for(text, category):
    if category == "exam" and re.search(r"end[- ]semester", text, re.I):
        code = re.search(r"\b[A-Z]{2,5}\s?\d{2,4}\b", text)
        if code:
            return code.group() + " End-Semester Examination"
    prefix = DATE.split(text, maxsplit=1)[0]
    prefix = re.sub(
        r"^(?:actually,?\s*)?(?:(?:please )?(?:add|schedule|record|mark|put|remind me (?:of|about|to))\s+)?(?:(?:i have|there is)\s+)?(?:my |an? |the |our )?",
        "",
        prefix,
        flags=re.I,
    )
    prefix = re.split(
        r"\b(?:is due|is on|is at|is scheduled|will be|due|on|at|has been|was|moved|changed|postponed|extended|from|deadline is)\b",
        prefix,
        maxsplit=1,
        flags=re.I,
    )[0].strip(" ,.-")
    if len(prefix) > 90 or not prefix:
        return category.capitalize()
    return prefix[0].upper() + prefix[1:]


def fields(payload: EventInput, tz):
    zone = payload.timezone or tz
    return dict(
        title=payload.title,
        category=payload.category,
        description=payload.description,
        local_date=payload.date.isoformat(),
        timezone=zone,
        all_day=payload.time is None,
        start_utc=local_instant(payload.date, payload.time, zone) if payload.time is not None else None,
        end_utc=local_instant(payload.date, payload.end_time, zone) if payload.end_time else None,
    )
