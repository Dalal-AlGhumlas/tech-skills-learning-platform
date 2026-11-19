# Database: job-market dataset

A local development database in **SQLite**, built into Python with no server and no credentials. The schema is written in portable SQL so it can move to PostgreSQL later.

## Build / rebuild (from the project root)

```bash
.venv/Scripts/python -B database/import_release.py          # imports release V2 into database/tech_skills.db and activates it
```

* **Source:** only the approved V2 release in `data-analysis/preprocessing/output/multi_source_integration/release_v2/`, read-only.
* **Idempotent:** re-running replaces only that release's rows inside one transaction. Other releases are untouched, and skill IDs stay stable.
* **Validated:** after inserting, the importer checks the counts against the V2 files and rolls back on any mismatch. Checks cover:
  * 1,137 jobs and the per-specialization distribution;
  * 12,189 job–skill links and 332 distinct skills;
  * 41 pending rows;
  * provenance and the single representative record per job;
  * Arabic text;
  * foreign keys.
* **Audit:** every run is logged in `import_run`.
* **Ignored by git:** `tech_skills.db` is generated (`database/.gitignore`).

**Future releases** are imported next to V2 without overwriting it:

```bash
.venv/Scripts/python -B database/import_release.py --release-dir <release_v3_dir> --release-id v3     # becomes active
.venv/Scripts/python -B database/import_release.py --release-dir <dir> --release-id v3 --no-activate  # keep v2 active
```

The importer currently expects the V2 file layout and `v2_summary.json` field names. A future release with a different layout would need a small adapter.

## Schema (`schema.sql`)

```
dataset_release (release_id PK, is_active [only one active], status, source file hashes, methodology_json, counts)
   │ 1
   │ *
job (job_pk PK, UNIQUE(release_id, combined_id), FK specialization, FK previous_specialization,
     full description, url, location/date NULL when unknown, classification provenance,
     evidence, quality flags, review status)
   ├──* job_source_record      (PK job_pk+dataset+record_id; original H:/T: record ids, one representative)
   ├──* job_source_membership  (PK job_pk+source; headcount_labs / jsearch / linkedin)
   ├──* job_url                (PK job_pk+url; primary + alternative URLs)
   └──* job_skill              (PK job_pk+skill_id; evidence_level, counts_as_requirement, evidence_source, evidence_snippet)
                                      │ *
                                      │ 1
specialization (9 rows, PK id)    skill (skill_id PK, canonical_name UNIQUE NOCASE, category, ranking_eligible, parent_skill_id FK self)
pending_job (release_id, combined_id, pending_type): traceability only; NEVER counted in statistics
import_run, schema_version
```

**Referential integrity**
* Deleting a release cascades to its jobs, provenance, job–skill links and pending rows.
* Skills and specializations are shared reference data and are not cascaded.
* `job.final_decision` must be `in_scope`. Only approved jobs can be stored; pending jobs live in `pending_job`.

**Indexes**
* `(release_id, specialization_id)`, `(release_id, location)` and `combined_id` on `job`.
* `(skill_id, counts_as_requirement)` on `job_skill`.
* A partial unique index on the active release flag.

## Moving to PostgreSQL later

The schema needs only small changes:

| SQLite | PostgreSQL |
|---|---|
| `INTEGER PRIMARY KEY` | `BIGINT GENERATED ALWAYS AS IDENTITY` |
| `COLLATE NOCASE` | `citext`, or a unique index on `lower(canonical_name)` |
| `strftime(...)` defaults | `now()` |
| `PRAGMA` lines | remove |
| `*_json TEXT` | `jsonb` |

The partial unique index, `ON CONFLICT … DO UPDATE`, `CHECK` constraints and `ON DELETE CASCADE` already work the same way in PostgreSQL.
