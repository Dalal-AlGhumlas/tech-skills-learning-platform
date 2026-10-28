
"""
Headcount Labs - Saudi Job Collection (2026)

Features:
- Automatically collect 2026 job postings
- Skip August API collection
- Reuse two existing August batches
- Split date ranges when exports reach their cap
- Resume previously saved exports
- Preserve complete job descriptions
- Validate against Collection Schema
- Merge data and remove duplicates
- Export CSV, JSONL, and quality reports

No specialization classification or skills extraction happens here.
"""

import argparse
import csv
import gzip
import json
import os
import time

from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from dotenv import load_dotenv
from jsonschema import Draft7Validator, FormatChecker


# =========================================================
# 1. PROJECT CONFIGURATION
# =========================================================

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

load_dotenv(ROOT / ".env")

SCHEMA_FILE = (
    ROOT
    / "Data & Schemas"
    / "job_collection_schema.json"
)

if not SCHEMA_FILE.is_file():
    raise SystemExit(
        f"Missing collection schema: {SCHEMA_FILE}"
    )

SCHEMA = json.loads(
    SCHEMA_FILE.read_text(encoding="utf-8")
)

Draft7Validator.check_schema(SCHEMA)

VALIDATOR = Draft7Validator(
    SCHEMA,
    format_checker=FormatChecker()
)

RAW = HERE / "raw"
NORMALIZED = HERE / "normalized"

BASE_URL = "https://api.headcountlabs.com"

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

# August is already collected.
# These batches must be reused, not downloaded again.

AUGUST = [
    (
        "2026-08-01_to_2026-08-07",
        date(2026, 8, 1),
        date(2026, 8, 7)
    ),
    (
        "2026-08-08_to_2026-08-31",
        date(2026, 8, 8),
        date(2026, 8, 31)
    )
]

SESSION = requests.Session()


# =========================================================
# 2. API CONNECTION
# =========================================================

def ensure_api_key():

    key = os.getenv("HEADCOUNTLABS_API_KEY")

    if not key:
        raise SystemExit(
            "HEADCOUNTLABS_API_KEY is missing "
            "from the root .env"
        )

    SESSION.headers["Authorization"] = (
        f"Bearer {key}"
    )


def api(method, path, payload=None):

    ensure_api_key()

    # Do not automatically retry POST exports.
    # A retry could create a second export.

    response = SESSION.request(
        method,
        urljoin(BASE_URL, path),
        json=payload,
        timeout=90
    )

    if not response.ok:
        raise RuntimeError(
            f"Headcount HTTP {response.status_code}: "
            f"{response.text[:600]}"
        )

    return response.json()


# =========================================================
# 3. GENERAL HELPERS
# =========================================================

def value(item):

    if isinstance(item, dict) and "state" in item:

        if item.get("state") in ("known", "derived"):
            return item.get("value")

        return None

    return item


def batch_label(start, end, whole_month=False):

    if whole_month:
        return start.strftime("%Y-%m")

    return f"{start}_to_{end}"


def report_paths(label):

    return (
        NORMALIZED / f"headcount_{label}_report.json",
        NORMALIZED / f"headcount_{label}.jsonl",
        NORMALIZED / f"headcount_{label}.csv"
    )


# =========================================================
# 4. VERIFY PREVIOUSLY SAVED BATCHES
# =========================================================

def saved_report(label, start, end):

    report_path, jsonl_path, _ = report_paths(label)

    if (
        not report_path.exists()
        or not jsonl_path.exists()
    ):
        return None

    report = json.loads(
        report_path.read_text(encoding="utf-8")
    )

    if report.get("period") != [
        str(start), str(end)
    ]:
        raise RuntimeError(
            f"Unexpected period in {report_path}"
        )

    cap = int(report.get("max_records") or 0)

    counts = report.get("counts") or {}

    raw = int(
        counts.get("export_record_count")
        or counts.get("raw_jobs")
        or 0
    )

    if cap < 1:
        raise RuntimeError(
            f"Missing max_records in {report_path}"
        )

    # An export that reached its cap may be incomplete.

    if raw >= cap:
        return None

    actual = 0

    with jsonl_path.open(
        encoding="utf-8"
    ) as file:

        for line in file:

            if not line.strip():
                continue

            record = json.loads(line)

            error = next(
                VALIDATOR.iter_errors(record),
                None
            )

            if error:
                raise RuntimeError(
                    f"Invalid row in {jsonl_path.name}: "
                    f"{error.message}"
                )

            actual += 1

    expected = int(
        counts.get("normalized_jobs") or 0
    )

    if actual != expected:
        raise RuntimeError(
            f"Mismatch in {jsonl_path.name}: "
            f"{actual} rows, expected {expected}"
        )

    return report


# =========================================================
# 5. CHECK AUGUST WITHOUT API CALLS
# =========================================================

def check_august():

    labels = []

    for label, start, end in AUGUST:

        report = saved_report(
            label,
            start,
            end
        )

        if report is None:

            raise SystemExit(
                f"August is not verified: {label}. "
                "Both its report and JSONL must exist, "
                "and exported records must be below "
                "that batch's cap. "
                "No new API export was created."
            )

        count = report["counts"].get(
            "normalized_jobs", 0
        )

        print(
            f"August saved: {label} "
            f"({count} normalized rows; no API call)"
        )

        labels.append(label)

    return labels


# =========================================================
# 6. NORMALIZE HEADCOUNT JOBS
# =========================================================

def normalize(job, start, end):

    options = []

    for posting in job.get("postings") or []:

        if not isinstance(posting, dict):
            continue

        posted = value(
            posting.get("source_posted_at")
        )

        url = value(
            posting.get("posting_url")
        )

        if (
            not isinstance(posted, str)
            or not isinstance(url, str)
        ):
            continue

        try:
            day = date.fromisoformat(
                posted[:10]
            )
        except ValueError:
            continue

        if (
            start <= day <= end
            and url.startswith(
                ("https://", "http://")
            )
        ):
            options.append(
                (day, posting, url)
            )

    if not options:

        return (
            None,
            "no_matching_posting_date_or_url"
        )

    day, posting, url = min(
        options,
        key=lambda x: x[0]
    )

    title = value(
        job.get("title")
    )

    company = value(
        job.get("employer_name")
    )

    description = value(
        job.get("description")
    )

    required_fields = [
        ("title", title),
        ("company", company),
        ("description", description)
    ]

    for field_name, field_value in required_fields:

        if (
            not isinstance(field_value, str)
            or not field_value.strip()
        ):
            return (
                None,
                "missing_" + field_name
            )

    city = None
    sa_location_found = False

    for item in job.get("locations") or []:

        loc = value(item)

        if not isinstance(loc, dict):
            continue

        country = value(
            loc.get("country")
        )

        if (
            country
            and str(country).upper() == "SA"
        ):

            sa_location_found = True

            maybe_city = value(
                loc.get("city")
            )

            if (
                isinstance(maybe_city, str)
                and maybe_city.strip()
            ):

                city = maybe_city.strip()
                break

    job_id = value(
        job.get("job_id")
    )

    publisher = value(
        posting.get("source")
    )

    record = {
        "source_job_id": (
            str(job_id)
            if job_id is not None
            else None
        ),

        "job_title": title.strip(),

        "company": company.strip(),

        "location": city,

        "country": (
            "SA"
            if sa_location_found
            else None
        ),

        "description": description.strip(),

        "source": "headcount_labs",

        "publisher": (
            publisher
            if isinstance(publisher, str)
            else None
        ),

        "url": url,

        "posted_date": day.isoformat()
    }

    error = next(
        VALIDATOR.iter_errors(record),
        None
    )

    if error:

        return (
            None,
            "schema_invalid: " + error.message[:100]
        )

    return record, None


# =========================================================
# 7. DOWNLOAD RAW EXPORT FILES
# =========================================================

def download_export_files(info, export_id, folder):

    files = []

    for item in info.get("files") or []:

        n = int(item["n"])

        destination = (
            folder / f"jobs_{n}.jsonl.gz"
        )

        remote_url = urljoin(
            BASE_URL,
            item["url"]
        )

        parsed = urlparse(remote_url)

        expected_prefix = (
            f"/v1/jobs/exports/"
            f"{export_id}/files/"
        )

        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.headcountlabs.com"
            or not parsed.path.startswith(
                expected_prefix
            )
        ):
            raise RuntimeError(
                "Unexpected export-file URL; "
                "download blocked"
            )

        if not destination.exists():

            print(
                "Downloading:",
                destination.name,
                flush=True
            )

            ensure_api_key()

            with SESSION.get(
                remote_url,
                timeout=180,
                stream=True
            ) as response:

                response.raise_for_status()

                temp = destination.with_suffix(
                    ".part"
                )

                with temp.open("wb") as file:

                    for chunk in response.iter_content(
                        chunk_size=1024 * 1024
                    ):

                        if chunk:
                            file.write(chunk)

                os.replace(
                    temp,
                    destination
                )

        files.append(destination)

    return files


# =========================================================
# 8. COLLECT ONE DATE RANGE
# =========================================================

def collect_range(
    start,
    end,
    cap,
    label,
    offline=False
):

    folder = RAW / label

    folder.mkdir(
        parents=True,
        exist_ok=True
    )

    NORMALIZED.mkdir(
        parents=True,
        exist_ok=True
    )

    manifest_path = (
        folder / "export_manifest.json"
    )

    filters = {
        "country": "SA",

        "posted_since": str(start),

        "posted_until": str(end),

        "currentness": [
            "current",
            "uncertain",
            "not_current"
        ],

        "has_description": True,

        "max_records": cap
    }

    new_post = False

    # Resume an existing export when available.

    if manifest_path.exists():

        manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )

        if manifest.get("filters") != filters:

            raise RuntimeError(
                f"Existing manifest for {label} "
                "has different filters/cap; "
                "rerun using the saved cap."
            )

        print(
            "Resuming existing export:",
            label,
            flush=True
        )

    else:

        if offline:
            raise RuntimeError(
                f"Offline mode: no saved export "
                f"for {label}"
            )

        print(
            f"Creating ONE export for {label} "
            f"(cap {cap})",
            flush=True
        )

        result = api(
            "POST",
            "/v1/jobs/exports",
            payload=filters
        )

        manifest = {
            "filters": filters,
            "export_id": result["export_id"]
        }

        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2
            ),
            encoding="utf-8"
        )

        new_post = True

    export_id = manifest["export_id"]

    info = manifest.get("export_info")

    files = (
        [
            folder / (
                f"jobs_{int(item['n'])}.jsonl.gz"
            )
            for item in info.get("files", [])
        ]
        if info
        else []
    )

    # Reuse downloaded raw files.

    if info and all(
        file.exists()
        for file in files
    ):

        print(
            "Using saved raw export "
            "(no new API calls)."
        )

    else:

        if offline:

            raise RuntimeError(
                f"Offline mode: missing saved "
                f"raw data for {label}"
            )

        # Wait for export completion.

        for _ in range(90):

            info = api(
                "GET",
                f"/v1/jobs/exports/{export_id}"
            )

            print(
                "Export status:",
                info.get("status"),
                flush=True
            )

            if info.get("status") == "completed":
                break

            if info.get("status") in (
                "failed",
                "expired"
            ):
                raise RuntimeError(
                    f"Export {info.get('status')}: "
                    f"{info.get('error')}"
                )

            time.sleep(10)

        else:
            raise TimeoutError(
                "Export still running; "
                "rerun to resume it"
            )

        manifest["export_info"] = info

        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2
            ),
            encoding="utf-8"
        )

        files = download_export_files(
            info,
            export_id,
            folder
        )

    # =====================================================
    # 9. NORMALIZE AND SAVE RESULTS
    # =====================================================

    counts = Counter()

    seen_ids = set()

    path_report, path_jsonl, path_csv = (
        report_paths(label)
    )

    temp_jsonl = path_jsonl.with_suffix(
        ".jsonl.part"
    )

    temp_csv = path_csv.with_suffix(
        ".csv.part"
    )

    with (
        temp_jsonl.open(
            "w",
            encoding="utf-8"
        ) as json_file,

        temp_csv.open(
            "w",
            encoding="utf-8-sig",
            newline=""
        ) as csv_file
    ):

        writer = csv.DictWriter(
            csv_file,
            fieldnames=COLUMNS
        )

        writer.writeheader()

        for filepath in files:

            with gzip.open(
                filepath,
                "rt",
                encoding="utf-8"
            ) as stream:

                for line in stream:

                    if not line.strip():
                        continue

                    counts["raw_jobs"] += 1

                    job = json.loads(line)

                    job_id = value(
                        job.get("job_id")
                    )

                    if (
                        job_id is not None
                        and str(job_id) in seen_ids
                    ):

                        counts["duplicate_job_id"] += 1
                        continue

                    if job_id is not None:
                        seen_ids.add(
                            str(job_id)
                        )

                    record, problem = normalize(
                        job,
                        start,
                        end
                    )

                    if problem:

                        counts[problem] += 1
                        continue

                    writer.writerow(record)

                    json_file.write(
                        json.dumps(
                            record,
                            ensure_ascii=False
                        ) + "\n"
                    )

                    counts["normalized_jobs"] += 1

    os.replace(
        temp_jsonl,
        path_jsonl
    )

    os.replace(
        temp_csv,
        path_csv
    )

    counts["export_record_count"] = int(
        info.get("record_count")
        or counts["raw_jobs"]
    )

    report = {
        "label": label,

        "period": [
            str(start),
            str(end)
        ],

        "counts": dict(counts),

        "max_records": cap,

        "export_id": export_id
    }

    path_report.write_text(
        json.dumps(
            report,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        f"Done: {label}, "
        f"raw={counts['raw_jobs']}, "
        f"valid={counts['normalized_jobs']}"
    )

    return report, new_post


# =========================================================
# 10. MERGE ALL COMPLETED BATCHES
# =========================================================

def merge_all(labels, cutoff):

    NORMALIZED.mkdir(
        parents=True,
        exist_ok=True
    )

    stem = (
        f"headcount_2026_through_{cutoff}"
    )

    jsonl_path = NORMALIZED / f"{stem}.jsonl"
    csv_path = NORMALIZED / f"{stem}.csv"
    report_path = NORMALIZED / f"{stem}_report.json"

    temp_jsonl = jsonl_path.with_suffix(
        ".jsonl.part"
    )

    temp_csv = csv_path.with_suffix(
        ".csv.part"
    )

    counts = Counter()

    seen_ids = set()
    seen_urls = set()

    with (
        temp_jsonl.open(
            "w",
            encoding="utf-8"
        ) as json_file,

        temp_csv.open(
            "w",
            encoding="utf-8-sig",
            newline=""
        ) as csv_file
    ):

        writer = csv.DictWriter(
            csv_file,
            fieldnames=COLUMNS
        )

        writer.writeheader()

        for label in labels:

            _, source, _ = report_paths(label)

            with source.open(
                encoding="utf-8"
            ) as file:

                for line in file:

                    if not line.strip():
                        continue

                    record = json.loads(line)

                    error = next(
                        VALIDATOR.iter_errors(record),
                        None
                    )

                    if error:
                        raise RuntimeError(
                            f"Invalid record in {label}: "
                            f"{error.message}"
                        )

                    counts["input_rows"] += 1

                    job_id = record.get(
                        "source_job_id"
                    )

                    url = record.get(
                        "url", ""
                    ).strip().lower()

                    # Deduplicate by Headcount job ID
                    # or original posting URL.

                    if (
                        (job_id and job_id in seen_ids)
                        or (url and url in seen_urls)
                    ):

                        counts["duplicates_removed"] += 1
                        continue

                    if job_id:
                        seen_ids.add(job_id)

                    if url:
                        seen_urls.add(url)

                    writer.writerow({
                        column: record.get(column)
                        for column in COLUMNS
                    })

                    json_file.write(
                        json.dumps(
                            record,
                            ensure_ascii=False
                        ) + "\n"
                    )

                    counts["unique_jobs"] += 1

    os.replace(
        temp_jsonl,
        jsonl_path
    )

    os.replace(
        temp_csv,
        csv_path
    )

    report_path.write_text(
        json.dumps(
            {
                "period": [
                    "2026-01-01",
                    str(cutoff)
                ],

                "source": "headcount_labs",

                "segments_used": labels,

                "counts": dict(counts),

                "note": (
                    "August reused from two saved "
                    "batches. No skill extraction "
                    "or domain classification."
                )
            },
            indent=2
        ),
        encoding="utf-8"
    )

    print("\n=== YEAR MERGED ===")

    print(
        "Input rows:",
        counts["input_rows"]
    )

    print(
        "Unique rows:",
        counts["unique_jobs"]
    )

    print(
        "Duplicates removed:",
        counts["duplicates_removed"]
    )

    print(
        "JSONL:",
        jsonl_path
    )

    print(
        "CSV:",
        csv_path
    )

    print(
        "Report:",
        report_path
    )


# =========================================================
# 11. AUTOMATED 2026 COLLECTION
# =========================================================

def run_year(
    cutoff,
    max_records,
    max_new_records,
    offline=False
):

    if not (
        date(2026, 8, 31)
        <= cutoff
        <= date(2026, 12, 31)
    ):

        raise SystemExit(
            "--through must be between "
            "2026-08-31 and 2026-12-31"
        )

    if cutoff > date.today():

        raise SystemExit(
            "--through cannot be in the future"
        )

    # Verify August first.
    # No new API calls for August.

    august_labels = check_august()

    consumed = 0

    labels = []

    # -----------------------------------------------------
    # Collect a single interval, or reuse existing data.
    # -----------------------------------------------------

    def run_interval(
        start,
        end,
        whole_month=False
    ):

        nonlocal consumed

        label = batch_label(
            start,
            end,
            whole_month
        )

        existing = saved_report(
            label,
            start,
            end
        )

        if existing is not None:

            print(
                "Reusing completed batch:",
                label
            )

            labels.append(label)
            return

        path, _, _ = report_paths(label)

        # If the previous export reached its cap,
        # split instead of repeating it.

        if path.exists():

            previous = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            count = int(
                previous.get(
                    "counts", {}
                ).get(
                    "export_record_count"
                ) or 0
            )

            cap = int(
                previous.get(
                    "max_records"
                ) or 0
            )

            if cap and count >= cap:

                print(
                    "Capped saved batch, splitting:",
                    label
                )

                split(start, end)
                return

        # Resume existing manifests if present.

        manifest_file = (
            RAW
            / label
            / "export_manifest.json"
        )

        manifest = (
            json.loads(
                manifest_file.read_text(
                    encoding="utf-8"
                )
            )
            if manifest_file.exists()
            else None
        )

        if manifest:

            cap = int(
                manifest["filters"]["max_records"]
            )

        else:

            remaining = (
                max_new_records - consumed
            )

            if remaining <= 0:

                raise SystemExit(
                    "Reached new-export budget "
                    f"({max_new_records}). "
                    "Saved batches are safe; "
                    "rerun later."
                )

            cap = min(
                max_records,
                remaining
            )

        report, new_post = collect_range(
            start,
            end,
            cap,
            label,
            offline=offline
        )

        if new_post:

            consumed += int(
                report["counts"].get(
                    "export_record_count"
                ) or 0
            )

        exported_count = int(
            report["counts"].get(
                "export_record_count"
            ) or 0
        )

        if exported_count >= cap:

            if start == end:

                raise SystemExit(
                    f"A single day {start} "
                    "reached its export cap. "
                    "Cannot claim full coverage. "
                    "Increase the cap or "
                    "refine filters."
                )

            print(
                "Export reached cap; splitting:",
                label
            )

            split(start, end)

        else:

            labels.append(label)

    # -----------------------------------------------------
    # Split an interval into two smaller date ranges.
    # -----------------------------------------------------

    def split(start, end):

        if start >= end:

            raise SystemExit(
                f"Cannot split one day: {start}"
            )

        middle = start + timedelta(
            days=(end - start).days // 2
        )

        run_interval(
            start,
            middle
        )

        run_interval(
            middle + timedelta(days=1),
            end
        )

    # -----------------------------------------------------
    # Iterate over the months.
    # -----------------------------------------------------

    for month in range(
        1,
        cutoff.month + 1
    ):

        # AUGUST EXCEPTION

        if month == 8:

            labels.extend(
                august_labels
            )

            print(
                "August skipped "
                "(saved batches added to merge)."
            )

            continue

        first = date(
            2026,
            month,
            1
        )

        next_month = (
            date(2027, 1, 1)
            if month == 12
            else date(2026, month + 1, 1)
        )

        month_end = (
            next_month - timedelta(days=1)
        )

        last = min(
            month_end,
            cutoff
        )

        run_interval(
            first,
            last,
            whole_month=(
                last == month_end
            )
        )

    # Merge only after all periods finish successfully.

    merge_all(
        labels,
        cutoff
    )

    print(
        "New records exported during this run:",
        consumed
    )


# =========================================================
# 12. COMMAND LINE
# =========================================================

def main():

    parser = argparse.ArgumentParser(
        description="Headcount Labs 2026 collector"
    )

    parser.add_argument(
        "--year",
        type=int,
        choices=[2026]
    )

    parser.add_argument(
        "--check-august",
        action="store_true"
    )

    parser.add_argument(
        "--through",
        default="2026-10-28",
        help="Year collection cutoff YYYY-MM-DD"
    )

    parser.add_argument(
        "--max-records",
        type=int,
        default=5000
    )

    parser.add_argument(
        "--max-new-records",
        type=int,
        default=25000
    )

    parser.add_argument(
        "--start",
        help="Manual range start YYYY-MM-DD"
    )

    parser.add_argument(
        "--end",
        help="Manual range end YYYY-MM-DD"
    )

    parser.add_argument(
        "--normalize-only",
        action="store_true",
        help="Use saved files only; no API"
    )

    args = parser.parse_args()

    if args.check_august:

        check_august()

        print(
            "August confirmed. "
            "No API calls were made."
        )

        return

    if (
        args.max_records < 1
        or args.max_records > 100000
    ):

        parser.error(
            "--max-records must be 1..100000"
        )

    if args.max_new_records < 0:

        parser.error(
            "--max-new-records must be >= 0"
        )

    if args.year == 2026:

        if args.start or args.end:

            parser.error(
                "--year cannot be used with "
                "--start or --end"
            )

        cutoff = date.fromisoformat(
            args.through
        )

        run_year(
            cutoff,
            args.max_records,
            args.max_new_records,
            args.normalize_only
        )

    elif args.start and args.end:

        start = date.fromisoformat(
            args.start
        )

        end = date.fromisoformat(
            args.end
        )

        if not (
            date(2026, 1, 1)
            <= start
            <= end
            <= date.today()
        ):

            parser.error(
                "Manual date range must be "
                "within 2026 and cannot be future"
            )

        label = batch_label(
            start,
            end
        )

        report, _ = collect_range(
            start,
            end,
            args.max_records,
            label,
            args.normalize_only
        )

        count = int(
            report["counts"].get(
                "export_record_count"
            ) or 0
        )

        if count >= args.max_records:

            print(
                "WARNING: This date range "
                "reached the cap and may "
                "be incomplete"
            )

    else:

        parser.error(
            "Choose --year 2026, "
            "--check-august, "
            "or --start and --end"
        )


if __name__ == "__main__":
    main()
