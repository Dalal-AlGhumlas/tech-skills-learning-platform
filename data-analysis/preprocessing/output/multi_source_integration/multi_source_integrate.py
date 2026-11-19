#!/usr/bin/env python3
"""
STAGE 2 - Validate teammate LLM classifications, integrate with the completed Headcount Labs
baseline, cross-source deduplicate, recompute skills, write all outputs + summary.

Reads (read-only):
  multi_source_integration/teammate_normalized_jobs.csv, teammate_duplicate_groups.csv, _stage1_report.json
  <batch-dir>/batch_XX_results.jsonl            (Claude subagent classifications; copied into
                                                  multi_source_integration/teammate_llm_classifications.jsonl)
  Data & Schemas/Processed/jsearch_all.json      (apply_options links for cross-source URL matching)
  .../postclassification_reviewed/deduplicated_jobs.csv, reviewed_classifications_all.csv,
      top10_skills_per_specialization.csv, summary.json
  .../postclassification_reviewed/headcount_postclassification_analysis.py + skill_taxonomy.py (imported, NOT modified;
      bytecode writing disabled so no __pycache__ is created there)

Run from project root:
  python -B data-analysis/preprocessing/output/multi_source_integration/multi_source_integrate.py --batch-dir <dir>
"""
import sys
sys.dont_write_bytecode = True

import argparse
import collections
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
HC_DIR = ROOT / "data-analysis/preprocessing/output/headcount/ai_classification/full_dataset/postclassification_reviewed"
sys.path.insert(0, str(HC_DIR))
import headcount_postclassification_analysis as HCA  # noqa: E402  (functions only; main() not executed)
from skill_taxonomy import S as SKILLS, NON_RANKING_CATEGORIES  # noqa: E402

SPECS = HCA.SPECIALIZATIONS
DECISIONS = {"in_scope", "out_of_scope", "needs_review"}
csv.field_size_limit(2**31 - 1)


def read_csv(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(name, rows, cols=None):
    cols = cols or (list(rows[0].keys()) if rows else ["empty"])
    with open(HERE / name, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return str(HERE / name)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def nq(s):
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    s = re.sub(r"[*#_`\\]", "", s)
    return ws(s).lower()


def nt(s):
    return re.sub(r"[^a-z0-9؀-ۿ]+", " ", (s or "").lower()).strip()


STOP_CO = r"\b(company|co|ltd|limited|llc|inc|group|the|saudi|arabia|ksa|for|and|of|technologies|technology|solutions|services|middle east|regional|headquarters|fz|br\d+)\b"


def nc(s):
    return ws(re.sub(STOP_CO, " ", nt(s)))


def title_tokens(s):
    t = set(nt(re.sub(r"\(.*?\)|\|.*$| - .*$", " ", s or "")).split())
    return {x for x in t if x not in {"senior", "sr", "junior", "jr", "lead", "ii", "iii", "i", "saudi", "national", "nationals", "only", "ksa", "riyadh", "jeddah", "remote", "the", "and", "of", "for"}}


def tjac(a, b):
    A, B = title_tokens(a), title_tokens(b)
    return len(A & B) / max(1, len(A | B))


def company_ok(a, b, desc_a="", desc_b=""):
    A, B = nc(a), nc(b)
    if not A or not B:
        return False
    if A == B or A in B or B in A:
        return True
    ta, tb = set(A.split()), set(B.split())
    if len(ta & tb) / max(1, min(len(ta), len(tb))) >= 0.5:
        return True
    return (len(A) >= 4 and A in nt(desc_b)) or (len(B) >= 4 and B in nt(desc_a))


def shingles(t, k=5):
    w = re.findall(r"\w+", (t or "").lower())
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


def url_ids(url):
    ids = set()
    for tok in re.split(r"[/_\-?=&.,;%+]", url or ""):
        if re.fullmatch(r"\d{6,}", tok):
            ids.add("num:" + tok)
        elif re.fullmatch(r"[A-Za-z]{1,4}\d{5,}", tok):
            ids.add("req:" + tok.upper())
    return ids


def canon_url(u):
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://(www\.)?", "", u)
    u = re.sub(r"[?#].*$", "", u).rstrip("/")
    return u


# ============================================================================ stage A: teammate classification
def load_classifications(batch_dir, norm_unique, log):
    files = sorted(batch_dir.glob("batch_*_results.jsonl"))
    rows, bad_lines = [], 0
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad_lines += 1
    # provenance copy
    with open(HERE / "teammate_llm_classifications.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by = {}
    dup_ids = 0
    for r in rows:
        k = r.get("teammate_record_id")
        if k in by:
            dup_ids += 1
        by[k] = r
    expected = {r["teammate_record_id"] for r in norm_unique}
    log["classification_input"] = {"result_files": [f.name for f in files], "result_rows": len(rows), "unparseable_lines": bad_lines,
                                   "duplicate_ids_in_results": dup_ids, "expected_unique_records": len(expected),
                                   "classified": len(expected & set(by)), "missing": sorted(expected - set(by)),
                                   "unexpected_ids": sorted(set(by) - expected)}
    return by


def validate_classification(rec, c):
    """Return dict of validated classification fields for one teammate unique record."""
    out = {"llm_decision": "", "llm_specialization": "", "confidence": "", "reason": "", "evidence": "",
           "evidence_verified": "", "job_location_assessment": "", "location_evidence": "", "description_quality": "",
           "classification_status": "", "validation_notes": ""}
    if c is None:
        out.update(classification_status="unclassified", decision="", specialization="", needs_manual_review="true",
                   validation_notes="no LLM result returned for this record")
        return out
    notes = []
    dec = (c.get("decision") or "").strip()
    spec = c.get("specialization") or ""
    spec = spec.strip() if isinstance(spec, str) else ""
    conf = (c.get("confidence") or "").strip()
    ev = c.get("evidence") or ""
    text = nq(rec["job_title"] + " \n " + rec["description"])
    ev_ok = bool(ev.strip()) and nq(ev) in text
    out.update(llm_decision=dec, llm_specialization=spec, confidence=conf, reason=c.get("reason") or "", evidence=ev,
               evidence_verified=str(ev_ok).lower(), job_location_assessment=c.get("job_location_assessment") or "",
               location_evidence=c.get("location_evidence") or "", description_quality=c.get("description_quality") or "")
    final_dec, final_spec = dec, spec
    if dec not in DECISIONS:
        notes.append(f"invalid decision '{dec}'")
        final_dec, final_spec = "needs_review", ""
    if final_dec == "in_scope" and spec not in SPECS:
        notes.append(f"in_scope without valid specialization '{spec}'")
        final_dec, final_spec = "needs_review", ""
    if final_dec != "in_scope":
        final_spec = ""
    if conf not in {"high", "medium", "low"}:
        notes.append("invalid confidence")
    if not ev_ok:
        notes.append("evidence not found verbatim in title/description")
        if final_dec != "needs_review":
            notes.append(f"decision '{final_dec}' downgraded to needs_review (Qwen V3 rule: no reliable verbatim evidence -> needs_review)")
            final_dec, final_spec = "needs_review", ""
    nmr = bool(c.get("needs_manual_review")) or final_dec == "needs_review" or conf == "low" or not ev_ok
    out.update(decision=final_dec, specialization=final_spec, needs_manual_review=str(nmr).lower(),
               classification_status="classified" if not notes else "classified_with_validation_adjustment",
               validation_notes="; ".join(notes))
    return out


# ============================================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-dir", type=Path, required=True)
    args = ap.parse_args()
    log = {"generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    protected = sorted(p for p in (ROOT / "Data & Schemas").rglob("*") if p.is_file())
    protected += sorted(p for p in HC_DIR.rglob("*") if p.is_file())
    protected += [ROOT / "data-analysis/preprocessing/output/headcount/ai_classification/full_dataset" / n
                  for n in ("classifications_all.csv", "classifications_all.jsonl", "classification_cache.jsonl", "report_all.json")]
    hashes_before = {str(p): sha256(p) for p in protected}

    stage1 = json.loads((HERE / "_stage1_report.json").read_text(encoding="utf-8"))
    norm = read_csv(HERE / "teammate_normalized_jobs.csv")
    tm_by = {r["teammate_record_id"]: r for r in norm}
    tm_unique = [r for r in norm if r["tm_analytical_status"] != "redundant_duplicate_excluded"]
    cls = load_classifications(args.batch_dir, tm_unique, log)

    # ---------------- A. teammate classification (unique records), inherited by teammate duplicates
    METHOD = ("claude_llm_subagent_reading_full_description (Claude Code session subagents; Qwen V3 SYSTEM prompt from "
              "classify_headcount.py as standard; AI decision, NOT human-approved)")
    tm_cls = {}
    for r in tm_unique:
        v = validate_classification(r, cls.get(r["teammate_record_id"]))
        v["classification_method"] = METHOD
        tm_cls[r["teammate_record_id"]] = v
    classified_rows = []
    for r in norm:
        prim = r["tm_primary_record_id"]
        v = dict(tm_cls[prim])
        v["classification_inherited_from"] = "" if prim == r["teammate_record_id"] else prim
        row = {k: r[k] for k in r if k not in ("description", "description_clean")}
        row.update(v)
        # Saudi-location status (do not assume Saudi from the search query)
        la = v.get("job_location_assessment")
        flags = r["data_quality_flags"]
        if la == "outside_saudi":
            st = "outside_saudi_excluded"
        elif "suspect_geocoded" in flags and la != "saudi":
            st = "saudi_location_unverified"
        elif la in ("remote_unclear", "unclear") or "description_mentions_only_non_saudi" in flags or "french_internship" in flags:
            st = "saudi_location_unverified"
        else:
            st = "saudi"
        row["saudi_location_status"] = st
        row["description"] = r["description"]
        classified_rows.append(row)
    cl_by = {r["teammate_record_id"]: r for r in classified_rows}

    def analytical_decision(r):
        """Decision used in confirmed statistics (outside-Saudi jobs are excluded from Saudi market counts)."""
        if r["saudi_location_status"] == "outside_saudi_excluded":
            return "excluded_outside_saudi"
        return r["decision"] or "unclassified"

    tm_uniq_rows = [cl_by[r["teammate_record_id"]] for r in tm_unique]
    for r in classified_rows:
        r["analytical_decision"] = analytical_decision(r)

    # ---------------- B. Headcount baseline
    HC = read_csv(HC_DIR / "deduplicated_jobs.csv")
    HC_ALL = read_csv(HC_DIR / "reviewed_classifications_all.csv")
    hc_summary = json.loads((HC_DIR / "summary.json").read_text(encoding="utf-8"))
    hc_by = {r["record_key"]: r for r in HC}

    # ---------------- C. cross-source dedup (Headcount unique x teammate unique)
    JS = json.load(open(ROOT / "Data & Schemas/Processed/jsearch_all.json", encoding="utf-8"))
    js_links = {}
    for x in JS:
        links = {x.get("job_apply_link") or ""} | {o.get("apply_link") or "" for o in (x.get("apply_options") or [])}
        js_links[x["job_id"]] = {canon_url(l) for l in links if l}
    hc_url = collections.defaultdict(list)
    for r in HC:
        hc_url[canon_url(r["url"])].append(r["record_key"])
    hc_title_idx = collections.defaultdict(set)
    hc_co_idx = collections.defaultdict(set)
    for r in HC:
        for t in title_tokens(r["job_title"]):
            hc_title_idx[t].add(r["record_key"])
        for t in nc(r["company"]).split():
            if len(t) >= 3:
                hc_co_idx[t].add(r["record_key"])
    hc_sh = {}
    hc_ids = {r["record_key"]: url_ids(r["url"]) for r in HC}

    cross_pairs = []
    for t in tm_unique:
        tid = t["teammate_record_id"]
        tl = {canon_url(t["url"])} | (js_links.get(t["job_id"], set()) if t["source"] == "jsearch" else set())
        for mid in filter(None, t["merged_jsearch_job_ids"].split("|")):
            tl |= js_links.get(mid, set())
        cand = set()
        for u in tl:
            cand |= set(hc_url.get(u, []))
        url_hits = set(cand)
        co_c = set()
        for tok in nc(t["company"]).split():
            if len(tok) >= 3:
                co_c |= hc_co_idx.get(tok, set())
        ti_c = set()
        for tok in title_tokens(t["job_title"]):
            ti_c |= hc_title_idx.get(tok, set())
        cand |= (co_c & ti_c)
        if not cand:
            continue
        tsh = shingles(t["description"])
        tids = url_ids(t["url"])
        for k in cand:
            h = hc_by[k]
            if k not in hc_sh:
                hc_sh[k] = shingles(h["description"])
            inter = len(tsh & hc_sh[k])
            cont = inter / max(1, min(len(tsh), len(hc_sh[k])))
            jac = inter / max(1, len(tsh | hc_sh[k]))
            tj = tjac(t["job_title"], h["job_title"])
            same_title = nt(t["job_title"]) == nt(h["job_title"])
            co = company_ok(t["company"], h["company"], t["description"], h["description"])
            shared_ids = sorted(tids & hc_ids[k])
            if k in url_hits and (tj >= 0.5 or cont >= 0.5):
                v, rule = "confirmed", "teammate apply link / URL identical to Headcount posting URL"
            elif co and (same_title or tj >= 0.6) and cont >= 0.70:
                v, rule = "confirmed", "compatible employer + same/near-identical title + description containment >= 0.70"
            elif co and (same_title or tj >= 0.6) and shared_ids and cont >= 0.4:
                v, rule = "confirmed", "compatible employer + similar title + shared requisition ID"
            elif co and (same_title or tj >= 0.5) and cont >= 0.35:
                v, rule = "possible", "compatible employer + similar title, but description containment below 0.70 (not merged)"
            elif same_title and cont >= 0.8 and not co:
                v, rule = "possible", "identical title and description but employer names not reconcilable (not merged)"
            else:
                continue
            cross_pairs.append({"teammate_record_id": tid, "headcount_record_key": k, "verdict": v, "rule": rule,
                                "description_containment": round(cont, 4), "description_jaccard": round(jac, 4), "title_token_jaccard": round(tj, 3),
                                "company_compatible": co, "url_match": k in url_hits, "shared_ids": "|".join(shared_ids)})

    # union-find over confirmed cross pairs (nodes: H:<key>, T:<id>)
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    # One-to-one matching: records within each source were already judged distinct, so a cross-source
    # match must never chain two Headcount (or two teammate) vacancies together. Greedy by evidence strength.
    used_h, used_t = set(), set()
    for p in sorted((p for p in cross_pairs if p["verdict"] == "confirmed"),
                    key=lambda p: (not p["url_match"], -p["description_containment"], -p["title_token_jaccard"], p["headcount_record_key"], p["teammate_record_id"])):
        if p["headcount_record_key"] in used_h or p["teammate_record_id"] in used_t:
            p["verdict"] = "possible"
            p["rule"] = "confirmed-level match superseded: the other record already matched a stronger counterpart (one-to-one rule)"
            continue
        used_h.add(p["headcount_record_key"])
        used_t.add(p["teammate_record_id"])
        union("H:" + p["headcount_record_key"], "T:" + p["teammate_record_id"])
    comp = collections.defaultdict(list)
    for x in list(parent):
        comp[find(x)].append(x)
    xgroups = [sorted(m) for m in comp.values() if len(m) > 1]

    # ---------------- D. combined unique records
    def hc_unified(h):
        dec = h["group_final_decision"]
        spec = h["group_final_specialization"] if dec == "in_scope" else ""
        sb = hc_all_by[h["record_key"]]["specialization_basis"] if dec == "in_scope" else ""
        return {
            "source_dataset": "headcount_labs", "source_record_id": h["record_key"], "source_job_id": h["source_job_id"],
            "job_title": h["job_title"], "company": h["company"], "location": h["location"], "country": h["country"],
            "posted_date": h["posted_date"], "url": h["url"], "publisher": h["publisher"],
            "source_memberships": "headcount_labs",
            "decision": dec, "specialization": spec,
            "decision_basis": "human_review" if h["decision_basis"] == "human_review" else "qwen_v3_llm_not_human_validated",
            "specialization_basis": ("qwen_v3" if sb == "qwen" else ("ai_proposed_claude_not_human_approved" if sb.startswith("ai_proposed") else ("unassigned" if dec == "in_scope" else ""))),
            "confidence": h["qwen_confidence"] if h["decision_basis"] != "human_review" else "human",
            "evidence": h["qwen_evidence"] if h["decision_basis"] != "human_review" else (h["ai_proposed_evidence"] or ""),
            "saudi_location_status": "saudi_per_source_country_field" if h["country"] == "SA" else "unverified",
            "headcount_duplicate_group_id": h["duplicate_group_id"], "headcount_member_record_keys": h["all_member_record_keys"],
            "description": h["description"],
        }
    hc_all_by = {r["record_key"]: r for r in HC_ALL}

    def tm_unified(t):
        r = cl_by[t]
        ad = r["analytical_decision"]
        return {
            "source_dataset": "teammate_jsearch_linkedin", "source_record_id": t, "source_job_id": r["job_id"],
            "job_title": r["job_title"], "company": r["company"], "location": r["location"], "country": r["country"],
            "posted_date": r["posted_date"], "url": r["url"], "publisher": r["publisher"],
            "source_memberships": r["original_sources"],
            "decision": ad if ad in DECISIONS else ad, "specialization": r["specialization"] if ad == "in_scope" else "",
            "decision_basis": "claude_llm_not_human_approved", "specialization_basis": "claude_llm_not_human_approved" if ad == "in_scope" else "",
            "confidence": r["confidence"], "evidence": r["evidence"], "saudi_location_status": r["saudi_location_status"],
            "headcount_duplicate_group_id": "", "headcount_member_record_keys": "",
            "teammate_duplicate_group_id": r["tm_duplicate_group_id"],
            "description": tm_by[t]["description"],
        }

    in_x = {}
    xrows = []
    conflicts = []
    combined = []
    for n, m in enumerate(sorted(xgroups, key=lambda m: m[0]), start=1):
        gid = f"XDUP-{n:03d}"
        hs = [x[2:] for x in m if x.startswith("H:")]
        ts = [x[2:] for x in m if x.startswith("T:")]
        rep_key = sorted(hs, key=lambda k: (0 if hc_by[k]["decision_basis"] == "human_review" else 1, k))[0]
        rep = hc_unified(hc_by[rep_key])
        h_dec = {hc_by[k]["group_final_decision"] for k in hs}
        h_spec = {hc_by[k]["group_final_specialization"] for k in hs if hc_by[k]["group_final_decision"] == "in_scope"}
        t_dec = {cl_by[k]["analytical_decision"] for k in ts}
        t_spec = {cl_by[k]["specialization"] for k in ts if cl_by[k]["analytical_decision"] == "in_scope"}
        human = any(hc_by[k]["decision_basis"] == "human_review" for k in hs)
        all_dec = h_dec | t_dec
        if len(all_dec) == 1:
            cdec, policy = next(iter(all_dec)), "all sources agree on decision"
            dconf = "no"
        elif "excluded_outside_saudi" in t_dec and h_dec == {"in_scope"} and len(t_dec) == 1:
            cdec, policy, dconf = "needs_review", "CONFLICT: teammate LLM judged job outside Saudi Arabia while Headcount lists it as SA in_scope -> needs_review", "yes"
        elif human and len(h_dec) == 1:
            cdec, policy, dconf = next(iter(h_dec)), "CONFLICT: Headcount human-reviewed decision kept over teammate LLM decision", "yes"
        else:
            cdec, policy, dconf = "needs_review", "CONFLICT: Qwen (Headcount) vs Claude LLM (teammate) disagree -> needs_review, listed in unresolved_cases", "yes"
        cspec = ""
        sconf = "no"
        if cdec == "in_scope":
            specs = {s for s in h_spec | t_spec if s}
            cspec = rep["specialization"] or (next(iter(t_spec)) if len(t_spec) == 1 else "")
            if len(specs) > 1:
                sconf = "yes"
                policy += f"; SPECIALIZATION CONFLICT {sorted(specs)}: representative (Headcount) specialization kept, listed in unresolved_cases"
        alt_urls = sorted({hc_by[k]["url"] for k in hs} | {cl_by[k]["url"] for k in ts})
        memberships = set(["headcount_labs"]) | {s for k in ts for s in cl_by[k]["original_sources"].split("|")}
        ts_all = ts + [x["teammate_record_id"] for k in ts for x in norm if x["tm_primary_record_id"] == k and x["teammate_record_id"] != k]
        rep.update(combined_group_id=gid, member_source_record_ids="|".join(["H:" + k for k in hs] + ["T:" + k for k in ts_all]),
                   source_memberships="|".join(sorted(memberships)), all_urls="|".join(alt_urls),
                   combined_decision=cdec, combined_specialization=cspec, decision_conflict=dconf, specialization_conflict=sconf,
                   conflict_policy=policy, teammate_decisions="|".join(f"{k}:{cl_by[k]['decision']}/{cl_by[k]['specialization']}/{cl_by[k]['saudi_location_status']}" for k in ts))
        combined.append(rep)
        if dconf == "yes" or sconf == "yes":
            conflicts.append(gid)
        for k in hs:
            in_x["H:" + k] = (gid, "H:" + rep_key)
        for k in ts:
            in_x["T:" + k] = (gid, "H:" + rep_key)
        for x in m:
            src = "headcount_labs" if x.startswith("H:") else "teammate"
            rid = x[2:]
            ev = [p for p in cross_pairs if p["verdict"] == "confirmed" and (p["headcount_record_key"] == rid or p["teammate_record_id"] == rid)]
            xrows.append({"cross_group_id": gid, "group_size": len(m), "dataset": src, "source_record_id": rid,
                          "is_representative": "yes" if x == "H:" + rep_key else "no",
                          "job_title": hc_by[rid]["job_title"] if src == "headcount_labs" else cl_by[rid]["job_title"],
                          "company": hc_by[rid]["company"] if src == "headcount_labs" else cl_by[rid]["company"],
                          "location": hc_by[rid]["location"] if src == "headcount_labs" else cl_by[rid]["location"],
                          "posted_date": hc_by[rid]["posted_date"] if src == "headcount_labs" else cl_by[rid]["posted_date"],
                          "publisher": hc_by[rid]["publisher"] if src == "headcount_labs" else cl_by[rid]["publisher"],
                          "url": hc_by[rid]["url"] if src == "headcount_labs" else cl_by[rid]["url"],
                          "source_decision": hc_by[rid]["group_final_decision"] if src == "headcount_labs" else cl_by[rid]["analytical_decision"],
                          "source_specialization": hc_by[rid]["group_final_specialization"] if src == "headcount_labs" else cl_by[rid]["specialization"],
                          "source_decision_basis": hc_by[rid]["decision_basis"] if src == "headcount_labs" else "claude_llm",
                          "match_rule": ev[0]["rule"] if ev else "", "description_containment": ev[0]["description_containment"] if ev else "",
                          "title_token_jaccard": ev[0]["title_token_jaccard"] if ev else "", "url_match": ev[0]["url_match"] if ev else "",
                          "combined_decision": cdec, "combined_specialization": cspec, "decision_conflict": dconf,
                          "specialization_conflict": sconf, "conflict_policy": policy})

    for h in HC:
        if "H:" + h["record_key"] in in_x:
            continue
        r = hc_unified(h)
        r.update(combined_group_id="", member_source_record_ids="H:" + h["record_key"], all_urls=h["url"],
                 combined_decision=r["decision"], combined_specialization=r["specialization"], decision_conflict="no",
                 specialization_conflict="no", conflict_policy="", teammate_decisions="")
        combined.append(r)
    for t in tm_unique:
        tid = t["teammate_record_id"]
        if "T:" + tid in in_x:
            continue
        r = tm_unified(tid)
        mem = [tid] + [x["teammate_record_id"] for x in norm if x["tm_primary_record_id"] == tid and x["teammate_record_id"] != tid]
        r.update(combined_group_id="", member_source_record_ids="|".join("T:" + m for m in mem),
                 all_urls="|".join(sorted({cl_by[m]["url"] for m in mem})),
                 combined_decision=r["decision"], combined_specialization=r["specialization"], decision_conflict="no",
                 specialization_conflict="no", conflict_policy="", teammate_decisions="")
        combined.append(r)
    for i, r in enumerate(combined, start=1):
        r["combined_id"] = f"CMB-{i:05d}"

    # every original record -> combined id
    cid_by_member = {}
    for r in combined:
        for m in r["member_source_record_ids"].split("|"):
            cid_by_member[m] = r["combined_id"]
    all_rows = []
    for h in HC_ALL:
        prim = h["primary_record_key"] if h["analytical_status"] == "redundant_duplicate_excluded" else h["record_key"]
        cid = cid_by_member.get("H:" + prim, "")
        all_rows.append({"dataset": "headcount_labs", "source_record_id": h["record_key"], "source_job_id": h["source_job_id"],
                         "job_title": h["job_title"], "company": h["company"], "location": h["location"], "country": h["country"],
                         "posted_date": h["posted_date"], "url": h["url"], "publisher": h["publisher"], "original_sources": "headcount_labs",
                         "within_source_status": h["analytical_status"], "within_source_primary": prim,
                         "source_decision": h["reviewed_decision"], "source_final_decision_after_within_source_dedup": h["group_final_decision"],
                         "source_specialization": h["group_final_specialization"], "decision_basis": h["decision_basis"],
                         "specialization_basis": h["specialization_basis"], "combined_id": cid})
    for t in classified_rows:
        prim = t["tm_primary_record_id"]
        all_rows.append({"dataset": "teammate_jsearch_linkedin", "source_record_id": t["teammate_record_id"], "source_job_id": t["job_id"],
                         "job_title": t["job_title"], "company": t["company"], "location": t["location"], "country": t["country"],
                         "posted_date": t["posted_date"], "url": t["url"], "publisher": t["publisher"], "original_sources": t["original_sources"],
                         "within_source_status": t["tm_analytical_status"], "within_source_primary": prim,
                         "source_decision": t["decision"], "source_final_decision_after_within_source_dedup": t["analytical_decision"],
                         "source_specialization": t["specialization"], "decision_basis": "claude_llm_not_human_approved",
                         "specialization_basis": "claude_llm_not_human_approved" if t["specialization"] else "",
                         "combined_id": cid_by_member.get("T:" + prim, "")})
    cmb_by = {r["combined_id"]: r for r in combined}
    for a in all_rows:
        c = cmb_by.get(a["combined_id"], {})
        a["combined_representative"] = c.get("member_source_record_ids", "").split("|")[0] if c else ""
        a["combined_decision"] = c.get("combined_decision", "")
        a["combined_specialization"] = c.get("combined_specialization", "")

    # ---------------- E. skills
    def jobs_from(recs):
        return [{"record_key": r["source_record_id"], "specialization": r["spec_for_skills"], "job_title": r["job_title"],
                 "company": r["company"], "description": r["description"]} for r in recs]

    def top10(job_list, label):
        ev_rows, job_skill = HCA.skills_for_jobs(job_list)
        tot = collections.Counter(j["specialization"] for j in job_list)
        agg = collections.defaultdict(lambda: collections.defaultdict(set))
        for (rk, sk), (lvl, row) in job_skill.items():
            agg[(row["specialization"], sk)][lvl].add(rk)
        allr = []
        for (sp, sk), d in agg.items():
            req = d["required"] | d["responsibility"]
            allr.append({"scope": label, "specialization": sp, "canonical_skill": sk, "skill_category": SKILLS[sk]["cat"],
                         "ranking_eligible": "no" if SKILLS[sk]["cat"] in NON_RANKING_CATEGORIES else "yes",
                         "specialization_unique_jobs": tot[sp], "jobs_requiring_skill": len(req), "jobs_explicit_requirement": len(d["required"]),
                         "jobs_responsibility_only": len(d["responsibility"]), "jobs_preferred_only": len(d["preferred"]),
                         "jobs_unclear_only": len(d["unclear"]), "jobs_company_context_only": len(d["company_context"]),
                         "pct_jobs_requiring_skill": round(100 * len(req) / tot[sp], 2) if tot[sp] else "",
                         "source_record_ids_requiring": "|".join(sorted(req))})
        tops = []
        for sp in SPECS:
            el = sorted([x for x in allr if x["specialization"] == sp and x["ranking_eligible"] == "yes" and x["jobs_requiring_skill"] > 0],
                        key=lambda x: (-x["jobs_requiring_skill"], -x["jobs_explicit_requirement"], x["canonical_skill"]))
            cut_tie = len(el) > 10 and el[10]["jobs_requiring_skill"] == el[9]["jobs_requiring_skill"]
            prev, rank = None, 0
            for i, x in enumerate(el[:10], start=1):
                if x["jobs_requiring_skill"] != prev:
                    rank, prev = i, x["jobs_requiring_skill"]
                evs = []
                for k in x["source_record_ids_requiring"].split("|")[:3]:
                    lvl, row = job_skill[(k, x["canonical_skill"])]
                    evs.append(f"[{k} | {lvl}] {row['evidence_snippet'][:200]}")
                tops.append({"scope": label, "specialization": sp, "rank": rank, "row_order": i, "canonical_skill": x["canonical_skill"],
                             "skill_category": x["skill_category"], "jobs_requiring_skill": x["jobs_requiring_skill"],
                             "specialization_unique_jobs": x["specialization_unique_jobs"], "pct_jobs_requiring_skill": x["pct_jobs_requiring_skill"],
                             "jobs_explicit_requirement": x["jobs_explicit_requirement"], "jobs_responsibility_only": x["jobs_responsibility_only"],
                             "jobs_preferred_only_not_counted": x["jobs_preferred_only"], "jobs_unclear_only_not_counted": x["jobs_unclear_only"],
                             "tie_at_rank_10_cutoff": "yes" if cut_tie and x["jobs_requiring_skill"] == el[9]["jobs_requiring_skill"] else "no",
                             "evidence_snippets": " || ".join(evs), "source_record_ids": x["source_record_ids_requiring"]})
        return tops, allr, ev_rows, job_skill, tot

    # scopes
    for r in combined:
        r["spec_for_skills"] = r["combined_specialization"]
    comb_conf = [r for r in combined if r["combined_decision"] == "in_scope" and r["combined_specialization"] in SPECS]
    # headcount-only = baseline set (Headcount unique in_scope with specialization), its own decisions
    hc_conf = []
    for h in HC:
        if h["group_final_decision"] == "in_scope" and h["group_final_specialization"] in SPECS:
            hc_conf.append({"source_record_id": h["record_key"], "spec_for_skills": h["group_final_specialization"], "job_title": h["job_title"],
                            "company": h["company"], "description": h["description"]})
    tm_conf = []
    for t in tm_uniq_rows:
        if t["analytical_decision"] == "in_scope" and t["specialization"] in SPECS:
            tm_conf.append({"source_record_id": t["teammate_record_id"], "spec_for_skills": t["specialization"], "job_title": t["job_title"],
                            "company": t["company"], "description": tm_by[t["teammate_record_id"]]["description"]})
    # combined: for teammate-sourced representatives the id is teammate id; for headcount reps the record_key
    c_top, c_all, c_ev, c_js, c_tot = top10(jobs_from(comb_conf), "combined")
    h_top, h_all, _, h_js, h_tot = top10(jobs_from(hc_conf), "headcount_only")
    t_top, t_all, t_ev, t_js, t_tot = top10(jobs_from(tm_conf), "teammate_only")

    rep_src = {r["source_record_id"]: r for r in combined}
    ev_out = []
    for e in c_ev:
        r = rep_src[e["record_key"]]
        e2 = dict(e)
        e2["combined_id"] = r["combined_id"]
        e2["representative_dataset"] = r["source_dataset"]
        e2["source_memberships"] = r["source_memberships"]
        e2["source_record_id"] = e2.pop("record_key")
        ev_out.append(e2)

    # ---------------- F. distributions
    def dist(recs_dec, recs_spec_key, label, n_unique):
        n_in = sum(1 for d, s in recs_dec if d == "in_scope")
        n_as = sum(1 for d, s in recs_dec if d == "in_scope" and s in SPECS)
        out = []
        for sp in SPECS:
            c = sum(1 for d, s in recs_dec if d == "in_scope" and s == sp)
            out.append({"scope": label, "specialization": sp, "unique_in_scope_jobs": c,
                        "pct_of_in_scope_with_specialization": round(100 * c / n_as, 2) if n_as else "",
                        "pct_of_in_scope": round(100 * c / n_in, 2) if n_in else "",
                        "pct_of_all_unique_ads_in_scope_dataset": round(100 * c / n_unique, 2) if n_unique else ""})
        out.append({"scope": label, "specialization": "UNASSIGNED", "unique_in_scope_jobs": n_in - n_as, "pct_of_in_scope_with_specialization": "",
                    "pct_of_in_scope": round(100 * (n_in - n_as) / n_in, 2) if n_in else "", "pct_of_all_unique_ads_in_scope_dataset": ""})
        out.append({"scope": label, "specialization": "TOTAL in_scope", "unique_in_scope_jobs": n_in, "pct_of_in_scope_with_specialization": "",
                    "pct_of_in_scope": 100.0 if n_in else "", "pct_of_all_unique_ads_in_scope_dataset": round(100 * n_in / n_unique, 2) if n_unique else ""})
        return out
    d_comb = dist([(r["combined_decision"], r["combined_specialization"]) for r in combined], None, "combined", len(combined))
    d_hc = dist([(h["group_final_decision"], h["group_final_specialization"]) for h in HC], None, "headcount_only", len(HC))
    d_tm = dist([(t["analytical_decision"], t["specialization"]) for t in tm_uniq_rows], None, "teammate_only", len(tm_uniq_rows))

    # source comparison
    src_cmp = []
    for sp in SPECS + ["UNASSIGNED", "TOTAL in_scope"]:
        a = next(x for x in d_hc if x["specialization"] == sp)
        b = next(x for x in d_tm if x["specialization"] == sp)
        c = next(x for x in d_comb if x["specialization"] == sp)
        src_cmp.append({"metric": "in_scope_jobs_by_specialization", "specialization": sp,
                        "headcount_jobs": a["unique_in_scope_jobs"], "headcount_pct_of_in_scope": a["pct_of_in_scope"],
                        "teammate_jobs": b["unique_in_scope_jobs"], "teammate_pct_of_in_scope": b["pct_of_in_scope"],
                        "combined_jobs": c["unique_in_scope_jobs"], "combined_pct_of_in_scope": c["pct_of_in_scope"],
                        "teammate_jobs_also_in_headcount": sum(1 for x in xrows if x["dataset"] == "teammate" and x["source_specialization"] == sp and x["source_decision"] == "in_scope"),
                        "headcount_top3": "; ".join(f"{t['canonical_skill']} ({t['pct_jobs_requiring_skill']}%)" for t in h_top if t["specialization"] == sp and t["row_order"] <= 3),
                        "teammate_top3": "; ".join(f"{t['canonical_skill']} ({t['pct_jobs_requiring_skill']}%)" for t in t_top if t["specialization"] == sp and t["row_order"] <= 3),
                        "combined_top3": "; ".join(f"{t['canonical_skill']} ({t['pct_jobs_requiring_skill']}%)" for t in c_top if t["specialization"] == sp and t["row_order"] <= 3),
                        "top10_overlap_headcount_vs_teammate": len({t["canonical_skill"] for t in h_top if t["specialization"] == sp} & {t["canonical_skill"] for t in t_top if t["specialization"] == sp}) if sp in SPECS else ""})
    for k, hv, tv in [("unique_job_advertisements", len(HC), len(tm_uniq_rows)),
                      ("in_scope_share_pct", round(100 * sum(1 for h in HC if h["group_final_decision"] == "in_scope") / len(HC), 2),
                       round(100 * sum(1 for t in tm_uniq_rows if t["analytical_decision"] == "in_scope") / len(tm_uniq_rows), 2)),
                      ("posting_date_range", f"{min(h['posted_date'] for h in HC if h['posted_date'])}..{max(h['posted_date'] for h in HC if h['posted_date'])}",
                       f"LinkedIn {min(t['posted_date'] for t in tm_uniq_rows if t['posted_date'])}..{max(t['posted_date'] for t in tm_uniq_rows if t['posted_date'])}; JSearch: relative ages only (\"date_posted=month\" query)"),
                      ("records_without_posted_date", sum(1 for h in HC if not h["posted_date"]), sum(1 for t in tm_uniq_rows if not t["posted_date"])),
                      ("collection_method", "Headcount Labs full feed (all occupations)", "keyword search queries per specialization (JSearch Google-Jobs aggregator, LinkedIn API)")]:
        src_cmp.append({"metric": k, "specialization": "", "headcount_jobs": hv, "teammate_jobs": tv})

    # ---------------- G. unresolved
    unresolved = []
    for r in combined:
        why = []
        if r["combined_decision"] == "needs_review":
            why.append("needs_review" + (" (cross-source conflict)" if r["decision_conflict"] == "yes" else ""))
        if r["combined_decision"] == "in_scope" and r["combined_specialization"] not in SPECS:
            why.append("in_scope without supported specialization")
        if r["specialization_conflict"] == "yes":
            why.append("cross-source specialization conflict")
        if r["decision_conflict"] == "yes" and r["combined_decision"] != "needs_review":
            why.append("cross-source decision conflict resolved by documented policy")
        if r["combined_decision"] == "unclassified":
            why.append("unclassified (no LLM result)")
        if r["source_dataset"].startswith("teammate"):
            t = cl_by[r["source_record_id"]]
            if t["evidence_verified"] == "false":
                why.append("LLM evidence not verbatim -> downgraded")
            if r["combined_decision"] == "in_scope" and t["confidence"] == "low":
                why.append("teammate in_scope with low LLM confidence")
            if t["saudi_location_status"] == "outside_saudi_excluded":
                why.append("excluded: job located outside Saudi Arabia per description")
            elif t["saudi_location_status"] == "saudi_location_unverified" and r["combined_decision"] == "in_scope":
                why.append("in_scope but Saudi location unverified (kept)")
        if r["source_dataset"] == "headcount_labs" and r["specialization_basis"] == "ai_proposed_claude_not_human_approved" and r["combined_decision"] == "in_scope":
            hb = hc_all_by[r["source_record_id"]]
            if hb["ai_proposed_confidence"] in ("low", "medium"):
                why.append(f"Headcount AI-proposed specialization ({hb['ai_proposed_confidence']} confidence)")
        if why:
            unresolved.append({"combined_id": r["combined_id"], "representative_dataset": r["source_dataset"], "source_record_id": r["source_record_id"],
                               "member_source_record_ids": r["member_source_record_ids"], "job_title": r["job_title"], "company": r["company"],
                               "combined_decision": r["combined_decision"], "combined_specialization": r["combined_specialization"],
                               "issues": "; ".join(why), "conflict_policy": r["conflict_policy"], "teammate_decisions": r["teammate_decisions"],
                               "url": r["url"]})

    # ---------------- H. validation
    V = {}
    s1 = stage1
    V["teammate_inputs"] = {
        "final_jobs_json_728": s1["file_counts"]["final_jobs.json"] == 728,
        "final_jobs_csv_equals_json_count": s1["file_counts"]["final_jobs.csv"] == s1["file_counts"]["final_jobs.json"],
        "final_jobs_csv_json_content_identical_except_line_endings": s1["csv_vs_json"]["content_identical"],
        "all_final_records_mapped_to_source_record": s1["final_to_source_mapping"]["unmapped"] == 0,
        "jsearch_all_fully_reconciled_kept_plus_absent": s1["normalized"]["source_counts"]["jsearch"] + s1["source_reconciliation"]["jsearch_all_not_in_final"] == s1["file_counts"]["jsearch_all.json"],
        "linkedin_all_fully_reconciled_kept_plus_absent": s1["normalized"]["source_counts"]["linkedin"] + s1["source_reconciliation"]["linkedin_all_not_in_final"] == s1["file_counts"]["linkedin_all.json"],
        "every_absent_source_record_has_documented_reason": all(r["reason"] for r in read_csv(HERE / "teammate_source_reconciliation.csv"))
        and len(read_csv(HERE / "teammate_source_reconciliation.csv")) == s1["source_reconciliation"]["jsearch_all_not_in_final"] + s1["source_reconciliation"]["linkedin_all_not_in_final"],
        "normalized_records_equal_final_jobs": len(norm) == 728,
        "stable_ids_unique": len({r["teammate_record_id"] for r in norm}) == len(norm),
    }
    V["classification"] = {
        "every_unique_record_has_llm_result": not log["classification_input"]["missing"],
        "no_unexpected_ids": not log["classification_input"]["unexpected_ids"],
        "no_duplicate_result_ids": log["classification_input"]["duplicate_ids_in_results"] == 0,
        "all_decisions_valid": all(t["decision"] in DECISIONS for t in tm_uniq_rows),
        "in_scope_have_valid_specialization": all(t["specialization"] in SPECS for t in tm_uniq_rows if t["decision"] == "in_scope"),
        "non_in_scope_have_no_specialization": all(not t["specialization"] for t in tm_uniq_rows if t["decision"] != "in_scope"),
        "all_final_classifications_have_verified_evidence_or_are_needs_review": all(t["evidence_verified"] == "true" or t["decision"] == "needs_review" for t in tm_uniq_rows),
        "nine_specialization_taxonomy_matches_classifier": SPECS == ["ai", "data_analytics", "software_development", "cloud_devops", "cybersecurity", "infrastructure_networking", "qa_testing", "database_enterprise_systems", "uiux_technical_products"],
        "duplicates_inherit_primary_classification": all(cl_by[r["teammate_record_id"]]["decision"] == cl_by[r["tm_primary_record_id"]]["decision"] for r in norm),
    }
    cmember = collections.Counter(m for r in combined for m in r["member_source_record_ids"].split("|"))
    V["dedup_and_combined"] = {
        "every_headcount_unique_record_in_exactly_one_combined_row": all(cmember["H:" + h["record_key"]] == 1 for h in HC),
        "every_teammate_unique_record_in_exactly_one_combined_row": all(cmember["T:" + t["teammate_record_id"]] == 1 for t in tm_unique),
        "teammate_redundant_records_attached_to_primary": all(cmember.get("T:" + r["teammate_record_id"], 0) == 1 for r in norm),
        "combined_count_identity": len(combined) == len(HC) + len(tm_unique) - sum(len(m) - 1 for m in xgroups),
        "all_original_records_mapped_to_combined_id": all(a["combined_id"] for a in all_rows),
        "all_rows_total_8807_plus_728": len(all_rows) == len(HC_ALL) + len(norm) == 8807 + 728,
        "each_cross_group_has_one_representative": all(sum(1 for x in xrows if x["cross_group_id"] == g and x["is_representative"] == "yes") == 1 for g in {x["cross_group_id"] for x in xrows}),
        "headcount_baseline_unique_8474": len(HC) == 8474,
        "headcount_baseline_in_scope_741": sum(1 for h in HC if h["group_final_decision"] == "in_scope") == 741,
        "combined_decisions_sum": sum(collections.Counter(r["combined_decision"] for r in combined).values()) == len(combined),
        "combined_ids_unique": len({r["combined_id"] for r in combined}) == len(combined),
    }
    base_top = read_csv(HC_DIR / "top10_skills_per_specialization.csv")
    base_sig = [(b["specialization"], b["canonical_skill"], int(b["jobs_requiring_skill"])) for b in base_top]
    new_sig = [(t["specialization"], t["canonical_skill"], t["jobs_requiring_skill"]) for t in h_top]
    V["skills"] = {
        "headcount_only_top10_reproduces_baseline_exactly": base_sig == new_sig,
        "combined_pct_uses_specialization_denominator": all(abs(t["pct_jobs_requiring_skill"] - round(100 * t["jobs_requiring_skill"] / c_tot[t["specialization"]], 2)) < 1e-9 for t in c_top),
        "teammate_pct_uses_specialization_denominator": all(abs(t["pct_jobs_requiring_skill"] - round(100 * t["jobs_requiring_skill"] / t_tot[t["specialization"]], 2)) < 1e-9 for t in t_top),
        "combined_skill_once_per_job": len(c_js) == len(set(c_js)),
        "combined_top10_sorted_desc": all([t["jobs_requiring_skill"] for t in c_top if t["specialization"] == sp] == sorted([t["jobs_requiring_skill"] for t in c_top if t["specialization"] == sp], reverse=True) for sp in SPECS),
        "combined_skill_jobs_are_unique_combined_in_scope": all(rep_src[k]["combined_decision"] == "in_scope" for t in c_top for k in t["source_record_ids"].split("|")),
        "combined_denominators_match_distribution": all(c_tot[sp] == next(x["unique_in_scope_jobs"] for x in d_comb if x["specialization"] == sp) for sp in SPECS),
        "no_job_counted_twice_in_combined": len({r["source_record_id"] for r in comb_conf}) == len(comb_conf),
    }
    hashes_after = {p: sha256(Path(p)) for p in hashes_before}
    changed = [p for p in hashes_before if hashes_before[p] != hashes_after[p]]
    V["originals_unchanged"] = {"protected_files_hashed": len(hashes_before), "all_unchanged": not changed, "changed": changed,
                                "no_pycache_created_in_headcount_folder": not (HC_DIR / "__pycache__").exists()}
    all_ok = all(all(v.values()) for k, v in V.items() if k != "originals_unchanged") and not changed and V["originals_unchanged"]["no_pycache_created_in_headcount_folder"]

    # ---------------- I. write outputs
    files = {}
    tcols = [c for c in classified_rows[0].keys() if c != "description"] + ["description"]
    files["teammate_classified_jobs.csv"] = write_csv("teammate_classified_jobs.csv", classified_rows, tcols)
    files["teammate_unique_jobs.csv"] = write_csv("teammate_unique_jobs.csv", tm_uniq_rows, tcols)
    files["cross_source_duplicate_groups.csv"] = write_csv("cross_source_duplicate_groups.csv", xrows,
                                                           list(xrows[0].keys()) if xrows else ["cross_group_id"])
    files["cross_source_possible_duplicates_not_merged.csv"] = write_csv("cross_source_possible_duplicates_not_merged.csv",
                                                                         [p for p in cross_pairs if p["verdict"] == "possible"],
                                                                         list(cross_pairs[0].keys()) if cross_pairs else ["teammate_record_id"])
    files["combined_all_jobs.csv"] = write_csv("combined_all_jobs.csv", all_rows)
    ccols = ["combined_id", "source_dataset", "source_record_id", "source_job_id", "member_source_record_ids", "source_memberships",
             "combined_group_id", "job_title", "company", "location", "country", "posted_date", "url", "all_urls", "publisher",
             "decision", "specialization", "decision_basis", "specialization_basis", "confidence", "evidence",
             "combined_decision", "combined_specialization", "decision_conflict", "specialization_conflict", "conflict_policy",
             "teammate_decisions", "saudi_location_status", "headcount_duplicate_group_id", "teammate_duplicate_group_id", "description"]
    files["combined_unique_jobs.csv"] = write_csv("combined_unique_jobs.csv", combined, ccols)
    files["combined_specialization_distribution.csv"] = write_csv("combined_specialization_distribution.csv", d_comb + d_hc + d_tm)
    files["source_comparison.csv"] = write_csv("source_comparison.csv", src_cmp,
                                               ["metric", "specialization", "headcount_jobs", "headcount_pct_of_in_scope", "teammate_jobs", "teammate_pct_of_in_scope",
                                                "combined_jobs", "combined_pct_of_in_scope", "teammate_jobs_also_in_headcount", "headcount_top3", "teammate_top3",
                                                "combined_top3", "top10_overlap_headcount_vs_teammate"])
    files["combined_top10_skills.csv"] = write_csv("combined_top10_skills.csv", c_top)
    files["top10_skills_by_source.csv"] = write_csv("top10_skills_by_source.csv", h_top + t_top)
    files["combined_skill_evidence.csv"] = write_csv("combined_skill_evidence.csv", ev_out)
    files["combined_all_canonical_skills.csv"] = write_csv("combined_all_canonical_skills.csv",
                                                           sorted(c_all + t_all, key=lambda x: (x["scope"], x["specialization"], -x["jobs_requiring_skill"], x["canonical_skill"])))
    files["unresolved_cases.csv"] = write_csv("unresolved_cases.csv", unresolved)

    cnt = lambda rows, key: dict(collections.Counter(r[key] for r in rows))  # noqa: E731
    summary = {
        "title": "Multi-source job market integration: Headcount Labs + teammate (JSearch, LinkedIn)",
        "generated_at_utc": log["generated_at_utc"],
        "headcount_baseline": {"source": str(HC_DIR), "unique_job_advertisements": len(HC), "decisions": cnt(HC, "group_final_decision"),
                               "baseline_summary_unique_in_scope": hc_summary["deduplication"]["unique_in_scope_jobs"]},
        "teammate_inputs": {"file_counts": s1["file_counts"], "csv_vs_json": s1["csv_vs_json"], "raw": {k: v for k, v in s1["raw"].items() if k != "of_which_other"},
                            "source_reconciliation": s1["source_reconciliation"], "final_jobs_source_counts": s1["normalized"]["source_counts"],
                            "found_in_counts": s1["normalized"]["found_in_counts"], "missing_fields": s1["normalized"]["missing"],
                            "data_quality_flags": s1["normalized"]["flags"], "country_basis": s1["normalized"]["country_basis"],
                            "existing_classification_or_skill_fields": s1["normalized"]["existing_classification_or_skill_fields"]},
        "teammate_dedup": s1["dedup"],
        "teammate_classification": {
            "method": METHOD, "classifier_prompt_sha256": s1.get("classifier_prompt_sha256"), "input": log["classification_input"],
            "llm_raw_decisions": cnt(tm_uniq_rows, "llm_decision"),
            "validated_decisions_unique": cnt(tm_uniq_rows, "decision"),
            "analytical_decisions_unique (outside-Saudi excluded)": cnt(tm_uniq_rows, "analytical_decision"),
            "in_scope_by_specialization": dict(collections.Counter(t["specialization"] for t in tm_uniq_rows if t["analytical_decision"] == "in_scope")),
            "confidence": cnt(tm_uniq_rows, "confidence"),
            "evidence_verified": cnt(tm_uniq_rows, "evidence_verified"),
            "validation_adjustments": sum(1 for t in tm_uniq_rows if t["validation_notes"]),
            "needs_manual_review_true": sum(1 for t in tm_uniq_rows if t["needs_manual_review"] == "true"),
            "saudi_location_status": cnt(tm_uniq_rows, "saudi_location_status"),
            "job_location_assessment": cnt(tm_uniq_rows, "job_location_assessment"),
            "description_quality": cnt(tm_uniq_rows, "description_quality"),
            "all_records_decisions_incl_duplicates": cnt(classified_rows, "analytical_decision"),
        },
        "cross_source": {"confirmed_groups": len(xgroups), "teammate_records_matched_to_headcount": sum(1 for x in xrows if x["dataset"] == "teammate"),
                         "headcount_records_in_groups": sum(1 for x in xrows if x["dataset"] == "headcount_labs"),
                         "redundant_records_removed": sum(len(m) - 1 for m in xgroups),
                         "rule_counts": dict(collections.Counter(x["match_rule"] for x in xrows if x["dataset"] == "teammate")),
                         "possible_pairs_not_merged": sum(1 for p in cross_pairs if p["verdict"] == "possible"),
                         "groups_with_conflicts": conflicts},
        "combined": {"headcount_unique": len(HC), "teammate_unique": len(tm_uniq_rows), "cross_source_redundant": sum(len(m) - 1 for m in xgroups),
                     "combined_unique_job_advertisements": len(combined), "combined_decisions": cnt(combined, "combined_decision"),
                     "combined_in_scope_with_specialization": len(comb_conf),
                     "combined_by_representative_dataset": cnt(combined, "source_dataset")},
        "distribution": {"combined": d_comb, "headcount_only": d_hc, "teammate_only": d_tm},
        "skills": {"taxonomy": "reused unchanged from postclassification_reviewed/skill_taxonomy.py (343 canonical skills) for comparability",
                   "counting_rule": "required or responsibility evidence only; preferred/unclear/company-context reported separately",
                   "combined_jobs_analyzed": len(comb_conf), "headcount_jobs": len(hc_conf), "teammate_jobs": len(tm_conf),
                   "combined_top10": {sp: [(t["rank"], t["canonical_skill"], t["jobs_requiring_skill"], t["pct_jobs_requiring_skill"]) for t in c_top if t["specialization"] == sp] for sp in SPECS},
                   "teammate_top10": {sp: [(t["rank"], t["canonical_skill"], t["jobs_requiring_skill"], t["pct_jobs_requiring_skill"]) for t in t_top if t["specialization"] == sp] for sp in SPECS}},
        "unresolved": {"rows": len(unresolved), "by_issue": dict(collections.Counter(i.strip() for u in unresolved for i in u["issues"].split(";")))},
        "validation": V, "all_checks_passed": all_ok, "output_files": files,
    }
    summary["output_files"].update({n: str(HERE / n) for n in ("summary.json", "data_quality_report.md", "methodology_and_limitations.md",
                                                                "teammate_normalized_jobs.csv", "teammate_duplicate_groups.csv",
                                                                "teammate_possible_duplicates_not_merged.csv", "teammate_source_reconciliation.csv",
                                                                "teammate_llm_classifications.jsonl", "teammate_prepare.py", "multi_source_integrate.py")})
    (HERE / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("teammate_classification", "cross_source", "combined")}, indent=1, ensure_ascii=False, default=str)[:7000])
    for k, v in V.items():
        bad = [x for x, ok in v.items() if not ok] if k != "originals_unchanged" else ([] if v["all_unchanged"] and v["no_pycache_created_in_headcount_folder"] else v)
        print(k, "OK" if not bad else f"FAILED {bad}")
    print("ALL CHECKS PASSED:", all_ok)


if __name__ == "__main__":
    main()
