#!/usr/bin/env python3
"""
Import an approved dataset release (default: V2) into the local SQLite database.

  python database/import_release.py                        # import V2 into database/tech_skills.db and activate it
  python database/import_release.py --db other.db --no-activate
  python database/import_release.py --release-dir <dir> --release-id v3   # future releases

Properties
  * Reproducible: reads only the release folder (read-only) + schema.sql.
  * Idempotent: re-importing the same release replaces that release's rows inside ONE transaction;
    other releases are untouched. Skills/specializations are upserted by natural key (stable IDs).
  * Safe: any validation mismatch rolls the whole import back (database left as before).
  * No invented values: empty CSV cells become NULL.
  * UTF-8 throughout (Arabic + English).
"""
import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_DIR = ROOT / "data-analysis/preprocessing/output/multi_source_integration/release_v2"
DEFAULT_DB = ROOT / "database/tech_skills.db"
SCHEMA = ROOT / "database/schema.sql"
TAXONOMY_DIR = ROOT / "data-analysis/preprocessing/output/headcount/ai_classification/full_dataset/postclassification_reviewed"
csv.field_size_limit(2**31 - 1)

# Definitions copied from the classifier standard (data-analysis/preprocessing/classify_headcount.py, SYSTEM prompt).
SPECIALIZATIONS = [
    ("ai", "Artificial Intelligence", "AI engineering, machine learning, computer vision, NLP, and developing AI systems."),
    ("data_analytics", "Data Analytics", "Data analytics, business intelligence, data engineering, analytical data science."),
    ("software_development", "Software Development", "Software development, backend, frontend, mobile applications, APIs, application engineering."),
    ("cloud_devops", "Cloud & DevOps", "Cloud engineering, DevOps, SRE, CI/CD, infrastructure as code, cloud platforms."),
    ("cybersecurity", "Cybersecurity", "Cybersecurity engineering, SOC, penetration testing, threat analysis and security operations."),
    ("infrastructure_networking", "Infrastructure & Networking", "Network engineering, network architecture, systems administration and IT infrastructure."),
    ("qa_testing", "QA & Software Testing", "Software quality assurance, test automation, software testing and performance testing."),
    ("database_enterprise_systems", "Database & Enterprise Systems", "Database administration, ERP, SAP, enterprise systems implementation and development."),
    ("uiux_technical_products", "UI/UX & Technical Products", "UI/UX design for digital products, interaction design, UX research and digital interfaces."),
]
REQUIRED_FILES = ["combined_in_scope_jobs_v2.csv", "job_skills_v2.csv", "pending_review_jobs.csv",
                  "combined_specialization_distribution_v2.csv", "combined_top10_skills_v2.csv", "v2_summary.json"]


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def nn(v):
    """Empty string -> NULL (never invent values)."""
    v = (v or "").strip()
    return v if v else None


def flag(v):
    v = (v or "").strip().lower()
    if v in ("yes", "true", "1"):
        return 1
    if v in ("no", "false", "0"):
        return 0
    return None


def load_taxonomy_parents():
    sys.path.insert(0, str(TAXONOMY_DIR))
    try:
        from skill_taxonomy import S  # noqa: WPS433  (read-only reuse of the analysis taxonomy)
        return {name: spec.get("parent") for name, spec in S.items()}
    except ImportError:
        return {}
    finally:
        sys.path.pop(0)


def connect(db_path):
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def apply_schema(con):
    con.executescript(SCHEMA.read_text(encoding="utf-8"))


def import_release(db_path=DEFAULT_DB, release_dir=DEFAULT_RELEASE_DIR, release_id="v2", activate=True, quiet=False):
    release_dir = Path(release_dir)
    missing = [f for f in REQUIRED_FILES if not (release_dir / f).exists()]
    if missing:
        raise FileNotFoundError(f"release files missing: {missing}")
    summary = json.loads((release_dir / "v2_summary.json").read_text(encoding="utf-8"))
    if not summary.get("all_checks_passed"):
        raise ValueError("release summary reports failed validation checks; refusing to import")
    jobs = read_csv(release_dir / "combined_in_scope_jobs_v2.csv")
    job_skills = read_csv(release_dir / "job_skills_v2.csv")
    pending = read_csv(release_dir / "pending_review_jobs.csv")
    dist = {d["specialization"]: int(d["v2_in_scope_jobs"]) for d in read_csv(release_dir / "combined_specialization_distribution_v2.csv")}
    files_hash = {f: sha256(release_dir / f) for f in REQUIRED_FILES}
    parents = load_taxonomy_parents()

    con = connect(db_path)
    apply_schema(con)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = con.execute("INSERT INTO import_run (release_id, started_at, status) VALUES (?, ?, 'running')", (release_id, started)).lastrowid
    con.commit()
    try:
        con.execute("BEGIN")
        # idempotent: remove this release's previous rows (cascades to jobs, links, pending); other releases untouched
        con.execute("DELETE FROM dataset_release WHERE release_id = ?", (release_id,))
        for order, (sid, name, definition) in enumerate(SPECIALIZATIONS, start=1):
            con.execute("""INSERT INTO specialization (specialization_id, display_name, definition, sort_order) VALUES (?, ?, ?, ?)
                           ON CONFLICT (specialization_id) DO UPDATE SET display_name = excluded.display_name,
                           definition = excluded.definition, sort_order = excluded.sort_order""", (sid, name, definition, order))
        methodology = {k: summary.get(k) for k in ("approval", "v1_in_scope", "v2_approved_in_scope", "excluded_POL-001",
                                                     "excluded_verified_false_positives", "pending_excluded_from_statistics",
                                                     "pending_specialization_corrections_counted_under_v1_spec",
                                                     "specializations_corrected", "source_representation_v2")}
        methodology["skills_pipeline"] = summary.get("skills", {}).get("pipeline")
        methodology["counting_rule"] = ("A skill counts for a job once, only with 'required' or 'responsibility' evidence; "
                                        "percentages use unique approved jobs of the active release in that specialization.")
        methodology["limitations"] = [
            "No accuracy estimate: there is no human-validated evaluation sample.",
            "Specializations are Qwen- or Claude-assigned (none human-approved); decision basis recorded per job.",
            "About 913 unflagged in-scope jobs and all out-of-scope jobs were not re-reviewed.",
            "JSearch posting dates are unavailable; some locations are country-level only.",
            "Teammate data came from targeted search queries, so specialization shares are not market shares.",
            "Results describe the collected Headcount Labs, JSearch and LinkedIn datasets, not the whole Saudi labour market.",
        ]
        n_pending_excluded = sum(1 for p in pending if p["counted_in_v2_statistics"] == "no")
        con.execute("""INSERT INTO dataset_release (release_id, label, status, is_active, approved_on, approval_note, source_directory,
                       source_files_json, approved_job_count, pending_job_count, methodology_json)
                       VALUES (?, ?, 'approved', 0, ?, ?, ?, ?, ?, ?, ?)""",
                    (release_id, f"Multi-source job dataset {release_id.upper()}", "2026-11-19", summary.get("approval"),
                     str(release_dir.relative_to(ROOT)).replace("\\", "/") if release_dir.is_relative_to(ROOT) else str(release_dir),
                     json.dumps(files_hash), len(jobs), n_pending_excluded, json.dumps(methodology, ensure_ascii=False)))

        # skills (upsert by canonical name; parents resolved after all names exist)
        cats = {}
        for js in job_skills:
            cats[js["canonical_skill"]] = (js["skill_category"], 1 if js["ranking_eligible"] == "yes" else 0)
        for name, (cat, elig) in cats.items():
            con.execute("""INSERT INTO skill (canonical_name, category, ranking_eligible) VALUES (?, ?, ?)
                           ON CONFLICT (canonical_name) DO UPDATE SET category = excluded.category,
                           ranking_eligible = excluded.ranking_eligible""", (name, cat, elig))
        skill_id = {r[0]: r[1] for r in con.execute("SELECT canonical_name, skill_id FROM skill")}
        for name in cats:
            p = parents.get(name)
            con.execute("UPDATE skill SET parent_skill_id = ? WHERE canonical_name = ?", (skill_id.get(p) if p else None, name))

        # jobs + provenance
        job_pk = {}
        for r in jobs:
            prev = r["v1_primary_specialization"] if r["v1_primary_specialization"] != r["primary_specialization"] else None
            cur = con.execute("""INSERT INTO job (release_id, combined_id, job_title, company, location, country, posted_date,
                    posted_relative_raw, url, publisher, description, final_decision, specialization_id, specialization_basis,
                    specialization_human_approved, previous_specialization_id, decision_basis, confidence, classification_evidence,
                    quality_review_evidence, quality_review_evidence_status, release_status, pending_specialization_correction, change_ids,
                    saudi_location_status, decision_conflict, specialization_conflict, conflict_policy, unresolved_issues, data_quality_flags,
                    needs_manual_review, description_quality, human_review_number, representative_dataset, representative_source_record_id,
                    representative_source_job_id, cross_source_group_id, headcount_duplicate_group_id, teammate_duplicate_group_id, skill_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (release_id, r["combined_id"], r["job_title"], r["company"], nn(r["location"]), nn(r["country"]), nn(r["posted_date"]),
                 nn(r["teammate_posted_relative_raw"]), r["url"], nn(r["publisher"]), r["description"], r["final_decision"],
                 r["primary_specialization"], r["specialization_assigned_by"], 1 if flag(r["specialization_human_approved"]) else 0, prev,
                 r["decision_basis"], nn(r["confidence"]), nn(r["evidence"]), nn(r["quality_review_evidence"]),
                 nn(r["quality_review_evidence_status"]), r["v2_status"], nn(r["v2_pending_specialization_correction"]), nn(r["v2_change_ids"]),
                 nn(r["saudi_location_status"]), flag(r["decision_conflict"]) or 0, flag(r["specialization_conflict"]) or 0,
                 nn(r["conflict_policy"]), nn(r["unresolved_issues"]), nn(r["data_quality_flags"]), flag(r["needs_manual_review"]),
                 nn(r["description_quality"]), int(r["human_review_number"]) if r["human_review_number"].strip() else None,
                 r["source_dataset"], r["source_record_id"], nn(r["source_job_id"]), nn(r["cross_source_group_id"]),
                 nn(r["headcount_duplicate_group_id"]), nn(r["teammate_duplicate_group_id"]), r["skill_status_v2"]))
            pk = cur.lastrowid
            job_pk[r["combined_id"]] = pk
            rep = ("H:" if r["source_dataset"] == "headcount_labs" else "T:") + r["source_record_id"]
            for m in filter(None, r["member_source_record_ids"].split("|")):
                ds = "headcount_labs" if m.startswith("H:") else "teammate_jsearch_linkedin"
                con.execute("INSERT INTO job_source_record VALUES (?, ?, ?, ?)", (pk, ds, m[2:], 1 if m == rep else 0))
            for s in sorted(set(filter(None, r["source_memberships"].split("|")))):
                con.execute("INSERT INTO job_source_membership VALUES (?, ?)", (pk, s))
            urls = [r["url"]] + [u for u in r["all_urls"].split("|") if u and u != r["url"]]
            for u in dict.fromkeys(urls):
                con.execute("INSERT INTO job_url VALUES (?, ?, ?)", (pk, u, 1 if u == r["url"] else 0))

        # job-skill relationships (only for approved jobs of this release)
        skipped = 0
        for js in job_skills:
            pk = job_pk.get(js["combined_id"])
            if pk is None:
                skipped += 1
                continue
            con.execute("INSERT INTO job_skill VALUES (?, ?, ?, ?, ?, ?)",
                        (pk, skill_id[js["canonical_skill"]], js["best_evidence_level"], 1 if js["counts_as_requirement"] == "yes" else 0,
                         js["evidence_source"], js["evidence_snippet"]))
        for p in pending:
            con.execute("INSERT INTO pending_job VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (release_id, p["combined_id"], p["pending_type"], p["counted_in_v2_statistics"], p["job_title"], p["company"],
                         p["source_dataset"], p["source_record_id"], nn(p["url"]), nn(p["v1_final_decision"]), nn(p["v1_specialization"]),
                         nn(p["ai_recommended_decision"]), nn(p["ai_recommended_specialization"]), nn(p["evidence"]), nn(p["reason"])))

        # ---------------- validation against the release files (rollback on any mismatch)
        q = lambda sql, *a: con.execute(sql, a).fetchone()[0]  # noqa: E731
        got_dist = dict(con.execute("SELECT specialization_id, COUNT(*) FROM job WHERE release_id = ? GROUP BY specialization_id", (release_id,)).fetchall())
        checks = {
            "jobs_equal_csv_rows": q("SELECT COUNT(*) FROM job WHERE release_id = ?", release_id) == len(jobs),
            "jobs_equal_summary": q("SELECT COUNT(*) FROM job WHERE release_id = ?", release_id) == summary["v2_approved_in_scope"],
            "unique_combined_ids": q("SELECT COUNT(DISTINCT combined_id) FROM job WHERE release_id = ?", release_id) == len(jobs),
            "nine_specializations": q("SELECT COUNT(*) FROM specialization") == 9,
            "specialization_distribution_matches": all(got_dist.get(s, 0) == dist[s] for s, _, _ in SPECIALIZATIONS),
            "job_skill_rows_equal_csv": q("SELECT COUNT(*) FROM job_skill js JOIN job j ON j.job_pk = js.job_pk WHERE j.release_id = ?", release_id) == len(job_skills),
            "no_job_skill_rows_skipped": skipped == 0,
            "distinct_skills_equal_csv": q("SELECT COUNT(DISTINCT js.skill_id) FROM job_skill js JOIN job j ON j.job_pk = js.job_pk WHERE j.release_id = ?", release_id) == len(cats),
            "pending_rows_equal_csv": q("SELECT COUNT(*) FROM pending_job WHERE release_id = ?", release_id) == len(pending),
            "pending_excluded_not_in_job_table": q("""SELECT COUNT(*) FROM pending_job p JOIN job j ON j.release_id = p.release_id AND j.combined_id = p.combined_id
                                                     WHERE p.release_id = ? AND p.counted_in_statistics = 'no'""", release_id) == 0,
            "source_records_equal_members": q("SELECT COUNT(*) FROM job_source_record s JOIN job j ON j.job_pk = s.job_pk WHERE j.release_id = ?", release_id)
                == sum(len([m for m in r["member_source_record_ids"].split("|") if m]) for r in jobs),
            "one_representative_per_job": q("""SELECT COUNT(*) FROM (SELECT s.job_pk FROM job_source_record s JOIN job j ON j.job_pk = s.job_pk
                                               WHERE j.release_id = ? GROUP BY s.job_pk HAVING SUM(is_representative) = 1)""", release_id) == len(jobs),
            "arabic_text_preserved": q("SELECT COUNT(*) FROM job WHERE release_id = ? AND (description GLOB '*[ء-ي]*' OR job_title GLOB '*[ء-ي]*' OR company GLOB '*[ء-ي]*' OR location GLOB '*[ء-ي]*')", release_id)
                == sum(1 for r in jobs if any("ء" <= ch <= "ي" for ch in r["description"] + r["job_title"] + r["company"] + r["location"])),
            "foreign_keys_ok": not con.execute("PRAGMA foreign_key_check").fetchall(),
        }
        counts = {"jobs": len(jobs), "job_skill": len(job_skills), "distinct_skills": len(cats), "pending": len(pending),
                  "pending_excluded_from_statistics": n_pending_excluded, "specializations": dist}
        if not all(checks.values()):
            raise ValueError(f"import validation failed: {[k for k, v in checks.items() if not v]}")
        if activate:
            con.execute("UPDATE dataset_release SET is_active = 0 WHERE release_id <> ?", (release_id,))
            con.execute("UPDATE dataset_release SET is_active = 1 WHERE release_id = ?", (release_id,))
        con.execute("COMMIT")
        con.execute("UPDATE import_run SET finished_at = ?, status = 'succeeded', counts_json = ? WHERE run_id = ?",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps({"counts": counts, "checks": checks}), run_id))
        con.commit()
        if not quiet:
            print(json.dumps({"release": release_id, "db": str(db_path), "active": activate, "counts": counts, "checks": checks}, indent=1, ensure_ascii=False))
        return {"counts": counts, "checks": checks}
    except Exception as exc:
        con.execute("ROLLBACK") if con.in_transaction else None
        con.execute("UPDATE import_run SET finished_at = ?, status = 'failed', message = ? WHERE run_id = ?",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(exc)[:2000], run_id))
        con.commit()
        raise
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    ap.add_argument("--release-id", default="v2")
    ap.add_argument("--no-activate", action="store_true")
    a = ap.parse_args()
    import_release(a.db, a.release_dir, a.release_id, activate=not a.no_activate)


if __name__ == "__main__":
    main()
