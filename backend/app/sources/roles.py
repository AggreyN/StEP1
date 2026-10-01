"""Canonical role taxonomy + title classification.

Why this exists: the source lists' own `category` field is both too coarse and
too unstable to drive matching. Simplify ships five values (AI/ML/Data,
Software, Hardware, Product, Quant) under two different spellings, and
vanshb03 ships none at all. Meanwhile the roles a student actually wants to
filter on -- solutions architect, TPM, security, IT, cloud/infra, UX -- are
all flattened into "Software" or dropped.

So: classify off the TITLE, which every source has, and keep the source's
category only as a fallback.

Rules are ordered. First match wins, and a title may match in more than one
family (a "Security Software Engineer Intern" is both SECURITY and SOFTWARE),
so `classify()` returns a list, most specific first. Specific families are
listed before general ones for exactly that reason.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# Canonical roles
# --------------------------------------------------------------------------- #
QUANT = "quant"
AI_ML_DATA = "ai_ml_data"
DATA_ANALYTICS = "data_analytics"
SECURITY = "security"
INFRA_DEVOPS = "infra_devops"
SOLUTIONS = "solutions_architecture"
PRODUCT = "product_management"
PROGRAM = "program_management"
DESIGN_UX = "design_ux"
IT_SUPPORT = "it_support"
TECH_CONSULTING = "tech_consulting"
HARDWARE = "hardware"
RESEARCH = "research"
SOFTWARE = "software"
OTHER = "other"

ROLE_LABELS = {
    SOFTWARE: "Software Engineering",
    AI_ML_DATA: "AI / ML / Data Science",
    DATA_ANALYTICS: "Data & Business Analytics",
    HARDWARE: "Hardware & Embedded",
    QUANT: "Quantitative Finance",
    PRODUCT: "Product Management",
    PROGRAM: "Technical Program Management",
    SOLUTIONS: "Solutions & Sales Engineering",
    SECURITY: "Security",
    INFRA_DEVOPS: "Cloud, Infra & DevOps",
    DESIGN_UX: "Design & UX",
    IT_SUPPORT: "IT & Systems",
    TECH_CONSULTING: "Technology Consulting",
    RESEARCH: "Research",
    OTHER: "Other",
}

# --------------------------------------------------------------------------- #
# Ordered rules: (role, compiled pattern)
#
# Ordering is the whole design. Narrow families first so that e.g. "Quant
# Developer" lands in QUANT rather than SOFTWARE, and "ML Infrastructure
# Engineer" picks up AI_ML_DATA before INFRA_DEVOPS.
# --------------------------------------------------------------------------- #
_RULES: list[tuple[str, str]] = [
    (QUANT, r"\bquant(itative)?\b|\btrading\b|\btrader\b|\bmarket\s*mak|"
            r"\bportfolio\s+(research|manage)|\bsystematic\s+(trading|strateg)|"
            r"\binvestment\s+analy|\bfundamental\s+research\b"),

    (AI_ML_DATA, r"\bml\b|\bmachine\s+learning\b|\bdeep\s+learning\b|\bai\b|"
                 r"\bartificial\s+intelligence\b|\bdata\s+scien|\bdata\s+engineer|"
                 r"\bnlp\b|\bcomputer\s+vision\b|\bllm\b|\bgen(erative)?\s*ai\b|"
                 r"\brecommend|\bapplied\s+scien|\bresearch\s+scien|"
                 r"\binference\b|\bsupercomput|\bhpc\b|\bhigh\s+performance\s+comput"),

    (SECURITY, r"\bsecurity\b|\bcyber|\binfosec\b|\bappsec\b|\bpen(etration)?\s*test|"
               r"\bthreat\b|\bvulnerab|\bcryptograph|\bgrc\b|\btrust\s*(and|&)\s*safety\b"),

    (INFRA_DEVOPS, r"\bdevops\b|\bsre\b|\bsite\s+reliability\b|\bplatform\s+engineer|"
                   r"\binfrastructure\b|\bcloud\b|\bkubernetes\b|\bnetwork\s+engineer|"
                   r"\bobservability\b|\bdeveloper\s+(experience|productivity)\b"),

    (SOLUTIONS, r"\bsolutions?\s+(architect|engineer|consult|special)|"
                r"\bsales\s+engineer|\bpre[\s-]?sales\b|\bcustomer\s+engineer|"
                r"\bforward\s+deployed\b|\bimplementation\s+(engineer|consult)|"
                r"\btechnical\s+account\s+manage|\bfield\s+engineer|"
                r"\bpartner\s+engineer|\bdeveloper\s+(advocate|relations)\b"),

    (PROGRAM, r"\btechnical\s+program\s+manage|\btpm\b|\bprogram\s+manage|"
              r"\bproject\s+manage|\bscrum\b|\bagile\s+coach|\bchief\s+of\s+staff\b"),

    (PRODUCT, r"\bproduct\s+manage|\bproduct\s+manager\b|\bapm\b|\bpm\s+intern\b|"
              r"\bproduct\s+owner\b|\bproduct\s+strateg|\bproduct\s+analy|"
              r"\bproduct\s+operations\b|\bgrowth\s+product\b|\btechnical\s+product\b"),

    (DESIGN_UX, r"\bux\b|\bui\s*/?\s*ux\b|\buser\s+experience\b|\buser\s+research\b|"
                r"\bproduct\s+design|\binteraction\s+design|\bvisual\s+design|"
                r"\bdesign\s+research"),

    (TECH_CONSULTING, r"\btechnology\s+consult|\btech(nical)?\s+consult|"
                      r"\bbusiness\s+technology\b|\bdigital\s+(transformation|strateg)|"
                      r"\bmanagement\s+consult|\btechnology\s+(analyst|advisory)\b"),

    (IT_SUPPORT, r"\bit\s+(intern|support|operations|services|analyst|audit)|"
                 r"\binformation\s+technology\b|\bsystems?\s+admin|\bhelp\s*desk\b|"
                 r"\bend\s+user\s+comput|\bservice\s+desk\b|\berp\b|\bsalesforce\b|"
                 r"\bsap\b|\bworkday\b|\bidentity\s+(and|&)\s+access\b"),

    (DATA_ANALYTICS, r"\bdata\s+analy|\bbusiness\s+intelligence\b|\bbi\s+(analyst|develop)|"
                     r"\banalytics\b|\bbusiness\s+analy|\breporting\s+analy|"
                     r"\bdata\s+(governance|quality|management)\b|\btableau\b|\bpower\s*bi\b|"
                     r"\binsights?\s+analy|\bdecision\s+scien"),

    (HARDWARE, r"\bhardware\b|\bfirmware\b|\bembedded\b|\basic\b|\bfpga\b|\bvlsi\b|"
               r"\bsilicon\b|\banalog\b|\bmixed[\s-]?signal\b|\brf\b|\bpcb\b|"
               r"\belectrical\s+engineer|\bmechanical\s+engineer|\brobotic|"
               r"\bsignal\s+(integrity|process)|\bthermal\b|\bcircuit\b|"
               r"\bdesign\s+verification\b|\bphysical\s+design\b"),

    (RESEARCH, r"\bresearch\s+(intern|assistant|engineer)\b|\bphd\s+(intern|research)\b|"
               r"\br\s*&\s*d\b|\bresearch\s+(and|&)\s+development\b"),

    (SOFTWARE, r"\bsoftware\b|\bswe\b|\bfull[\s-]?stack\b|\bfront[\s-]?end\b|"
               r"\bback[\s-]?end\b|\bmobile\b|\bios\b|\bandroid\b|\bweb\s+develop|"
               r"\bapplication\s+develop|\bgame\s+develop|\bqa\b|\bquality\s+assurance\b|"
               r"\bautomation\s+engineer|\bcompiler\b|\bdistributed\s+systems\b|"
               r"\bmember\s+of\s+technical\s+staff\b|\bmts\b|"
               r"\bdeveloper\b|\bprogrammer\b|\bengineer(ing)?\b"),
]

_COMPILED = [(role, re.compile(pat, re.I)) for role, pat in _RULES]

# Source `category` values, both spellings, as the fallback when no title rule
# fires. Deliberately coarse -- this is the safety net, not the mechanism.
_CATEGORY_FALLBACK = {
    "software": SOFTWARE,
    "software engineering": SOFTWARE,
    "ai/ml/data": AI_ML_DATA,
    "data science, ai & machine learning": AI_ML_DATA,
    "hardware": HARDWARE,
    "hardware engineering": HARDWARE,
    "product": PRODUCT,
    "product management": PRODUCT,
    "quant": QUANT,
    "quantitative finance": QUANT,
    # The jobright.ai lists, one per field; the list says which.
    "data analysis": DATA_ANALYTICS,
    "business analyst": DATA_ANALYTICS,
}


def classify(title: str, category: str | None = None) -> list[str]:
    """Return canonical roles for a posting, most specific first.

    Always returns at least one element; falls back to the source category,
    then to OTHER.
    """
    hits: list[str] = []
    for role, pat in _COMPILED:
        if pat.search(title) and role not in hits:
            hits.append(role)
    if hits:
        return hits[:3]
    if category:
        fallback = _CATEGORY_FALLBACK.get(category.strip().lower())
        if fallback:
            return [fallback]
    return [OTHER]
