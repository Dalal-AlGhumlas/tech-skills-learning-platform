
import os
import json
from pathlib import Path
from datetime import date

import requests
from dotenv import load_dotenv

# Load API key
ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("HEADCOUNTLABS_API_KEY")

if not API_KEY:
    raise ValueError("Missing API key")

BASE_URL = "https://api.headcountlabs.com"

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

# Test only August 2026
START_DATE = "2026-08-01"
END_DATE = "2026-08-31"

params = {
    "country": "SA",
    "posted_since": START_DATE,
    "posted_until": END_DATE,
    "currentness": ["current", "uncertain", "not_current"] ,
    "has_description": "true",
    "limit": 10
}

print("Fetching August 2026 Saudi jobs...")

response = requests.get(
    f"{BASE_URL}/v1/jobs",
    headers=headers,
    params=params,
    timeout=40
)

print("HTTP Status:", response.status_code)
response.raise_for_status()

jobs = response.json().get("data", [])

# Save original data
raw_dir = Path(__file__).resolve().parent / "raw"
raw_dir.mkdir(exist_ok=True)

output_file = raw_dir / "august_sample.json"

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(jobs, f, ensure_ascii=False, indent=2)

def get_value(field):
    if isinstance(field, dict):
        return field.get("value")
    return field

print("\n=== AUGUST 2026 SAMPLE ===")

for i, job in enumerate(jobs, start=1):
    title = get_value(job.get("title"))
    desc = get_value(job.get("description")) or ""

    matching_postings = [
        p for p in job.get("postings", [])
        if p.get("source_posted_at")
        and START_DATE <= p["source_posted_at"][:10] <= END_DATE
    ]

    print(f"\nJob {i}: {title}")
    print("Description Length:", len(desc))
    print("Matching Postings:", len(matching_postings))

    for post in matching_postings:
        print("Posted Date:", post["source_posted_at"][:10])
        print("Publisher:", post.get("source"))

print("\nTotal Jobs:", len(jobs))
print("Saved to:", output_file)
