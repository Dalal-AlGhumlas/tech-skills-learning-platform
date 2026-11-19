
#!/usr/bin/env python3
"""Headcount Labs: classification quality and skills audit."""

import argparse
import collections
import csv
import json
import random
import re
import sys
from pathlib import Path

SPECIALIZATIONS = [
    "ai",
    "data_analytics",
    "software_development",
    "cloud_devops",
    "cybersecurity",
    "infrastructure_networking",
    "qa_testing",
    "database_enterprise_systems",
    "uiux_technical_products",
]

DECISIONS = {"in_scope", "out_of_scope", "needs_review"}

# Candidate technical skills. Matches require human validation.
SKILL_MAP = {
    "Python": [r"\bpython\b"],
    "SQL": [r"\bSQL\b"],
    "JavaScript": [r"\bjavascript\b", r"\bECMAScript\b"],
    "TypeScript": [r"\btypescript\b"],
    "Java": [r"\bjava\b(?!script)"],
    "C#": [r"(?<!\w)C\s*#(?!\w)"],
    "C++": [r"(?<!\w)C\s*\+\+(?!\w)"],
    "Go (Golang)": [r"\bgolang\b", r"\bGo programming language\b"],
    "Rust": [r"\bRust (?:language|programming)\b"],
    "Scala": [r"\bscala\b"],
    "Kotlin": [r"\bkotlin\b"],
    "Swift": [r"\bswift\b(?=\s+(?:language|programming|UI))"],
    "PHP": [r"\bPHP\b"],
    "Bash": [r"\bbash\b", r"\bshell scripting\b"],
    "PowerShell": [r"\bpowershell\b"],
    "HTML": [r"\bHTML(?:5)?\b"],
    "CSS": [r"\bCSS(?:3)?\b"],
    ".NET": [r"(?<!\w)\.NET\b", r"\bASP\.NET\b"],
    "Node.js": [r"\bNode\.?js\b"],
    "React": [r"\bReact(?:\.js|JS)?\b"],
    "Angular": [r"\bAngular(?:JS)?\b"],
    "Vue.js": [r"\bVue(?:\.js|JS)?\b"],
    "Next.js": [r"\bNext\.js\b", r"\bNextJS\b"],
    "Spring Boot": [r"\bSpring Boot\b"],
    "Django": [r"\bdjango\b"],
    "Flask": [r"\bFlask\b"],
    "FastAPI": [r"\bFastAPI\b"],
    "REST APIs": [
        r"\bREST(?:ful)?\s+APIs?\b",
        r"\bREST\s+services?\b",
    ],
    "GraphQL": [r"\bGraphQL\b"],
    "Microservices": [r"\bmicro[- ]services?\b"],
    "Git": [r"\bGit\b", r"\bGitHub\b", r"\bGitLab\b"],
    "Linux": [r"\bLinux\b"],
    "Docker": [r"\bDocker\b"],
    "Kubernetes": [r"\bKubernetes\b", r"\bK8s\b"],
    "Terraform": [r"\bTerraform\b"],
    "Ansible": [r"\bAnsible\b"],
    "Jenkins": [r"\bJenkins\b"],
    "CI/CD": [
        r"\bCI\s*/\s*CD\b",
        r"\bcontinuous (?:integration|delivery|deployment)\b",
    ],
    "AWS": [r"\bAWS\b", r"\bAmazon Web Services\b"],
    "Microsoft Azure": [r"\bMicrosoft Azure\b", r"\bAzure\b"],
    "Google Cloud (GCP)": [
        r"\bGoogle Cloud(?: Platform)?\b",
        r"\bGCP\b",
    ],
    "Azure DevOps": [r"\bAzure DevOps\b"],
    "GitHub Actions": [r"\bGitHub Actions\b"],
    "Apache Spark": [r"\bApache Spark\b", r"\bPySpark\b"],
    "Hadoop": [r"\bHadoop\b"],
    "Databricks": [r"\bDatabricks\b"],
    "Snowflake": [r"\bSnowflake\b"],
    "Apache Airflow": [r"\bAirflow\b"],
    "Apache Kafka": [r"\bKafka\b"],
    "dbt": [r"\bdbt\b"],
    "ETL/ELT": [
        r"\bETL\b",
        r"\bELT\b",
        r"\bextract\s*,?\s*transform\s*,?\s*(?:and\s*)?load\b",
    ],
    "Power BI": [r"\bPower\s*BI\b", r"\bPowerBI\b"],
    "Tableau": [r"\bTableau\b"],
    "Microsoft Excel": [r"\bExcel\b"],
    "Pandas": [r"\bPandas\b"],
    "NumPy": [r"\bNumPy\b"],
    "PyTorch": [r"\bPyTorch\b"],
    "TensorFlow": [r"\bTensorFlow\b"],
    "scikit-learn": [
        r"\bscikit[- ]learn\b",
        r"\bsklearn\b",
    ],
    "Machine Learning": [r"\bmachine learning\b"],
    "Deep Learning": [r"\bdeep learning\b"],
    "Natural Language Processing": [
        r"\bnatural language processing\b",
        r"\bNLP\b",
    ],
    "Large Language Models": [
        r"\blarge language models?\b",
        r"\bLLMs?\b",
    ],
    "RAG": [
        r"\bretrieval[- ]augmented generation\b",
        r"\bRAG\b",
    ],
    "Computer Vision": [r"\bcomputer vision\b"],
    "MLOps": [r"\bMLOps\b"],
    "MLflow": [r"\bMLflow\b"],
    "Data Modeling": [
        r"\bdata modell?ing\b",
        r"\bdimensional modell?ing\b",
    ],
    "Data Warehousing": [r"\bdata warehous(?:e|ing)\b"],
    "Data Governance": [r"\bdata governance\b"],
    "SOC": [
        r"\bSecurity Operations Center\b",
        r"\bSOC analyst\b",
        r"\bSOC operations\b",
    ],
    "SIEM": [
        r"\bSIEM\b",
        r"\bsecurity information and event management\b",
    ],
    "Splunk": [r"\bSplunk\b"],
    "IBM QRadar": [r"\bQRadar\b"],
    "Microsoft Sentinel": [
        r"\bMicrosoft Sentinel\b",
        r"\bAzure Sentinel\b",
    ],
    "Identity and Access Management": [
        r"\bidentity (?:and|&) access management\b",
        r"\bIAM\b",
    ],
    "Penetration Testing": [
        r"\bpenetration test(?:ing|s)?\b",
        r"\bpen[- ]testing\b",
    ],
    "Vulnerability Management": [
        r"\bvulnerabilit(?:y|ies) (?:assessment|management|scanning)\b",
    ],
    "Incident Response": [r"\bincident response\b"],
    "ISO 27001": [r"\bISO\s*27001\b"],
    "NIST": [r"\bNIST\b"],
    "OWASP": [r"\bOWASP\b"],
    "Firewalls": [r"\bfirewalls?\b"],
    "Fortinet": [r"\bFortinet\b", r"\bFortiGate\b"],
    "Palo Alto Networks": [
        r"\bPalo Alto Networks\b",
        r"\bPAN-OS\b",
    ],
    "TCP/IP": [r"\bTCP\s*/\s*IP\b"],
    "DNS": [r"\bDNS\b", r"\bdomain name system\b"],
    "DHCP": [r"\bDHCP\b"],
    "BGP": [r"\bBGP\b"],
    "OSPF": [r"\bOSPF\b"],
    "VPN": [r"\bVPN\b"],
    "Cisco": [r"\bCisco\b"],
    "VMware": [r"\bVMware\b", r"\bvSphere\b"],
    "Windows Server": [r"\bWindows Server\b"],
    "Active Directory": [
        r"\bActive Directory\b",
        r"\bMicrosoft Entra\b",
    ],
    "PostgreSQL": [r"\bPostgreSQL\b", r"\bPostgres\b"],
    "MySQL": [r"\bMySQL\b"],
    "Microsoft SQL Server": [
        r"\bMicrosoft SQL Server\b",
        r"\bMS SQL Server\b",
        r"\bMSSQL\b",
    ],
    "Oracle Database": [
        r"\bOracle (?:Database|DB|SQL|PL/SQL)\b",
        r"\bPL/SQL\b",
    ],
    "MongoDB": [r"\bMongoDB\b"],
    "Redis": [r"\bRedis\b"],
    "SAP": [
        r"\bSAP(?:\s+(?:S/4HANA|HANA|ERP|ABAP|Basis|FICO|SD|MM))?\b",
    ],
    "Salesforce": [r"\bSalesforce\b"],
    "Microsoft Dynamics": [
        r"\bMicrosoft Dynamics\b",
        r"\bDynamics 365\b",
        r"\bDynamics CRM\b",
    ],
    "Oracle ERP": [r"\bOracle ERP\b", r"\bOracle Fusion\b"],
    "Selenium": [r"\bSelenium\b"],
    "Cypress": [r"\bCypress\b"],
    "Playwright": [r"\bPlaywright\b"],
    "JUnit": [r"\bJUnit\b"],
    "pytest": [r"\bpytest\b"],
    "API Testing": [r"\bAPI test(?:ing|s)?\b"],
    "Test Automation": [
        r"\btest automation\b",
        r"\bautomated (?:software )?test(?:s|ing)\b",
    ],
    "Performance Testing": [
        r"\bperformance test(?:ing|s)?\b",
        r"\bload test(?:ing|s)?\b",
    ],
    "JMeter": [r"\bJMeter\b"],
    "Postman": [r"\bPostman\b"],
    "Figma": [r"\bFigma\b"],
    "Adobe XD": [r"\bAdobe XD\b"],
    "User Research": [
        r"\buser research\b",
        r"\bUX research\b",
    ],
    "Usability Testing": [r"\busability test(?:ing|s)?\b"],
    "Wireframing": [r"\bwirefram(?:e|es|ing)\b"],
    "Prototyping": [r"\bprototyp(?:e|es|ing)\b"],
    "Accessibility (WCAG)": [
        r"\bWCAG\b",
        r"\bweb accessibility\b",
    ],
}

COMPILED_SKILLS = {
    skill: [re.compile(pattern, re.I) for pattern in patterns]
    for skill, patterns in SKILL_MAP.items()
}

TITLE_CLUES = {
    "software_engineering":
        r"\b(?:software|frontend|front.end|backend|back.end|full.?stack|web|mobile|application)\s+(?:developer|engineer|architect|programmer)\b",

    "data_role":
        r"\b(?:data (?:scientist|engineer|analyst|architect)|analytics engineer|BI developer|database administrator)\b",

    "ai_role":
        r"\b(?:machine learning|deep learning|AI|ML|NLP)\s+(?:engineer|scientist|developer|researcher)\b",

    "security_role":
        r"\b(?:cybersecurity|information security|cloud security|security operations|SOC|penetration test)\b",

    "infra_role":
        r"\b(?:network|systems?|cloud|DevOps|SRE|site reliability|data center|IT support|IT infrastructure)\s+(?:engineer|administrator|specialist|technician|architect)\b",

    "qa_software":
        r"\b(?:software QA|software quality assurance|automation test|software test(?:ing|er)?|SDET)\b",

    "erp_role":
        r"\b(?:SAP|ERP|Salesforce|Dynamics 365|Oracle Fusion)\s+(?:developer|consultant|engineer|specialist|administrator|architect)\b",

    "ux_role":
        r"\b(?:UX|UI|product design|user experience)\s+(?:designer|researcher|engineer)\b",
}

DESCRIPTION_CLUES = {
    "coding":
        r"\b(?:Python|JavaScript|TypeScript|C\+\+|C#|Git|software development|code reviews?|programming)\b",

    "platforms":
        r"\b(?:AWS|Microsoft Azure|Google Cloud|Kubernetes|Terraform|Docker|Linux|CI/CD|SQL|Power BI|Tableau)\b",

    "security_tech":
        r"\b(?:SIEM|Splunk|QRadar|incident response|penetration testing|firewall|IAM|vulnerability management)\b",

    "technical_build":
        r"\b(?:build|deploy|implement|develop|configure|administer|automate)\b.{0,65}\b(?:software|systems?|application|infrastructure|database|network|pipelines?|APIs?)\b",
}

COMPILED_TITLES = {
    k: re.compile(v, re.I)
    for k, v in TITLE_CLUES.items()
}

COMPILED_DESCRIPTIONS = {
    k: re.compile(v, re.I | re.S)
    for k, v in DESCRIPTION_CLUES.items()
}


def normalize_decision(value):
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def write_csv(path, rows, columns):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=columns,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path):
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        csv.field_size_limit(2**31 - 1)

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise ValueError("CSV has no header")

        columns = list(reader.fieldnames)
        rows = list(reader)

    return columns, rows


def review_row(row, risk_score=None, risk_signals=None):
    result = dict(row)

    result["audit_human_decision"] = ""
    result["audit_human_specialization"] = ""
    result["audit_human_notes"] = ""
    result["audit_review_status"] = "pending"

    if risk_score is not None:
        result["audit_risk_score"] = risk_score
        result["audit_risk_signals"] = "; ".join(
            risk_signals or []
        )

    return result


def extract_snippet(text, match, width=115):
    start = max(0, match.start() - width)
    end = min(len(text), match.end() + width)

    snippet = text[start:end]
    snippet = re.sub(r"\s+", " ", snippet).strip()

    return snippet[:265]


def main():
    parser = argparse.ArgumentParser(
        description="Headcount quality and skills audit"
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            "data-analysis/preprocessing/output/headcount/"
            "ai_classification/full_dataset/classifications_all.csv"
        ),
    )

    parser.add_argument(
        "--out",
        type=Path,
        default=None,
    )

    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--random-review", type=int, default=150)
    parser.add_argument("--high-risk-review", type=int, default=100)

    args = parser.parse_args()

    source = args.input.resolve()

    if not source.exists():
        sys.exit(
            f"ERROR: Classification CSV not found: {source}"
        )

    output = (
        args.out or source.parent / "quality_and_skills_audit"
    ).resolve()

    if output == source.parent:
        sys.exit(
            "ERROR: Output must be a separate folder"
        )

    output.mkdir(parents=True, exist_ok=True)

    columns, rows = load_csv(source)

    if not rows:
        sys.exit("ERROR: No jobs found in CSV")

    decision_col = next(
        (
            k for k in (
                "decision",
                "ai_decision",
                "predicted_decision",
            )
            if k in columns
        ),
        None,
    )

    spec_col = next(
        (
            k for k in (
                "specialization",
                "ai_specialization",
                "predicted_specialization",
            )
            if k in columns
        ),
        None,
    )

    desc_col = next(
        (
            k for k in (
                "description",
                "job_description",
                "description_text",
                "job_text",
                "full_description",
            )
            if k in columns
        ),
        None,
    )

    title_col = next(
        (
            k for k in (
                "job_title",
                "title",
                "position_title",
            )
            if k in columns
        ),
        None,
    )

    id_col = next(
        (
            k for k in (
                "record_key",
                "source_job_id",
                "job_id",
                "id",
            )
            if k in columns
        ),
        None,
    )

    if not decision_col or not spec_col:
        sys.exit(
            f"ERROR: Missing classification columns. "
            f"Available columns: {columns}"
        )

    if not desc_col:
        sys.exit(
            f"ERROR: Missing job description column. "
            f"Available columns: {columns}"
        )

    if not id_col:
        sys.exit(
            f"ERROR: Missing stable job ID. "
            f"Available columns: {columns}"
        )

    identifiers = [row.get(id_col) for row in rows]

    duplicates = len(identifiers) - len(set(identifiers))

    if duplicates:
        sys.exit(
            f"ERROR: {duplicates} duplicate job identifiers"
        )

    groups = collections.defaultdict(list)

    for row in rows:
        decision = normalize_decision(
            row.get(decision_col)
        )
        groups[decision].append(row)

    unknown = sorted(
        decision for decision in groups
        if decision not in DECISIONS
    )

    if unknown:
        sys.exit(
            f"ERROR: Unknown decisions: {unknown}"
        )

    total = len(rows)

    included = groups["in_scope"]
    excluded = groups["out_of_scope"]
    ambiguous = groups["needs_review"]

    invalid_specs = [
        row.get(id_col)
        for row in included
        if (row.get(spec_col) or "").strip()
        not in SPECIALIZATIONS
    ]

    if invalid_specs:
        sys.exit(
            f"ERROR: {len(invalid_specs)} in_scope jobs "
            f"have invalid specializations"
        )

    base_review_columns = columns + [
        "audit_human_decision",
        "audit_human_specialization",
        "audit_human_notes",
        "audit_review_status",
    ]

    # 1. All needs_review jobs

    write_csv(
        output / "01_needs_review_all.csv",
        [review_row(row) for row in ambiguous],
        base_review_columns,
    )

    # 2. Random sample of out_of_scope jobs

    rng = random.Random(args.seed)

    random_review = rng.sample(
        excluded,
        min(args.random_review, len(excluded)),
    )

    write_csv(
        output / "02_out_of_scope_random_review.csv",
        [review_row(row) for row in random_review],
        base_review_columns,
    )

    # 3. Potentially misclassified technical jobs

    random_keys = {
        row.get(id_col) for row in random_review
    }

    scored = []

    for row in excluded:
        title = (
            row.get(title_col, "") if title_col else ""
        ) or ""

        description = row.get(desc_col, "") or ""

        title_hits = [
            name
            for name, pattern in COMPILED_TITLES.items()
            if pattern.search(title)
        ]

        description_hits = [
            name
            for name, pattern in COMPILED_DESCRIPTIONS.items()
            if pattern.search(description[:6000])
        ]

        score = (
            3 * len(title_hits)
            + len(description_hits)
        )

        if score > 0:
            scored.append((
                score,
                str(row.get(id_col)),
                row,
                title_hits + description_hits,
            ))

    scored.sort(
        key=lambda item: (-item[0], item[1])
    )

    high_risk = [
        item
        for item in scored
        if item[2].get(id_col) not in random_keys
    ][:args.high_risk_review]

    write_csv(
        output / "03_out_of_scope_high_risk_review.csv",
        [
            review_row(
                row,
                risk_score=score,
                risk_signals=signals,
            )
            for score, _, row, signals in high_risk
        ],
        base_review_columns + [
            "audit_risk_score",
            "audit_risk_signals",
        ],
    )

    # 4. Distribution of nine specializations

    spec_counts = collections.Counter(
        (row.get(spec_col) or "").strip()
        for row in included
    )

    distribution = []

    for spec in SPECIALIZATIONS:
        count = spec_counts[spec]

        distribution.append({
            "specialization": spec,
            "in_scope_jobs": count,
            "pct_of_in_scope": (
                f"{100 * count / len(included):.2f}"
                if included else "0.00"
            ),
            "pct_of_all_jobs": (
                f"{100 * count / total:.2f}"
                if total else "0.00"
            ),
        })

    write_csv(
        output / "04_specialization_distribution.csv",
        distribution,
        [
            "specialization",
            "in_scope_jobs",
            "pct_of_in_scope",
            "pct_of_all_jobs",
        ],
    )

    # 5. Provisional skills from job descriptions

    skill_counts = collections.defaultdict(
        collections.Counter
    )

    evidence = []
    no_skills = []
    missing_descriptions = 0

    for row in included:
        spec = (row.get(spec_col) or "").strip()
        description = row.get(desc_col, "") or ""

        if not description.strip():
            missing_descriptions += 1
            no_skills.append(str(row.get(id_col)))
            continue

        matches_found = 0

        for skill, patterns in COMPILED_SKILLS.items():
            matches = [
                match
                for pattern in patterns
                if (match := pattern.search(description))
            ]

            if not matches:
                continue

            first_match = min(
                matches,
                key=lambda match: match.start(),
            )

            # Each skill is counted once per job.
            skill_counts[spec][skill] += 1
            matches_found += 1

            evidence.append({
                id_col: row.get(id_col, ""),
                "job_title": (
                    row.get(title_col, "")
                    if title_col else ""
                ),
                "specialization": spec,
                "skill": skill,
                "evidence_snippet_from_description":
                    extract_snippet(
                        description,
                        first_match,
                    ),
            })

        if matches_found == 0:
            no_skills.append(str(row.get(id_col)))

    all_skills = []
    top_skills = []

    for spec in SPECIALIZATIONS:
        denominator = spec_counts[spec]

        ranked = sorted(
            skill_counts[spec].items(),
            key=lambda item: (-item[1], item[0]),
        )

        for rank, (skill, count) in enumerate(
            ranked,
            start=1,
        ):
            item = {
                "specialization": spec,
                "rank": rank,
                "skill": skill,
                "jobs_mentioning_skill": count,
                "specialization_jobs": denominator,
                "pct_of_specialization_jobs": (
                    f"{100 * count / denominator:.2f}"
                    if denominator else "0.00"
                ),
                "method":
                    "Keyword matching; requires validation",
            }

            all_skills.append(item)

            if rank <= 10:
                top_skills.append(item)

    skill_columns = [
        "specialization",
        "rank",
        "skill",
        "jobs_mentioning_skill",
        "specialization_jobs",
        "pct_of_specialization_jobs",
        "method",
    ]

    write_csv(
        output / "05_top10_skills_PROVISIONAL.csv",
        top_skills,
        skill_columns,
    )

    write_csv(
        output / "06_all_detected_skills_PROVISIONAL.csv",
        all_skills,
        skill_columns,
    )

    write_csv(
        output / "07_skill_evidence.csv",
        evidence,
        [
            id_col,
            "job_title",
            "specialization",
            "skill",
            "evidence_snippet_from_description",
        ],
    )

    write_csv(
        output / "08_in_scope_no_detected_skills.csv",
        [{id_col: key} for key in no_skills],
        [id_col],
    )

    # 6. Summary report

    summary = {
        "source_file": str(source),
        "total_jobs": total,
        "decisions": {
            label: len(groups[label])
            for label in (
                "in_scope",
                "out_of_scope",
                "needs_review",
            )
        },
        "specializations": dict(spec_counts),
        "review_queues": {
            "needs_review_all": len(ambiguous),
            "out_of_scope_random": len(random_review),
            "out_of_scope_high_risk": len(high_risk),
            "high_risk_candidates": len(scored),
        },
        "random_seed": args.seed,
        "missing_descriptions_in_scope":
            missing_descriptions,
        "in_scope_with_no_detected_skills":
            len(no_skills),
        "skill_dictionary_size": len(SKILL_MAP),
        "limitations": [
            "No human review is performed automatically.",
            "All review decisions are intentionally blank.",
            "Qwen classifications require validation.",
            "Keyword skill matches are provisional.",
            "Skill mentions may not be job requirements.",
            "Original classification files are not changed.",
        ],
    }

    with (
        output / "09_audit_summary.json"
    ).open("w", encoding="utf-8") as f:
        json.dump(
            summary,
            f,
            indent=2,
            ensure_ascii=False,
        )

    instructions = """
HEADCOUNT LABS - POST-CLASSIFICATION REVIEW

Original Qwen CSV and cache are not modified.

01_needs_review_all.csv
Review all uncertain jobs manually.

02_out_of_scope_random_review.csv
Random audit sample for checking false exclusions.

03_out_of_scope_high_risk_review.csv
Prioritized technical-looking excluded jobs.
This is not a representative random sample.

For each reviewed job:
- audit_human_decision: in_scope/out_of_scope/needs_review
- audit_human_specialization: one of the nine categories if in_scope
- audit_human_notes: evidence-based explanation
- audit_review_status: reviewed

04_specialization_distribution.csv
Current Qwen-only specialty counts.

05_top10_skills_PROVISIONAL.csv
Candidate Top 10 skills per specialty.

06_all_detected_skills_PROVISIONAL.csv
All keyword-matched skills.

07_skill_evidence.csv
Evidence snippets from original job descriptions.

08_in_scope_no_detected_skills.csv
Jobs requiring deeper skill extraction.

09_audit_summary.json
Counts, checks, and limitations.

Do not treat provisional skill counts as final results.
"""

    (
        output / "READ_ME_FIRST.txt"
    ).write_text(
        instructions,
        encoding="utf-8",
    )

    print()
    print("=== HEADCOUNT QUALITY AND SKILLS AUDIT ===")
    print(f"Total jobs: {total:,}")
    print(f"In scope: {len(included):,}")
    print(f"Out of scope: {len(excluded):,}")
    print(f"Needs review: {len(ambiguous):,}")

    print("\nSpecialization distribution:")

    for spec in SPECIALIZATIONS:
        print(f"  {spec}: {spec_counts[spec]}")

    print(
        f"\nRandom review sample: {len(random_review)}"
    )
    print(
        f"High-risk review sample: {len(high_risk)}"
    )
    print(
        f"Provisional Top 10 skill rows: {len(top_skills)}"
    )

    if (
        len(included) == 718
        and len(excluded) == 8036
        and len(ambiguous) == 53
    ):
        print(
            "\nCounts match the completed Qwen V3 report."
        )
    else:
        print(
            "\nNOTE: Counts differ from the earlier report."
        )

    print(f"\nOUTPUT FOLDER: {output}")
    print("Original classification files unchanged.")


if __name__ == "__main__":
    main()
