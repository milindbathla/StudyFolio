import re

from ..contracts import EpisodeProposal, FactProposal


def normal(text):
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def words(text):
    return set(normal(text).split())


def clean(value):
    return value.strip(" \t.,!;").strip()


RULES = (
    ("identity.name", r"\b(?:my name is|call me) (.+)"),
    (
        "identity.academic_year",
        r"\b(?:i am|i'm) (?:currently )?(?:in )?(?:my )?((?:first|second|third|fourth|final|\d+(?:st|nd|rd|th)) year)\b",
    ),
    ("identity.institution", r"\bi (?:study at|attend) (.+)"),
    ("identity.degree", r"\b(?:my degree is|i am pursuing|i'm pursuing) (.+)"),
    (
        "identity.branch",
        r"\b(?:i(?: am|'m) (?:currently )?studying|my major is|i major in) ([\w &-]+engineering)\b",
    ),
    ("academic_profile.current_courses", r"\bi(?: am|'m) (?:currently )?(?:taking|enrolled in) (.+)"),
    ("academic_profile.completed_courses", r"\bi(?: have|'ve)? completed (.+)"),
    ("academic_profile.topics_studied", r"\bi (?:studied|learned) (.+)"),
    ("academic_profile.reported_strengths", r"\bi(?: am|'m) (?:good|strong) (?:at|in) (.+)"),
    (
        "academic_profile.reported_difficulties",
        r"\bi (?:struggled|struggle|had difficulty|have trouble) (?:with |understanding )?(.+?)(?: yesterday| today| last week|$)",
    ),
    ("goals.short_term", r"\b(?:my (?:short.term )?goal is|i aim to|i plan to) (.+)"),
    ("goals.long_term", r"\bmy long.term goal is (.+)"),
    ("goals.active_projects", r"\bi(?: am|'m) working on (.+)"),
    (
        "learning_preferences.language_preferences",
        r"\b(?:please respond|please explain|i prefer explanations) in (english|hindi|spanish|french|german|tamil|bengali)\b",
    ),
    ("learning_preferences.explanation_depth", r"\bi (?:now |usually )?prefer (.+)"),
    ("learning_preferences.preferred_learning_style", r"\b(?:from now on,? |please )explain (.+)"),
    ("behavioral_patterns.study_routines", r"\bi (?:usually|regularly|always) study (.+)"),
    ("constraints.time_constraints", r"\bi (?:only have|can only study) (.+)"),
    ("interests.academic", r"\bi(?: am|'m) interested in (.+)"),
)


def rule_facts(m):
    result = []
    for clause in re.split(r"[.!?;\n]+|(?<=\w),?\s+and\s+(?=I\b)", m.content):
        clause = clause.strip()
        if (
            not clause
            or "?" in m.content
            and m.content.strip().endswith("?")
            and len(m.content.split(".")) == 1
        ):
            continue
        for path, pattern in RULES:
            match = re.search(pattern, clause, re.I)
            if not match:
                continue
            value = clean(match.group(1))[:600]
            if not value:
                continue
            scope = ""
            scoped = re.search(r"(?:^|,\s*)for ([^,]+),", clause, re.I)
            if scoped and path.startswith("learning_preferences."):
                scope = clean(scoped.group(1)).lower()[:90]
            if path == "learning_preferences.explanation_depth" and not re.search(
                r"explan|detail|short|brief|concise|derivation|conceptual|example|visual|step.by.step|long answer",
                value,
                re.I,
            ):
                continue
            result.append(
                FactProposal(
                    path=path,
                    value=value,
                    scope=scope,
                    quote=clause[:600],
                    message_id=m.id,
                    confidence=0.93,
                    correction=bool(
                        re.search(
                            r"\b(actually|now|instead|correction|no longer|from now on)\b", clause, re.I
                        )
                    ),
                )
            )
            break
    return result


EVENTS = (
    (
        "difficulty",
        r"(?:struggl(?:e|ed|ing)|difficulty|trouble|extra help) (?:with |understanding )?(.+)",
    ),
    ("practice", r"(?:attempted|practiced|solved|worked through) (.+)"),
    ("success", r"(?:successfully explained|finally understood) (.+)"),
    ("goal", r"(?:my goal is|i plan to|my study plan is) (.+)"),
    ("deadline", r"((?:[\w-]+ ){0,3}(?:exam|quiz|assignment|deadline|submission|midterm)\b.*)"),
    ("study", r"(?:we discussed|i studied|i learned|i reviewed|help me understand) (.+)"),
)


def rule_episodes(m):
    if m.content.rstrip().endswith("?"):
        return []
    for kind, pattern in EVENTS:
        match = re.search(pattern, m.content, re.I)
        if match:
            topic = re.split(
                r"\b(?:yesterday|last week|today|is due|on|is on|at)\b|[.!?]",
                match.group(1),
                maxsplit=1,
                flags=re.I,
            )[0]
            return [
                EpisodeProposal(
                    summary=m.content[:600],
                    topic=clean(topic)[:120] or kind,
                    kind=kind,
                    quote=m.content[:600],
                    message_id=m.id,
                )
            ]
    return []


SENSITIVE = re.compile(
    r"\b(?:diagnos\w*|depress\w*|autis\w*|adhd|bipolar|religio\w*|ethnic\w*|sexuali\w*|personality disorder|political affiliation|intelligence quotient)\b",
    re.I,
)


def grounded(p, m):
    if (
        not m
        or m.role != "user"
        or m.id != p.message_id
        or p.quote not in m.content
        or p.confidence < 0.62
    ):
        return False
    if SENSITIVE.search(p.value) or SENSITIVE.search(p.quote):
        return False
    if p.scope and not words(p.scope) <= words(p.quote):
        return False
    # Generated values must retain the actual words in the learner's evidence.
    return words(p.value) <= words(p.quote) and bool(words(p.value))


def stated_as(path, quote):
    return any(p == path and re.search(pattern, quote, re.I) for p, pattern in RULES)
