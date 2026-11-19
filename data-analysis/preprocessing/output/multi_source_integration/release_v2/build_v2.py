#!/usr/bin/env python3
"""
V2 RELEASE BUILD - Tech Skills Learning Platform, multi-source job dataset.

Applies ONLY the release decisions approved by the project owner on 2026-11-19 to the V1 export
(combined_in_scope_jobs.csv, 1,201 jobs). V1 and all upstream files are read-only.

Approved decisions (owner release approval, items R1-R7):
  R1  POL-001 on the 16 previously human-reviewed jobs: 14 out_of_scope, 2 needs_review
  R2  POL-001 consistency candidates: 3 remain in_scope, 2 out_of_scope, 1 needs_review
  R3  high-confidence verified false positives -> out_of_scope, ONLY if the recommendation is out_of_scope
  R4  other false-positive recommendations -> pending_review (excluded from approved statistics, original kept)
  R5  8 high-confidence verified specialization corrections; other proposals stay pending
  R6  the 4 cross-source specialization conflicts follow their verified recommendations (never applied twice)
  R7  all overlaps resolved by unique combined_id

Run from project root:
  python -B data-analysis/preprocessing/output/multi_source_integration/release_v2/build_v2.py
"""
import collections, csv, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
MSI = HERE.parent
QR = MSI / "final_quality_review"
HC = MSI.parent / "headcount/ai_classification/full_dataset/postclassification_reviewed"
ROOT = MSI.parents[3]
sys.path.insert(0, str(HC))
import headcount_postclassification_analysis as HCA  # noqa: E402  (evidence-based skill extraction, unchanged)
from skill_taxonomy import S as SKILLS, NON_RANKING_CATEGORIES  # noqa: E402
csv.field_size_limit(2**31 - 1)
SPECS = HCA.SPECIALIZATIONS
APPROVAL = "Project-owner V2 release approval, 2026-11-19"
RELEASE = "v2"


def rd(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def wr(name, rows, cols=None):
    cols = cols or (list(rows[0].keys()) if rows else ["empty"])
    with open(HERE / name, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return str(HERE / name)


def nq(s):
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-").replace("‎", "")
    s = re.sub(r"[*#_`\\]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    protected = [p for p in MSI.parent.rglob("*") if p.is_file() and HERE not in p.parents] + \
                [p for p in (ROOT / "Data & Schemas").rglob("*") if p.is_file()]
    before = {str(p): sha(p) for p in protected}

    V1 = rd(MSI / "combined_in_scope_jobs.csv")
    J = {r["combined_id"]: r for r in V1}
    HD = {h["combined_id"]: h for h in rd(QR / "human_decisions_required.csv")}
    POL = rd(QR / "policy_pol001_review_16_jobs.csv")
    CAN = rd(QR / "policy_pol001_consistency_candidates.csv")
    CON = {c["combined_id"]: c for c in rd(QR / "classification_concerns.csv") if c["concern_type"] == "cross_source_specialization_conflict"}
    SKF = rd(QR / "proposed_skill_fixes.csv")
    EVF = {e["combined_id"]: e for e in rd(QR / "proposed_evidence_fixes.csv")}  # verified supporting quotes (separate column; decisions untouched)
    text = lambda cid: J[cid]["job_title"] + " \n " + J[cid]["description"]  # noqa: E731

    decision = {}   # combined_id -> (v2_decision_status, change dict)   (first approved rule wins; R7)
    changes, pending, spec_change = [], [], {}
    rejected = []

    def add_change(cid, rule, ctype, field, old, new, basis, ev, conf=""):
        ok = nq(ev) in nq(text(cid)) if ev else False
        changes.append({"change_id": f"V2-{len(changes) + 1:04d}", "release": RELEASE, "approval": f"{APPROVAL}, item {rule}",
                        "combined_id": cid, "source_dataset": J[cid]["source_dataset"], "source_record_id": J[cid]["source_record_id"],
                        "member_source_record_ids": J[cid]["member_source_record_ids"], "job_title": J[cid]["job_title"], "company": J[cid]["company"],
                        "change_type": ctype, "field": field, "v1_value": old, "v2_value": new,
                        "v1_decision_basis": J[cid]["decision_basis"], "v1_specialization_basis": J[cid]["specialization_assigned_by"],
                        "change_basis": basis, "evidence": ev, "evidence_verified_verbatim": ok, "confidence": conf})
        return ok

    # R1 POL-001 (16)
    for p in POL:
        cid = p["combined_id"]
        new = p["pol001_recommended_decision"]
        st = "excluded_out_of_scope_POL-001" if new == "out_of_scope" else "needs_review_POL-001"
        ok = add_change(cid, "R1", "policy_POL-001_" + new, "final_decision", "in_scope", new,
                        f"Approved project policy POL-001 applied to human-reviewed job #{p['human_review_number']} (original human decision preserved in V1)",
                        p["pol001_evidence"], p["pol001_confidence"])
        assert ok, cid
        decision[cid] = st
    # R2 consistency candidates (6)
    for c in CAN:
        cid = c["combined_id"]
        assert cid not in decision
        new = c["pol001_recommended_decision"]
        if new == "in_scope":
            decision[cid] = "confirmed_in_scope_POL-001_reviewed"
            continue
        st = "excluded_out_of_scope_POL-001" if new == "out_of_scope" else "needs_review_POL-001"
        ok = add_change(cid, "R2", "policy_POL-001_consistency_" + new, "final_decision", "in_scope", new,
                        "Approved project policy POL-001, consistency application" + (f" to human-reviewed job #{c['human_review_number']}" if c["human_review_number"] else ""),
                        c["pol001_evidence"], c["pol001_confidence"])
        assert ok, cid
        decision[cid] = st
    # R3 / R4 false positives
    for cid, h in HD.items():
        if h["priority"] != "high" or h["contradicts_human_decision"] == "yes" or cid in decision:
            continue
        clear = (h["suggested_bulk_action"] == "accept_if_agree" and h["ai_recommended_decision"] == "out_of_scope"
                 and h["evidence_verified_verbatim"] == "True" and h["ai_review_confidence"] == "high")
        if clear:
            ok = add_change(cid, "R3", "verified_false_positive_exclusion", "final_decision", "in_scope", "out_of_scope",
                            "High-confidence AI quality-review recommendation with verified evidence, approved by owner (R3)",
                            h["evidence"], h["ai_review_confidence"])
            if ok:
                decision[cid] = "excluded_out_of_scope_verified_false_positive"
                continue
            rejected.append((cid, "evidence not verified at build time"))
        why = ("high-confidence row but recommendation is not out_of_scope: " + h["decision_needed"]) if h["suggested_bulk_action"] == "accept_if_agree" else h["decision_needed"]
        pending.append({"combined_id": cid, "pending_type": "decision_pending_review", "counted_in_v2_statistics": "no",
                        "v1_final_decision": "in_scope", "v1_specialization": J[cid]["primary_specialization"],
                        "ai_recommended_decision": h["ai_recommended_decision"], "ai_recommended_specialization": h["ai_recommended_specialization"],
                        "ai_review_confidence": h["ai_review_confidence"], "evidence": h["evidence"], "evidence_verified_verbatim": h["evidence_verified_verbatim"],
                        "reason": why, "rule": "R4"})
        decision[cid] = "pending_review"
    for cid, st in decision.items():
        if st == "needs_review_POL-001":
            p = next((x for x in POL + CAN if x["combined_id"] == cid))
            pending.append({"combined_id": cid, "pending_type": "needs_review_under_POL-001", "counted_in_v2_statistics": "no",
                            "v1_final_decision": "in_scope", "v1_specialization": J[cid]["primary_specialization"],
                            "ai_recommended_decision": "needs_review", "ai_recommended_specialization": "",
                            "ai_review_confidence": p["pol001_confidence"], "evidence": p["pol001_evidence"], "evidence_verified_verbatim": "True",
                            "reason": p["pol001_reason"], "rule": "R1" if x_in(POL, cid) else "R2"})

    # R5 / R6 specialization corrections (only for jobs still approved in_scope)
    approved_ids = [cid for cid in J if decision.get(cid, "confirmed_in_scope") in ("confirmed_in_scope", "confirmed_in_scope_POL-001_reviewed")]
    for cid, h in HD.items():
        if h["priority"] != "medium" or cid not in approved_ids:
            continue
        rec = h["ai_recommended_specialization"]
        is_conflict = cid in CON
        if is_conflict:
            continue  # handled once under R6
        if h["suggested_bulk_action"] == "accept_if_agree" and rec in SPECS and h["evidence_verified_verbatim"] == "True":
            if add_change(cid, "R5", "specialization_correction", "specialization", J[cid]["primary_specialization"], rec,
                          "High-confidence AI quality-review specialization correction with verified evidence, approved by owner (R5)",
                          h["evidence"], h["ai_review_confidence"]):
                spec_change[cid] = rec
                continue
        pending.append({"combined_id": cid, "pending_type": "specialization_correction_pending", "counted_in_v2_statistics": "yes (under V1 specialization)",
                        "v1_final_decision": "in_scope", "v1_specialization": J[cid]["primary_specialization"],
                        "ai_recommended_decision": "in_scope", "ai_recommended_specialization": rec,
                        "ai_review_confidence": h["ai_review_confidence"], "evidence": h["evidence"], "evidence_verified_verbatim": h["evidence_verified_verbatim"],
                        "reason": h["decision_needed"], "rule": "R5"})
    for cid, c in CON.items():
        rec = c["recommended_specialization"]
        cur = J[cid]["primary_specialization"]
        if cid not in approved_ids:
            continue
        if c["quality_status"] == "clear_recommendation_verified" and rec in SPECS and rec != cur:
            evq = c["evidence"]
            ok = add_change(cid, "R6", "cross_source_conflict_resolution", "specialization", cur, rec,
                            "Verified cross-source conflict recommendation (both original decisions preserved in V1 cross_source_duplicate_groups.csv), approved by owner (R6)",
                            evq if nq(evq) in nq(text(cid)) else "", c["review_confidence"])
            if not ok:  # conflict evidence may come from the counterpart description; record it from there
                changes[-1]["evidence"] = evq
                changes[-1]["evidence_verified_verbatim"] = c["evidence_verified_verbatim"] == "True"
                changes[-1]["change_basis"] += " [evidence quoted from the other source's description]"
            spec_change[cid] = rec
        else:
            changes.append({"change_id": f"V2-{len(changes) + 1:04d}", "release": RELEASE, "approval": f"{APPROVAL}, item R6",
                            "combined_id": cid, "source_dataset": J[cid]["source_dataset"], "source_record_id": J[cid]["source_record_id"],
                            "member_source_record_ids": J[cid]["member_source_record_ids"], "job_title": J[cid]["job_title"], "company": J[cid]["company"],
                            "change_type": "cross_source_conflict_resolution_no_change", "field": "specialization", "v1_value": cur, "v2_value": cur,
                            "v1_decision_basis": J[cid]["decision_basis"], "v1_specialization_basis": J[cid]["specialization_assigned_by"],
                            "change_basis": "Verified recommendation confirms the kept specialization; conflict marked resolved", "evidence": c["evidence"],
                            "evidence_verified_verbatim": c["evidence_verified_verbatim"] == "True", "confidence": c["review_confidence"]})

    # ---------------- V2 dataset
    v2 = []
    for r in V1:
        cid = r["combined_id"]
        st = decision.get(cid, "confirmed_in_scope")
        if st not in ("confirmed_in_scope", "confirmed_in_scope_POL-001_reviewed"):
            continue
        o = {"combined_id": cid}
        o.update({k: v for k, v in r.items() if k not in ("combined_id", "primary_specialization", "specialization_assigned_by",
                                                           "required_technical_skills", "required_technical_skills_count",
                                                           "preferred_only_technical_skills", "skill_extraction_status", "description")})
        o["v1_primary_specialization"] = r["primary_specialization"]
        o["v1_specialization_assigned_by"] = r["specialization_assigned_by"]
        o["primary_specialization"] = spec_change.get(cid, r["primary_specialization"])
        o["specialization_assigned_by"] = ("v2_correction_approved_by_owner (" + ("R6 conflict" if cid in CON else "R5") + ")") if cid in spec_change else r["specialization_assigned_by"]
        o["v2_status"] = ("in_scope_specialization_corrected" if cid in spec_change else
                          ("confirmed_in_scope_POL-001_reviewed" if st == "confirmed_in_scope_POL-001_reviewed" else "confirmed_in_scope"))
        o["v2_pending_specialization_correction"] = next((p["ai_recommended_specialization"] for p in pending if p["combined_id"] == cid and p["pending_type"] == "specialization_correction_pending"), "")
        o["v2_change_ids"] = "|".join(c["change_id"] for c in changes if c["combined_id"] == cid and c["v1_value"] != c["v2_value"])
        ef = EVF.get(cid)
        ok_ev = bool(ef) and ef["proposed_evidence_verified_verbatim"] == "True" and ef["quality_status"] in ("credible_evidence_verified", "weak_evidence_verified") \
            and nq(ef["proposed_evidence_NEW"]) in nq(text(cid))
        o["quality_review_evidence"] = ef["proposed_evidence_NEW"] if ok_ev else ""
        o["quality_review_evidence_status"] = ef["quality_status"] if ok_ev else ("" if not ef else "not_used")
        o["release"] = RELEASE
        o["description"] = r["description"]
        v2.append(o)
    assert all(o["primary_specialization"] in SPECS for o in v2), "unassigned job in approved V2"

    # ---------------- skills: rerun the unchanged evidence-based extractor on approved V2 jobs
    jobs = [{"record_key": o["combined_id"], "specialization": o["primary_specialization"], "job_title": o["job_title"],
             "company": o["company"], "description": o["description"]} for o in v2]
    ev_rows, job_skill = HCA.skills_for_jobs(jobs)
    v2ids = {o["combined_id"] for o in v2}
    spec_of = {o["combined_id"]: o["primary_specialization"] for o in v2}
    # incorporate SAFE verified skill fixes: existing taxonomy skills, verbatim evidence, required/responsibility level
    supplements = []
    for s in SKF:
        cid = s["combined_id"]
        if (cid in v2ids and s["quality_status"] == "verified_existing_skill_missed_by_extractor" and s["would_count_if_accepted"] == "True"
                and s["proposed_skill"] in SKILLS and SKILLS[s["proposed_skill"]]["cat"] not in NON_RANKING_CATEGORIES
                and nq(s["evidence"]) in nq(text(cid))):
            for sk in [s["proposed_skill"]] + ([SKILLS[s["proposed_skill"]]["parent"]] if SKILLS[s["proposed_skill"]]["parent"] else []):
                if (cid, sk) in job_skill and job_skill[(cid, sk)][0] in ("required", "responsibility"):
                    continue
                row = {"record_key": cid, "specialization": spec_of[cid], "job_title": J[cid]["job_title"], "company": J[cid]["company"],
                       "canonical_skill": sk, "credited_via": "" if sk == s["proposed_skill"] else f"child skill '{s['proposed_skill']}'",
                       "skill_category": SKILLS[sk]["cat"], "ranking_eligible": "yes", "matched_text": s["evidence"][:80], "char_offset": "",
                       "section_detected": "", "evidence_level": s["proposed_level"],
                       "evidence_level_reason": "verified quality-review supplement (extractor missed: non-English/unstructured text)",
                       "counts_as_requirement": "yes", "evidence_snippet": s["evidence"]}
                job_skill[(cid, sk)] = (s["proposed_level"], row)
                ev_rows.append(row)
                supplements.append((cid, sk))
    tot = collections.Counter(spec_of.values())
    agg = collections.defaultdict(lambda: collections.defaultdict(set))
    for (cid, sk), (lvl, row) in job_skill.items():
        agg[(spec_of[cid], sk)][lvl].add(cid)
    top = []
    for sp in SPECS:
        el = []
        for (s2, sk), d in agg.items():
            if s2 != sp or SKILLS[sk]["cat"] in NON_RANKING_CATEGORIES:
                continue
            req = d["required"] | d["responsibility"]
            if req:
                el.append((sk, req, d))
        el.sort(key=lambda x: (-len(x[1]), -len(x[2]["required"]), x[0]))
        tie = len(el) > 10 and len(el[10][1]) == len(el[9][1])
        prev, rank = None, 0
        for i, (sk, req, d) in enumerate(el[:10], start=1):
            if len(req) != prev:
                rank, prev = i, len(req)
            evs = [f"[{k} | {job_skill[(k, sk)][0]}] {job_skill[(k, sk)][1]['evidence_snippet'][:200]}" for k in sorted(req)[:3]]
            top.append({"release": RELEASE, "specialization": sp, "rank": rank, "row_order": i, "canonical_skill": sk, "skill_category": SKILLS[sk]["cat"],
                        "jobs_requiring_skill": len(req), "specialization_v2_jobs": tot[sp], "pct_jobs_requiring_skill": round(100 * len(req) / tot[sp], 2),
                        "jobs_explicit_requirement": len(d["required"]), "jobs_responsibility_only": len(d["responsibility"]),
                        "jobs_preferred_only_not_counted": len(d["preferred"]), "jobs_unclear_only_not_counted": len(d["unclear"]),
                        "jobs_via_verified_supplement": sum(1 for k in req if (k, sk) in set(supplements)),
                        "tie_at_rank_10_cutoff": "yes" if tie and len(req) == len(el[9][1]) else "no",
                        "evidence_snippets": " || ".join(evs), "source_combined_ids": "|".join(sorted(req))})
    # job-level skill lists + job_skills table
    req_by = collections.defaultdict(set)
    jsk = []
    for (cid, sk), (lvl, row) in sorted(job_skill.items()):
        elig = SKILLS[sk]["cat"] not in NON_RANKING_CATEGORIES
        if elig and lvl in ("required", "responsibility"):
            req_by[cid].add(sk)
        jsk.append({"release": RELEASE, "combined_id": cid, "specialization": spec_of[cid], "canonical_skill": sk, "skill_category": SKILLS[sk]["cat"],
                    "ranking_eligible": "yes" if elig else "no", "best_evidence_level": lvl,
                    "counts_as_requirement": "yes" if (elig and lvl in ("required", "responsibility")) else "no",
                    "evidence_source": "verified_quality_review_supplement" if (cid, sk) in set(supplements) else "extractor",
                    "evidence_snippet": row["evidence_snippet"]})
    for o in v2:
        o["required_technical_skills_v2"] = "|".join(sorted(req_by.get(o["combined_id"], ())))
        o["required_technical_skills_v2_count"] = len(req_by.get(o["combined_id"], ()))
        o["skill_status_v2"] = "extracted" if req_by.get(o["combined_id"]) else "no_required_technical_skill_found"
    cols = list(v2[0].keys())
    cols.remove("description")
    cols.append("description")

    # ---------------- distribution
    by_src = collections.defaultdict(collections.Counter)
    for o in v2:
        by_src[o["primary_specialization"]][o["source_dataset"]] += 1
    v1cnt = collections.Counter(r["primary_specialization"] for r in V1)
    dist = []
    for sp in SPECS:
        n = tot[sp]
        dist.append({"release": RELEASE, "specialization": sp, "v2_in_scope_jobs": n, "pct_of_v2_in_scope": round(100 * n / len(v2), 2),
                     "v1_jobs": v1cnt[sp], "change_vs_v1": n - v1cnt[sp],
                     "represented_by_headcount_labs": by_src[sp]["headcount_labs"], "represented_by_teammate": by_src[sp]["teammate_jsearch_linkedin"],
                     "specializations_corrected_into": sum(1 for c, s in spec_change.items() if s == sp),
                     "specializations_corrected_out_of": sum(1 for c in spec_change if J[c]["primary_specialization"] == sp)})
    dist.append({"release": RELEASE, "specialization": "TOTAL", "v2_in_scope_jobs": len(v2), "pct_of_v2_in_scope": 100.0, "v1_jobs": len(V1),
                 "change_vs_v1": len(v2) - len(V1), "represented_by_headcount_labs": sum(1 for o in v2 if o["source_dataset"] == "headcount_labs"),
                 "represented_by_teammate": sum(1 for o in v2 if o["source_dataset"] != "headcount_labs"),
                 "specializations_corrected_into": len(spec_change), "specializations_corrected_out_of": len(spec_change)})

    # ---------------- pending file enrichment
    for p in pending:
        r = J[p["combined_id"]]
        p.update(job_title=r["job_title"], company=r["company"], source_dataset=r["source_dataset"], source_record_id=r["source_record_id"],
                 member_source_record_ids=r["member_source_record_ids"], url=r["url"], v1_decision_basis=r["decision_basis"],
                 v1_specialization_basis=r["specialization_assigned_by"], human_decision="", human_notes="")
    pending.sort(key=lambda p: ({"decision_pending_review": 0, "needs_review_under_POL-001": 1, "specialization_correction_pending": 2}[p["pending_type"]], p["combined_id"]))
    pcols = ["combined_id", "pending_type", "counted_in_v2_statistics", "job_title", "company", "source_dataset", "source_record_id",
             "member_source_record_ids", "url", "v1_final_decision", "v1_specialization", "v1_decision_basis", "v1_specialization_basis",
             "ai_recommended_decision", "ai_recommended_specialization", "ai_review_confidence", "evidence", "evidence_verified_verbatim",
             "reason", "rule", "human_decision", "human_notes"]

    # ---------------- validation
    C = collections.Counter
    st_count = C(decision.get(cid, "confirmed_in_scope") for cid in J)
    excluded_pol = sum(1 for v in decision.values() if v == "excluded_out_of_scope_POL-001")
    excluded_fp = sum(1 for v in decision.values() if v == "excluded_out_of_scope_verified_false_positive")
    pend_dec = sum(1 for p in pending if p["counted_in_v2_statistics"] == "no")
    pend_spec = sum(1 for p in pending if p["pending_type"] == "specialization_correction_pending")
    ids = [o["combined_id"] for o in v2]
    members = [m for o in v2 for m in o["member_source_record_ids"].split("|")]
    applied = [c for c in changes if c["v1_value"] != c["v2_value"]]
    checks = {
        "v1_input_rows_1201": len(V1) == 1201,
        "every_v1_job_has_exactly_one_v2_status": sum(st_count.values()) == len(V1),
        "identity_v2 = v1 - excluded - pending_decisions": len(v2) == len(V1) - excluded_pol - excluded_fp - pend_dec,
        "no_duplicate_combined_id_in_v2": len(ids) == len(set(ids)),
        "no_source_record_in_two_v2_rows": len(members) == len(set(members)),
        "no_combined_id_changed_twice_same_field": len({(c["combined_id"], c["field"]) for c in applied}) == len(applied),
        "no_job_both_in_v2_and_pending_decision": not (set(ids) & {p["combined_id"] for p in pending if p["counted_in_v2_statistics"] == "no"}),
        "excluded_jobs_not_in_v2": not (set(ids) & {c for c, v in decision.items() if v.startswith("excluded")}),
        "all_applied_changes_have_verified_evidence": all(c["evidence_verified_verbatim"] in (True, "True") for c in applied),
        "every_v2_job_has_one_of_nine_specializations": all(o["primary_specialization"] in SPECS for o in v2),
        "specialization_counts_sum_to_v2_total": sum(d["v2_in_scope_jobs"] for d in dist[:9]) == len(v2),
        "pol001_exclusions_16": excluded_pol == 16,
        "four_conflicts_handled_once": sum(1 for c in changes if c["combined_id"] in CON) == 4,
        "pct_uses_v2_specialization_denominator": all(abs(t["pct_jobs_requiring_skill"] - round(100 * t["jobs_requiring_skill"] / tot[t["specialization"]], 2)) < 1e-9 and t["specialization_v2_jobs"] == tot[t["specialization"]] for t in top),
        "top10_sorted_desc": all([t["jobs_requiring_skill"] for t in top if t["specialization"] == sp] == sorted([t["jobs_requiring_skill"] for t in top if t["specialization"] == sp], reverse=True) for sp in SPECS),
        "top10_max_10_per_specialization": all(sum(1 for t in top if t["specialization"] == sp) <= 10 for sp in SPECS),
        "skill_source_ids_all_in_v2": all(k in v2ids for t in top for k in t["source_combined_ids"].split("|")),
        "skill_counted_once_per_job": len(job_skill) == len(set(job_skill)),
        "supplement_quotes_verified": all(nq(job_skill[k][1]["evidence_snippet"]) in nq(text(k[0])) for k in supplements),
        "descriptions_identical_to_v1": all(o["description"] == J[o["combined_id"]]["description"] for o in v2),
        "no_rejected_changes": not rejected,
    }
    after = {p: sha(Path(p)) for p in before}
    changed = [p for p in before if before[p] != after[p]]
    checks["v1_and_upstream_files_unchanged_sha256"] = not changed
    checks["no_pycache_in_headcount_folder"] = not (HC / "__pycache__").exists()
    ok_all = all(checks.values())

    files = {
        "combined_in_scope_jobs_v2.csv": wr("combined_in_scope_jobs_v2.csv", v2, cols),
        "combined_top10_skills_v2.csv": wr("combined_top10_skills_v2.csv", top),
        "combined_specialization_distribution_v2.csv": wr("combined_specialization_distribution_v2.csv", dist),
        "pending_review_jobs.csv": wr("pending_review_jobs.csv", pending, pcols),
        "v2_change_log.csv": wr("v2_change_log.csv", changes),
        "job_skills_v2.csv": wr("job_skills_v2.csv", jsk),
    }
    summary = {
        "release": RELEASE, "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "approval": APPROVAL,
        "input_v1": str(MSI / "combined_in_scope_jobs.csv"), "v1_in_scope": len(V1),
        "v2_approved_in_scope": len(v2),
        "excluded_POL-001": {"total": excluded_pol, "R1_previously_human_reviewed": sum(1 for c in changes if c["change_type"] == "policy_POL-001_out_of_scope"),
                             "R2_consistency": sum(1 for c in changes if c["change_type"] == "policy_POL-001_consistency_out_of_scope")},
        "excluded_verified_false_positives": excluded_fp,
        "pending_excluded_from_statistics": {"total": pend_dec, "by_type": dict(C(p["pending_type"] for p in pending if p["counted_in_v2_statistics"] == "no"))},
        "pending_specialization_corrections_counted_under_v1_spec": pend_spec,
        "specializations_corrected": {"total": len(spec_change), "R5": sum(1 for c in changes if c["change_type"] == "specialization_correction"),
                                      "R6_conflicts": sum(1 for c in changes if c["change_type"] == "cross_source_conflict_resolution"),
                                      "transitions": dict(C(f"{J[c]['primary_specialization']} -> {s}" for c, s in spec_change.items()))},
        "conflicts": {c: spec_change.get(c, J[c]["primary_specialization"] + " (kept)") for c in sorted(CON)},
        "v2_status_counts": dict(C(o["v2_status"] for o in v2)),
        "v1_job_dispositions": dict(st_count),
        "distribution_v2": {d["specialization"]: d["v2_in_scope_jobs"] for d in dist},
        "distribution_v2_pct": {d["specialization"]: d["pct_of_v2_in_scope"] for d in dist[:9]},
        "source_representation_v2": dict(C(o["source_dataset"] for o in v2)),
        "source_memberships_v2": dict(C(o["source_memberships"] for o in v2)),
        "skills": {"pipeline": "headcount_postclassification_analysis.skills_for_jobs + skill_taxonomy.py (unchanged, 343 canonical skills)",
                   "jobs_analyzed": len(jobs), "verified_supplement_pairs_added": len(supplements),
                   "jobs_with_required_skill": sum(1 for o in v2 if o["required_technical_skills_v2"]),
                   "jobs_without_required_skill": sum(1 for o in v2 if not o["required_technical_skills_v2"]),
                   "new_canonical_skills_proposed_NOT_added": sorted({s["proposed_skill"] for s in SKF if s["quality_status"] == "verified_new_canonical_skill_proposed"}),
                   "top10": {sp: [(t["rank"], t["canonical_skill"], t["jobs_requiring_skill"], t["pct_jobs_requiring_skill"]) for t in top if t["specialization"] == sp] for sp in SPECS}},
        "missing_values_v2": {k: sum(1 for o in v2 if not str(o[k]).strip()) for k in ("job_title", "company", "location", "country", "posted_date", "url", "description", "evidence", "required_technical_skills_v2")},
        "jobs_without_any_classification_evidence (evidence and quality_review_evidence both empty)": sum(1 for o in v2 if not o["evidence"].strip() and not o["quality_review_evidence"].strip()),
        "quality_review_evidence_attached": dict(C(o["quality_review_evidence_status"] for o in v2 if o["quality_review_evidence_status"])),
        "validation": checks, "all_checks_passed": ok_all, "changed_files": changed, "rejected_changes": rejected,
        "files": {**files, "v2_validation_report.md": str(HERE / "v2_validation_report.md"), "v2_summary.json": str(HERE / "v2_summary.json"), "build_v2.py": str(HERE / "build_v2.py")},
    }
    (HERE / "v2_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    write_report(summary, dist, top, checks)
    print(json.dumps({k: summary[k] for k in ("v2_approved_in_scope", "excluded_POL-001", "excluded_verified_false_positives", "pending_excluded_from_statistics",
                                               "pending_specialization_corrections_counted_under_v1_spec", "specializations_corrected", "conflicts",
                                               "distribution_v2", "skills", "validation", "all_checks_passed")}, indent=1, ensure_ascii=False, default=str))


def x_in(rows, cid):
    return any(r["combined_id"] == cid for r in rows)


def write_report(s, dist, top, checks):
    L = ["# V2 release: validation report", "",
         f"**Release:** {s['release']}",
         f"**Approval:** {s['approval']}",
         f"**Input:** V1 `combined_in_scope_jobs.csv` (1,201 jobs), unchanged (SHA-256 verified).", "",
         "## Result", "",
         "| | Jobs |", "|---|---:|",
         f"| V1 in_scope | {s['v1_in_scope']} |",
         f"| Excluded under POL-001 | {s['excluded_POL-001']['total']} ({s['excluded_POL-001']['R1_previously_human_reviewed']} reviewed + {s['excluded_POL-001']['R2_consistency']} consistency) |",
         f"| Excluded as verified false positives | {s['excluded_verified_false_positives']} |",
         f"| Pending review, not counted in V2 statistics | {s['pending_excluded_from_statistics']['total']} |",
         f"| **V2 approved in_scope** | **{s['v2_approved_in_scope']}** |", "",
         "### Pending decisions by type", "",
         "| Pending type | Jobs |", "|---|---:|"]
    L += [f"| {k} | {v} |" for k, v in s["pending_excluded_from_statistics"]["by_type"].items()]
    L += ["",
          f"**Specializations corrected:** {s['specializations_corrected']['total']} "
          f"({s['specializations_corrected']['R5']} approved corrections + {s['specializations_corrected']['R6_conflicts']} conflict resolutions).", "",
          f"**Still pending:** {s['pending_specialization_corrections_counted_under_v1_spec']} specialization corrections. "
          "These jobs are counted in V2 under their V1 specialization.", "",
          "## Checks", "",
          "| Check | Result |", "|---|---|"]
    L += [f"| {k} | {'PASS' if v else 'FAIL'} |" for k, v in checks.items()]
    L += ["", "## Specialization distribution (V2)", "",
          "| Specialization | V2 | % | V1 | Change |", "|---|---:|---:|---:|---:|"]
    L += [f"| {d['specialization']} | {d['v2_in_scope_jobs']} | {d['pct_of_v2_in_scope']} | {d['v1_jobs']} | {d['change_vs_v1']:+d} |" for d in dist]
    L += ["", "## Top 10 skills (V2, recomputed)", "",
          "Recomputed with the unchanged evidence-based extractor on V2 approved jobs only.",
          "The percentage denominator is each specialization's V2 job count.", "",
          f"{s['skills']['verified_supplement_pairs_added']} verified skill supplements from the quality review were added. "
          "These are existing taxonomy skills that the extractor missed, and every one has a verbatim quote.", "",
          "New canonical skills were **not** added; that taxonomy change is pending.", ""]
    for sp in [d["specialization"] for d in dist[:9]]:
        L.append(f"- **{sp}** ({next(d['v2_in_scope_jobs'] for d in dist if d['specialization'] == sp)}): " +
                 " · ".join(f"{t['rank']}. {t['canonical_skill']} {t['jobs_requiring_skill']} ({t['pct_jobs_requiring_skill']}%)" for t in top if t["specialization"] == sp))
    L += ["", "## Missing values in V2", "", "| Column | Empty |", "|---|---:|"]
    L += [f"| {k} | {v} |" for k, v in s["missing_values_v2"].items()]
    L += ["", "The `evidence` column holds Qwen's original evidence and was left unchanged.",
          "Verified quotes from the quality review are in the separate `quality_review_evidence` column "
          f"({s['quality_review_evidence_attached']}).", "",
          f"Jobs with no evidence in either column: "
          f"**{s['jobs_without_any_classification_evidence (evidence and quality_review_evidence both empty)']}**."]
    L += ["", "## Notes and limitations", "",
          "- **No accuracy estimate.** There is no validated evaluation sample. Decisions and specializations are human-, Qwen- or Claude-based; the basis is recorded per job.",
          "- **Pending jobs** are listed in `pending_review_jobs.csv`. Their V1 decisions are untouched; they are only excluded from the approved V2 statistics.",
          "- **Unreviewed records.** About 913 unflagged in-scope jobs and all out-of-scope jobs were not re-reviewed.",
          "- **Missing JSearch dates.** JSearch posting dates are unavailable.",
          "- **Scope of the data.** The teammate data comes from targeted queries, and the results describe these datasets, not the whole Saudi labour market.", "",
          f"**Overall: {'ALL CHECKS PASSED' if s['all_checks_passed'] else 'CHECK FAILURES, see table'}**"]
    (HERE / "v2_validation_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
