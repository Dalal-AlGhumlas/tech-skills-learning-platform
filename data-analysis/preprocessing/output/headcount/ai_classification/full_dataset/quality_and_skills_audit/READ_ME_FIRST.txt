
HEADCOUNT LABS - POST-CLASSIFICATION REVIEW

Original Qwen CSV and cache are not modified.

01_needs_review_all.csv
Review all uncertain jobs manually.

02_out_of_scope_random_review.csv
Random audit sample for checking false exclusions.

03_out_of_scope_high_risk_review.csv
Prioritized technical-looking excluded jobs.
This is not a representative random sample.

For each reviewed job:
- audit_human_decision: in_scope/out_of_scope/needs_review
- audit_human_specialization: one of the nine categories if in_scope
- audit_human_notes: evidence-based explanation
- audit_review_status: reviewed

04_specialization_distribution.csv
Current Qwen-only specialty counts.

05_top10_skills_PROVISIONAL.csv
Candidate Top 10 skills per specialty.

06_all_detected_skills_PROVISIONAL.csv
All keyword-matched skills.

07_skill_evidence.csv
Evidence snippets from original job descriptions.

08_in_scope_no_detected_skills.csv
Jobs requiring deeper skill extraction.

09_audit_summary.json
Counts, checks, and limitations.

Do not treat provisional skill counts as final results.
