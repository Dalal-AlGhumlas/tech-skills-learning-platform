
"""
Headcount Labs - Data Cleaning & Technical Job Filtering

Input:
    2026 merged Headcount Labs JSONL dataset

Outputs:
    tech_candidates
    needs_review
    non_tech
    quality_excluded
    filter_audit.csv
    filter_report.json

Original dataset is never modified.
No API calls are made.
"""

import csv
import json
import re

from collections import Counter
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit
)

from jsonschema import Draft7Validator, FormatChecker


# =====================================================
# 1. PATHS & CONFIGURATION
# =====================================================

ROOT = Path(__file__).resolve().parents[2]

INPUT = (
    ROOT
    / "data-analysis"
    / "data-collection"
    / "headcount-labs"
    / "normalized"
    / "headcount_2026_through_2026-10-28.jsonl"
)

SCHEMA_PATH = (
    ROOT
    / "Data & Schemas"
    / "job_collection_schema.json"
)

OUTPUT = (
    ROOT
    / "data-analysis"
    / "preprocessing"
    / "output"
    / "headcount"
)

START = date(2026, 1, 1)
END = date(2026, 10, 28)

COLUMNS = [
    "source_job_id",
    "job_title",
    "company",
    "location",
    "country",
    "description",
    "source",
    "publisher",
    "url",
    "posted_date"
]

BUCKETS = [
    "tech_candidates",
    "needs_review",
    "non_tech",
    "quality_excluded"
]


# =====================================================
# 2. TECHNICAL JOB TITLE PATTERNS
# =====================================================

TECH_TITLE = re.compile(
    r"\b(?:"
    r"software engineer|software developer|"
    r"backend|back.end|front.end|full.stack|"
    r"web developer|mobile developer|"
    r"android developer|ios developer|"
    r"data analyst|data engineer|data scientist|"
    r"analytics engineer|bi developer|"
    r"business intelligence|"
    r"machine learning|deep learning|"
    r"artificial intelligence|ai engineer|"
    r"ml engineer|mlops|llm engineer|"
    r"computer vision|nlp engineer|"
    r"devops|devsecops|"
    r"cloud engineer|cloud architect|"
    r"cloud developer|site reliability|"
    r"sre engineer|platform engineer|"
    r"cybersecurity|cyber security|"
    r"security analyst|security engineer|"
    r"soc analyst|penetration tester|"
    r"incident response|"
    r"network engineer|network architect|"
    r"network administrator|"
    r"database administrator|database engineer|"
    r"database developer|sql developer|dba|"
    r"sap consultant|sap developer|"
    r"erp consultant|dynamics 365|"
    r"servicenow developer|"
    r"systems administrator|"
    r"linux administrator|"
    r"windows server administrator|"
    r"software tester|test automation|"
    r"automation test|sdet|qa automation|"
    r"ui designer|ux designer|ui/ux|"
    r"ux researcher"
    r")\b",
    re.IGNORECASE
)


# =====================================================
# 3. LIKELY NON-TECHNICAL JOB TITLES
# =====================================================

NONTECH_TITLE = re.compile(
    r"\b(?:"
    r"cashier|waiter|waitress|chef|cook|"
    r"receptionist|concierge|warehouse|"
    r"driver|delivery rider|housekeeper|"
    r"security guard|accountant|"
    r"finance officer|auditor|"
    r"procurement|purchasing|"
    r"human resources|hr specialist|"
    r"recruiter|recruitment|"
    r"sales representative|sales executive|"
    r"marketing specialist|digital marketing|"
    r"social media|influencer marketing|"
    r"customer service|call center|"
    r"store manager|retail associate|"
    r"civil engineer|mechanical engineer|"
    r"electrical engineer|"
    r"architectural engineer|"
    r"construction manager|bim specialist|"
    r"nurse|pharmacist|physician|dentist|"
    r"laboratory technician|"
    r"administrative assistant|office assistant"
    r")\b",
    re.IGNORECASE
)


# =====================================================
# 4. TECHNICAL TOOLS IN DESCRIPTIONS
# =====================================================

TECH_TOOLS = re.compile(
    r"\b(?:"
    r"python|javascript|typescript|java|"
    r"kotlin|swift|golang|sql|postgresql|"
    r"mysql|mongodb|oracle database|"
    r"react|angular|vue\.js|node\.js|"
    r"django|flask|fastapi|docker|"
    r"kubernetes|terraform|ansible|jenkins|"
    r"gitlab ci|aws|azure|google cloud|gcp|"
    r"snowflake|databricks|pytorch|"
    r"tensorflow|scikit.learn|spark|hadoop|"
    r"airflow|power bi|tableau|looker|"
    r"linux|wireshark|splunk|siem|"
    r"cisco|sap abap|selenium|"
    r"playwright|cypress|figma|"
    r"rest api|graphql|etl|ci/cd"
    r")\b",
    re.IGNORECASE
)


# =====================================================
# 5. URL NORMALIZATION FOR DEDUPLICATION
# =====================================================

def normalized_url(url):

    parts = urlsplit(url)

    query = [
        (key, val)
        for key, val in parse_qsl(
            parts.query,
            keep_blank_values=True
        )
        if (
            not key.lower().startswith("utm_")
            and key.lower() not in {
                "fbclid",
                "gclid",
                "msclkid"
            }
        )
    ]

    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        urlencode(query),
        ""
    ))


# =====================================================
# 6. PRELIMINARY TECHNICAL FILTER
# =====================================================

def classify_title(title, description):

    if TECH_TITLE.search(title):
        return (
            "tech_candidates",
            "strong_technical_job_title"
        )

    if NONTECH_TITLE.search(title):
        return (
            "non_tech",
            "clear_non_technical_job_title"
        )

    # Description-based evidence.
    # These are candidates, not final classifications.

    tools = {
        match.group(0).lower()
        for match in TECH_TOOLS.finditer(description)
    }

    if len(tools) >= 2:
        return (
            "tech_candidates",
            "multiple_technical_tools_in_description"
        )

    return (
        "needs_review",
        "ambiguous_role_needs_classification"
    )


# =====================================================
# 7. MAIN FILTERING PIPELINE
# =====================================================

def main():

    if not INPUT.is_file():
        raise SystemExit(
            f"Input file not found: {INPUT}"
        )

    if not SCHEMA_PATH.is_file():
        raise SystemExit(
            f"Schema not found: {SCHEMA_PATH}"
        )

    schema = json.loads(
        SCHEMA_PATH.read_text(encoding="utf-8")
    )

    Draft7Validator.check_schema(schema)

    validator = Draft7Validator(
        schema,
        format_checker=FormatChecker()
    )

    OUTPUT.mkdir(
        parents=True,
        exist_ok=True
    )

    counts = Counter()
    reasons = Counter()
    month_counts = Counter()

    seen_ids = set()
    seen_urls = set()

    # -------------------------------------------------
    # Create output files
    # -------------------------------------------------

    with ExitStack() as stack:

        jsonl_files = {
            bucket: stack.enter_context(
                (OUTPUT / f"{bucket}.jsonl").open(
                    "w",
                    encoding="utf-8"
                )
            )
            for bucket in BUCKETS
        }

        csv_files = {
            bucket: stack.enter_context(
                (OUTPUT / f"{bucket}.csv").open(
                    "w",
                    encoding="utf-8-sig",
                    newline=""
                )
            )
            for bucket in (
                "tech_candidates",
                "needs_review"
            )
        }

        csv_writers = {
            bucket: csv.DictWriter(
                csv_files[bucket],
                fieldnames=COLUMNS
            )
            for bucket in csv_files
        }

        for writer in csv_writers.values():
            writer.writeheader()

        audit_file = stack.enter_context(
            (OUTPUT / "filter_audit.csv").open(
                "w",
                encoding="utf-8-sig",
                newline=""
            )
        )

        audit_writer = csv.DictWriter(
            audit_file,
            fieldnames=[
                "source_job_id",
                "job_title",
                "posted_date",
                "bucket",
                "reason"
            ]
        )

        audit_writer.writeheader()

        # ---------------------------------------------
        # Save a record to its selected bucket
        # ---------------------------------------------

        def save(bucket, job, reason):

            counts[bucket] += 1
            reasons[reason] += 1

            jsonl_files[bucket].write(
                json.dumps(
                    job,
                    ensure_ascii=False
                ) + "\n"
            )

            if bucket in csv_writers:

                csv_writers[bucket].writerow({
                    col: job.get(col)
                    for col in COLUMNS
                })

            audit_writer.writerow({
                "source_job_id": job.get(
                    "source_job_id"
                ),
                "job_title": job.get(
                    "job_title"
                ),
                "posted_date": job.get(
                    "posted_date"
                ),
                "bucket": bucket,
                "reason": reason
            })

        # ---------------------------------------------
        # Read the annual dataset
        # ---------------------------------------------

        with INPUT.open(
            "r",
            encoding="utf-8-sig"
        ) as source:

            for line_number, line in enumerate(
                source,
                start=1
            ):

                if not line.strip():
                    continue

                counts["input_rows"] += 1

                try:
                    job = json.loads(line)

                except json.JSONDecodeError:

                    save(
                        "quality_excluded",
                        {
                            "source_job_id": None,
                            "job_title": (
                                f"INVALID_JSON_AT_LINE_"
                                f"{line_number}"
                            )
                        },
                        "invalid_json"
                    )

                    continue

                if not isinstance(job, dict):

                    save(
                        "quality_excluded",
                        {},
                        "not_a_json_object"
                    )

                    continue

                # -------------------------------------
                # Validate Collection Schema
                # -------------------------------------

                error = next(
                    validator.iter_errors(job),
                    None
                )

                if error:

                    save(
                        "quality_excluded",
                        job,
                        "schema_invalid"
                    )

                    continue

                # -------------------------------------
                # Validate publication date
                # -------------------------------------

                try:
                    published = date.fromisoformat(
                        job["posted_date"]
                    )

                except (ValueError, TypeError):

                    save(
                        "quality_excluded",
                        job,
                        "missing_or_invalid_posted_date"
                    )

                    continue

                if not START <= published <= END:

                    save(
                        "quality_excluded",
                        job,
                        "outside_study_period"
                    )

                    continue

                # -------------------------------------
                # Validate country
                # -------------------------------------

                if job["country"] not in (
                    "SA",
                    None
                ):

                    save(
                        "quality_excluded",
                        job,
                        "outside_sa"
                    )

                    continue

                # -------------------------------------
                # Remove duplicate IDs and URLs
                # -------------------------------------

                job_id = str(
                    job["source_job_id"] or ""
                ).strip()

                url_key = normalized_url(
                    job["url"]
                )

                if (
                    (job_id and job_id in seen_ids)
                    or url_key in seen_urls
                ):

                    save(
                        "quality_excluded",
                        job,
                        "duplicate_id_or_url"
                    )

                    continue

                if job_id:
                    seen_ids.add(job_id)

                seen_urls.add(url_key)

                month_counts[
                    published.strftime("%Y-%m")
                ] += 1

                # -------------------------------------
                # Missing country requires review
                # -------------------------------------

                if job["country"] is None:

                    save(
                        "needs_review",
                        job,
                        "country_missing_check_original_location"
                    )

                    continue

                # -------------------------------------
                # Preliminary technical classification
                # -------------------------------------

                bucket, reason = classify_title(
                    job["job_title"],
                    job["description"]
                )

                save(
                    bucket,
                    job,
                    reason
                )

    # =================================================
    # 8. QUALITY REPORT
    # =================================================

    report = {
        "input": str(
            INPUT.relative_to(ROOT)
        ),

        "study_period": [
            str(START),
            str(END)
        ],

        "counts": dict(counts),

        "reasons": dict(reasons),

        "monthly_quality_pass": dict(
            sorted(month_counts.items())
        ),

        "warning": (
            "This is preliminary filtering only. "
            "Technical candidates require final "
            "classification into 9 domains. "
            "Review ambiguous and non-tech cases "
            "before permanently excluding them."
        )
    }

    report_path = (
        OUTPUT / "filter_report.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    # =================================================
    # 9. PRINT SUMMARY
    # =================================================

    print("\n=== HEADCOUNT FILTER SUMMARY ===")

    for key in [
        "input_rows",
        "tech_candidates",
        "needs_review",
        "non_tech",
        "quality_excluded"
    ]:
        print(
            f"{key}: {counts[key]}"
        )

    print("\nOutput directory:")
    print(OUTPUT)

    print(
        "\nOriginal dataset was NOT modified."
    )

    print(
        "No API calls were made."
    )


if __name__ == "__main__":
    main()
