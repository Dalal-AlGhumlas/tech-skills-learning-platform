# Backend: job-market API (read-only)

**Stack:** Python 3.13, FastAPI, SQLite (`database/tech_skills.db`). Pinned versions are in `backend/requirements.txt`.

## Setup (from the project root)

```bash
.venv/Scripts/python -m pip install -r backend/requirements.txt
.venv/Scripts/python -B database/import_release.py                 # build the local database from release V2
.venv/Scripts/python -m uvicorn backend.app.main:app --reload       # http://127.0.0.1:8000/docs
.venv/Scripts/python -B -m pytest backend/tests -p no:cacheprovider # tests (build their own temporary database)
```

**Environment variables (optional):**
* `TSLP_DB_PATH`: the database file to use.
* `TSLP_CORS_ORIGINS`: comma-separated allowed origins. The default is `http://localhost:3000,http://localhost:5173`.

The API opens the database **read-only**.

## Endpoints (`/api/v1`, all `GET`)

Every endpoint accepts `?release=<id>`. The default is the active release (V2).

| Endpoint | Purpose |
|---|---|
| `/health` | liveness + database presence |
| `/releases`, `/releases/active` | dataset versions |
| `/methodology` | approval, source file hashes, counting rule, limitations, sample disclaimer |
| `/specializations` | 9 specializations with job counts and % of release jobs |
| `/stats/specializations` | per specialization: jobs, distinct required skills, jobs without skills, corrected specializations, human-reviewed decisions, top 3 skills; source breakdown |
| `/specializations/{id}/top-skills?limit=10` | ranked required skills (competition ranking, tie flag) |
| `/stats/top-skills?limit=10` | Top N for all nine specializations |
| `/skills?specialization=&q=&include_non_ranking=&page=&page_size=` | skills with job counts and % (denominator returned) |
| `/locations?specialization=` | available locations with counts (`Unknown` = no location in source) |
| `/jobs?specialization=&skill=&skill_evidence=required\|any&location=&source=headcount_labs\|jsearch\|linkedin&q=&page=&page_size=` | search and filter approved jobs (`page_size` ≤ 100) |
| `/jobs/{combined_id}` | full job: description, URLs, provenance, classification basis, evidence, quality flags, skills with evidence |

## Counting rules

* Statistics count unique approved jobs of one release.
* A skill counts once per job, only with `required` or `responsibility` evidence.
* Certifications, methodologies and similar items are excluded from rankings.
* Percentages use the specialization's (or the release's) approved job count. Each response returns its denominator.
* Pending jobs are never exposed or counted.
* Results are sample statistics, **not labour-market shares**. Every statistics response includes that note.
