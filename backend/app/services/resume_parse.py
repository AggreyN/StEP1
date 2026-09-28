"""Resume text extraction and skill matching. No LLM, no OCR.

`extract_text()` reads the PDF's text layer with PyMuPDF. `find_skills()`
matches text against a curated vocabulary of ~200 terms.

The same matcher reads posting titles in services/matching.py, so "you have
this skill" and "this posting asks for it" are decided by one rule.

Matching is on tokens, not substrings: "Java" does not fire on "JavaScript",
and "C++", "C#", ".NET" and "Node.js" survive as tokens. A few names are also
ordinary English words or initials (C, R, Go, Excel, SAS, REST); those match
case-sensitively only. Words too ambiguous to be worth it are deliberately
absent — "Spring" (a term), "Julia" (a name), "Shell" and "Express"
(companies), "Assembly" (a job) — and appear only in their unambiguous forms.
"""

from __future__ import annotations

import re

from app import config

# --------------------------------------------------------------------------- #
# The vocabulary. canonical name -> aliases. Keep it curated: every entry is
# something a student would list under "Skills" and a posting would ask for.
# --------------------------------------------------------------------------- #
SKILLS: dict[str, tuple[str, ...]] = {
    # --- Languages ---
    "Python": (),
    "Java": (),
    "JavaScript": ("JS", "ECMAScript"),
    # No "TS" alias: around DC it far more often means TS/SCI clearance.
    "TypeScript": (),
    "C": (),
    "C++": ("CPP",),
    "C#": ("CSharp",),
    "Go": ("Golang",),
    "Rust": (),
    "Swift": (),
    "Kotlin": (),
    "Scala": (),
    "Ruby": (),
    "PHP": (),
    "Perl": (),
    "R": (),
    "MATLAB": (),
    "Dart": (),
    "Lua": (),
    "Haskell": (),
    "OCaml": (),
    "Elixir": (),
    "Clojure": (),
    "Objective-C": (),
    "Bash": ("Shell Scripting", "Shell Script", "Zsh"),
    "PowerShell": (),
    "SQL": (),
    "PL/SQL": (),
    "T-SQL": (),
    "HTML": ("HTML5",),
    "CSS": ("CSS3",),
    "Sass": ("SCSS",),
    "Solidity": (),
    "VBA": (),
    "COBOL": (),
    "Fortran": (),
    # --- Frontend ---
    "React": ("React.js", "ReactJS"),
    "React Native": (),
    "Next.js": ("NextJS",),
    "Vue": ("Vue.js", "VueJS"),
    "Nuxt": ("Nuxt.js",),
    "Angular": ("AngularJS",),
    "Svelte": (),
    "Redux": (),
    "jQuery": (),
    "Tailwind": ("Tailwind CSS", "TailwindCSS"),
    "Bootstrap": (),
    "Webpack": (),
    "Vite": (),
    "Three.js": (),
    "D3.js": ("D3",),
    # --- Backend / frameworks ---
    "Node.js": ("NodeJS",),
    "Express.js": ("ExpressJS",),
    "NestJS": (),
    "Django": (),
    "Flask": (),
    "FastAPI": (),
    "Spring Boot": ("Spring Framework", "Spring MVC"),
    "Ruby on Rails": ("Rails",),
    "Laravel": (),
    ".NET": ("ASP.NET", "DotNet", ".NET Core"),
    "GraphQL": (),
    "REST": ("REST API", "REST APIs", "RESTful", "RESTful API", "RESTful APIs"),
    "gRPC": (),
    "WebSockets": ("WebSocket",),
    "Microservices": (),
    "OAuth": ("OAuth2",),
    # --- Mobile ---
    "iOS": (),
    "Android": (),
    "SwiftUI": (),
    "Flutter": (),
    "Xcode": (),
    # --- Data stores ---
    "PostgreSQL": ("Postgres",),
    "MySQL": (),
    "SQLite": (),
    "SQL Server": ("MSSQL",),
    "Oracle": ("Oracle Database",),
    "MongoDB": ("Mongo",),
    "Redis": (),
    "Elasticsearch": (),
    "DynamoDB": (),
    "Cassandra": (),
    "Neo4j": (),
    "Firebase": ("Firestore",),
    "Supabase": (),
    "NoSQL": (),
    # --- Data engineering / analytics ---
    "Snowflake": (),
    "BigQuery": (),
    "Redshift": (),
    "Databricks": (),
    "Spark": ("Apache Spark", "PySpark"),
    "Hadoop": (),
    "Kafka": ("Apache Kafka",),
    "Airflow": ("Apache Airflow",),
    "dbt": (),
    "ETL": ("ELT",),
    "Data Warehousing": ("Data Warehouse",),
    "Data Modeling": ("Data Modelling",),
    "Tableau": (),
    "Power BI": ("PowerBI",),
    "Looker": (),
    "Excel": ("Microsoft Excel",),
    "Google Sheets": (),
    "SAS": (),
    "SPSS": (),
    "Stata": (),
    "Alteryx": (),
    "Data Analysis": ("Data Analytics",),
    "Data Visualization": (),
    "Statistics": ("Statistical Analysis", "Statistical Modeling"),
    "A/B Testing": (),
    # --- ML / AI ---
    "Machine Learning": (),
    "Deep Learning": (),
    "Natural Language Processing": ("NLP",),
    "Computer Vision": (),
    "Reinforcement Learning": (),
    "Generative AI": ("GenAI",),
    "LLMs": ("LLM", "Large Language Models"),
    "RAG": (),
    "PyTorch": (),
    "TensorFlow": (),
    "Keras": (),
    "scikit-learn": ("sklearn",),
    "XGBoost": (),
    "pandas": (),
    "NumPy": (),
    "SciPy": (),
    "Matplotlib": (),
    "Seaborn": (),
    "Plotly": (),
    "Jupyter": (),
    "OpenCV": (),
    "Hugging Face": ("HuggingFace",),
    "LangChain": (),
    "MLflow": (),
    "CUDA": (),
    "MLOps": (),
    # --- Cloud / infra ---
    "AWS": ("Amazon Web Services",),
    "Azure": ("Microsoft Azure",),
    "Google Cloud": ("GCP", "Google Cloud Platform"),
    "EC2": (),
    "S3": (),
    "Lambda": ("AWS Lambda",),
    "ECS": (),
    "CloudFormation": (),
    "Docker": (),
    "Kubernetes": ("K8s",),
    "Helm": (),
    "Terraform": (),
    "Ansible": (),
    "Jenkins": (),
    "GitHub Actions": (),
    "GitLab CI": (),
    "CI/CD": (),
    "Linux": ("Unix",),
    "Nginx": (),
    "Prometheus": (),
    "Grafana": (),
    "Datadog": (),
    "Splunk": (),
    "Serverless": (),
    # --- Tools / practices ---
    "Git": (),
    "GitHub": (),
    "GitLab": (),
    "Jira": (),
    "Confluence": (),
    "Agile": (),
    "Scrum": (),
    "Unit Testing": ("TDD", "Test Driven Development"),
    "Selenium": (),
    "Cypress": (),
    "Playwright": (),
    "Jest": (),
    "pytest": (),
    "JUnit": (),
    "Postman": (),
    "Object-Oriented Programming": ("OOP",),
    "Data Structures": (),
    "Algorithms": (),
    "Distributed Systems": (),
    "Operating Systems": (),
    # --- Security ---
    "Penetration Testing": ("Pen Testing",),
    "Wireshark": (),
    "Burp Suite": (),
    "Metasploit": (),
    "Nmap": (),
    "SIEM": (),
    "Cryptography": (),
    "Network Security": (),
    "Active Directory": (),
    # --- Enterprise / IT ---
    "Salesforce": (),
    "SAP": (),
    "ServiceNow": (),
    "Workday": (),
    "SharePoint": (),
    "Power Automate": (),
    # --- Design ---
    "Figma": (),
    "Sketch": (),
    "Adobe XD": (),
    "Photoshop": (),
    "Illustrator": (),
    "Wireframing": (),
    "Prototyping": (),
    "User Research": (),
    # --- Hardware / embedded ---
    "Verilog": (),
    "SystemVerilog": (),
    "VHDL": (),
    "FPGA": (),
    "RTL": (),
    "Embedded Systems": ("Embedded C",),
    "RTOS": ("FreeRTOS",),
    "Arduino": (),
    "Raspberry Pi": (),
    "ARM": (),
    "PCB Design": (),
    "Altium": (),
    "KiCad": (),
    "SPICE": ("LTspice",),
    "Simulink": (),
    "LabVIEW": (),
    "AutoCAD": (),
    "SolidWorks": (),
    "ROS": (),
    "Unity": ("Unity3D",),
    "Unreal Engine": (),
    "OpenGL": (),
    # --- Quant ---
    "Stochastic Calculus": (),
    "Time Series": ("Time Series Analysis",),
    "Linear Algebra": (),
    "Probability": (),
    "Bloomberg Terminal": (),
}

# These are also ordinary words or initials, so they only count when the
# casing is exactly the skill's ("Go", not "go"; "REST", not "rest").
_CASE_SENSITIVE = {"C", "R", "Go", "Excel", "SAS", "SAP", "REST", "RAG", "ARM", "ROS", "Sketch"}
_CASE_SENSITIVE |= {"Lambda", "Helm", "Swift", "Rust", "Dart", "Unity", "Oracle", "Spark", "S3"}
# ...and even then not in these phrases: "Go-to-market", "R&D".
_NOT_BEFORE = {"Go": {"to"}, "R": {"d"}}

_MAX_NGRAM = 3
_TOKEN = re.compile(r"\.?[A-Za-z0-9][A-Za-z0-9+#.]*")


def _raw_tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text) if t.rstrip(".")]


def tokenize(text: str) -> list[str]:
    """Words, keeping the characters that distinguish C++ / C# / .NET /
    Node.js. Hyphens and slashes separate, so "scikit-learn", "CI/CD" and
    "PL/SQL" match however they are punctuated."""
    return [t.rstrip(".") for t in _raw_tokens(text)]


def _build_index() -> dict[tuple[str, ...], tuple[str, tuple[str, ...] | None]]:
    index: dict[tuple[str, ...], tuple[str, tuple[str, ...] | None]] = {}
    for canonical, aliases in SKILLS.items():
        for phrase in (canonical, *aliases):
            tokens = tuple(tokenize(phrase))
            if not tokens or len(tokens) > _MAX_NGRAM:
                raise ValueError(f"skill phrase {phrase!r} does not tokenize into 1-3 tokens")
            exact = tokens if phrase in _CASE_SENSITIVE else None
            index[tuple(t.lower() for t in tokens)] = (canonical, exact)
    return index


_INDEX = _build_index()
_CANONICAL_BY_LOWER = {name.lower(): name for name in SKILLS}


def find_skills(text: str) -> list[str]:
    """Canonical skill names mentioned in `text`, in order of first mention."""
    raw = _raw_tokens(text or "")
    tokens = [t.rstrip(".") for t in raw]
    lowered = [t.lower() for t in tokens]
    found: list[str] = []
    i = 0
    while i < len(tokens):
        step = 1
        # Longest phrase first, so "React Native" isn't read as "React".
        for n in range(min(_MAX_NGRAM, len(tokens) - i), 0, -1):
            hit = _INDEX.get(tuple(lowered[i : i + n]))
            if hit is None:
                continue
            canonical, exact = hit
            if exact is not None and tuple(tokens[i : i + n]) != exact:
                continue
            following = lowered[i + n] if i + n < len(tokens) else ""
            if following in _NOT_BEFORE.get(canonical, ()):
                continue
            # "John C. Smith": a single letter written with a period is an
            # initial, not a language.
            if len(canonical) == 1 and raw[i].endswith("."):
                continue
            if canonical not in found:
                found.append(canonical)
            step = n
            break
        i += step
    return found


def canonicalize(skills: list[str]) -> list[str]:
    """Clean a user-edited skill list: trim, de-duplicate case-insensitively,
    and restore the vocabulary's casing where the skill is a known one.
    Unknown skills are kept — the student knows their resume better than the
    vocabulary does."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in skills:
        name = " ".join((raw or "").split())[:60]
        if not name:
            continue
        known = _INDEX.get(tuple(t.lower() for t in tokenize(name)))
        name = _CANONICAL_BY_LOWER.get(name.lower()) or (known[0] if known else name)
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out[:100]


# --------------------------------------------------------------------------- #
# PDF -> text
# --------------------------------------------------------------------------- #


class ResumeParseError(Exception):
    """The bytes are not a PDF PyMuPDF can open."""


# A resume is 1-2 pages. Anything past this is a portfolio or the wrong file,
# and reading all of it only makes the request slow.
_MAX_PAGES = 10
_MAX_CHARS = 100_000


def extract_text(data: bytes) -> str:
    if not data.startswith(b"%PDF-"):
        raise ResumeParseError("That file is not a PDF.")
    import pymupdf

    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise ResumeParseError("That PDF is password-protected.")
            parts = [page.get_text() for page in list(doc)[:_MAX_PAGES]]
    except ResumeParseError:
        raise
    except Exception as exc:  # PyMuPDF raises several unrelated types
        raise ResumeParseError("That PDF could not be read.") from exc
    # Postgres TEXT cannot hold NUL, and some PDF generators emit it.
    return "\n".join(parts).replace("\x00", "")[:_MAX_CHARS].strip()


def parse_resume(data: bytes) -> tuple[str, list[str], bool]:
    """(text, skills, needs_ocr). An image-only PDF is not an error: it comes
    back flagged for OCR with no skills, and the upload still succeeds."""
    text = extract_text(data)
    needs_ocr = len(text) < config.RESUME_MIN_TEXT_CHARS
    return text, ([] if needs_ocr else find_skills(text)), needs_ocr
