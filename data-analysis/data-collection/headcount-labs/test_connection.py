
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# Read API key
ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("HEADCOUNTLABS_API_KEY")

if not API_KEY:
    raise ValueError("API key missing from .env")

BASE_URL = "https://api.headcountlabs.com"

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

# Small test: 5 current Saudi jobs
params = {
    "country": "SA",
    "currentness": "current",
    "limit": 5
}

print("Testing Headcount Labs API...", flush=True)

try:
    response = requests.get(
        f"{BASE_URL}/v1/jobs",
        headers=headers,
        params=params,
        timeout=30
    )

    print("HTTP Status:", response.status_code)

    response.raise_for_status()

    data = response.json()
    jobs = data.get("data", [])

    print("Jobs retrieved:", len(jobs))

    for i, job in enumerate(jobs, 1):
        title = job.get("title")

        if isinstance(title, dict):
            title = title.get("value")

        print(f"Job {i}: {title}")

    print("API connection successful!")

except requests.exceptions.HTTPError:
    print("API returned an error:")
    print(response.text[:1000])

except requests.exceptions.RequestException as error:
    print("Connection failed:", error)


import json

# Create a folder for raw data
raw_dir = Path(__file__).resolve().parent / "raw"
raw_dir.mkdir(exist_ok=True)

# Save the original API response
output_file = raw_dir / "sample_jobs.json"

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(jobs, f, ensure_ascii=False, indent=2)

print("\n=== DATA INSPECTION ===")
print("Saved sample to:", output_file)

for i, job in enumerate(jobs, start=1):
    title = job.get("title")
    description = job.get("description")

    if isinstance(title, dict):
        title = title.get("value")

    if isinstance(description, dict):
        description = description.get("value")

    postings = job.get("postings") or []

    print(f"\nJob {i}: {title}")
    print("Description length:", len(description or ""))
    print("Number of postings:", len(postings))

    for post in postings[:3]:
        print("  Publisher:", post.get("source"))
        print("  Posted date:", post.get("source_posted_at"))

print("\nAvailable job fields:")
if jobs:
    print(list(jobs[0].keys()))
