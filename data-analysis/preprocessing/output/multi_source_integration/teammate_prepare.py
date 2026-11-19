#!/usr/bin/env python3
"""
STAGE 1 - Inspect, normalize and deduplicate the teammate (JSearch + LinkedIn) dataset,
and write classification batches.

Reads (read-only):  Data & Schemas/Processed/{final_jobs,jsearch_all,linkedin_all}.{csv,json}
                    Data & Schemas/Raw/JSearch_API/*.json, Data & Schemas/Raw/LinkedIn_API/*.json
                    data-analysis/preprocessing/classify_headcount.py  (SYSTEM prompt, via ast - not executed)
Writes only into:   data-analysis/preprocessing/output/multi_source_integration/
                    (+ classification batch files into --batch-dir)

Run from project root:
  python -B data-analysis/preprocessing/output/multi_source_integration/teammate_prepare.py --batch-dir <dir>
"""
import argparse
import ast
import collections
import csv
import glob
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DS = ROOT / "Data & Schemas"
PROC = DS / "Processed"
CLASSIFIER = ROOT / "data-analysis" / "preprocessing" / "classify_headcount.py"

csv.field_size_limit(2**31 - 1)

# Arabic / variant city names -> English (only places observed in the data)
CITY_MAP = {
    "الرياض": "Riyadh", "riyadh": "Riyadh",
    "جدة": "Jeddah", "jeddah": "Jeddah",
    "المدينة المنورة": "Madinah",
    "الدمام": "Dammam", "dammam": "Dammam",
    "مكة": "Makkah", "makkah al mukarramah": "Makkah",
    "الخبر": "Al Khobar", "al khobar": "Al Khobar",
    "الظهران": "Dhahran", "dhahran": "Dhahran",
    "ثول": "Thuwal", "الباحة": "Al Baha", "جيزان": "Jazan",
    "الجبيل": "Jubail", "al jubayl": "Jubail", "al jubayl governorate": "Jubail",
    "الهفوف": "Al Hofuf", "الرس": "Ar Rass", "ar rass": "Ar Rass",
    "القطيف": "Qatif", "المنطقة الشرقية": "Eastern Province (region)", "نجران": "Najran",
    "املج": "Umluj", "حائل": "Hail", "ينبع": "Yanbu", "تبوك": "Tabuk", "عنيزة": "Unaizah",
    "rabigh": "Rabigh", "najran": "Najran", "duba": "Duba", "an na`ayim": "An Na'ayim",
    "eastern province": "Eastern Province (region)", "al-qassim province": "Al-Qassim (region)",
    "saudi arabia": "Saudi Arabia (country only)",
    "dawamat al jandal": "Dumat Al Jandal",
}
SUSPECT_GEOCODE = {"dawamat al jandal"}

FOREIGN_RX = re.compile(
    r"\b(Dubai|Abu Dhabi|United Arab Emirates|UAE|Qatar|Doha|Kuwait|Bahrain|Manama|Oman|Muscat|Egypt|Cairo|Jordan|Amman|"
    r"Morocco|Casablanca|Rabat|Tunisia|Tunis|Algeria|India|Bangalore|Bengaluru|Hyderabad|Pune|Pakistan|Lahore|Karachi|"
    r"Turkey|Istanbul|United Kingdom|London|Germany|France|Paris|Spain|Poland|Romania|Portugal|Netherlands|"
    r"United States|USA|Canada|Philippines|Malaysia|Singapore|Lebanon|Beirut|Nigeria|Kenya|South Africa|Europe|EMEA|LATAM|APAC)\b")
SAUDI_RX = re.compile(r"\b(Saudi|KSA|Riyadh|Jeddah|Dammam|Khobar|Dhahran|Makkah|Mecca|Madinah|Medina|NEOM|Jubail|Yanbu|Tabuk|Abha|Qassim|AlUla)\b|السعودية|الرياض|جدة", re.I)
RECRUITER_RX = re.compile(r"\b(recruit\w*|staffing|talent|headhunt\w*|manpower|outsourcing|jobs? for|hiring partner|on behalf of (?:our|a) client|our client)\b", re.I)
BOILER_RX = re.compile(r"\b(about us|who we are|our mission|equal opportunity|benefits|we offer|why join|our client is|founded in|is a leading)\b", re.I)


def ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def nt(s):
    return re.sub(r"[^a-z0-9؀-ۿ]+", " ", (s or "").lower()).strip()


def nc(s):
    s = nt(s)
    s = re.sub(r"\b(company|co|ltd|limited|llc|inc|group|the|saudi|arabia|ksa|for|and|of|technologies|technology|solutions|services)\b", " ", s)
    return ws(s)


def shingles(t, k=5):
    w = re.findall(r"\w+", (t or "").lower())
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


def jac(a, b):
    return len(a & b) / max(1, len(a | b))


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def url_ids(url):
    ids = set()
    for tok in re.split(r"[/_\-?=&.,;%+]", url or ""):
        if re.fullmatch(r"\d{6,}", tok):
            ids.add("num:" + tok)
        elif re.fullmatch(r"[A-Za-z]{1,4}\d{5,}", tok):
            ids.add("req:" + tok.upper())
    return ids


def write_csv(path, rows, cols):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-dir", type=Path, required=True)
    ap.add_argument("--batches", type=int, default=9)
    ap.add_argument("--max-chars", type=int, default=4500)
    args = ap.parse_args()
    args.batch_dir.mkdir(parents=True, exist_ok=True)
    rep = {"inputs": {}}

    # ---------------------------------------------------------------- load + inspect
    FJ = json.load(open(PROC / "final_jobs.json", encoding="utf-8"))
    with open(PROC / "final_jobs.csv", encoding="utf-8-sig", newline="") as f:
        FC = list(csv.DictReader(f))
    JS = json.load(open(PROC / "jsearch_all.json", encoding="utf-8"))
    LI = json.load(open(PROC / "linkedin_all.json", encoding="utf-8"))
    with open(PROC / "jsearch_all.csv", encoding="utf-8-sig", newline="") as f:
        JSC = list(csv.DictReader(f))
    with open(PROC / "linkedin_all.csv", encoding="utf-8-sig", newline="") as f:
        LIC = list(csv.DictReader(f))
    for p in sorted(PROC.glob("*")):
        rep["inputs"][p.name] = {"sha256": sha256(p)}
    rep["file_counts"] = {"final_jobs.json": len(FJ), "final_jobs.csv": len(FC), "jsearch_all.json": len(JS),
                          "jsearch_all.csv": len(JSC), "linkedin_all.json": len(LI), "linkedin_all.csv": len(LIC)}

    # column types (JSON)
    def types(recs):
        t = collections.defaultdict(collections.Counter)
        for r in recs:
            for k, v in r.items():
                t[k][type(v).__name__] += 1
        return {k: dict(v) for k, v in t.items()}
    rep["final_jobs_columns_types"] = types(FJ)
    rep["jsearch_all_columns"] = list(JS[0].keys())
    rep["linkedin_all_columns"] = list(LI[0].keys())

    # csv vs json consistency
    def sv(v):
        if v is None:
            return ""
        if isinstance(v, list):
            return None  # compared separately
        return str(v)
    diff = collections.Counter()
    for c, j in zip(FC, FJ):
        for k in j:
            if k == "found_in":
                if [x.strip() for x in j[k]] != [x.strip() for x in re.split(r"[;,|]", c[k]) if x.strip()]:
                    diff["found_in_value"] += 1
                continue
            a, b = c[k], sv(j[k])
            if a == b:
                continue
            if k == "description" and a.replace("\r\n", "\n") == b:
                diff["description_crlf_only"] += 1
            elif k == "description" and ws(a) == ws(b):
                diff["description_whitespace_only"] += 1
            else:
                diff[f"{k}_content"] += 1
    rep["csv_vs_json"] = {"same_count": len(FC) == len(FJ), "same_order_titles": all(c["job_title"] == j["job_title"] for c, j in zip(FC, FJ)),
                          "differences": dict(diff),
                          "content_identical": all(not k.endswith("_content") and k != "found_in_value" for k in diff)}

    # raw counts
    raw_js, raw_li = [], []
    for f in sorted(glob.glob(str(DS / "Raw" / "JSearch_API" / "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        for x in d["data"]["jobs"]:
            raw_js.append((Path(f).name, d.get("_meta", {}), d.get("parameters", {}), x))
    for f in sorted(glob.glob(str(DS / "Raw" / "LinkedIn_API" / "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        L = d if isinstance(d, list) else d.get("data", d.get("jobs", []))
        for x in L:
            raw_li.append((Path(f).name, x))
    js_ids = {x["job_id"] for x in JS}
    js_uids = {x["job_uid"] for x in JS}
    raw_js_missing = [x for _, _, _, x in raw_js if x["job_id"] not in js_ids]
    rep["raw"] = {
        "jsearch_raw_files": len(glob.glob(str(DS / "Raw" / "JSearch_API" / "*.json"))),
        "jsearch_raw_records": len(raw_js), "jsearch_raw_unique_job_id": len({x["job_id"] for *_, x in raw_js}),
        "jsearch_raw_unique_job_uid": len({x["job_uid"] for *_, x in raw_js}),
        "jsearch_raw_not_in_jsearch_all": len(raw_js_missing),
        "of_which_same_job_uid_as_kept_record": sum(1 for x in raw_js_missing if x["job_uid"] in js_uids),
        "of_which_other": [{"job_title": x["job_title"], "employer": x["employer_name"], "publisher": x["job_publisher"]} for x in raw_js_missing if x["job_uid"] not in js_uids],
        "jsearch_query_parameters": dict(collections.Counter(f"country={p.get('country')}|date_posted={p.get('date_posted')}|exclude={p.get('exclude_job_publishers')}" for _, _, p, _ in raw_js)),
        "linkedin_raw_files": len(glob.glob(str(DS / "Raw" / "LinkedIn_API" / "*.json"))),
        "linkedin_raw_records": len(raw_li), "linkedin_raw_unique_id": len({x["id"] for _, x in raw_li}),
        "linkedin_raw_ids_missing_from_linkedin_all": len({x["id"] for _, x in raw_li} - {x["id"] for x in LI}),
    }
    rep["raw"]["of_which_other_publishers"] = dict(collections.Counter(d["publisher"] for d in rep["raw"]["of_which_other"]))

    # ---------------------------------------------------------------- map final -> source records
    js_by_link = {x["job_apply_link"]: x for x in JS}
    li_by_url = {x["url"]: x for x in LI}
    unmapped = []
    src_of = []
    for i, j in enumerate(FJ):
        s = js_by_link.get(j["url"]) if j["source"] == "jsearch" else li_by_url.get(j["url"])
        if s is None:
            unmapped.append(i)
        src_of.append(s)
    rep["final_to_source_mapping"] = {"mapped": len(FJ) - len(unmapped), "unmapped": len(unmapped)}

    used_js = {s["job_id"] for j, s in zip(FJ, src_of) if s and j["source"] == "jsearch"}
    used_li = {s["id"] for j, s in zip(FJ, src_of) if s and j["source"] == "linkedin"}
    final_sh = [shingles(j["description"]) for j in FJ]

    # reconcile source records absent from final_jobs
    recon = []
    merged_js_into = collections.defaultdict(list)
    for x in JS:
        if x["job_id"] in used_js:
            continue
        sx = shingles(x["job_description"])
        sims = [(jac(sx, final_sh[i]), i) for i in range(len(FJ))]
        best, bi = max(sims)
        tc_match = [i for i in range(len(FJ)) if nt(FJ[i]["job_title"]) == nt(x["job_title"]) and nc(FJ[i]["company"]) == nc(x["employer_name"])]
        if best >= 0.8:
            reason = "near-identical description kept as another record (teammate dedup)"
            target = bi
        elif tc_match:
            target = max(tc_match, key=lambda i: jac(sx, final_sh[i]))
            best = jac(sx, final_sh[target])
            reason = "same normalized title+company as a kept record but description differs (teammate title/company dedup - questionable)" if best < 0.5 else "same title+company and similar description (teammate dedup)"
        else:
            target = None
            reason = "NOT FOUND in final_jobs: no matching description or title/company (unexplained loss)"
        if target is not None and FJ[target]["source"] == "linkedin" and "jsearch" in FJ[target]["found_in"]:
            merged_js_into[target].append(x["job_id"])
        recon.append({"source": "jsearch", "source_record_id": x["job_id"], "job_uid": x["job_uid"], "job_title": x["job_title"],
                      "company": x["employer_name"], "publisher": x["job_publisher"], "url": x["job_apply_link"],
                      "kept_as_final_index": target if target is not None else "", "kept_as_title": FJ[target]["job_title"] if target is not None else "",
                      "kept_as_source": FJ[target]["source"] if target is not None else "", "description_similarity": round(best, 3), "reason": reason})
    for x in LI:
        if x["id"] in used_li:
            continue
        sx = shingles(x["description_text"])
        best, bi = max((jac(sx, final_sh[i]), i) for i in range(len(FJ)))
        tc_match = [i for i in range(len(FJ)) if nc(FJ[i]["company"]) == nc(x["organization"]) and (nt(FJ[i]["job_title"]) in nt(x["title"]) or nt(x["title"]) in nt(FJ[i]["job_title"]))]
        if best >= 0.8:
            reason, target = "near-identical description kept as another record (teammate dedup)", bi
        elif tc_match:
            target = max(tc_match, key=lambda i: jac(sx, final_sh[i]))
            best = jac(sx, final_sh[target])
            reason = "similar title + same company as a kept record but description differs (teammate dedup - questionable)" if best < 0.5 else "similar title+company and similar description (teammate dedup)"
        else:
            target, reason = None, "NOT FOUND in final_jobs (unexplained loss)"
        recon.append({"source": "linkedin", "source_record_id": x["id"], "job_uid": "", "job_title": x["title"], "company": x["organization"],
                      "publisher": "LinkedIn", "url": x["url"], "kept_as_final_index": target if target is not None else "",
                      "kept_as_title": FJ[target]["job_title"] if target is not None else "", "kept_as_source": FJ[target]["source"] if target is not None else "",
                      "description_similarity": round(best, 3), "reason": reason})
    write_csv(HERE / "teammate_source_reconciliation.csv", recon, list(recon[0].keys()))
    rep["source_reconciliation"] = {
        "jsearch_all_not_in_final": sum(1 for r in recon if r["source"] == "jsearch"),
        "linkedin_all_not_in_final": sum(1 for r in recon if r["source"] == "linkedin"),
        "by_reason": dict(collections.Counter(f"{r['source']}: {r['reason']}" for r in recon)),
        "found_in_both_records": sum(1 for j in FJ if len(j["found_in"]) > 1),
        "found_in_both_with_recovered_jsearch_id": sum(1 for i in merged_js_into if len(FJ[i]["found_in"]) > 1),
        "identity": f"{len(JS)} jsearch_all = {len(used_js)} kept + {rep and sum(1 for r in recon if r['source']=='jsearch')} absent; {len(LI)} linkedin_all = {len(used_li)} kept + {sum(1 for r in recon if r['source']=='linkedin')} absent",
    }

    # ---------------------------------------------------------------- normalize
    norm = []
    for i, (j, s) in enumerate(zip(FJ, src_of)):
        src = j["source"]
        if src == "jsearch":
            sid, uid = s["job_id"], s["job_uid"]
            rel = s.get("job_posted_at") or ""
            posted = ""  # JSearch returned only relative ages ("قبل ٦ أيام"); no absolute date / timestamp available
            raw_country, is_remote = s.get("job_country"), s.get("job_is_remote")
            agency = ""
            li_derived = ""
        else:
            sid, uid = str(s["id"]), ""
            rel = ""
            posted = (s.get("date_posted") or "")[:10]
            raw_country, is_remote = "|".join(s.get("countries_derived") or []), s.get("ai_work_arrangement")
            agency = s.get("org_linkedin_recruitment_agency_derived")
            li_derived = "|".join(s.get("locations_derived") or [])
        loc_raw = (j["location"] or "").replace("‎", "").strip()
        loc_basis = "final_jobs_location" if loc_raw else ""
        if not loc_raw and src == "jsearch":
            # recover from JSearch raw 'job_location' text, e.g. "السعودية • عبر Foundit" (Google Jobs display location)
            jl = ws((s.get("job_location") or "").replace("‎", "")).split("•")[0].strip()
            jl = re.sub(r"\s*\(\+.*\)$", "", jl).strip()
            if jl:
                loc_raw, loc_basis = jl, "recovered_from_jsearch_raw_job_location"
        key = loc_raw.lower()
        loc_norm = CITY_MAP.get(loc_raw, CITY_MAP.get(key, loc_raw))
        country = j["country"] or ""
        if country:
            basis = "source_country_field"
        elif loc_raw == "السعودية":
            country, basis, loc_norm = "SA", "jsearch_raw_job_location_says_saudi_arabia", "Saudi Arabia (country only)"
        elif loc_raw and loc_norm in set(CITY_MAP.values()):
            country, basis = "SA", "inferred_from_saudi_city_name_in_jsearch_raw_location"
        else:
            basis = "unknown"
        desc = j["description"]
        title, comp = j["job_title"], j["company"]
        flags = []
        if not j["location"]:
            flags.append("missing_location_in_final_jobs" + ("_recovered_from_raw" if loc_raw else "_unrecoverable"))
        if not j["country"]:
            flags.append("missing_country_in_source")
        if not posted:
            flags.append("missing_posted_date")
        if key in SUSPECT_GEOCODE:
            flags.append("suspect_geocoded_location_dumat_al_jandal")
        foreign = sorted(set(m.group(0) for m in FOREIGN_RX.finditer(desc + " " + title)))
        saudi = bool(SAUDI_RX.search(desc + " " + title))
        if foreign and not saudi:
            flags.append("description_mentions_only_non_saudi_locations")
        elif foreign:
            flags.append("description_mentions_non_saudi_locations_too")
        if re.search(r"\bPFE\b|stage de fin|alternance", desc + " " + title, re.I):
            flags.append("french_internship_pfe_likely_outside_saudi")
        if len(desc) < 300:
            flags.append("short_description_lt300")
        if agency is True or RECRUITER_RX.search(comp) or re.search(r"\b(confidential|undisclosed)\b", comp, re.I):
            flags.append("employer_is_recruiter_or_confidential")
        m = re.search(r"\b(?:at|@)\s+([A-Z][\w&.\- ]{2,40})$", title)
        if m and nc(m.group(1)) and nc(m.group(1)) not in nc(comp) and nc(comp) not in nc(m.group(1)):
            flags.append("title_names_different_company")
        bp = len(BOILER_RX.findall(desc))
        if bp >= 4 and len(desc) < 1500:
            flags.append("boilerplate_heavy_short_description")
        rid = "tm_" + hashlib.sha1(f"{src}|{sid}".encode()).hexdigest()[:16]
        norm.append({
            "teammate_record_id": rid,
            "final_jobs_index": i,
            "job_id": sid,
            "jsearch_job_uid": uid,
            "linkedin_job_id": str(s.get("linkedin_id") or "") if src == "linkedin" else "",
            "merged_jsearch_job_ids": "|".join(merged_js_into.get(i, [])),
            "job_title": title,
            "company": comp,
            "location": loc_norm,
            "location_raw": j["location"] or "",
            "location_recovered": loc_raw if loc_basis.startswith("recovered") else "",
            "location_basis": loc_basis,
            "location_derived_linkedin": li_derived,
            "country": country,
            "country_raw": j["country"] or "",
            "country_basis": basis,
            "remote_or_work_arrangement": "" if is_remote is None else str(is_remote),
            "posted_date": posted,
            "posted_relative_raw": rel,
            "url": j["url"],
            "source": src,
            "publisher": j["publisher"],
            "original_sources": "|".join(j["found_in"]),
            "found_in": json.dumps(j["found_in"]),
            "source_file": j["source_file"],
            "search_hint": j["search_hint"] or "",
            "description_chars": len(desc),
            "data_quality_flags": "|".join(flags),
            "description": desc,
            "description_clean": ws(desc.replace("\r\n", "\n")),
        })

    # ---------------------------------------------------------------- teammate dedup
    by = {r["teammate_record_id"]: r for r in norm}
    sh = {r["teammate_record_id"]: shingles(r["description"]) for r in norm}
    pairs = []
    ids = {r["teammate_record_id"]: url_ids(r["url"]) | ({"li:" + r["linkedin_job_id"]} if r["linkedin_job_id"] else set()) | ({"uid:" + r["jsearch_job_uid"]} if r["jsearch_job_uid"] else set()) for r in norm}
    keys = list(by)

    def city_in_text(r):
        c = r["location"].split(" (")[0].lower()
        d = r["description"].lower()
        return bool(c and c in d) or bool(r["location_raw"] and r["location_raw"].lower() in d)

    for a_i in range(len(keys)):
        for b_i in range(a_i + 1, len(keys)):
            a, b = by[keys[a_i]], by[keys[b_i]]
            if nc(a["company"]) != nc(b["company"]) and not (ids[a["teammate_record_id"]] & ids[b["teammate_record_id"]]):
                continue
            s = jac(sh[a["teammate_record_id"]], sh[b["teammate_record_id"]])
            same_title = nt(a["job_title"]) == nt(b["job_title"])
            shared = sorted(ids[a["teammate_record_id"]] & ids[b["teammate_record_id"]])
            loc_ok = (a["location"] == b["location"]) or not a["location_raw"] or not b["location_raw"] or "country only" in a["location"] + b["location"]
            if not (same_title or shared) or s < 0.5:
                continue
            if shared and s >= 0.8:
                v, rule = "confirmed", "shared source/external ID + near-identical description"
            elif same_title and s >= 0.90 and loc_ok:
                v, rule = "confirmed", "same title + same employer + near-identical description (>=0.90) + compatible location"
            elif (same_title and s >= 0.98 and "jsearch" in (a["source"], b["source"])
                  and not city_in_text(a) and not city_in_text(b)):
                v, rule = "confirmed", ("aggregator re-listing: identical title, employer and description (>=0.98); the differing city "
                                        "appears only in aggregator metadata, not in either description")
            else:
                why = []
                if not loc_ok:
                    why.append("location differs")
                if s < 0.90:
                    why.append(f"description similarity {s:.2f} < 0.90")
                v, rule = "possible", "not merged: " + ", ".join(why or ["insufficient evidence"])
            pairs.append((a["teammate_record_id"], b["teammate_record_id"], v, rule, round(s, 4), "|".join(shared)))
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b, v, *_ in pairs:
        if v == "confirmed":
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups = collections.defaultdict(list)
    for k in keys:
        groups[find(k)].append(k)
    dup_groups = [sorted(m, key=lambda k: by[k]["final_jobs_index"]) for m in groups.values() if len(m) > 1]

    def prim_key(k):
        r = by[k]
        return (0 if r["source"] == "linkedin" else 1, 0 if r["posted_date"] else 1, -r["description_chars"], r["final_jobs_index"])
    grows = []
    for n, m in enumerate(sorted(dup_groups, key=lambda m: by[m[0]]["final_jobs_index"]), start=1):
        gid = f"TMDUP-{n:03d}"
        prim = sorted(m, key=prim_key)[0]
        for k in m:
            ev = [p for p in pairs if k in p[:2] and p[2] == "confirmed"]
            other = ev[0][1] if ev and ev[0][0] == k else (ev[0][0] if ev else "")
            by[k].update(tm_duplicate_group_id=gid, tm_primary_record_id=prim, tm_analytical_status="primary" if k == prim else "redundant_duplicate_excluded")
            grows.append({"tm_duplicate_group_id": gid, "group_size": len(m), "teammate_record_id": k, "is_primary": "yes" if k == prim else "no",
                          "primary_record_id": prim, "job_title": by[k]["job_title"], "company": by[k]["company"], "location": by[k]["location"],
                          "source": by[k]["source"], "publisher": by[k]["publisher"], "url": by[k]["url"], "posted_date": by[k]["posted_date"],
                          "matched_with": other, "match_rule": ev[0][3] if ev else "", "description_similarity": ev[0][4] if ev else "",
                          "shared_ids": ev[0][5] if ev else ""})
    for r in norm:
        r.setdefault("tm_duplicate_group_id", "")
        r.setdefault("tm_primary_record_id", r["teammate_record_id"])
        r.setdefault("tm_analytical_status", "unique")
    poss = [{"record_a": a, "record_b": b, "title_a": by[a]["job_title"], "title_b": by[b]["job_title"], "company": by[a]["company"],
             "location_a": by[a]["location"], "location_b": by[b]["location"], "description_similarity": s, "shared_ids": sh_, "reason": rule}
            for a, b, v, rule, s, sh_ in pairs if v == "possible"]

    ncols = [c for c in norm[0].keys() if c not in ("description", "description_clean")] + ["description", "description_clean"]
    write_csv(HERE / "teammate_normalized_jobs.csv", norm, ncols)
    write_csv(HERE / "teammate_duplicate_groups.csv", grows, list(grows[0].keys()) if grows else ["tm_duplicate_group_id"])
    write_csv(HERE / "teammate_possible_duplicates_not_merged.csv", poss, list(poss[0].keys()) if poss else ["record_a"])

    uniq = [r for r in norm if r["tm_analytical_status"] != "redundant_duplicate_excluded"]
    rep["normalized"] = {
        "records": len(norm), "source_counts": dict(collections.Counter(r["source"] for r in norm)),
        "found_in_counts": dict(collections.Counter(r["original_sources"] for r in norm)),
        "missing": {k: sum(1 for r in norm if not str(r[k]).strip()) for k in ("job_title", "company", "location_raw", "country_raw", "posted_date", "url", "description")},
        "country_after_normalization": dict(collections.Counter(r["country"] or "unknown" for r in norm)),
        "country_basis": dict(collections.Counter(r["country_basis"] for r in norm)),
        "flags": dict(collections.Counter(f for r in norm for f in r["data_quality_flags"].split("|") if f)),
        "stable_ids_unique": len({r["teammate_record_id"] for r in norm}) == len(norm),
        "existing_classification_or_skill_fields": {"final_jobs": [k for k in FJ[0] if re.search(r"special|skill|classif|categor|decision", k)],
                                                      "search_hint_values (query category, NOT a classification)": dict(collections.Counter(r["search_hint"] for r in norm)),
                                                      "linkedin_all_ai_fields (vendor-generated)": [k for k in LI[0] if k.startswith("ai_")]},
    }
    rep["dedup"] = {"records_before": len(norm), "confirmed_groups": len(dup_groups), "records_in_groups": sum(len(m) for m in dup_groups),
                    "redundant": sum(len(m) - 1 for m in dup_groups), "unique": len(uniq), "possible_not_merged_pairs": len(poss)}

    # ---------------------------------------------------------------- classification batches (unique records only)
    tree = ast.parse(CLASSIFIER.read_text(encoding="utf-8"))
    system = next(n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "SYSTEM" for t in n.targets))
    (args.batch_dir / "CLASSIFIER_SYSTEM_PROMPT.txt").write_text(system, encoding="utf-8")
    rep["classifier_prompt_sha256"] = hashlib.sha256(system.encode()).hexdigest()
    order = sorted(uniq, key=lambda r: r["final_jobs_index"])
    nb = args.batches
    size = -(-len(order) // nb)
    for b in range(nb):
        chunk = order[b * size:(b + 1) * size]
        with open(args.batch_dir / f"batch_{b + 1:02d}.jsonl", "w", encoding="utf-8") as f:
            for r in chunk:
                f.write(json.dumps({"teammate_record_id": r["teammate_record_id"], "job_title": r["job_title"], "company": r["company"],
                                    "location": r["location_raw"], "country": r["country_raw"], "publisher": r["publisher"],
                                    "description": r["description"].replace("\r\n", "\n")[:args.max_chars]}, ensure_ascii=False) + "\n")
    rep["classification_batches"] = {"dir": str(args.batch_dir), "batches": nb, "records": len(order), "max_chars": args.max_chars, "truncated_records": sum(1 for r in order if len(r["description"]) > args.max_chars)}
    (HERE / "_stage1_report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("file_counts", "csv_vs_json", "final_to_source_mapping", "source_reconciliation", "normalized", "dedup", "classification_batches")}, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
