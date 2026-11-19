"""Tech Skills Learning Platform - read-only job-market API (FastAPI).

Run locally (from the project root):
    .venv/Scripts/python -m uvicorn backend.app.main:app --reload
Configuration (environment variables):
    TSLP_DB_PATH        path to the SQLite database (default: database/tech_skills.db)
    TSLP_CORS_ORIGINS   comma-separated allowed origins (default: local dev servers)
"""
import os
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import repository as repo

ROOT = Path(__file__).resolve().parents[2]
API_PREFIX = "/api/v1"
Source = Literal["headcount_labs", "jsearch", "linkedin"]


def db_path() -> Path:
    return Path(os.environ.get("TSLP_DB_PATH", ROOT / "database" / "tech_skills.db"))


def get_con():
    path = db_path()
    if not path.exists():
        raise HTTPException(503, f"database not found at {path}; run database/import_release.py first")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)  # read-only connection
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except repo.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


app = FastAPI(title="Tech Skills Learning Platform - Job Market API", version="1.0.0",
              description="Read-only API over approved, versioned job-market dataset releases. " + repo.SAMPLE_NOTE)
app.add_middleware(CORSMiddleware,
                   allow_origins=[o.strip() for o in os.environ.get("TSLP_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()],
                   allow_methods=["GET"], allow_headers=["*"])

ReleaseQ = Query(None, description="dataset release id; default = active release")


@app.get("/health")
def health():
    return {"status": "ok", "database_present": db_path().exists()}


@app.get(f"{API_PREFIX}/releases")
def releases(con=Depends(get_con)):
    return {"items": repo.list_releases(con)}


@app.get(f"{API_PREFIX}/releases/active")
def active_release(con=Depends(get_con)):
    return call(repo.methodology, con)["release"]


@app.get(f"{API_PREFIX}/methodology")
def methodology(release: str | None = ReleaseQ, con=Depends(get_con)):
    return call(repo.methodology, con, release)


@app.get(f"{API_PREFIX}/specializations")
def specializations(release: str | None = ReleaseQ, con=Depends(get_con)):
    return call(repo.list_specializations, con, release)


@app.get(f"{API_PREFIX}/stats/specializations")
def specialization_stats(release: str | None = ReleaseQ, con=Depends(get_con)):
    return call(repo.specialization_stats, con, release)


@app.get(f"{API_PREFIX}/stats/top-skills")
def all_top_skills(release: str | None = ReleaseQ, limit: int = Query(10, ge=1, le=50), con=Depends(get_con)):
    return call(repo.all_top_skills, con, release, limit)


@app.get(f"{API_PREFIX}/specializations/{{specialization_id}}/top-skills")
def top_skills(specialization_id: str, release: str | None = ReleaseQ, limit: int = Query(10, ge=1, le=50), con=Depends(get_con)):
    return call(repo.top_skills, con, specialization_id, release, limit)


@app.get(f"{API_PREFIX}/skills")
def skills(release: str | None = ReleaseQ, specialization: str | None = None, q: str | None = Query(None, max_length=100),
           include_non_ranking: bool = False, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), con=Depends(get_con)):
    return call(repo.list_skills, con, release, specialization, q, include_non_ranking, page, page_size)


@app.get(f"{API_PREFIX}/locations")
def locations(release: str | None = ReleaseQ, specialization: str | None = None, con=Depends(get_con)):
    return call(repo.list_locations, con, release, specialization)


@app.get(f"{API_PREFIX}/jobs")
def jobs(release: str | None = ReleaseQ, specialization: str | None = None, skill: str | None = None,
         skill_evidence: Literal["required", "any"] = "required", location: str | None = None,
         q: str | None = Query(None, max_length=200), source: Source | None = None,
         page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), con=Depends(get_con)):
    return call(repo.list_jobs, con, release, specialization, skill, location, q, source, skill_evidence, page, page_size)


@app.get(f"{API_PREFIX}/jobs/{{combined_id}}")
def job_detail(combined_id: str, release: str | None = ReleaseQ, con=Depends(get_con)):
    return call(repo.get_job, con, combined_id, release)
