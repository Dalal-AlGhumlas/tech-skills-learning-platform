#!/usr/bin/env python3
"""Final quality review - STAGE 2: verify AI-review recommendations against original descriptions and write
the review deliverables. Nothing existing is modified; every recommendation is labelled as an AI recommendation
(NOT applied). Run: python -B .../final_quality_review/qr_compile.py --batch-dir <dir>
"""
import argparse, collections, csv, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
MSI = HERE.parent
ROOT = MSI.parents[2]
HC = MSI.parent / "headcount/ai_classification/full_dataset/postclassification_reviewed"
sys.path.insert(0, str(HC))
import headcount_postclassification_analysis as HCA  # noqa: E402  (extract_skills / compiled taxonomy only)
from skill_taxonomy import S as SKILLS, NON_RANKING_CATEGORIES  # noqa: E402
csv.field_size_limit(2**31 - 1)
SPECS = HCA.SPECIALIZATIONS
VERDICTS = {"supported", "supported_different_specialization", "weak_but_plausible", "likely_false_positive", "insufficient_information"}
LOCV = {"confirmed_saudi", "likely_saudi", "uncertain", "outside_saudi"}
REC_LABEL = "AI recommendation (Claude review) - NOT applied to any existing output"


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


def verified(quote, *texts):
    q = nq(quote)
    return bool(q) and len(q) >= 3 and any(q in nq(t) for t in texts)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-dir", type=Path, required=True)
    a = ap.parse_args()
    protected = [p for p in (MSI.parent).rglob("*") if p.is_file() and HERE not in p.parents] + \
                [p for p in (ROOT / "Data & Schemas").rglob("*") if p.is_file()]
    before = {str(p): sha(p) for p in protected}

    R = {r["combined_id"]: r for r in rd(MSI / "combined_in_scope_jobs.csv")}
    TN = {r["teammate_record_id"]: r for r in rd(MSI / "teammate_normalized_jobs.csv")}
    work = {}
    for f in sorted(a.batch_dir.glob("qr_batch_[0-9].jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                x = json.loads(line)
                work[x["combined_id"]] = x
    res, bad = {}, 0
    raw_rows = []
    for f in sorted(a.batch_dir.glob("qr_batch_[0-9]_results.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                x = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            raw_rows.append(x)
            res[x.get("combined_id")] = x
    with open(HERE / "ai_review_raw.jsonl", "w", encoding="utf-8") as f:
        for x in raw_rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    coverage = {"flagged": len(work), "reviewed": len(set(work) & set(res)), "missing": sorted(set(work) - set(res)),
                "unexpected": sorted(set(res) - set(work)), "unparseable_lines": bad, "duplicate_results": len(raw_rows) - len(res)}

    all_rows, ev_rows, sk_rows, concern_rows, loc_rows, human_rows = [], [], [], [], [], []
    for cid, w in sorted(work.items()):
        r = R[cid]
        x = res.get(cid, {})
        desc = r["description"]
        title = r["job_title"]
        flags = w["flags"]
        verdict = x.get("classification_verdict") if x.get("classification_verdict") in VERDICTS else "not_reviewed"
        rdec = x.get("recommended_decision") or ""
        rspec = x.get("recommended_specialization") or ""
        rspec = rspec if rspec in SPECS else ""
        conf = x.get("review_confidence") or ""
        pev = x.get("proposed_evidence") or ""
        pev_ok = verified(pev, title, desc)
        cur_spec = r["primary_specialization"]
        # ---- evidence fixes (missing evidence)
        if "missing_evidence" in flags:
            if not pev:
                st = "no_evidence_proposed"
            elif not pev_ok:
                st = "rejected_quote_not_found_in_description"
            elif verdict in ("supported", "supported_different_specialization"):
                st = "credible_evidence_verified"
            elif verdict == "weak_but_plausible":
                st = "weak_evidence_verified"
            elif verdict == "likely_false_positive":
                st = "evidence_contradicts_in_scope"
            else:
                st = "insufficient_information"
            ev_rows.append({"combined_id": cid, "source_record_id": r["source_record_id"], "job_title": title, "company": r["company"],
                            "current_final_decision": r["final_decision"], "current_specialization": cur_spec,
                            "existing_qwen_evidence": r["evidence"], "existing_qwen_reason": w["prior_reason"],
                            "proposed_evidence_NEW": pev, "proposed_evidence_verified_verbatim": pev_ok,
                            "review_verdict": verdict, "recommended_decision": rdec, "recommended_specialization": rspec,
                            "review_confidence": conf, "review_reason": x.get("review_reason", ""),
                            "quality_status": st, "recommendation_label": REC_LABEL})
        # ---- skill fixes
        if "missing_skills_none_detected" in flags or "missing_skills_unassigned" in flags:
            ps = x.get("proposed_skills") or []
            if not ps:
                sk_rows.append({"combined_id": cid, "job_title": title, "current_specialization": cur_spec,
                                "missing_skill_reason_group": "unassigned_not_extracted" if "missing_skills_unassigned" in flags else "extracted_none_detected",
                                "proposed_skill": "", "skill_in_existing_taxonomy": "", "proposed_level": "", "evidence": "",
                                "evidence_verified_verbatim": "", "existing_extractor_matches_evidence": "",
                                "would_count_if_accepted": "", "quality_status": "no_explicit_technical_skill_found",
                                "skills_note": x.get("skills_note", ""), "recommendation_label": REC_LABEL})
            for s in ps:
                name = (s.get("skill") or "").strip()
                ev = s.get("evidence") or ""
                ok = verified(ev, title, desc)
                in_tax = name in SKILLS
                lvl = s.get("level") or ""
                matched = sorted({m[2] for m in HCA.extract_skills(ev)}) if ev else []
                if not ok:
                    st = "rejected_quote_not_found_in_description"
                elif in_tax and SKILLS[name]["cat"] in NON_RANKING_CATEGORIES:
                    st = "verified_but_non_ranking_category"
                elif in_tax:
                    st = "verified_existing_skill_missed_by_extractor"
                else:
                    st = "verified_new_canonical_skill_proposed"
                sk_rows.append({"combined_id": cid, "job_title": title, "current_specialization": cur_spec,
                                "missing_skill_reason_group": "unassigned_not_extracted" if "missing_skills_unassigned" in flags else "extracted_none_detected",
                                "proposed_skill": name, "skill_in_existing_taxonomy": in_tax, "proposed_level": lvl, "evidence": ev,
                                "evidence_verified_verbatim": ok, "existing_extractor_matches_evidence": "|".join(matched),
                                "would_count_if_accepted": ok and lvl in ("required", "responsibility") and not (in_tax and SKILLS[name]["cat"] in NON_RANKING_CATEGORIES),
                                "quality_status": st, "skills_note": x.get("skills_note", ""), "recommendation_label": REC_LABEL})
        # ---- location
        lv = x.get("location_verdict") if x.get("location_verdict") in LOCV else ""
        if "location_unverified" in flags:
            lev = x.get("location_evidence") or ""
            lok = verified(lev, title, desc) if lev else None
            if lv in ("confirmed_saudi",) and (lok or (not lev and x.get("location_note"))):
                lst = "resolved_confirmed_saudi"
            elif lv == "likely_saudi":
                lst = "resolved_likely_saudi"
            elif lv == "outside_saudi":
                lst = "outside_saudi_human_decision"
            elif lv == "uncertain":
                lst = "genuinely_uncertain"
            elif lv == "confirmed_saudi" and lev and not lok:
                lst = "rejected_quote_not_found_in_description"
            else:
                lst = "not_assessed"
            ex = w["extra"]
            loc_rows.append({"combined_id": cid, "source_record_id": r["source_record_id"], "job_title": title, "company": r["company"],
                             "publisher": r["publisher"], "metadata_location": r["location"], "metadata_country": r["country"],
                             "location_raw": ex.get("location_raw", ""), "location_basis": ex.get("location_basis", ""),
                             "linkedin_location_derived": ex.get("linkedin_location_derived", ""),
                             "previous_llm_location_assessment": ex.get("job_location_assessment", ""),
                             "data_quality_flags": ex.get("data_quality_flags", ""),
                             "review_location_verdict": lv, "location_evidence": lev, "location_evidence_verified_verbatim": lok,
                             "location_note": x.get("location_note", ""), "quality_status": lst, "recommendation_label": REC_LABEL})
        # ---- specialization conflicts
        conflict = {}
        if "specialization_conflict" in flags:
            cps = w["counterpart_records"]
            cpd = [TN[c["record_id"]]["description"] for c in cps]
            cev = x.get("conflict_evidence") or ""
            cok = verified(cev, title, desc, *cpd, *[c["job_title"] for c in cps])
            rec = x.get("conflict_recommendation") or ""
            conflict = {"rec": rec, "ok": cok}
            concern_rows.append({"concern_type": "cross_source_specialization_conflict", "combined_id": cid, "job_title": title, "company": r["company"],
                                 "current_final_decision": r["final_decision"], "current_specialization": cur_spec,
                                 "current_basis": r["specialization_assigned_by"],
                                 "headcount_original": f"{r['source_record_id']}: {cur_spec} (Qwen) - {w['prior_reason']}",
                                 "teammate_original": " || ".join(f"{c['record_id']}: {c['specialization']} (Claude) - {c['reason']}" for c in cps),
                                 "review_verdict": verdict, "recommended_decision": rdec, "recommended_specialization": rec,
                                 "review_confidence": conf, "evidence": cev, "evidence_verified_verbatim": cok,
                                 "review_reason": x.get("conflict_reason", ""),
                                 "quality_status": ("clear_recommendation_verified" if rec in SPECS and cok else ("unresolved" if rec == "unresolved" else "recommendation_quote_not_verified")),
                                 "recommendation_label": REC_LABEL})
        # ---- other classification concerns (one row per record, not duplicated with conflict rows)
        concern = None
        if "specialization_conflict" not in flags:
            if verdict == "likely_false_positive":
                concern = "likely_false_positive"
            elif verdict == "insufficient_information":
                concern = "insufficient_information"
            elif verdict == "supported_different_specialization" or (rspec and cur_spec in SPECS and rspec != cur_spec and verdict != "likely_false_positive"):
                concern = "better_supported_specialization"
            elif cur_spec == "UNASSIGNED" and rspec:
                concern = "unassigned_specialization_recommendation"
            elif verdict == "weak_but_plausible":
                concern = "weak_but_plausible_classification"
        if concern:
            concern_rows.append({"concern_type": concern, "combined_id": cid, "job_title": title, "company": r["company"],
                                 "current_final_decision": r["final_decision"], "current_specialization": cur_spec,
                                 "current_basis": r["specialization_assigned_by"], "headcount_original": w["prior_reason"] if r["source_dataset"] == "headcount_labs" else "",
                                 "teammate_original": w["prior_reason"] if r["source_dataset"] != "headcount_labs" else "",
                                 "review_verdict": verdict, "recommended_decision": rdec, "recommended_specialization": rspec,
                                 "review_confidence": conf, "evidence": pev, "evidence_verified_verbatim": pev_ok,
                                 "review_reason": x.get("review_reason", ""),
                                 "quality_status": "verified_recommendation" if pev_ok else "recommendation_quote_not_verified",
                                 "recommendation_label": REC_LABEL})
        # ---- human decision required? (minimised: only items that would change a decision/specialization/inclusion)
        reasons = []
        if verdict == "likely_false_positive" or (rdec and rdec != "in_scope"):
            reasons.append(f"AI review recommends decision '{rdec or 'not in_scope'}' instead of in_scope ({verdict}, {conf} confidence)")
        if verdict == "insufficient_information":
            reasons.append("description insufficient to confirm in_scope")
        if concern == "better_supported_specialization" and rspec:
            reasons.append(f"specialization change recommended: {cur_spec} -> {rspec}")
        if concern == "unassigned_specialization_recommendation":
            reasons.append(f"unassigned job: recommended specialization {rspec}")
        if "specialization_conflict" in flags:
            if conflict.get("rec") in SPECS and conflict["rec"] != cur_spec:
                reasons.append(f"conflict: recommended {conflict['rec']} instead of kept {cur_spec}")
            elif conflict.get("rec") not in SPECS:
                reasons.append("cross-source specialization conflict unresolved")
        if lv == "outside_saudi":
            reasons.append("review says job is outside Saudi Arabia (would be excluded)")
        human_basis = r["decision_basis"] == "human_review"
        if human_basis and any(s.startswith("AI review recommends decision") for s in reasons):
            reasons.insert(0, "CONTRADICTS AN EXISTING HUMAN-REVIEW DECISION (in_scope was decided by the project owner; AI does not override it)")
        pr = "high" if any(s.startswith("AI review recommends decision") or "outside Saudi" in s for s in reasons) else ("medium" if reasons else "")
        if reasons:
            human_rows.append({"priority": pr, "combined_id": cid, "source_dataset": r["source_dataset"], "source_record_id": r["source_record_id"],
                               "job_title": title, "company": r["company"], "url": r["url"],
                               "current_final_decision": r["final_decision"], "current_specialization": cur_spec, "current_basis": r["specialization_assigned_by"],
                               "ai_recommended_decision": rdec, "ai_recommended_specialization": conflict.get("rec") if "specialization_conflict" in flags else rspec,
                               "ai_review_confidence": conf, "evidence": pev if pev else "", "evidence_verified_verbatim": pev_ok,
                               "decision_needed": "; ".join(reasons), "review_reason": x.get("review_reason", ""),
                               "contradicts_human_decision": "yes" if human_basis and rdec and rdec != "in_scope" else "no",
                               "suggested_bulk_action": ("inspect_individually" if human_basis else ("accept_if_agree" if conf == "high" and pev_ok else "inspect_individually")),
                               "human_decision": "", "human_notes": ""})
        all_rows.append({"combined_id": cid, "source_dataset": r["source_dataset"], "source_record_id": r["source_record_id"],
                         "job_title": title, "company": r["company"], "flags": "|".join(flags),
                         "current_final_decision": r["final_decision"], "current_specialization": cur_spec,
                         "current_specialization_basis": r["specialization_assigned_by"], "current_decision_basis": r["decision_basis"],
                         "existing_evidence": r["evidence"],
                         "ai_review_verdict": verdict, "ai_recommended_decision": rdec, "ai_recommended_specialization": rspec,
                         "ai_review_confidence": conf, "ai_proposed_evidence": pev, "ai_evidence_verified_verbatim": pev_ok,
                         "ai_review_reason": x.get("review_reason", ""),
                         "ai_proposed_skills": "|".join(s.get("skill", "") for s in (x.get("proposed_skills") or [])),
                         "ai_location_verdict": lv, "ai_conflict_recommendation": conflict.get("rec", ""),
                         "human_decision_required": "yes" if reasons else "no", "human_priority": pr,
                         "status": "reviewed" if x else "NOT_REVIEWED", "recommendation_label": REC_LABEL})

    human_rows.sort(key=lambda h: ({"high": 0, "medium": 1}.get(h["priority"], 2), h["combined_id"]))
    files = {
        "quality_review_all_flagged.csv": wr("quality_review_all_flagged.csv", all_rows),
        "proposed_evidence_fixes.csv": wr("proposed_evidence_fixes.csv", ev_rows),
        "proposed_skill_fixes.csv": wr("proposed_skill_fixes.csv", sk_rows),
        "classification_concerns.csv": wr("classification_concerns.csv", concern_rows),
        "location_verification.csv": wr("location_verification.csv", loc_rows),
        "human_decisions_required.csv": wr("human_decisions_required.csv", human_rows),
    }

    C = collections.Counter
    ev_st = C(e["quality_status"] for e in ev_rows)
    sk_jobs = collections.defaultdict(list)
    for s in sk_rows:
        sk_jobs[s["combined_id"]].append(s)
    sk_improvable = {k for k, v in sk_jobs.items() if any(s["would_count_if_accepted"] is True for s in v)}
    sk_group = {g: len({s["combined_id"] for s in sk_rows if s["missing_skill_reason_group"] == g}) for g in ("extracted_none_detected", "unassigned_not_extracted")}
    sk_improvable_by_group = {g: len({k for k in sk_improvable if sk_jobs[k][0]["missing_skill_reason_group"] == g}) for g in sk_group}
    new_skills = C(s["proposed_skill"] for s in sk_rows if s["quality_status"] == "verified_new_canonical_skill_proposed")
    missed_existing = C(s["proposed_skill"] for s in sk_rows if s["quality_status"] == "verified_existing_skill_missed_by_extractor")
    loc_st = C(l["quality_status"] for l in loc_rows)
    fp = [c for c in concern_rows if c["concern_type"] == "likely_false_positive"]
    fp_missing_ev = [e for e in ev_rows if e["review_verdict"] == "likely_false_positive"]
    impact = C(c["current_specialization"] for c in fp)
    all_quotes = [(e["proposed_evidence_NEW"], e["proposed_evidence_verified_verbatim"]) for e in ev_rows if e["proposed_evidence_NEW"]] + \
                 [(s["evidence"], s["evidence_verified_verbatim"]) for s in sk_rows if s["evidence"]] + \
                 [(l["location_evidence"], l["location_evidence_verified_verbatim"]) for l in loc_rows if l["location_evidence"]] + \
                 [(c["evidence"], c["evidence_verified_verbatim"]) for c in concern_rows if c["evidence"]]
    after = {p: sha(Path(p)) for p in before}
    changed = [p for p in before if before[p] != after[p]]
    checks = {
        "every_flagged_record_reviewed": not coverage["missing"],
        "no_unexpected_or_duplicate_results": not coverage["unexpected"] and coverage["duplicate_results"] == 0 and bad == 0,
        "missing_evidence_rows_158": len(ev_rows) == 158,
        "location_rows_53": len(loc_rows) == 53,
        "conflict_rows_4": sum(1 for c in concern_rows if c["concern_type"] == "cross_source_specialization_conflict") == 4,
        "missing_skill_jobs_70": len(sk_jobs) == 70,
        "flagged_unique_288": len(all_rows) == 288,
        "no_record_duplicated_in_all_flagged": len({r["combined_id"] for r in all_rows}) == len(all_rows),
        "no_record_duplicated_in_human_decisions": len({h["combined_id"] for h in human_rows}) == len(human_rows),
        "all_quotes_checked_against_full_original_text": True if all_quotes else False,
        "existing_outputs_unchanged_sha256": not changed,
        "no_pycache_in_headcount_folder": not (HC / "__pycache__").exists(),
    }
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": str(MSI / "combined_in_scope_jobs.csv"), "in_scope_rows": len(R),
        "method": "Claude Code subagents (4 batches) reviewed each flagged record's full description against the Qwen V3 classifier standard; every quote verified in code against the full original description",
        "coverage": coverage,
        "flag_counts": dict(C(f for w in work.values() for f in w["flags"])),
        "review_verdicts_all_flagged": dict(C(r["ai_review_verdict"] for r in all_rows)),
        "missing_evidence_158": {"quality_status": dict(ev_st), "verdicts": dict(C(e["review_verdict"] for e in ev_rows)),
                                 "credible_verified_evidence": ev_st.get("credible_evidence_verified", 0),
                                 "weak_but_verified": ev_st.get("weak_evidence_verified", 0),
                                 "likely_false_positives": len(fp_missing_ev),
                                 "by_current_specialization_false_positive": dict(C(e["current_specialization"] for e in fp_missing_ev))},
        "missing_skills_70": {"jobs_by_group": sk_group, "jobs_improvable_with_verified_countable_skill": len(sk_improvable),
                              "improvable_by_group": sk_improvable_by_group,
                              "skill_rows_by_status": dict(C(s["quality_status"] for s in sk_rows)),
                              "existing_taxonomy_skills_missed": dict(missed_existing.most_common()),
                              "new_canonical_skills_proposed": dict(new_skills.most_common())},
        "location_53": {"by_status": dict(loc_st), "resolved": loc_st.get("resolved_confirmed_saudi", 0) + loc_st.get("resolved_likely_saudi", 0)},
        "specialization_conflicts_4": [{"combined_id": c["combined_id"], "job_title": c["job_title"], "current": c["current_specialization"],
                                        "recommended": c["recommended_specialization"], "status": c["quality_status"]}
                                       for c in concern_rows if c["concern_type"] == "cross_source_specialization_conflict"],
        "classification_concerns": dict(C(c["concern_type"] for c in concern_rows)),
        "likely_false_positives_total": len(fp), "likely_false_positives_by_current_specialization": dict(impact),
        "in_scope_if_all_false_positives_removed (hypothetical, NOT applied)": len(R) - len(fp),
        "human_decisions_required": {"total": len(human_rows), "by_priority": dict(C(h["priority"] for h in human_rows)),
                                     "contradicting_existing_human_decisions": sum(1 for h in human_rows if h["contradicts_human_decision"] == "yes"),
                                     "high_confidence_verified_bulk_acceptable": sum(1 for h in human_rows if h["suggested_bulk_action"] == "accept_if_agree"),
                                     "inspect_individually": sum(1 for h in human_rows if h["suggested_bulk_action"] == "inspect_individually")},
        "quotes_checked": len(all_quotes), "quotes_verified": sum(1 for _, ok in all_quotes if ok is True),
        "validation": checks, "all_checks_passed": all(checks.values()), "changed_files": changed,
        "notes": ["No accuracy estimate is reported: no validated evaluation sample exists.",
                  "All recommendations are AI (Claude) recommendations and were NOT applied to combined_in_scope_jobs.csv or any other existing output."],
        "output_files": files,
    }
    (HERE / "quality_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("output_files",)}, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
