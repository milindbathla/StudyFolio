"""Source parsers return reviewable rows. Only an explicit learner decision promotes a survey field."""

import json
import re
from typing import Literal

from pydantic import BaseModel

Kind = Literal[
    "survey_json",
    "academic_transcript",
    "curriculum_template",
    "academic_notice",
    "general_academic_document",
    "unknown",
]
COURSE = r"[A-Z]{2,5}\s*\d{2,4}[A-Z]{0,2}"
GRADE = r"(?:A\*|[A-F][+-]?|S|U|P|NP|I|W)"
VARIANT = re.compile(
    r"\b(BTH|BTM|BT|B\.?\s*Tech(?:\s+Honours|\s+Honors)?|dual[- ]degree|double[- ]major|minor|management track)\b",
    re.I,
)
FIELDS = {
    "institution": ("ENROLLED_AT", "identity.institution"),
    "programme": ("PURSUING_PROGRAMME", "identity.degree"),
    "department": ("BELONGS_TO_DEPARTMENT", "identity.branch"),
    "year_of_study": ("ACADEMIC_YEAR", "identity.academic_year"),
    "name": ("LEARNER_NAME", "identity.name"),
    "cpi": ("DOCUMENTED_CPI", ""),
    "current_semester": ("CURRENT_SEMESTER", ""),
    "current_courses": ("CURRENT_COURSE", "academic_profile.current_courses"),
    "completed_courses": ("HAS_COMPLETED_COURSE", "academic_profile.completed_courses"),
    "explanation_depth": ("HAS_PREFERENCE", "learning_preferences.explanation_depth"),
    "study_language": ("HAS_PREFERENCE", "learning_preferences.language_preferences"),
    "short_term_goals": ("HAS_GOAL", "goals.short_term"),
    "career_goals": ("HAS_GOAL", "goals.long_term"),
    "project_interests": ("INTERESTED_IN", "interests.technical"),
    "study_routine": ("HAS_PREFERENCE", "behavioral_patterns.study_routines"),
    "learning_constraints": ("HAS_CONSTRAINT", "constraints.other_constraints"),
    "study_hours": ("HAS_CONSTRAINT", "constraints.time_constraints"),
    "preferred_learning_resources": ("HAS_PREFERENCE", "learning_preferences.preferred_learning_style"),
}
ALIASES = {
    "college": "institution",
    "university": "institution",
    "institute": "institution",
    "institution_name": "institution",
    "program": "programme",
    "degree": "programme",
    "branch": "department",
    "academic_year": "year_of_study",
    "current_cpi": "cpi",
    "semester": "current_semester",
    "preferred_explanation_depth": "explanation_depth",
    "preferred_study_language": "study_language",
    "available_study_hours": "study_hours",
    "student_name": "name",
}


class Entry(BaseModel):
    field: str
    value: dict
    relation: str
    locator: str
    excerpt: str
    provenance: str
    status: str
    subject: str = "Learner"


def key(k):
    return re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")


def mapping(k):
    k = ALIASES.get(key(k), key(k))
    if k.startswith("goal_") and k != "goal_stability":
        return "HAS_GOAL", "goals.long_term"
    if k.startswith("skill_") or k.endswith("_skill_level"):
        return "HAS_REPORTED_SKILL_LEVEL", ""
    return FIELDS.get(k, ("SURVEY_FIELD", ""))


def entry(k, v, loc, prov, status, rel=None, subject="Learner", excerpt=None, **meta):
    return Entry(
        field=k,
        value={"raw": v, **meta},
        relation=rel or mapping(k)[0],
        locator=loc,
        excerpt=excerpt or f"{k}: {v}",
        provenance=prov,
        status=status,
        subject=subject,
    )


def survey(raw):
    obj = json.loads(
        raw.decode("utf-8-sig"),
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON number")),
    )
    if not isinstance(obj, dict) or not obj:
        raise ValueError("Expected a nonempty JSON object")
    metadata = obj.get("data_provenance", {})
    provenance = json.dumps(metadata, ensure_ascii=False).lower()
    labels = {}

    def label(text):
        for pattern, name in [
            (r"synthetic|demo", "synthetic"),
            (r"unverified", "unverified"),
            (r"transcript|academic record", "transcript_derived_unverified"),
            (r"self.report", "self_reported"),
        ]:
            if re.search(pattern, text, re.I):
                return name
        return None

    def collect(value, parents=()):
        if isinstance(value, dict):
            for k, v in value.items():
                collect(v, (*parents, str(k)))
        elif isinstance(value, list):
            for v in value:
                collect(v, parents)
        elif isinstance(value, str):
            parent = " ".join(parents)
            if (classification := label(parent)) and len(value) < 180:
                labels[key(value)] = classification
            elif (classification := label(value)) and parents:
                labels[key(parents[0])] = classification

    collect(metadata)
    rows = []

    def visit(node, path, field, depth):
        if depth > 16 or len(rows) >= 4000:
            raise ValueError("Survey exceeds nesting or field limit")
        if isinstance(node, dict) and node:
            for k, v in node.items():
                if k in ("data_provenance", "evidence"):
                    continue
                visit(v, path + "/" + k.replace("~", "~0").replace("/", "~1"), k, depth + 1)
        elif isinstance(node, list) and node:
            for i, v in enumerate(node):
                visit(v, path + "/" + str(i), field, depth + 1)
        else:
            k = ALIASES.get(key(field), key(field))
            if k in {"roll_number", "respondent_id", "roll_no", "student_id"}:
                rel = "IDENTIFIER"
            else:
                rel = mapping(k)[0]
            # Mixed-provenance exports are quarantined conservatively until individual confirmation.
            prov = (
                "synthetic_or_unverified"
                if re.search("synthetic|unverified|demo", provenance)
                else "transcript_derived_unverified"
                if path.startswith("/academic_record/")
                else "imported_survey"
            )
            prov = labels.get(key(path), labels.get(key(field), prov))
            meaning = (
                "missing"
                if node is None or node == ""
                else "not_applicable"
                if str(node).lower() in ("n/a", "not applicable")
                else "unknown"
                if str(node).lower() == "unknown"
                else "not_selected"
                if node is False and k.startswith("goal_")
                else "yes"
                if node is True
                else "no"
                if node is False
                else "provided"
            )
            rows.append(
                entry(k, node, path, prov, "review", rel, meaning=meaning, datatype=type(node).__name__)
            )

    visit(obj, "", "", 0)
    return rows


def variant(value):
    text = value.upper()
    if "HON" in text or text == "BTH":
        return "BTH"
    if "MANAGEMENT" in text or text == "BTM":
        return "BTM"
    return (
        "BT"
        if text in {"BT", "B.TECH", "BTECH", "B TECH", "BACHELOR OF TECHNOLOGY"}
        else text.replace("-", " ")
    )


def code(v):
    return re.sub(r"\s+", "", v.upper())


def classify(text):
    if re.search(r"\b(transcript|grade sheet|academic record|grade report)\b", text, re.I):
        return "academic_transcript"
    if re.search(r"\b(curriculum|programme template|program template)\b", text, re.I):
        return "curriculum_template"
    if re.search(r"\b(notice|deadline|is due|examination schedule)\b", text, re.I):
        return "academic_notice"
    return "general_academic_document" if text.strip() else "unknown"


def parse_pdf(raw, requested, ocr=False):
    import pymupdf

    pages, rows, warnings = [], [], []
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        if pdf.needs_pass or len(pdf) > 150:
            raise ValueError("Encrypted PDF or page limit exceeded")
        for page in pdf:
            txt = page.get_text("text", sort=True)
            scanned = len(txt.strip()) < 12
            if scanned and ocr:
                try:
                    txt = page.get_text(textpage=page.get_textpage_ocr(full=True))
                except Exception:
                    warnings.append(f"Page {page.number + 1}: local OCR unavailable")
            if scanned:
                warnings.append(f"Page {page.number + 1}: scanned or sparse page; review required")
            if len(txt) > 150000:
                raise ValueError("Page exceeds text limit")
            pages.append({"page": page.number + 1, "text": txt, "review": scanned})
        kind = (
            requested
            if requested not in ("auto", "unknown")
            else classify("\n".join(p["text"] for p in pages[:2]))
        )
        sem = session = programme = department = ""
        current = False

        def emit(k, v, rel=None, subject="Learner", **meta):
            rows.append(
                entry(
                    k,
                    v,
                    loc,
                    kind,
                    state,
                    rel,
                    subject,
                    line,
                    page=num,
                    semester=sem,
                    session=session,
                    programme=programme,
                    department=department,
                    **meta,
                )
            )

        for page, info in zip(pdf, pages, strict=True):
            num = info["page"]
            text = info["text"]
            state = "review" if info["review"] else "active"
            lines = text.splitlines()
            # PyMuPDF returns isolated table rows with cells in printed order.
            tables = []
            if kind in ("academic_transcript", "curriculum_template"):
                try:
                    tables = page.find_tables().tables
                except Exception:
                    warnings.append(f"Page {num}: table boundaries unavailable")
            if tables:
                # Replace each ruled table at its printed Y coordinate, preserving surrounding headings.
                events = []
                for block in page.get_text("dict")["blocks"]:
                    for printed in block.get("lines", []):
                        x0, y0, x1, y1 = printed["bbox"]
                        inside = any(
                            t.bbox[0] - 1 <= (x0 + x1) / 2 <= t.bbox[2] + 1
                            and t.bbox[1] - 1 <= (y0 + y1) / 2 <= t.bbox[3] + 1
                            for t in tables
                        )
                        if not inside:
                            events.append((y0, x0, [" ".join(v["text"] for v in printed["spans"])]))
                for table in tables:
                    matrix = table.extract()
                    headers = [str(c or "").lower() for c in matrix[0]] if matrix else []
                    column_terms = [re.search(r"(?:semester|sem)\s*(\d+)", h) for h in headers]
                    printed = []
                    if kind == "curriculum_template" and sum(bool(v) for v in column_terms) > 1:
                        for col, m in enumerate(column_terms):
                            if m:
                                printed.append("Semester " + m[1])
                                for cells in matrix[1:]:
                                    if col < len(cells) and cells[col]:
                                        printed.extend(cells[col].splitlines())
                    else:
                        for cells in matrix:
                            printed.append(" ".join(" ".join((v or "").split()) for v in cells).strip())
                    events.append((table.bbox[1], table.bbox[0], printed))
                lines = [
                    v for _, __, values in sorted(events, key=lambda x: (x[0], x[1])) for v in values
                ]
            for n, original in enumerate(lines):
                line = " ".join(original.split())
                if not line:
                    continue
                loc = f"page {num}, row {n + 1}"

                m = re.match(r"^(?:academic )?(?:semester|term)\s*[:#-]?\s*(\d+|[IVX]+)\b", line, re.I)
                if m:
                    sem = m[1]
                    current = False
                m = re.search(r"\b(20\d\d[-/]\d{2,4})\b", line)
                if m:
                    session = m[1]
                if kind == "academic_transcript":
                    if re.match(r"^current courses?", line, re.I):
                        current = True
                    if current and "NO DATA FOUND" in line.upper():
                        emit(
                            "current_courses_status", "unknown_or_not_available", "CURRENT_COURSE_STATUS"
                        )
                        continue
                    if (
                        current
                        and (record := re.fullmatch(rf"({COURSE})\s+(.+?)\s+(\d+(?:\.\d+)?)", line))
                        and not re.search(rf"\s{GRADE}$", record[2])
                    ):
                        emit(
                            "current_courses",
                            code(record[1]),
                            "CURRENT_COURSE",
                            title=record[2],
                            credits=float(record[3]),
                        )
                        continue
                    m = re.match(
                        r"^(institution|institute|university|programme|program|degree|department|student name|current cpi|cpi|spi)\s*[:=]\s*(.+)$",
                        line,
                        re.I,
                    )
                    if m:
                        k = ALIASES.get(key(m[1]), key(m[1]))
                        v = m[2].strip()
                        if k in ("cpi", "spi") and not re.fullmatch(
                            r"(?:10(?:\.0+)?|[0-9](?:\.\d+)?)", v
                        ):
                            warnings.append(f"{loc}: check performance value")
                            continue
                        emit(k, v, "DOCUMENTED_SPI" if k == "spi" else None)
                        continue
                    if re.fullmatch(
                        r"(?:Indian Institute of Technology[ ,]+[A-Za-z ]+|[A-Za-z ]+ University)",
                        line,
                        re.I,
                    ):
                        emit("institution", line)
                        continue
                    m = re.fullmatch(rf"({COURSE})\s+(.+?)\s+({GRADE})\s+(\d+(?:\.\d+)?)", line)
                    rev = re.fullmatch(rf"({COURSE})\s+(.+?)\s+(\d+(?:\.\d+)?)\s+({GRADE})", line)
                    if m or rev:
                        rec = m or rev
                        cc = code(rec[1])
                        grade = rec[3] if m else rec[4]
                        credits = float(rec[4] if m else rec[3])
                        if re.search(COURSE, rec[2]):
                            warnings.append(f"{loc}: multiple course codes; review layout")
                            continue
                        attempt = f"Attempt:{cc}:{session}:{sem}"
                        rel = (
                            "CURRENT_COURSE"
                            if current
                            else "COURSE_ATTEMPT"
                            if grade in ("F", "U", "NP", "W", "I")
                            else "HAS_COMPLETED_COURSE"
                        )
                        emit(
                            "current_courses"
                            if current
                            else "completed_courses"
                            if rel == "HAS_COMPLETED_COURSE"
                            else "course_attempt",
                            cc,
                            rel,
                            title=rec[2],
                            printed=rec[1],
                            grade=grade,
                            credits=credits,
                        )
                        emit("grade", grade, "HAS_DOCUMENTED_GRADE", attempt, course=cc)
                        continue
                    if re.search(COURSE, line):
                        warnings.append(f"{loc}: unrecognized course row; review the source page")
                if kind == "curriculum_template":
                    v = VARIANT.search(line)
                    dept = re.search(r"(?:department\s*:\s*|^)([\w ]+ Engineering)\b", line, re.I)
                    if dept and not re.search(COURSE, line):
                        department = dept[1].strip()
                    if v and not re.search(COURSE, line):
                        variants = {variant(m[1]) for m in VARIANT.finditer(line)}
                        programme = variants.pop() if len(variants) == 1 else ""
                        sem = ""
                        continue
                    cc = re.findall(COURSE, line)
                    if cc:
                        cc = list(map(code, cc))
                        sub = f"Programme:{programme or 'unspecified'}:{department}"
                        if len(cc) > 1 and re.search(r"prerequisit|equivalen", line, re.I):
                            for other in cc[1:]:
                                emit(
                                    "curriculum_rule",
                                    other,
                                    "HAS_PREREQUISITE"
                                    if "prerequis" in line.lower()
                                    else "EQUIVALENT_TO",
                                    "Course:" + cc[0],
                                )
                        elif len(cc) == 1:
                            credits = re.search(r"(\d+(?:\.\d+)?)\s*(?:credits?)?$", line, re.I)
                            emit(
                                "curriculum_course",
                                cc[0],
                                "HAS_CURRICULUM_COURSE",
                                sub,
                                credits=float(credits[1]) if credits else None,
                            )
                        else:
                            warnings.append(f"{loc}: multi-column course list needs review")
                    elif re.search(r"require|elective|condition", line, re.I):
                        emit(
                            "requirement",
                            line,
                            "HAS_REQUIREMENT",
                            f"Programme:{programme or 'unspecified'}",
                        )
                if kind in ("academic_notice", "general_academic_document"):
                    emit("passage", line[:2200], "PASSAGE", "Document")
            if len(rows) > 15000:
                raise ValueError("Too many extracted rows")
    return kind, pages, rows, warnings
