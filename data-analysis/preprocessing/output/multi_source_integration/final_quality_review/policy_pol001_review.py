#!/usr/bin/env python3
"""Policy POL-001 review of the 16 previously human-reviewed in-scope jobs challenged by the quality review.

POL-001 (approved by the project owner, 2026-11-19):
  Technical management, product, program, project and delivery roles WITHOUT substantial hands-on technical
  responsibilities within the nine specializations are OUT OF SCOPE. Technical consultants are judged by their
  actual responsibilities. Insufficient evidence -> needs_review. Same standard for all sources.

Writes ONLY: policy_pol001_review_16_jobs.csv, change_log_v2_POL-001.csv, policy_POL-001_decision_report.md
(in this folder). Reads existing outputs read-only. Nothing existing is modified.
"""
import collections, csv, hashlib, json, re, sys
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
MSI = HERE.parent
HC = MSI.parent / "headcount/ai_classification/full_dataset/postclassification_reviewed"
csv.field_size_limit(2**31 - 1)
POLICY_ID, POLICY_DATE, LOG_VERSION = "POL-001", "2026-11-19", "v2"
POLICY_TEXT = ("Technical management, product, program, project, and delivery roles without substantial hands-on technical "
               "responsibilities within the nine specializations are OUT OF SCOPE. Technical consultants are evaluated by their "
               "actual responsibilities; insufficient evidence -> needs_review; same standard across Headcount Labs, JSearch and LinkedIn.")

# combined_id -> (recommended decision, role category, confidence, reason, verbatim evidence)
DECISIONS = {
    "CMB-00009": ("out_of_scope", "project_management", "high",
                  "Senior project manager: scope, schedule, budget, contracts, RAID/escalation and coordination of AI teams; the AI lifecycle is coordinated, not performed.",
                  "managing project scope, schedules, budgets, quality, risks, and formal acceptance"),
    "CMB-00141": ("out_of_scope", "product_management", "high",
                  "Product leader who scopes and leads cross-functional AI projects; coding appears only as a nice-to-have, so no substantial hands-on technical responsibility.",
                  "Scope out new AI application use cases across various government entities"),
    "CMB-00335": ("out_of_scope", "consulting_strategy", "medium",
                  "Digital-transformation consultant: workshops, transformation strategy and advisory; technology knowledge is general, no hands-on engineering or analytics delivery in one of the nine areas.",
                  "Lead digital transformation strategies to improve clients business processes, enhance their customer experience, and drive innovation."),
    "CMB-00366": ("out_of_scope", "consulting_internship", "medium",
                  "IT-consulting internship centred on analysis support, meeting and presentation preparation; technologies are named as buzzwords only.",
                  "You'll be responsible for the preparation and follow-up of meetings and presentations and all project related analysis and data"),
    "CMB-00636": ("out_of_scope", "delivery_management", "high",
                  "Deployment strategist coordinating scope, plans and stakeholders; only 'comfort' with technical concepts required and hands-on engineering is a nice-to-have.",
                  "Coordinate deployments across Product, Engineering, and customer stakeholders."),
    "CMB-01391": ("needs_review", "graduate_programme_unspecified", "low",
                  "Graduate intake whose department (software, AI, cloud, security or business operations) is assigned after hiring; the posting does not establish whether the job is hands-on technical.",
                  "Support software development, implementation, consulting, or business operations based on assigned responsibilities."),
    "CMB-01431": ("out_of_scope", "project_management", "high",
                  "Technical project manager for a BI/DWH migration: plans, tracks and coordinates workstreams; requires understanding of data concepts but no hands-on data work.",
                  "Maintain RAID logs, status reports, steering committee updates, and delivery governance."),
    "CMB-02567": ("out_of_scope", "project_management", "high",
                  "PMO project manager leading business projects and PM frameworks; technical content is oversight in a single line.",
                  "Develop and refine project management frameworks, employing best practices tailored to the payments industry."),
    "CMB-03913": ("out_of_scope", "business_analysis_coordination", "medium",
                  "Business/solutions analyst bridging business and technology: requirements, BRDs, process maps and coordination; implementation and testing are only 'supported'. Consistent with how requirements-documentation BA roles were classified in the teammate data.",
                  "Prepare BRDs, functional specifications, process maps, and use cases."),
    "CMB-04361": ("needs_review", "graduate_job_family_unspecified", "low",
                  "Generic IT graduate job family (software, network, security majors) with a one-line duty statement; it is technical implementation in principle, but the evidence is too thin to confirm substantial hands-on work or a specialization.",
                  "Assists in developing and implementing business applications, systems and procedures"),
    "CMB-04762": ("out_of_scope", "product_management", "high",
                  "Head of Product owning direction, roadmap, specifications and adoption; prototyping is AI-assisted product work, not hands-on UI/UX design or engineering.",
                  "own product direction, roadmap, feature definition, acceptance, and customer enablement"),
    "CMB-04789": ("out_of_scope", "delivery_management", "high",
                  "Customer-facing AI delivery lead: requirements, sprints, timelines and stakeholder management; understanding of AI is required but no hands-on engineering.",
                  "Oversee sprints and project timelines, ensuring timely and high-quality solution delivery."),
    "CMB-05045": ("out_of_scope", "product_management", "high",
                  "Senior product manager owning catalog strategy, roadmap and a team of PMs; product strategy rather than hands-on technical work.",
                  "Own the catalog strategy end to end: sequence it into quarters, defend it in the room, and hold it accountable to the numbers it promised."),
    "CMB-05241": ("out_of_scope", "business_programme", "high",
                  "COOP programme in Consulting, Business Development, Finance and Marketing; no technical department or hands-on technical duties.",
                  "Opportunities available in the following 4 departments: Consulting, Business Development, Finance & Marketing."),
    "CMB-05629": ("out_of_scope", "operational_excellence_trainee", "medium",
                  "Continuous-improvement (Lean Six Sigma, Kaizen) trainee; dashboards and data collection are a minor supporting part, not substantial data-analytics work.",
                  "Support Lean Six Sigma, Kaizen, and operational excellence projects."),
    "CMB-07633": ("out_of_scope", "program_management", "high",
                  "Program manager for AI data-centre programmes: governance, portfolios, RAID logs, change control and executive reporting; data-centre knowledge is required but the responsibilities are management.",
                  "Develop and manage RAID logs, change control processes, escalation management and executive reporting."),
}


# Consistency candidates: other in-scope jobs with management/product/delivery titles found by a title scan.
# NOT part of the 16; recorded separately, pending the owner's confirmation; NOT entered in the change log.
CANDIDATES = {
    "CMB-02978": ("out_of_scope", "delivery_management", "medium",
                  "Delivery manager: planning, estimation, sprint/release management and vendor oversight; architecture review is governance, and technologies are required only as 'working knowledge'.",
                  "Drive technical planning, estimation, prioritization, sprint execution, and release management."),
    "CMB-03847": ("in_scope", "solution_architecture_integration", "medium",
                  "Leads forward-deployed engineers and personally designs and architects customer integrations of voice-AI models (technical integration / solution architecture).",
                  "Design and architect bespoke integrations for customers"),
    "CMB-06766": ("needs_review", "program_management_with_automation", "low",
                  "Technical program manager whose core is intake, triage and release coordination, but who also automates workflows via APIs and builds reporting; balance is unclear.",
                  "Automate operational workflows by integrating systems through APIs"),
    "CMB-07498": ("in_scope", "technical_delivery_lead", "medium",
                  "Delivery lead who also provides hands-on technical direction and troubleshooting for SIEM log ingestion, parsing and normalization.",
                  "Provide technical direction and troubleshooting support for complex log ingestion, parsing, mapping and data-quality issues."),
    "CMB-07505": ("in_scope", "technical_delivery_lead", "high",
                  "AI delivery manager explicitly contributing hands-on to model development, pipelines and API design, and designing AI architectures.",
                  "Contribute hands-on to model development, pipeline engineering, API design, and platform integration."),
    "CMB-07821": ("out_of_scope", "product_management", "medium",
                  "Product manager for reporting products: roadmap, requirements and prioritization; data models are co-developed with data engineers rather than built by the role.",
                  "Defining and executing the roadmap for customer-facing analytics, reporting portals, and internal reporting infrastructure."),
}


def rd(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def nq(s):
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[*#_`\\]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    protected = [p for p in MSI.parent.rglob("*") if p.is_file() and not (p.parent == HERE and p.name.startswith(("policy_", "change_log_v2", "_policy_")))]
    before = {str(p): sha(p) for p in protected}
    R = {r["combined_id"]: r for r in rd(MSI / "combined_in_scope_jobs.csv")}
    HCA = {r["record_key"]: r for r in rd(HC / "reviewed_classifications_all.csv")}
    HD = {h["combined_id"]: h for h in rd(HERE / "human_decisions_required.csv")}
    HUMAN = {r["record_key"]: r for r in rd(MSI.parents[3] / "headcount_human_review_decisions_53.csv")}
    target = sorted(c for c, h in HD.items() if h["contradicts_human_decision"] == "yes")
    assert sorted(DECISIONS) == target, (sorted(DECISIONS), target)

    rows, log = [], []
    for cid in target:
        r = R[cid]
        dec, cat, conf, why, ev = DECISIONS[cid]
        ok = nq(ev) in nq(r["job_title"] + " \n " + r["description"])
        hk = r["source_record_id"]
        h = HCA[hk]
        orig = HUMAN[hk]
        members = r["member_source_record_ids"].split("|")
        # include Headcount-internal duplicates of the representative (e.g. Dell #42 duplicate of #48)
        members += ["H:" + k for k, v in HCA.items() if v["primary_record_key"] == hk and k != hk and "H:" + k not in members]
        rows.append({"combined_id": cid, "source_record_id": hk, "all_member_record_ids": "|".join(members),
                     "human_review_number": orig["review_number"], "job_title": r["job_title"], "company": r["company"],
                     "original_qwen_decision": h["qwen_decision"], "original_human_decision": orig["user_final_decision"],
                     "original_human_review_notes": orig.get("review_notes", ""),
                     "current_final_decision": r["final_decision"], "current_specialization": r["primary_specialization"],
                     "current_specialization_basis": r["specialization_assigned_by"],
                     "ai_quality_review_recommendation": HD[cid]["ai_recommended_decision"],
                     "pol001_role_category": cat, "pol001_recommended_decision": dec,
                     "pol001_recommended_specialization": "",
                     "pol001_confidence": conf, "pol001_reason": why, "pol001_evidence": ev, "evidence_verified_verbatim": ok,
                     "change_basis": f"Approved project policy {POLICY_ID} ({POLICY_DATE}); NOT an AI override of the human decision",
                     "status": ("policy_decision_recorded_pending_application" if dec == "out_of_scope" else "needs_review_human_input_required")})
        for m in members:
            log.append({"log_version": LOG_VERSION, "log_date": POLICY_DATE, "policy_id": POLICY_ID, "combined_id": cid,
                        "record_id": m, "is_representative": "yes" if m == "H:" + hk else "no (duplicate of representative; follows it)",
                        "field": "final_decision", "previous_value": r["final_decision"],
                        "previous_value_basis": (f"human_review #{HUMAN[m[2:]]['review_number']} (user_final_decision={HUMAN[m[2:]]['user_final_decision']})"
                                                 if m.startswith("H:") and m[2:] in HUMAN else
                                                 f"teammate Claude LLM record, merged with human_review #{orig['review_number']} representative"),
                        "new_value": dec, "previous_specialization": r["primary_specialization"], "new_specialization": "",
                        "change_basis": f"Approved project policy {POLICY_ID}: {POLICY_TEXT}",
                        "evidence": ev, "evidence_verified_verbatim": ok, "applied_to_outputs": "no (recorded; existing outputs unchanged)",
                        "original_preserved_in": "headcount_human_review_decisions_53.csv; reviewed_classifications_all.csv; combined_in_scope_jobs.csv"})
    with open(HERE / "policy_pol001_review_16_jobs.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with open(HERE / "change_log_v2_POL-001.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(log[0].keys())); w.writeheader(); w.writerows(log)

    # ---- impact if ONLY POL-001 is applied
    cnt = collections.Counter(x["pol001_recommended_decision"] for x in rows)
    spec_before = collections.Counter(r["primary_specialization"] for r in R.values())
    affected = {x["combined_id"]: x for x in rows}
    spec_after = collections.Counter(r["primary_specialization"] for c, r in R.items() if c not in affected)
    remaining_in = len(R) - len(affected)
    # consistency scan (informational only): other in-scope jobs with management/product/delivery titles
    MGMT = re.compile(r"\b(project manager|program(?:me)? manager|product manager|product owner|delivery manager|delivery lead|pmo|head of product|scrum master|deployment strategist|deployment lead|program management|project management)\b", re.I)
    pending = {h["combined_id"] for h in HD.values()}
    scan = [r for c, r in R.items() if c not in affected and MGMT.search(r["job_title"])]
    scan_pending = [r for r in scan if r["combined_id"] in pending]
    assert sorted(CANDIDATES) == sorted(r["combined_id"] for r in scan), sorted(r["combined_id"] for r in scan)
    crow = []
    for cid, (dec, cat, conf, why, ev) in sorted(CANDIDATES.items()):
        r = R[cid]
        hk = r["source_record_id"]
        hb = HUMAN.get(hk)
        crow.append({"combined_id": cid, "source_record_id": hk, "job_title": r["job_title"], "company": r["company"],
                     "current_final_decision": r["final_decision"], "current_specialization": r["primary_specialization"],
                     "current_decision_basis": r["decision_basis"], "human_review_number": hb["review_number"] if hb else "",
                     "pol001_role_category": cat, "pol001_recommended_decision": dec, "pol001_confidence": conf,
                     "pol001_reason": why, "pol001_evidence": ev,
                     "evidence_verified_verbatim": nq(ev) in nq(r["job_title"] + " \n " + r["description"]),
                     "status": "consistency_candidate_pending_owner_confirmation (not in the 16; not in change log; not applied)"})
    with open(HERE / "policy_pol001_consistency_candidates.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(crow[0].keys())); w.writeheader(); w.writerows(crow)
    ccount = collections.Counter(c["pol001_recommended_decision"] for c in crow)
    after = {p: sha(p) for p in before}
    checks = {"consistency_candidate_evidence_verified": all(c["evidence_verified_verbatim"] for c in crow),"exactly_16_target_jobs": len(rows) == 16, "all_evidence_verified_verbatim": all(x["evidence_verified_verbatim"] for x in rows),
              "change_log_covers_all_member_records": len(log) == sum(len(x["all_member_record_ids"].split("|")) for x in rows),
              "all_original_human_decisions_were_in_scope": all(x["original_human_decision"] == "in_scope" for x in rows),
              "existing_files_unchanged_sha256": before == after}
    summary = {"policy": POLICY_ID, "counts": dict(cnt), "remaining_in_scope_of_16": cnt.get("in_scope", 0),
               "in_scope_before": len(R), "in_scope_if_only_POL001_applied": remaining_in,
               "of_which_assigned": sum(v for k, v in spec_after.items() if k != "UNASSIGNED"), "unassigned_after": spec_after.get("UNASSIGNED", 0),
               "needs_review_added": cnt.get("needs_review", 0),
               "specialization_change": {s: f"{spec_before.get(s, 0)} -> {spec_after.get(s, 0)}" for s in sorted(set(spec_before)) if spec_before.get(s, 0) != spec_after.get(s, 0)},
               "consistency_scan_other_management_titled_in_scope_jobs": len(scan),
               "of_which_already_in_pending_quality_review_decisions": len(scan_pending),
               "consistency_scan_titles": sorted(f"{r['combined_id']} {r['job_title'][:70]} ({r['source_dataset']})" for r in scan),
               "consistency_candidates": dict(ccount),
               "in_scope_if_POL001_and_consistency_candidates_applied": remaining_in - ccount.get("out_of_scope", 0) - ccount.get("needs_review", 0),
               "checks": checks}
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    (HERE / "_policy_pol001_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
