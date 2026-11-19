import csv
import sqlite3
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "database"))
RELEASE_DIR = ROOT / "data-analysis/preprocessing/output/multi_source_integration/release_v2"
csv.field_size_limit(2**31 - 1)

import import_release  # noqa: E402


def read_csv(name):
    with open(RELEASE_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def ref():
    """V2 reference outputs (read-only)."""
    return {"jobs": read_csv("combined_in_scope_jobs_v2.csv"), "job_skills": read_csv("job_skills_v2.csv"),
            "top10": read_csv("combined_top10_skills_v2.csv"), "dist": read_csv("combined_specialization_distribution_v2.csv"),
            "pending": read_csv("pending_review_jobs.csv")}


@pytest.fixture(scope="session")
def db_file(tmp_path_factory):
    """Fresh temporary database: V2 imported + activated, plus an inactive copy 'v2_copy' for version-selection tests."""
    path = tmp_path_factory.mktemp("db") / "test_tech_skills.db"
    import_release.import_release(path, RELEASE_DIR, "v2", activate=True, quiet=True)
    import_release.import_release(path, RELEASE_DIR, "v2_copy", activate=False, quiet=True)
    return path


@pytest.fixture()
def con(db_file):
    c = sqlite3.connect(db_file)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.rollback()
    c.close()


@pytest.fixture(scope="session")
def client(db_file):
    import os
    os.environ["TSLP_DB_PATH"] = str(db_file)
    from fastapi.testclient import TestClient
    from backend.app.main import app
    return TestClient(app)
