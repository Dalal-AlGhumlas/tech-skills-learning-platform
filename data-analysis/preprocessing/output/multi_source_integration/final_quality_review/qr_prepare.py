#!/usr/bin/env python3
"""Final quality review - STAGE 1: build the deduplicated worklist of flagged in-scope jobs and AI-review batches.
Read-only inputs; writes the worklist into this folder and batch files into --batch-dir.
Run: python -B data-analysis/preprocessing/output/multi_source_integration/final_quality_review/qr_prepare.py --batch-dir <dir>
"""
import argparse, collections, csv, json, sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
MSI = HERE.parent
HC = MSI.parent / "headcount/ai_classification/full_dataset/postclassification_reviewed"
sys.path.insert(0, str(HC))
from skill_taxonomy import S as SKILLS, NON_RANKING_CATEGORIES  # noqa: E402
csv.field_size_limit(2**31 - 1)


def rd(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def flags_of(r):
    f = []
    if not r["evidence"].strip():
        f.append("missing_evidence")
    if not r["required_technical_skills"].strip():
        f.append("missing_skills_unassigned" if r["primary_specialization"] == "UNASSIGNED" else "missing_skills_none_detected")
    if r["saudi_location_status"] == "saudi_location_unverified":
        f.append("location_unverified")
    if r["specialization_conflict"] == "yes":
        f.append("specialization_conflict")
    iss = r["unresolved_issues"]
    if "AI-proposed specialization" in iss:
        f.append("ai_proposed_specialization_" + ("low" if "(low" in iss else "medium"))
    if "low LLM confidence" in iss:
        f.append("low_llm_confidence")
    if "resolved by documented policy" in iss:
        f.append("cross_source_decision_conflict_resolved_by_human_precedence")
    if "without supported specialization" in iss:
        f.append("unassigned_specialization")
    if iss.strip():
        f.append("unresolved_issue")
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-dir", type=Path, required=True)
    ap.add_argument("--batches", type=int, default=4)
    a = ap.parse_args()
    a.batch_dir.mkdir(parents=True, exist_ok=True)
    R = rd(MSI / "combined_in_scope_jobs.csv")
    H = {r["record_key"]: r for r in rd(HC / "reviewed_classifications_all.csv")}
    T = {r["teammate_record_id"]: r for r in rd(MSI / "teammate_unique_jobs.csv")}
    TN = {r["teammate_record_id"]: r for r in rd(MSI / "teammate_normalized_jobs.csv")}
    X = rd(MSI / "cross_source_duplicate_groups.csv")
    xg = collections.defaultdict(list)
    for x in X:
        xg[x["cross_group_id"]].append(x)
    work = []
    for r in R:
        f = flags_of(r)
        if not f:
            continue
        ds = r["source_dataset"]
        if ds == "headcount_labs":
            h = H[r["source_record_id"]]
            prior_reason = h["qwen_reason"]
            prior_evidence = h["qwen_evidence"]
            extra = {"qwen_decision": h["qwen_decision"], "qwen_confidence": h["qwen_confidence"],
                     "human_decision": h["human_decision"], "ai_proposed_rationale": h["ai_proposed_rationale"],
                     "ai_proposed_alternatives": h["ai_proposed_alternatives"]}
        else:
            t = T[r["source_record_id"]]
            prior_reason, prior_evidence = t["reason"], t["evidence"]
            extra = {"claude_confidence": t["confidence"], "job_location_assessment": t["job_location_assessment"],
                     "location_evidence": t["location_evidence"], "location_raw": t["location_raw"],
                     "location_recovered": t.get("location_recovered", ""), "location_basis": t.get("location_basis", ""),
                     "linkedin_location_derived": t.get("location_derived_linkedin", ""), "data_quality_flags": t["data_quality_flags"]}
        counterpart = []
        if "specialization_conflict" in f and r["cross_source_group_id"]:
            for x in xg[r["cross_source_group_id"]]:
                if x["dataset"] == "teammate":
                    t = T[x["source_record_id"]]
                    counterpart.append({"dataset": "teammate", "record_id": x["source_record_id"], "job_title": t["job_title"],
                                        "company": t["company"], "decision": t["decision"], "specialization": t["specialization"],
                                        "reason": t["reason"], "evidence": t["evidence"],
                                        "description": TN[x["source_record_id"]]["description"][:8000]})
        work.append({"combined_id": r["combined_id"], "flags": f, "source_dataset": ds, "source_record_id": r["source_record_id"],
                     "job_title": r["job_title"], "company": r["company"], "location": r["location"], "country": r["country"],
                     "publisher": r["publisher"], "url": r["url"],
                     "current_final_decision": r["final_decision"], "current_specialization": r["primary_specialization"],
                     "specialization_assigned_by": r["specialization_assigned_by"], "decision_basis": r["decision_basis"],
                     "prior_reason": prior_reason, "prior_evidence": prior_evidence, "extra": extra,
                     "counterpart_records": counterpart, "description": r["description"][:9000],
                     "description_truncated_for_review": len(r["description"]) > 9000})
    # worklist summary (no descriptions)
    with open(HERE / "_worklist.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["combined_id", "flags", "source_dataset", "source_record_id", "job_title", "company", "current_specialization", "specialization_assigned_by"])
        w.writeheader()
        for x in work:
            w.writerow({k: ("|".join(x[k]) if k == "flags" else x[k]) for k in w.fieldnames})
    # balanced batches by description length
    order = sorted(work, key=lambda x: -len(x["description"]))
    bins = [[] for _ in range(a.batches)]
    sizes = [0] * a.batches
    for x in order:
        i = sizes.index(min(sizes))
        bins[i].append(x)
        sizes[i] += len(x["description"]) + sum(len(c["description"]) for c in x["counterpart_records"])
    for i, b in enumerate(bins, start=1):
        with open(a.batch_dir / f"qr_batch_{i}.jsonl", "w", encoding="utf-8") as f:
            for x in sorted(b, key=lambda x: x["combined_id"]):
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    names = sorted(k for k, v in SKILLS.items() if v["cat"] not in NON_RANKING_CATEGORIES)
    (a.batch_dir / "CANONICAL_SKILLS.txt").write_text("\n".join(names), encoding="utf-8")
    print(json.dumps({"flagged_unique": len(work), "flag_counts": dict(collections.Counter(f for x in work for f in x["flags"])),
                      "batch_sizes": [len(b) for b in bins], "batch_chars": sizes, "canonical_skills": len(names)}, indent=1))


if __name__ == "__main__":
    main()
