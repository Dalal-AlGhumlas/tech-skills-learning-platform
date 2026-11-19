"""API behaviour, compared against the V2 reference CSV outputs."""
import collections

SPECS = ["ai", "data_analytics", "software_development", "cloud_devops", "cybersecurity",
         "infrastructure_networking", "qa_testing", "database_enterprise_systems", "uiux_technical_products"]
P = "/api/v1"


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_active_release_and_methodology(client):
    r = client.get(f"{P}/releases/active").json()
    assert r["release_id"] == "v2" and r["approved_job_count"] == 1137 and r["pending_job_count_excluded_from_statistics"] == 27
    m = client.get(f"{P}/methodology").json()
    assert m["release"]["release_id"] == "v2"
    assert m["methodology"]["v2_approved_in_scope"] == 1137
    assert "not estimates of Saudi labour-market shares" in m["statistics_note"]
    assert len(m["methodology"]["limitations"]) >= 5


def test_release_selection(client):
    ids = {r["release_id"] for r in client.get(f"{P}/releases").json()["items"]}
    assert {"v2", "v2_copy"} <= ids
    assert client.get(f"{P}/specializations", params={"release": "v2_copy"}).json()["release_id"] == "v2_copy"
    assert client.get(f"{P}/specializations").json()["release_id"] == "v2"
    assert client.get(f"{P}/jobs", params={"release": "does_not_exist"}).status_code == 404


def test_specializations_match_distribution(client, ref):
    body = client.get(f"{P}/specializations").json()
    exp = {d["specialization"]: (int(d["v2_in_scope_jobs"]), float(d["pct_of_v2_in_scope"])) for d in ref["dist"] if d["specialization"] in SPECS}
    got = {i["specialization_id"]: (i["job_count"], i["pct_of_release_jobs"]) for i in body["items"]}
    assert got == exp
    assert body["total_approved_jobs"] == 1137


def test_specialization_stats(client):
    body = client.get(f"{P}/stats/specializations").json()
    assert sum(i["job_count"] for i in body["items"]) == 1137
    assert sum(body["jobs_by_representative_dataset"].values()) == 1137
    assert all(len(i["top_3_skills"]) == 3 for i in body["items"])


def test_top10_skills_match_v2_reference(client, ref):
    exp = collections.defaultdict(list)
    for t in ref["top10"]:
        exp[t["specialization"]].append((int(t["rank"]), t["canonical_skill"], int(t["jobs_requiring_skill"]), float(t["pct_jobs_requiring_skill"]),
                                         int(t["specialization_v2_jobs"])))
    for sp in SPECS:
        body = client.get(f"{P}/specializations/{sp}/top-skills").json()
        got = [(i["rank"], i["canonical_name"], i["jobs_requiring_skill"], i["pct_of_specialization_jobs"], body["specialization_job_count"]) for i in body["items"]]
        assert got == exp[sp], sp


def test_all_top_skills_endpoint(client):
    body = client.get(f"{P}/stats/top-skills", params={"limit": 5}).json()
    assert set(body["items"]) == set(SPECS) and all(len(v["items"]) == 5 for v in body["items"].values())


def test_skill_job_counts_match_reference(client, ref):
    jobs_by_skill = collections.defaultdict(set)
    for r in ref["job_skills"]:
        if r["counts_as_requirement"] == "yes" and r["ranking_eligible"] == "yes":
            jobs_by_skill[r["canonical_skill"]].add(r["combined_id"])
    body = client.get(f"{P}/skills", params={"page_size": 200}).json()
    assert body["denominator_jobs"] == 1137
    items = body["items"]
    while body["page"] < body["pages"]:
        body = client.get(f"{P}/skills", params={"page_size": 200, "page": body["page"] + 1}).json()
        items += body["items"]
    assert {i["canonical_name"]: i["jobs_requiring_skill"] for i in items} == {k: len(v) for k, v in jobs_by_skill.items()}
    for i in items:
        assert i["pct_of_jobs"] == round(100 * i["jobs_requiring_skill"] / 1137, 2)


def test_skills_by_specialization_denominator(client, ref):
    n = sum(1 for j in ref["jobs"] if j["primary_specialization"] == "cybersecurity")
    body = client.get(f"{P}/skills", params={"specialization": "cybersecurity", "q": "SIEM"}).json()
    assert body["denominator_jobs"] == n
    siem = next(i for i in body["items"] if i["canonical_name"] == "SIEM")
    assert siem["pct_of_jobs"] == round(100 * siem["jobs_requiring_skill"] / n, 2)


def test_jobs_pagination(client, ref):
    seen, page = [], 1
    while True:
        body = client.get(f"{P}/jobs", params={"page": page, "page_size": 100}).json()
        seen += [i["combined_id"] for i in body["items"]]
        if page >= body["pages"]:
            break
        page += 1
    assert body["total"] == 1137 and len(seen) == 1137 and len(set(seen)) == 1137
    assert seen == sorted(j["combined_id"] for j in ref["jobs"])
    assert client.get(f"{P}/jobs", params={"page_size": 101}).status_code == 422
    assert client.get(f"{P}/jobs", params={"page": 0}).status_code == 422


def test_jobs_filter_by_specialization(client, ref):
    for sp in SPECS:
        exp = sum(1 for j in ref["jobs"] if j["primary_specialization"] == sp)
        assert client.get(f"{P}/jobs", params={"specialization": sp, "page_size": 1}).json()["total"] == exp
    assert client.get(f"{P}/jobs", params={"specialization": "nope"}).status_code == 404


def test_jobs_filter_by_skill_matches_top10(client, ref):
    for t in ref["top10"][:30]:
        body = client.get(f"{P}/jobs", params={"specialization": t["specialization"], "skill": t["canonical_skill"], "page_size": 1}).json()
        assert body["total"] == int(t["jobs_requiring_skill"]), t["canonical_skill"]


def test_jobs_filter_by_location_and_source(client, ref):
    riyadh = sum(1 for j in ref["jobs"] if j["location"].lower() == "riyadh")
    assert client.get(f"{P}/jobs", params={"location": "riyadh", "page_size": 1}).json()["total"] == riyadh
    unknown = sum(1 for j in ref["jobs"] if not j["location"].strip())
    assert client.get(f"{P}/jobs", params={"location": "Unknown", "page_size": 1}).json()["total"] == unknown
    locs = client.get(f"{P}/locations").json()["items"]
    assert sum(l["jobs"] for l in locs) == 1137
    li = sum(1 for j in ref["jobs"] if "linkedin" in j["source_memberships"].split("|"))
    assert client.get(f"{P}/jobs", params={"source": "linkedin", "page_size": 1}).json()["total"] == li
    assert client.get(f"{P}/jobs", params={"source": "indeed"}).status_code == 422


def test_search_english_and_arabic(client, ref):
    body = client.get(f"{P}/jobs", params={"q": "kubernetes", "page_size": 1}).json()
    exp = sum(1 for j in ref["jobs"] if "kubernetes" in (j["job_title"] + j["company"] + j["description"]).lower())
    assert body["total"] == exp > 0
    term = "الرياض"  # Riyadh
    exp_ar = sum(1 for j in ref["jobs"] if term in j["job_title"] + j["company"] + j["description"])
    assert client.get(f"{P}/jobs", params={"q": term, "page_size": 1}).json()["total"] == exp_ar > 0


def test_job_detail_with_evidence(client, ref):
    j = next(x for x in ref["jobs"] if x["combined_id"] == "CMB-00031")
    d = client.get(f"{P}/jobs/CMB-00031").json()
    assert d["specialization_id"] == "infrastructure_networking" and d["previous_specialization_id"] == "cybersecurity"
    assert d["description"] == j["description"] and d["url"] == j["url"]
    assert {u["url"] for u in d["urls"]} == set(j["all_urls"].split("|"))
    req = {s["canonical_name"] for s in d["skills"] if s["counts_as_requirement"] and s["ranking_eligible"]}
    assert req == set(filter(None, j["required_technical_skills_v2"].split("|")))
    assert all(s["evidence_snippet"] for s in d["skills"])
    assert sum(s["is_representative"] for s in d["source_records"]) == 1
    assert client.get(f"{P}/jobs/CMB-99999").status_code == 404


def test_arabic_job_detail_roundtrip(client, ref):
    j = next(x for x in ref["jobs"] if any("؀" <= ch <= "ۿ" for ch in x["job_title"] + x["description"]))
    d = client.get(f"{P}/jobs/{j['combined_id']}").json()
    assert d["description"] == j["description"] and d["job_title"] == j["job_title"]


def test_pending_jobs_not_exposed(client, ref):
    for p in ref["pending"]:
        if p["counted_in_v2_statistics"] == "no":
            assert client.get(f"{P}/jobs/{p['combined_id']}").status_code == 404
