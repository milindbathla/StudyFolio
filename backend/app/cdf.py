import os
import re
from collections import defaultdict

from . import knowledge as kg
from .source_parse import COURSE, VARIANT, code, variant

RULES = [
    ("curriculum_lookup", r"prerequisit", ["HAS_PREREQUISITE"]),
    ("curriculum_lookup", r"equivalen", ["EQUIVALENT_TO"]),
    (
        "curriculum_lookup",
        r"curriculum|template|planned courses|requirements",
        ["HAS_CURRICULUM_COURSE", "HAS_REQUIREMENT"],
    ),
    (
        "identity_lookup",
        r"\bcollege\b|institut(?:e|ion)|universit|where.*(?:enroll|study|pursu|attend)",
        ["ENROLLED_AT"],
    ),
    ("academic_record_lookup", r"\bcpi\b|cumulative performance", ["DOCUMENTED_CPI"]),
    ("academic_record_lookup", r"\bspi\b|semester performance", ["DOCUMENTED_SPI"]),
    ("course_lookup", r"grade|marks", ["HAS_DOCUMENTED_GRADE"]),
    (
        "course_lookup",
        r"(?:current|taking|enrolled|this semester).*courses?|courses?.*(?:current|taking|this semester)",
        ["CURRENT_COURSE", "CURRENT_COURSE_STATUS"],
    ),
    ("course_lookup", r"courses?.*(?:completed|passed)|completed.*courses?", ["HAS_COMPLETED_COURSE"]),
    ("identity_lookup", r"department|branch|majoring", ["BELONGS_TO_DEPARTMENT"]),
    ("identity_lookup", r"degree|programme|program\b", ["PURSUING_PROGRAMME"]),
    ("identity_lookup", r"my name", ["LEARNER_NAME"]),
    ("identity_lookup", r"academic year|year of study", ["ACADEMIC_YEAR"]),
    ("academic_record_lookup", r"current semester", ["CURRENT_SEMESTER"]),
    ("goal_lookup", r"goals?|aspiration", ["HAS_GOAL"]),
    ("preference_lookup", r"prefer", ["HAS_PREFERENCE"]),
    ("persona_lookup", r"skill|good at|proficien", ["HAS_REPORTED_SKILL_LEVEL"]),
    ("temporal_event_lookup", r"deadline|upcoming|calendar", []),
    (
        "episodic_history_lookup",
        r"struggl|difficulty|last week|last conversation",
        ["EXPERIENCED_DIFFICULTY_WITH", "DISCUSSED_TOPIC"],
    ),
]


def intent(q):
    if re.search(r"completed|passed", q, re.I) and re.search(r"prerequisite|equivalen", q, re.I):
        return "analytical_question", ["HAS_COMPLETED_COURSE", "HAS_PREREQUISITE", "EQUIVALENT_TO"]
    for category, pattern, rels in RULES:
        if re.search(pattern, q, re.I):
            return category, rels
    return "general_conversation", []


def fusion(paths, k=60):
    scores = defaultdict(float)
    for path in paths:
        for rank, rid in enumerate(dict.fromkeys(path), 1):
            scores[rid] += 1 / (k + rank)
    return sorted(scores.items(), key=lambda v: (-v[1], v[0]))


def retrieve(s, engine, query, refinement=None, filters=None):
    category, relations = intent(query)
    if refinement and category == "general_conversation":
        category, relations = refinement.category, [refinement.relation]
    records = kg.catalog(s)
    if filters:
        if filters.document_type:
            records = [
                r
                for r in records
                if any(e["source_type"] == filters.document_type for e in r["evidence"])
            ]
        if filters.verification:
            records = [
                r
                for r in records
                if any(e.get("verification") == filters.verification for e in r["evidence"])
            ]
        if filters.start or filters.end:
            records = [
                r
                for r in records
                if any(
                    (not filters.start or e["timestamp"][:10] >= filters.start.isoformat())
                    and (not filters.end or e["timestamp"][:10] <= filters.end.isoformat())
                    for e in r["evidence"]
                )
            ]
    lookup = {r["id"]: r for r in records}
    cc = [code(c) for c in re.findall(COURSE, query.upper())]
    vv = VARIANT.search(query)
    programme = variant(vv[1]) if vv else ""
    if filters and filters.programme:
        programme = variant(filters.programme)
    if filters and filters.course_code:
        cc = [code(filters.course_code)]
    sem = re.search(r"semester\s*(\d+)", query, re.I)
    semester = sem[1] if sem else ""
    if "next semester" in query.lower():
        values = {
            r["value"] for r in records if r["relation"] == "CURRENT_SEMESTER" and r["value"].isdigit()
        }
        if len(values) == 1:
            semester = str(int(values.pop()) + 1)
    if category in ("curriculum_lookup", "analytical_question") and not programme:
        programmes = {variant(r["value"]) for r in records if r["relation"] == "PURSUING_PROGRAMME"}
        if len(programmes) == 1:
            programme = programmes.pop()
    departments = {r["value"].casefold() for r in records if r["relation"] == "BELONGS_TO_DEPARTMENT"}

    def matches(r):
        if (
            r["meta"].get("department")
            and len(departments) == 1
            and r["relation"] in ("HAS_CURRICULUM_COURSE", "HAS_REQUIREMENT", "HAS_PREREQUISITE")
            and r["meta"]["department"].casefold() not in departments
        ):
            return False
        return (
            r["relation"] in relations
            and (
                not cc
                or any(
                    c in [r["meta"].get("course"), r["value"], r["subject"].split(":")[-1]] for c in cc
                )
            )
            and (
                not programme
                or category != "curriculum_lookup"
                or r["meta"].get("programme") == programme
            )
            and (
                not semester
                or category not in ("curriculum_lookup", "academic_record_lookup", "course_lookup")
                or str(r["meta"].get("semester")) == semester
            )
        )

    direct = [r["id"] for r in records if matches(r)]
    refined = (
        refinement.semantic_query
        if refinement
        else query + " " + " ".join(rel.replace("_", " ").lower() for rel in relations)
    )
    vector_filters = (
        {
            k: getattr(filters, k, None)
            for k in ("document_type", "course_code", "programme", "verification")
        }
        if filters
        else None
    )
    vec = engine.vectors.search(refined, filters=vector_filters)
    semantic = [i for i in sorted(vec, key=vec.get, reverse=True) if i in lookup and vec[i] > 0.25][:18]
    terms = set(re.findall(r"\w{3,}", query.lower())) - set(
        "which what study about where the are have".split()
    )
    lexical = sorted(
        (
            (
                len(
                    terms
                    & set(
                        re.findall(
                            r"\w+",
                            (
                                r["value"] + " " + r["field"] + " " + r["evidence"][0].get("span", "")
                            ).lower(),
                        )
                    )
                ),
                r["id"],
            )
            for r in records
        ),
        reverse=True,
    )
    lexical = [i for score, i in lexical if score][:18]
    graph = engine.graph.traverse(records, relations)
    seeds = {node for i in (semantic or lexical)[:7] for node in kg.ends(lookup[i]) if node != "learner"}
    expansion = engine.graph.traverse(records, relations, seeds) if seeds else []
    rankings = fusion(
        [direct, semantic or lexical, graph, expansion], max(1, int(os.getenv("RRF_K", "60")))
    )
    ranked = [lookup[i] for i, _ in rankings]
    chosen = (
        [r for r in ranked if matches(r)]
        if relations
        else [r for r in ranked if r["relation"] == "PASSAGE"][:4]
    )
    pairs = []
    if category == "analytical_question":
        completed = {r["value"]: r for r in chosen if r["relation"] == "HAS_COMPLETED_COURSE"}
        if "math" in query.lower():
            completed = {
                k: r
                for k, r in completed.items()
                if k.startswith(("MTH", "MATH"))
                or re.search(r"math|calculus|algebra", r["meta"].get("title", ""), re.I)
            }
        connected = []
        for rule in chosen:
            if (
                rule["relation"] in ("HAS_PREREQUISITE", "EQUIVALENT_TO")
                and rule["value"] in completed
                and (not programme or rule["meta"].get("programme") == programme)
            ):
                connected.extend([completed[rule["value"]], rule])
                pairs.append(
                    rule["value"]
                    + " is a documented "
                    + ("prerequisite" if rule["relation"] == "HAS_PREREQUISITE" else "equivalent")
                    + " of "
                    + rule["subject"].removeprefix("Course:")
                )
        chosen = connected
    if category == "persona_lookup":
        skill_terms = {
            "machine learning": "ml",
            "programming": "program",
            "mathematics": "math",
            "dsa": "dsa",
        }
        for phrase, key in skill_terms.items():
            if phrase in query.lower():
                chosen = [r for r in chosen if key in r["field"]]
    if any(r["relation"] == "CURRENT_COURSE" for r in chosen):
        chosen = [r for r in chosen if r["relation"] != "CURRENT_COURSE_STATUS"]
    clarify = ""
    if category == "curriculum_lookup" and not programme and chosen:
        clarify = "Which programme variant should I use?"
    if category == "curriculum_lookup" and "next semester" in query.lower() and not semester:
        clarify = "Which semester should I look up in the template?"
    if (
        category == "course_lookup"
        and relations == ["HAS_DOCUMENTED_GRADE"]
        and len({(r["subject"], r["value"]) for r in chosen}) > 1
    ):
        clarify = "There are multiple documented attempts. Which course and semester do you mean?"
    if chosen and category in ("identity_lookup", "academic_record_lookup"):
        best = max(x["authority"] for x in chosen)
        supported = {r["value"].casefold() for r in chosen if r["authority"] == best}
        chosen = [r for r in chosen if r["value"].casefold() in supported]
        if len({r["value"].casefold() for r in chosen}) > 1:
            clarify = "The current sources disagree or cover different terms. Please clarify which record applies."
    grouped = {}
    for r in chosen:
        key = (r["relation"], r["subject"], r["value"].casefold())
        if key not in grouped:
            grouped[key] = dict(r, evidence=[])
        grouped[key]["evidence"].extend(r["evidence"])
    selected = list(grouped.values())[:30]
    answer = None
    if clarify:
        answer = clarify
    elif selected:
        vals = ", ".join(dict.fromkeys(r["value"] for r in selected))
        first = selected[0]["relation"]
        if pairs:
            answer = ". ".join(dict.fromkeys(pairs)) + "."
        elif first == "ENROLLED_AT":
            answer = f"You study at {vals}."
        elif first == "DOCUMENTED_CPI":
            answer = f"Your documented CPI is {vals}."
        elif first == "HAS_REPORTED_SKILL_LEVEL":
            answer = f"You reported {vals}. This is a self-assessment."
        elif first == "CURRENT_COURSE_STATUS" and not any(
            r["relation"] == "CURRENT_COURSE" for r in selected
        ):
            answer = "The academic record does not provide a verified current-course list."
        elif category == "curriculum_lookup":
            answer = "Your programme template lists " + vals + "."
        elif first == "HAS_COMPLETED_COURSE":
            answer = "Your completed courses include " + vals + "."
        elif first == "HAS_GOAL":
            answer = "Your recorded goals include " + vals + "."
        elif first == "HAS_PREFERENCE":
            answer = "Your stated preferences include " + vals + "."
        else:
            answer = first.replace("_", " ").capitalize() + ": " + vals + "."
    elif relations:
        answer = "I don’t have a verified source for that information."
    return dict(
        query=query,
        normalized_query=refined,
        intent=category,
        relations=relations,
        filters={"course": cc, "semester": semester, "programme": programme},
        direct=direct,
        semantic=semantic,
        lexical=lexical,
        graph=graph,
        expansion=expansion,
        rrf=[{"id": i, "score": v} for i, v in rankings[:60]],
        selected=selected,
        answer=answer,
        graph_status=engine.graph.state,
        vector_status=engine.vectors.state,
    )
