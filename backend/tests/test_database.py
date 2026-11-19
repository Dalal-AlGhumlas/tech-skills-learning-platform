"""Database schema, constraints and import completeness (against the V2 reference CSVs)."""
import collections
import sqlite3

import pytest

import import_release
from conftest import RELEASE_DIR

SPECS = ["ai", "data_analytics", "software_development", "cloud_devops", "cybersecurity",
         "infrastructure_networking", "qa_testing", "database_enterprise_systems", "uiux_technical_products"]


def scalar(con, sql, *args):
    return con.execute(sql, args).fetchone()[0]


# ----------------------------------------------------------------------------- import completeness
def test_all_approved_jobs_imported(con, ref):
    assert scalar(con, "SELECT COUNT(*) FROM job WHERE release_id = 'v2'") == len(ref["jobs"]) == 1137
    assert {r[0] for r in con.execute("SELECT combined_id FROM job WHERE release_id = 'v2'")} == {j["combined_id"] for j in ref["jobs"]}


def test_nine_specializations(con):
    assert [r[0] for r in con.execute("SELECT specialization_id FROM specialization ORDER BY sort_order")] == SPECS


def test_specialization_counts_match_v2(con, ref):
    got = dict(con.execute("SELECT specialization_id, COUNT(*) FROM job WHERE release_id = 'v2' GROUP BY specialization_id").fetchall())
    exp = {d["specialization"]: int(d["v2_in_scope_jobs"]) for d in ref["dist"] if d["specialization"] in SPECS}
    assert got == exp
    assert sum(got.values()) == 1137


def test_distinct_skills_and_job_skill_rows(con, ref):
    assert scalar(con, "SELECT COUNT(*) FROM job_skill js JOIN job j USING (job_pk) WHERE j.release_id = 'v2'") == len(ref["job_skills"])
    assert scalar(con, "SELECT COUNT(DISTINCT skill_id) FROM job_skill js JOIN job j USING (job_pk) WHERE j.release_id = 'v2'") == \
        len({r["canonical_skill"] for r in ref["job_skills"]})


def test_provenance_preserved(con, ref):
    for j in ref["jobs"][:200]:
        row = con.execute("SELECT * FROM job WHERE release_id = 'v2' AND combined_id = ?", (j["combined_id"],)).fetchone()
        assert row["url"] == j["url"] and row["representative_source_record_id"] == j["source_record_id"]
        assert row["description"] == j["description"]
        assert row["decision_basis"] == j["decision_basis"] and row["specialization_basis"] == j["specialization_assigned_by"]
        members = {f"{'H' if r[0] == 'headcount_labs' else 'T'}:{r[1]}" for r in
                   con.execute("SELECT source_dataset, source_record_id FROM job_source_record WHERE job_pk = ?", (row["job_pk"],))}
        assert members == set(j["member_source_record_ids"].split("|"))


def test_missing_values_stay_null_not_invented(con, ref):
    exp_no_date = sum(1 for j in ref["jobs"] if not j["posted_date"].strip())
    exp_no_loc = sum(1 for j in ref["jobs"] if not j["location"].strip())
    assert scalar(con, "SELECT COUNT(*) FROM job WHERE release_id = 'v2' AND posted_date IS NULL") == exp_no_date
    assert scalar(con, "SELECT COUNT(*) FROM job WHERE release_id = 'v2' AND location IS NULL") == exp_no_loc
    assert scalar(con, "SELECT COUNT(*) FROM job WHERE posted_date = '' OR location = ''") == 0


def test_pending_jobs_not_in_approved_table(con, ref):
    excluded = {p["combined_id"] for p in ref["pending"] if p["counted_in_v2_statistics"] == "no"}
    assert len(excluded) == 27
    assert scalar(con, "SELECT COUNT(*) FROM pending_job WHERE release_id = 'v2'") == len(ref["pending"])
    got = {r[0] for r in con.execute("SELECT combined_id FROM job WHERE release_id = 'v2'")}
    assert not (got & excluded)


def test_specialization_corrections_keep_previous_value(con, ref):
    corrected = {j["combined_id"]: j["v1_primary_specialization"] for j in ref["jobs"] if j["v1_primary_specialization"] != j["primary_specialization"]}
    assert len(corrected) == 10
    got = dict(con.execute("SELECT combined_id, previous_specialization_id FROM job WHERE release_id = 'v2' AND previous_specialization_id IS NOT NULL").fetchall())
    assert got == corrected


# ----------------------------------------------------------------------------- constraints & integrity
def test_foreign_keys_and_integrity(con):
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_duplicate_job_in_release_rejected(con):
    row = dict(con.execute("SELECT * FROM job WHERE release_id = 'v2' LIMIT 1").fetchone())
    row.pop("job_pk")
    cols = ", ".join(row)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(f"INSERT INTO job ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def test_duplicate_job_skill_rejected(con):
    js = con.execute("SELECT * FROM job_skill LIMIT 1").fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO job_skill VALUES (?, ?, ?, ?, ?, ?)", tuple(js))


def test_invalid_specialization_rejected(con):
    row = dict(con.execute("SELECT * FROM job WHERE release_id = 'v2' LIMIT 1").fetchone())
    row.pop("job_pk")
    row.update(combined_id="CMB-TEST-1", specialization_id="not_a_spec")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(f"INSERT INTO job ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def test_only_in_scope_decisions_allowed(con):
    row = dict(con.execute("SELECT * FROM job WHERE release_id = 'v2' LIMIT 1").fetchone())
    row.pop("job_pk")
    row.update(combined_id="CMB-TEST-2", final_decision="needs_review")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(f"INSERT INTO job ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def test_single_active_release(con):
    assert scalar(con, "SELECT COUNT(*) FROM dataset_release WHERE is_active = 1") == 1
    assert scalar(con, "SELECT release_id FROM dataset_release WHERE is_active = 1") == "v2"
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE dataset_release SET is_active = 1 WHERE release_id = 'v2_copy'")


def test_releases_coexist_without_overwriting(con):
    assert scalar(con, "SELECT COUNT(*) FROM job WHERE release_id = 'v2_copy'") == 1137
    assert scalar(con, "SELECT COUNT(*) FROM job WHERE release_id = 'v2'") == 1137


def test_reimport_is_idempotent(db_file):
    c = sqlite3.connect(db_file)
    before = [c.execute(q).fetchone()[0] for q in ("SELECT COUNT(*) FROM job", "SELECT COUNT(*) FROM job_skill", "SELECT COUNT(*) FROM skill",
                                                   "SELECT COUNT(*) FROM job_source_record", "SELECT group_concat(skill_id) FROM (SELECT skill_id FROM skill ORDER BY canonical_name)")]
    c.close()
    import_release.import_release(db_file, RELEASE_DIR, "v2", activate=True, quiet=True)
    c = sqlite3.connect(db_file)
    after = [c.execute(q).fetchone()[0] for q in ("SELECT COUNT(*) FROM job", "SELECT COUNT(*) FROM job_skill", "SELECT COUNT(*) FROM skill",
                                                  "SELECT COUNT(*) FROM job_source_record", "SELECT group_concat(skill_id) FROM (SELECT skill_id FROM skill ORDER BY canonical_name)")]
    assert after == before  # same rows, stable skill ids
    assert c.execute("SELECT release_id FROM dataset_release WHERE is_active = 1").fetchone()[0] == "v2"
    c.close()


def test_failed_validation_rolls_back(tmp_path, db_file):
    import shutil
    bad = tmp_path / "bad_release"
    shutil.copytree(RELEASE_DIR, bad, ignore=shutil.ignore_patterns("*.py"))
    dist = (bad / "combined_specialization_distribution_v2.csv").read_text(encoding="utf-8-sig").replace(",ai,158,", ",ai,999,")
    (bad / "combined_specialization_distribution_v2.csv").write_text(dist, encoding="utf-8-sig")
    test_db = tmp_path / "rb.db"
    shutil.copy(db_file, test_db)
    with pytest.raises(ValueError):
        import_release.import_release(test_db, bad, "v2", activate=True, quiet=True)
    c = sqlite3.connect(test_db)
    assert c.execute("SELECT COUNT(*) FROM job WHERE release_id = 'v2'").fetchone()[0] == 1137  # previous state intact
    assert c.execute("SELECT status FROM import_run ORDER BY run_id DESC LIMIT 1").fetchone()[0] == "failed"
    c.close()


# ----------------------------------------------------------------------------- UTF-8 / Arabic
def test_arabic_and_english_text_roundtrip(con, ref):
    arabic = [j for j in ref["jobs"] if any("؀" <= ch <= "ۿ" for ch in j["description"] + j["job_title"])]
    assert arabic, "V2 contains Arabic text"
    for j in arabic:
        row = con.execute("SELECT job_title, description, company FROM job WHERE release_id = 'v2' AND combined_id = ?", (j["combined_id"],)).fetchone()
        assert (row[0], row[1], row[2]) == (j["job_title"], j["description"], j["company"])
