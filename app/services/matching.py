"""Evidence-based matching. Reviewed aliases never conflate related technologies."""
import re

from app.core.errors import DomainError
from app.schemas.ai import SourceSpan, SkillRequirement, EvidenceStatement, StructuredJD

PIPELINE = "studio-v1"
ALIASES = {
    "Python": ("python",), "JavaScript": ("javascript", "js"), "TypeScript": ("typescript", "ts"),
    "Java": ("java",), "React Native": ("react native",), "React": ("react", "react.js", "reactjs"),
    "SQL": ("sql",), "PostgreSQL": ("postgresql", "postgres"), "MySQL": ("mysql",), "SQLite": ("sqlite",),
    "FastAPI": ("fastapi",), "Django": ("django",), "Flask": ("flask",), "Node.js": ("node.js", "nodejs"),
    "HTML": ("html", "html5"), "CSS": ("css", "css3"), "Git": ("git",), "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"), "AWS": ("aws", "amazon web services"), "Azure": ("azure",),
    "GCP": ("gcp", "google cloud"), "C++": ("c++",), "C#": ("c#",), "Go": ("golang", "go language"),
    "Rust": ("rust",), "Ruby": ("ruby",), "PHP": ("php",), "Swift": ("swift",), "Kotlin": ("kotlin",),
    "REST": ("rest", "restful"), "GraphQL": ("graphql",), "Redis": ("redis",), "MongoDB": ("mongodb",),
    "Linux": ("linux",), "Pandas": ("pandas",), "NumPy": ("numpy",), "TensorFlow": ("tensorflow",),
    "PyTorch": ("pytorch",), "scikit-learn": ("scikit-learn", "sklearn"), "Excel": ("excel",),
    "Power BI": ("power bi", "powerbi"), "Tableau": ("tableau",), "Spark": ("spark", "pyspark"),
    "RAG": ("rag", "retrieval-augmented generation", "retrieval augmented generation"),
    "LLMs": ("llms", "llm", "large language models"), "Agentic AI": ("agentic ai", "agentic workflows"),
    "Generative AI": ("generative ai", "gen ai"), "Machine Learning": ("machine learning", "ai/ml"),
    "DSA": ("dsa", "data structures & algorithms", "data structures and algorithms"),
    "System Design": ("system design",), "API integration": ("api integration",),
}


def phrase_pattern(value):
    return re.compile(r"(?<![\w+#])" + re.escape(value) + r"(?![\w+#])", re.I)


def skills_in(text):
    found, occupied = {}, []
    pairs = sorted(((name, alias) for name, aliases in ALIASES.items() for alias in aliases), key=lambda p: -len(p[1]))
    for name, alias in pairs:
        for match in phrase_pattern(alias).finditer(text):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            found.setdefault(name, match.span())
            occupied.append(match.span())
    return found


def affirmed_skills(text):
    found=skills_in(text)
    result={}
    for name,(start,end) in found.items():
        prefix=re.split(r'[.;\n]',text[:start])[-1][-65:].casefold()
        suffix=text[end:end+35].casefold()
        if re.search(r'\b(?:not|no|never|without|lack|lacking)\b',prefix) or re.match(r'\s+(?:is )?(?:not|never)\b',suffix):
            continue
        result[name]=(start,end)
    return result


def source_span(text, start, end):
    return SourceSpan(page=None, start_offset=start, end_offset=end, source_text=text[start:end])


def analyse_jd(text, title, employer):
    if not text.strip() or len(text) > 48000:
        raise DomainError("JD_TEXT_LIMIT", "The stored JD is empty or exceeds the analysis limit.", 422)
    required, preferred, responsibilities, eligibility, uncertainties = {}, {}, [], [], []
    section, offset = "unknown", 0
    for raw in text.splitlines(keepends=True):
        line = raw.strip()
        start = offset + len(raw) - len(raw.lstrip())
        offset += len(raw)
        if not line:
            continue
        lower = line.casefold().strip(': ')
        if len(line) < 70 and re.fullmatch(r"(?:minimum |basic |required |preferred )?(?:requirements|qualifications|skills|technical skills|what you.bring)", lower):
            section = "preferred" if "preferred" in lower else "required"
            continue
        if lower in ("preferred", "nice to have", "nice-to-have", "bonus", "preferred qualifications"):
            section = "preferred"; continue
        if re.fullmatch(r"(?:key |your )?(?:responsibilities|what you.ll do|duties)", lower):
            section = "responsibilities"; continue
        if lower in ("about the role", "about us", "benefits", "why join us", "why drivetrain.ai?"):
            section = "unknown"; continue
        if re.search(r"ignore.{0,35}(?:instruction|rule)|system prompt|pretend|invent|disregard", lower):
            uncertainties.append("Instruction-like JD content was excluded from requirements; it has no authority over the application.")
            continue
        if section == "responsibilities":
            responsibilities.append(EvidenceStatement(text=line, source_span=source_span(text,start,start+len(line))))
            continue
        # Sentence/contrast boundaries keep 'preferred projects' from reclassifying a preceding required skill.
        for clause in re.finditer(r'.+?(?:(?<=[.!?;])\s+|\s+but\s+|$)',line,re.I):
            value=clause.group().strip()
            value_start=start+clause.start()
            folded=value.casefold()
            if not value: continue
            span=source_span(text,value_start,value_start+len(value))
            if re.search(r"(?:degree|bachelor|master|years? of|work authori[sz]|visa|eligible|currently pursuing|graduat)",folded):
                eligibility.append(EvidenceStatement(text=value,source_span=span))
            if re.search(r"\b(?:not required|no .*required|optional)\b",folded):
                uncertainties.append("An optional/negated skill statement was excluded from required coverage.")
                continue
            target=None
            if re.search(r"\b(?:preferred|nice.to.have|bonus)\b",folded):target=preferred
            elif re.search(r"\b(?:must|required|proficien(?:t|cy)|strong (?:knowledge|understanding)|experience (?:in|with))\b",folded):target=required
            elif section in ('required','preferred'):target=required if section=='required' else preferred
            if target is None:continue
            found=skills_in(value)
            for name,(left,right) in found.items():
                target.setdefault(name,SkillRequirement(canonical_name=name,verbatim_text=value[left:right],
                    source_span=source_span(text,value_start+left,value_start+right)))
            if not found and not re.search(r"degree|years?|communication|problem.solving|academic|portfolio|team|passion",folded):
                uncertainties.append("A qualification could not be safely reduced to a reviewed technical skill: "+value)
    for name in required:
        preferred.pop(name, None)
    uncertainties.append("Automatic skill extraction uses a reviewed vocabulary. Unclassified qualifications remain visible in the full JD; coverage is not an eligibility or ATS score.")
    return StructuredJD(title=title, employer=employer, required_skills=list(required.values()),
        preferred_skills=list(preferred.values()), responsibilities=responsibilities, eligibility=eligibility,
        uncertainties=list(dict.fromkeys(uncertainties)))


def assess(facts, structured):
    def matches(requirements):
        result = []
        for requirement in requirements:
            name = requirement.canonical_name
            supporting = [f for f in facts if f['kind'] not in ('name', 'email', 'phone', 'links') and name in affirmed_skills(f['text'])]
            result.append({'skill': name, 'status': 'supported' if supporting else 'not_evidenced',
                'source_fact_ids': [f['id'] for f in supporting], 'evidence_kinds': sorted({f['kind'] for f in supporting})})
        return result
    required, preferred = matches(structured.required_skills), matches(structured.preferred_skills)
    count = sum(r['status'] == 'supported' for r in required)
    return {'required': required, 'preferred': preferred, 'coverage': round(100 * count / len(required), 1) if required else None,
        'reason': None if required else 'no_explicit_required_skills',
        'eligibility': [e.text + ' — Not assessed; compare with your confirmed facts. Project evidence does not establish professional experience.' for e in structured.eligibility],
        'scope': 'Coverage of extracted explicit technical skills only. Unclassified requirements require review. This is not an ATS pass or hiring probability.'}


def role_tokens(title):
    aliases = {'developer': 'engineer', 'development': 'engineer', 'engineering': 'engineer', 'internship': 'intern'}
    tokens = [aliases.get(t, t) for t in re.findall(r'[a-z0-9]+', title.casefold())]
    return [t for t in tokens if t not in ('the', 'a', 'an', 'junior') and not (t == 'software' and 'engineer' in tokens)]


def role_matches(preferred, title):
    tokens = role_tokens(title)
    return all(token in tokens for token in role_tokens(preferred))


def role_warning(title, facts):
    technical = any(t in role_tokens(title) for t in ('engineer', 'python', 'data', 'frontend', 'backend'))
    supported = set().union(*(affirmed_skills(f['text']) for f in facts if f['kind'] not in ('name','email','phone','links')))
    if technical and not supported:
        return 'The requested role has little explicit technical evidence in this profile. This is advisory: continue with your chosen role or change it.'
    return None
