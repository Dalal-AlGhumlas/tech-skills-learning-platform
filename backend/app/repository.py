"""Read-only data access for the job-market dataset (SQLite).

All statistics are computed from UNIQUE APPROVED jobs of ONE dataset release (the active release unless
another is requested). A skill counts for a job only when the job has 'required' or 'responsibility'
evidence for it (counts_as_requirement = 1); percentages use the number of approved jobs in the relevant
specialization (or in the whole release) as denominator. These are sample statistics of the collected
datasets, not labour-market shares.
"""
import json
import math
import sqlite3

SAMPLE_NOTE = ("Counts and percentages describe unique approved job advertisements in the selected dataset release "
               "(Headcount Labs, JSearch and LinkedIn samples). They are not estimates of Saudi labour-market shares.")


class NotFound(Exception):
    pass


# ----------------------------------------------------------------------------- releases
def get_release(con: sqlite3.Connection, release_id: str | None = None) -> dict:
    if release_id:
        row = con.execute("SELECT * FROM dataset_release WHERE release_id = ?", (release_id,)).fetchone()
        if row is None:
            raise NotFound(f"dataset release '{release_id}' not found")
    else:
        row = con.execute("SELECT * FROM dataset_release WHERE is_active = 1").fetchone()
        if row is None:
            raise NotFound("no active dataset release")
    return dict(row)


def _release_public(r: dict) -> dict:
    return {"release_id": r["release_id"], "label": r["label"], "status": r["status"], "is_active": bool(r["is_active"]),
            "approved_on": r["approved_on"], "approved_job_count": r["approved_job_count"],
            "pending_job_count_excluded_from_statistics": r["pending_job_count"], "imported_at": r["imported_at"]}


def list_releases(con) -> list[dict]:
    return [_release_public(dict(r)) for r in con.execute("SELECT * FROM dataset_release ORDER BY imported_at DESC, release_id")]


def methodology(con, release_id=None) -> dict:
    r = get_release(con, release_id)
    m = json.loads(r["methodology_json"])
    return {"release": _release_public(r), "approval": r["approval_note"], "source_directory": r["source_directory"],
            "source_files_sha256": json.loads(r["source_files_json"]), "methodology": m, "statistics_note": SAMPLE_NOTE}


# ----------------------------------------------------------------------------- specializations
def _spec_exists(con, spec_id):
    if con.execute("SELECT 1 FROM specialization WHERE specialization_id = ?", (spec_id,)).fetchone() is None:
        raise NotFound(f"specialization '{spec_id}' not found")


def list_specializations(con, release_id=None) -> dict:
    r = get_release(con, release_id)
    total = r["approved_job_count"]
    rows = con.execute("""SELECT s.specialization_id, s.display_name, s.definition, s.sort_order, COUNT(j.job_pk) AS job_count
                          FROM specialization s LEFT JOIN job j ON j.specialization_id = s.specialization_id AND j.release_id = ?
                          GROUP BY s.specialization_id ORDER BY s.sort_order""", (r["release_id"],)).fetchall()
    items = [{"specialization_id": x["specialization_id"], "display_name": x["display_name"], "definition": x["definition"],
              "job_count": x["job_count"], "pct_of_release_jobs": round(100 * x["job_count"] / total, 2) if total else 0.0} for x in rows]
    return {"release_id": r["release_id"], "total_approved_jobs": total, "items": items, "note": SAMPLE_NOTE}


def specialization_stats(con, release_id=None) -> dict:
    r = get_release(con, release_id)
    rid = r["release_id"]
    base = list_specializations(con, rid)
    for it in base["items"]:
        sid = it["specialization_id"]
        q = lambda sql: con.execute(sql, (rid, sid)).fetchone()[0]  # noqa: E731
        it["distinct_required_skills"] = q("""SELECT COUNT(DISTINCT js.skill_id) FROM job_skill js JOIN job j ON j.job_pk = js.job_pk
                                              JOIN skill s ON s.skill_id = js.skill_id
                                              WHERE j.release_id = ? AND j.specialization_id = ? AND js.counts_as_requirement = 1 AND s.ranking_eligible = 1""")
        it["jobs_without_required_skill"] = q("""SELECT COUNT(*) FROM job j WHERE j.release_id = ? AND j.specialization_id = ? AND NOT EXISTS
                                                 (SELECT 1 FROM job_skill js JOIN skill s ON s.skill_id = js.skill_id
                                                  WHERE js.job_pk = j.job_pk AND js.counts_as_requirement = 1 AND s.ranking_eligible = 1)""")
        it["jobs_with_specialization_correction"] = q("SELECT COUNT(*) FROM job WHERE release_id = ? AND specialization_id = ? AND previous_specialization_id IS NOT NULL")
        it["jobs_human_reviewed_decision"] = q("SELECT COUNT(*) FROM job WHERE release_id = ? AND specialization_id = ? AND decision_basis = 'human_review'")
        top = top_skills(con, sid, rid, limit=3)["items"]
        it["top_3_skills"] = [{"canonical_name": t["canonical_name"], "jobs_requiring_skill": t["jobs_requiring_skill"],
                               "pct_of_specialization_jobs": t["pct_of_specialization_jobs"]} for t in top]
    sources = dict(con.execute("SELECT source_name, COUNT(*) FROM job_source_membership m JOIN job j ON j.job_pk = m.job_pk WHERE j.release_id = ? GROUP BY source_name", (rid,)).fetchall())
    base["jobs_by_original_source_membership"] = sources
    base["jobs_by_representative_dataset"] = dict(con.execute("SELECT representative_dataset, COUNT(*) FROM job WHERE release_id = ? GROUP BY representative_dataset", (rid,)).fetchall())
    return base


def top_skills(con, specialization_id, release_id=None, limit=10) -> dict:
    r = get_release(con, release_id)
    _spec_exists(con, specialization_id)
    rid = r["release_id"]
    denom = con.execute("SELECT COUNT(*) FROM job WHERE release_id = ? AND specialization_id = ?", (rid, specialization_id)).fetchone()[0]
    rows = con.execute("""SELECT s.skill_id, s.canonical_name, s.category, COUNT(DISTINCT js.job_pk) AS jobs,
                                 SUM(CASE WHEN js.evidence_level = 'required' THEN 1 ELSE 0 END) AS explicit,
                                 SUM(CASE WHEN js.evidence_level = 'responsibility' THEN 1 ELSE 0 END) AS resp
                          FROM job_skill js JOIN job j ON j.job_pk = js.job_pk JOIN skill s ON s.skill_id = js.skill_id
                          WHERE j.release_id = ? AND j.specialization_id = ? AND js.counts_as_requirement = 1 AND s.ranking_eligible = 1
                          GROUP BY s.skill_id ORDER BY jobs DESC, explicit DESC, s.canonical_name ASC""", (rid, specialization_id)).fetchall()
    items, prev, rank = [], None, 0
    for i, x in enumerate(rows[:limit], start=1):
        if x["jobs"] != prev:
            rank, prev = i, x["jobs"]
        items.append({"rank": rank, "skill_id": x["skill_id"], "canonical_name": x["canonical_name"], "category": x["category"],
                      "jobs_requiring_skill": x["jobs"], "jobs_explicit_requirement": x["explicit"], "jobs_responsibility_only": x["resp"],
                      "pct_of_specialization_jobs": round(100 * x["jobs"] / denom, 2) if denom else 0.0})
    tie = len(rows) > limit and limit > 0 and rows[limit]["jobs"] == rows[limit - 1]["jobs"]
    return {"release_id": rid, "specialization_id": specialization_id, "specialization_job_count": denom,
            "tie_at_cutoff": bool(tie), "items": items,
            "counting_rule": "unique approved jobs with required/responsibility evidence; denominator = approved jobs in the specialization",
            "note": SAMPLE_NOTE}


def all_top_skills(con, release_id=None, limit=10) -> dict:
    r = get_release(con, release_id)
    specs = [x[0] for x in con.execute("SELECT specialization_id FROM specialization ORDER BY sort_order")]
    return {"release_id": r["release_id"], "items": {s: top_skills(con, s, r["release_id"], limit) for s in specs}, "note": SAMPLE_NOTE}


# ----------------------------------------------------------------------------- skills
def list_skills(con, release_id=None, specialization_id=None, q=None, include_non_ranking=False, page=1, page_size=50) -> dict:
    r = get_release(con, release_id)
    rid = r["release_id"]
    where, args = ["j.release_id = ?", "js.counts_as_requirement = 1"], [rid]
    if specialization_id:
        _spec_exists(con, specialization_id)
        where.append("j.specialization_id = ?")
        args.append(specialization_id)
    if not include_non_ranking:
        where.append("s.ranking_eligible = 1")
    if q:
        where.append("s.canonical_name LIKE ?")
        args.append(f"%{q}%")
    denom = con.execute("SELECT COUNT(*) FROM job WHERE release_id = ?" + (" AND specialization_id = ?" if specialization_id else ""),
                        [rid] + ([specialization_id] if specialization_id else [])).fetchone()[0]
    base = f"""FROM job_skill js JOIN job j ON j.job_pk = js.job_pk JOIN skill s ON s.skill_id = js.skill_id WHERE {' AND '.join(where)}"""
    total = con.execute(f"SELECT COUNT(DISTINCT s.skill_id) {base}", args).fetchone()[0]
    rows = con.execute(f"""SELECT s.skill_id, s.canonical_name, s.category, s.ranking_eligible, p.canonical_name AS parent,
                                  COUNT(DISTINCT js.job_pk) AS jobs
                           {base.replace('JOIN skill s ON s.skill_id = js.skill_id', 'JOIN skill s ON s.skill_id = js.skill_id LEFT JOIN skill p ON p.skill_id = s.parent_skill_id')}
                           GROUP BY s.skill_id ORDER BY jobs DESC, s.canonical_name ASC LIMIT ? OFFSET ?""",
                       args + [page_size, (page - 1) * page_size]).fetchall()
    items = [{"skill_id": x["skill_id"], "canonical_name": x["canonical_name"], "category": x["category"],
              "ranking_eligible": bool(x["ranking_eligible"]), "parent_skill": x["parent"], "jobs_requiring_skill": x["jobs"],
              "pct_of_jobs": round(100 * x["jobs"] / denom, 2) if denom else 0.0} for x in rows]
    return {"release_id": rid, "specialization_id": specialization_id, "denominator_jobs": denom,
            "page": page, "page_size": page_size, "total": total, "pages": math.ceil(total / page_size) if page_size else 0,
            "items": items, "note": SAMPLE_NOTE}


# ----------------------------------------------------------------------------- jobs
JOB_SUMMARY_COLS = ("combined_id", "job_title", "company", "location", "country", "posted_date", "url", "publisher",
                    "specialization_id", "specialization_basis", "decision_basis", "saudi_location_status", "release_status")


def _job_filters(release_id, specialization_id, skill, location, q, source, skill_evidence):
    where, args = ["j.release_id = ?"], [release_id]
    if specialization_id:
        where.append("j.specialization_id = ?")
        args.append(specialization_id)
    if skill:
        cond = "js.counts_as_requirement = 1" if skill_evidence == "required" else "1 = 1"
        where.append(f"""EXISTS (SELECT 1 FROM job_skill js JOIN skill s ON s.skill_id = js.skill_id
                                WHERE js.job_pk = j.job_pk AND s.canonical_name = ? COLLATE NOCASE AND {cond})""")
        args.append(skill)
    if location:
        if location.lower() == "unknown":
            where.append("j.location IS NULL")
        else:
            where.append("j.location = ? COLLATE NOCASE")
            args.append(location)
    if source:
        where.append("EXISTS (SELECT 1 FROM job_source_membership m WHERE m.job_pk = j.job_pk AND m.source_name = ?)")
        args.append(source)
    if q:
        where.append("(instr(lower(j.job_title), lower(?)) > 0 OR instr(lower(j.company), lower(?)) > 0 OR instr(lower(j.description), lower(?)) > 0)")
        args += [q, q, q]
    return " AND ".join(where), args


def list_jobs(con, release_id=None, specialization_id=None, skill=None, location=None, q=None, source=None,
              skill_evidence="required", page=1, page_size=20) -> dict:
    r = get_release(con, release_id)
    if specialization_id:
        _spec_exists(con, specialization_id)
    where, args = _job_filters(r["release_id"], specialization_id, skill, location, q, source, skill_evidence)
    total = con.execute(f"SELECT COUNT(*) FROM job j WHERE {where}", args).fetchone()[0]
    rows = con.execute(f"SELECT {', '.join('j.' + c for c in JOB_SUMMARY_COLS)} FROM job j WHERE {where} ORDER BY j.combined_id LIMIT ? OFFSET ?",
                       args + [page_size, (page - 1) * page_size]).fetchall()
    return {"release_id": r["release_id"], "filters": {"specialization": specialization_id, "skill": skill, "skill_evidence": skill_evidence,
                                                        "location": location, "q": q, "source": source},
            "page": page, "page_size": page_size, "total": total, "pages": math.ceil(total / page_size) if page_size else 0,
            "items": [dict(x) for x in rows]}


def get_job(con, combined_id, release_id=None) -> dict:
    r = get_release(con, release_id)
    row = con.execute("SELECT * FROM job WHERE release_id = ? AND combined_id = ?", (r["release_id"], combined_id)).fetchone()
    if row is None:
        raise NotFound(f"job '{combined_id}' not found in release '{r['release_id']}'")
    job = dict(row)
    pk = job.pop("job_pk")
    for k in ("decision_conflict", "specialization_conflict", "specialization_human_approved"):
        job[k] = bool(job[k])
    job["needs_manual_review"] = None if job["needs_manual_review"] is None else bool(job["needs_manual_review"])
    job["skills"] = [dict(x) | {"counts_as_requirement": bool(x["counts_as_requirement"]), "ranking_eligible": bool(x["ranking_eligible"])}
                     for x in con.execute("""SELECT s.canonical_name, s.category, s.ranking_eligible, js.evidence_level, js.counts_as_requirement,
                                                    js.evidence_source, js.evidence_snippet
                                             FROM job_skill js JOIN skill s ON s.skill_id = js.skill_id WHERE js.job_pk = ?
                                             ORDER BY js.counts_as_requirement DESC, s.canonical_name""", (pk,))]
    job["source_records"] = [dict(x) | {"is_representative": bool(x["is_representative"])}
                             for x in con.execute("SELECT source_dataset, source_record_id, is_representative FROM job_source_record WHERE job_pk = ? ORDER BY is_representative DESC, source_record_id", (pk,))]
    job["source_memberships"] = [x[0] for x in con.execute("SELECT source_name FROM job_source_membership WHERE job_pk = ? ORDER BY source_name", (pk,))]
    job["urls"] = [dict(x) | {"is_primary": bool(x["is_primary"])} for x in con.execute("SELECT url, is_primary FROM job_url WHERE job_pk = ? ORDER BY is_primary DESC, url", (pk,))]
    return job


def list_locations(con, release_id=None, specialization_id=None) -> dict:
    r = get_release(con, release_id)
    args = [r["release_id"]] + ([specialization_id] if specialization_id else [])
    rows = con.execute("SELECT COALESCE(location, 'Unknown') AS location, COUNT(*) AS jobs FROM job WHERE release_id = ?"
                       + (" AND specialization_id = ?" if specialization_id else "") + " GROUP BY location ORDER BY jobs DESC, location", args).fetchall()
    return {"release_id": r["release_id"], "items": [dict(x) for x in rows],
            "note": "'Unknown' = no location in the source data (not invented). Some locations are country-level only."}
