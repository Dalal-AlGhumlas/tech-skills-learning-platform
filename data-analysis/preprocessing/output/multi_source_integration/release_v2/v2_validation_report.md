# V2 release: validation report

**Release:** v2
**Approval:** Project-owner V2 release approval, 2026-11-19
**Input:** V1 `combined_in_scope_jobs.csv` (1,201 jobs), unchanged (SHA-256 verified).

## Result

| | Jobs |
|---|---:|
| V1 in_scope | 1201 |
| Excluded under POL-001 | 16 (14 reviewed + 2 consistency) |
| Excluded as verified false positives | 21 |
| Pending review, not counted in V2 statistics | 27 |
| **V2 approved in_scope** | **1137** |

### Pending decisions by type

| Pending type | Jobs |
|---|---:|
| decision_pending_review | 24 |
| needs_review_under_POL-001 | 3 |

**Specializations corrected:** 10 (7 approved corrections + 3 conflict resolutions).

**Still pending:** 14 specialization corrections. These jobs are counted in V2 under their V1 specialization.

## Checks

| Check | Result |
|---|---|
| v1_input_rows_1201 | PASS |
| every_v1_job_has_exactly_one_v2_status | PASS |
| identity_v2 = v1 - excluded - pending_decisions | PASS |
| no_duplicate_combined_id_in_v2 | PASS |
| no_source_record_in_two_v2_rows | PASS |
| no_combined_id_changed_twice_same_field | PASS |
| no_job_both_in_v2_and_pending_decision | PASS |
| excluded_jobs_not_in_v2 | PASS |
| all_applied_changes_have_verified_evidence | PASS |
| every_v2_job_has_one_of_nine_specializations | PASS |
| specialization_counts_sum_to_v2_total | PASS |
| pol001_exclusions_16 | PASS |
| four_conflicts_handled_once | PASS |
| pct_uses_v2_specialization_denominator | PASS |
| top10_sorted_desc | PASS |
| top10_max_10_per_specialization | PASS |
| skill_source_ids_all_in_v2 | PASS |
| skill_counted_once_per_job | PASS |
| supplement_quotes_verified | PASS |
| descriptions_identical_to_v1 | PASS |
| no_rejected_changes | PASS |
| v1_and_upstream_files_unchanged_sha256 | PASS |
| no_pycache_in_headcount_folder | PASS |

## Specialization distribution (V2)

| Specialization | V2 | % | V1 | Change |
|---|---:|---:|---:|---:|
| ai | 158 | 13.9 | 171 | -13 |
| data_analytics | 128 | 11.26 | 134 | -6 |
| software_development | 202 | 17.77 | 212 | -10 |
| cloud_devops | 155 | 13.63 | 169 | -14 |
| cybersecurity | 157 | 13.81 | 159 | -2 |
| infrastructure_networking | 86 | 7.56 | 81 | +5 |
| qa_testing | 77 | 6.77 | 91 | -14 |
| database_enterprise_systems | 129 | 11.35 | 131 | -2 |
| uiux_technical_products | 45 | 3.96 | 46 | -1 |
| TOTAL | 1137 | 100.0 | 1201 | -64 |

## Top 10 skills (V2, recomputed)

Recomputed with the unchanged evidence-based extractor on V2 approved jobs only.
The percentage denominator is each specialization's V2 job count.

67 verified skill supplements from the quality review were added. These are existing taxonomy skills that the extractor missed, and every one has a verbatim quote.

New canonical skills were **not** added; that taxonomy change is pending.

- **ai** (158): 1. Machine Learning 94 (59.49%) · 2. Large Language Models (LLMs) 88 (55.7%) · 3. Python 85 (53.8%) · 4. APIs & Integration 62 (39.24%) · 4. AI Agents / Agentic AI 62 (39.24%) · 6. Model Deployment & Evaluation 60 (37.97%) · 7. Generative AI 56 (35.44%) · 8. Retrieval-Augmented Generation (RAG) 49 (31.01%) · 9. CI/CD 38 (24.05%) · 9. Cloud Computing (general) 38 (24.05%)
- **data_analytics** (128): 1. SQL 72 (56.25%) · 2. Data Quality 61 (47.66%) · 3. Data Modeling 59 (46.09%) · 4. Data Visualization & Dashboards 55 (42.97%) · 5. ETL/ELT 53 (41.41%) · 6. Data Warehousing 51 (39.84%) · 7. Data Governance 46 (35.94%) · 8. Data Pipelines 45 (35.16%) · 9. Power BI 40 (31.25%) · 9. Python 40 (31.25%)
- **software_development** (202): 1. APIs & Integration 107 (52.97%) · 2. REST APIs 78 (38.61%) · 3. CI/CD 62 (30.69%) · 4. JavaScript 54 (26.73%) · 5. Git 50 (24.75%) · 6. Java 41 (20.3%) · 7. Cloud Computing (general) 40 (19.8%) · 8. System Design / Software Architecture 39 (19.31%) · 9. React 37 (18.32%) · 10. SQL 33 (16.34%)
- **cloud_devops** (155): 1. Kubernetes 74 (47.74%) · 1. Cloud Computing (general) 74 (47.74%) · 3. CI/CD 72 (46.45%) · 4. DevOps Practices 64 (41.29%) · 5. Terraform 54 (34.84%) · 6. Linux 49 (31.61%) · 6. AWS 49 (31.61%) · 8. Google Cloud Platform 48 (30.97%) · 8. Infrastructure as Code 48 (30.97%) · 10. Microsoft Azure 45 (29.03%)
- **cybersecurity** (157): 1. Incident Response 64 (40.76%) · 2. Security Risk Assessment & GRC 62 (39.49%) · 3. Firewalls 57 (36.31%) · 4. Vulnerability Management 53 (33.76%) · 5. Security Operations (SOC) 52 (33.12%) · 6. SIEM 47 (29.94%) · 7. Identity and Access Management (IAM) 40 (25.48%) · 8. NCA ECC / Saudi Cybersecurity Controls 36 (22.93%) · 9. EDR/XDR 33 (21.02%) · 9. Encryption & PKI 33 (21.02%)
- **infrastructure_networking** (86): 1. Firewalls 37 (43.02%) · 2. Routing & Switching 34 (39.53%) · 3. Linux 27 (31.4%) · 4. Cisco 25 (29.07%) · 4. Data Center Infrastructure 25 (29.07%) · 6. LAN/WAN 23 (26.74%) · 7. VPN 21 (24.42%) · 7. Cloud Computing (general) 21 (24.42%) · 7. Windows Server 21 (24.42%) · 10. Server Administration 20 (23.26%)
- **qa_testing** (77): 1. Test Planning & Test Case Design 43 (55.84%) · 2. Test Automation 41 (53.25%) · 3. APIs & Integration 27 (35.06%) · 4. CI/CD 24 (31.17%) · 5. API Testing 21 (27.27%) · 6. SQL 20 (25.97%) · 7. Postman 15 (19.48%) · 7. Integration Testing 15 (19.48%) · 9. Selenium 14 (18.18%) · 9. SDLC 14 (18.18%)
- **database_enterprise_systems** (129): 1. SAP 59 (45.74%) · 2. SAP S/4HANA 46 (35.66%) · 3. APIs & Integration 30 (23.26%) · 4. Database Administration 29 (22.48%) · 5. User Acceptance Testing (UAT) 28 (21.71%) · 6. SQL 27 (20.93%) · 7. Oracle Database 26 (20.16%) · 8. Backup & Disaster Recovery 25 (19.38%) · 9. Microsoft SQL Server 22 (17.05%) · 10. ERP Systems (general) 19 (14.73%)
- **uiux_technical_products** (45): 1. Prototyping 29 (64.44%) · 2. Figma 26 (57.78%) · 3. Design Systems 25 (55.56%) · 3. Wireframing 25 (55.56%) · 5. User Research 24 (53.33%) · 6. UI Design 23 (51.11%) · 7. Usability Testing 21 (46.67%) · 8. User Flows & Journey Mapping 18 (40.0%) · 9. Accessibility (WCAG) 14 (31.11%) · 9. UX Design 14 (31.11%)

## Missing values in V2

| Column | Empty |
|---|---:|
| job_title | 0 |
| company | 0 |
| location | 56 |
| country | 0 |
| posted_date | 365 |
| url | 0 |
| description | 0 |
| evidence | 138 |
| required_technical_skills_v2 | 17 |

The `evidence` column holds Qwen's original evidence and was left unchanged.
Verified quotes from the quality review are in the separate `quality_review_evidence` column ({'credible_evidence_verified': 128, 'weak_evidence_verified': 10}).

Jobs with no evidence in either column: **0**.

## Notes and limitations

- **No accuracy estimate.** There is no validated evaluation sample. Decisions and specializations are human-, Qwen- or Claude-based; the basis is recorded per job.
- **Pending jobs** are listed in `pending_review_jobs.csv`. Their V1 decisions are untouched; they are only excluded from the approved V2 statistics.
- **Unreviewed records.** About 913 unflagged in-scope jobs and all out-of-scope jobs were not re-reviewed.
- **Missing JSearch dates.** JSearch posting dates are unavailable.
- **Scope of the data.** The teammate data comes from targeted queries, and the results describe these datasets, not the whole Saudi labour market.

**Overall: ALL CHECKS PASSED**
