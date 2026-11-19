-- =============================================================================
-- Tech Skills Learning Platform — job-market dataset schema
-- Target: SQLite 3.35+ (local development). Written in portable SQL so it can be
-- migrated to PostgreSQL (see database/README.md for the few dialect notes).
--
-- Design principles
--   * Every analytical row belongs to a dataset_release; releases are never
--     overwritten by later releases (v3 can be imported alongside v2).
--   * Exactly one release can be active (partial unique index).
--   * Only APPROVED jobs live in `job`; pending cases live in `pending_job`
--     and are never part of analytical statistics.
--   * Missing values stay NULL (no invented dates/locations).
--   * Specializations and skills are reference data shared across releases.
-- =============================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version      INTEGER PRIMARY KEY,
    applied_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    description  TEXT    NOT NULL
);

-- ----------------------------------------------------------------------------- releases
CREATE TABLE IF NOT EXISTS dataset_release (
    release_id          TEXT    PRIMARY KEY,                 -- e.g. 'v2'
    label               TEXT    NOT NULL,
    status              TEXT    NOT NULL CHECK (status IN ('approved', 'draft', 'retired')),
    is_active           INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    approved_on         TEXT,                                -- ISO date
    approval_note       TEXT,
    source_directory    TEXT    NOT NULL,
    source_files_json   TEXT    NOT NULL,                    -- {file: sha256}
    approved_job_count  INTEGER NOT NULL CHECK (approved_job_count >= 0),
    pending_job_count   INTEGER NOT NULL DEFAULT 0,
    methodology_json    TEXT    NOT NULL,                    -- summary / limitations from the release
    imported_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
-- at most one active release
CREATE UNIQUE INDEX IF NOT EXISTS ux_release_single_active ON dataset_release (is_active) WHERE is_active = 1;

-- ----------------------------------------------------------------------------- reference data
CREATE TABLE IF NOT EXISTS specialization (
    specialization_id  TEXT    PRIMARY KEY,                  -- 'ai', 'data_analytics', ...
    display_name       TEXT    NOT NULL UNIQUE,
    definition         TEXT    NOT NULL,
    sort_order         INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS skill (
    skill_id          INTEGER PRIMARY KEY,
    canonical_name    TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    category          TEXT    NOT NULL,
    ranking_eligible  INTEGER NOT NULL CHECK (ranking_eligible IN (0, 1)),
    parent_skill_id   INTEGER REFERENCES skill (skill_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_skill_parent ON skill (parent_skill_id);

-- ----------------------------------------------------------------------------- jobs (approved only)
CREATE TABLE IF NOT EXISTS job (
    job_pk                         INTEGER PRIMARY KEY,
    release_id                     TEXT    NOT NULL REFERENCES dataset_release (release_id) ON DELETE CASCADE,
    combined_id                    TEXT    NOT NULL,           -- stable cross-release job identifier (CMB-xxxxx)
    job_title                      TEXT    NOT NULL,
    company                        TEXT    NOT NULL,
    location                       TEXT,                       -- NULL = unknown
    country                        TEXT,
    posted_date                    TEXT,                       -- ISO date; NULL = not available (e.g. JSearch)
    posted_relative_raw            TEXT,                       -- JSearch relative age text, kept verbatim
    url                            TEXT    NOT NULL,
    publisher                      TEXT,
    description                    TEXT    NOT NULL,           -- full original description (UTF-8)
    -- classification (final, approved)
    final_decision                 TEXT    NOT NULL CHECK (final_decision = 'in_scope'),
    specialization_id              TEXT    NOT NULL REFERENCES specialization (specialization_id),
    specialization_basis           TEXT    NOT NULL,           -- qwen_assigned / claude_* / v2_correction_approved_by_owner (...)
    specialization_human_approved  INTEGER NOT NULL DEFAULT 0 CHECK (specialization_human_approved IN (0, 1)),
    previous_specialization_id     TEXT    REFERENCES specialization (specialization_id),  -- V1 value when corrected
    decision_basis                 TEXT    NOT NULL,           -- human_review / qwen_v3_llm_not_human_validated / claude_llm_not_human_approved
    confidence                     TEXT,
    classification_evidence        TEXT,                       -- original classifier evidence (may be NULL for Qwen gaps)
    quality_review_evidence        TEXT,                       -- verified quote from the quality review (separate)
    quality_review_evidence_status TEXT,
    release_status                 TEXT    NOT NULL,           -- confirmed_in_scope / in_scope_specialization_corrected / ...
    pending_specialization_correction TEXT,                    -- proposed but NOT applied
    change_ids                     TEXT,                       -- V2 change-log ids
    -- quality flags / review status
    saudi_location_status          TEXT,
    decision_conflict              INTEGER NOT NULL DEFAULT 0 CHECK (decision_conflict IN (0, 1)),
    specialization_conflict        INTEGER NOT NULL DEFAULT 0 CHECK (specialization_conflict IN (0, 1)),
    conflict_policy                TEXT,
    unresolved_issues              TEXT,
    data_quality_flags             TEXT,
    needs_manual_review            INTEGER CHECK (needs_manual_review IN (0, 1)),
    description_quality            TEXT,
    human_review_number            INTEGER,
    -- provenance summary (detail in job_source_record / job_url / job_source_membership)
    representative_dataset         TEXT    NOT NULL CHECK (representative_dataset IN ('headcount_labs', 'teammate_jsearch_linkedin')),
    representative_source_record_id TEXT   NOT NULL,
    representative_source_job_id   TEXT,
    cross_source_group_id          TEXT,
    headcount_duplicate_group_id   TEXT,
    teammate_duplicate_group_id    TEXT,
    skill_status                   TEXT    NOT NULL,
    UNIQUE (release_id, combined_id)
);
CREATE INDEX IF NOT EXISTS ix_job_release_spec     ON job (release_id, specialization_id);
CREATE INDEX IF NOT EXISTS ix_job_release_location ON job (release_id, location);
CREATE INDEX IF NOT EXISTS ix_job_combined_id      ON job (combined_id);

-- every original source record merged into the job (H:<record_key> / T:<teammate_record_id>)
CREATE TABLE IF NOT EXISTS job_source_record (
    job_pk             INTEGER NOT NULL REFERENCES job (job_pk) ON DELETE CASCADE,
    source_dataset     TEXT    NOT NULL CHECK (source_dataset IN ('headcount_labs', 'teammate_jsearch_linkedin')),
    source_record_id   TEXT    NOT NULL,
    is_representative  INTEGER NOT NULL CHECK (is_representative IN (0, 1)),
    PRIMARY KEY (job_pk, source_dataset, source_record_id)
);
CREATE INDEX IF NOT EXISTS ix_jsr_record ON job_source_record (source_record_id);

-- original sources the advertisement was found in (headcount_labs / jsearch / linkedin)
CREATE TABLE IF NOT EXISTS job_source_membership (
    job_pk       INTEGER NOT NULL REFERENCES job (job_pk) ON DELETE CASCADE,
    source_name  TEXT    NOT NULL CHECK (source_name IN ('headcount_labs', 'jsearch', 'linkedin')),
    PRIMARY KEY (job_pk, source_name)
);

CREATE TABLE IF NOT EXISTS job_url (
    job_pk         INTEGER NOT NULL REFERENCES job (job_pk) ON DELETE CASCADE,
    url            TEXT    NOT NULL,
    is_primary     INTEGER NOT NULL CHECK (is_primary IN (0, 1)),
    PRIMARY KEY (job_pk, url)
);

-- job-to-skill relationships with evidence (one row per job and skill)
CREATE TABLE IF NOT EXISTS job_skill (
    job_pk                 INTEGER NOT NULL REFERENCES job (job_pk) ON DELETE CASCADE,
    skill_id               INTEGER NOT NULL REFERENCES skill (skill_id),
    evidence_level         TEXT    NOT NULL CHECK (evidence_level IN ('required', 'responsibility', 'preferred', 'unclear', 'company_context')),
    counts_as_requirement  INTEGER NOT NULL CHECK (counts_as_requirement IN (0, 1)),
    evidence_source        TEXT    NOT NULL CHECK (evidence_source IN ('extractor', 'verified_quality_review_supplement')),
    evidence_snippet       TEXT    NOT NULL,
    PRIMARY KEY (job_pk, skill_id)
);
CREATE INDEX IF NOT EXISTS ix_job_skill_skill ON job_skill (skill_id, counts_as_requirement);

-- pending cases: stored for traceability, NEVER part of analytical statistics
CREATE TABLE IF NOT EXISTS pending_job (
    release_id                 TEXT NOT NULL REFERENCES dataset_release (release_id) ON DELETE CASCADE,
    combined_id                TEXT NOT NULL,
    pending_type               TEXT NOT NULL,
    counted_in_statistics      TEXT NOT NULL,
    job_title                  TEXT NOT NULL,
    company                    TEXT NOT NULL,
    source_dataset             TEXT NOT NULL,
    source_record_id           TEXT NOT NULL,
    url                        TEXT,
    previous_decision          TEXT,
    previous_specialization    TEXT,
    ai_recommended_decision    TEXT,
    ai_recommended_specialization TEXT,
    evidence                   TEXT,
    reason                     TEXT,
    PRIMARY KEY (release_id, combined_id, pending_type)
);

-- import audit
CREATE TABLE IF NOT EXISTS import_run (
    run_id        INTEGER PRIMARY KEY,
    release_id    TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    counts_json   TEXT,
    message       TEXT
);

INSERT OR IGNORE INTO schema_version (version, description) VALUES (1, 'initial job-market schema (releases, jobs, skills, provenance)');
