# Anesthesia Risk Score 2.0 — Backend

## Project Overview
Backend API for an outpatient oral & maxillofacial surgery anesthesia risk 
assessment dashboard. This backend serves a frontend (React, built separately 
in Ember) that already exists with mock data — this backend must produce API 
responses matching the shapes that frontend already expects.

## Tech Stack (locked in, do not change without asking)
- Python, FastAPI (async)
- MongoDB Atlas (mandated by team)
- Beanie (async ODM, built on PyMongo's native async driver — `pymongo.AsyncMongoClient` —
  + Pydantic). Motor is deprecated (EOL May 2026) and no longer used.
- Deployment target: Render
- pytest + httpx for testing
- black + ruff for formatting/linting

## Data Modeling Approach
- Patient is the primary document — embed intake_record, exam_finding, 
  risk_assessment, recommendation_set, and alerts as sub-documents/arrays 
  within it (these are always read together on the Patient Detail view)
- User and AuditLogEntry are separate top-level collections (queried 
  independently across patients, not tied to a single patient view)
- Audit log writes must happen inside the same MongoDB transaction as the 
  patient document update they're logging, using PyMongo's async 
  session/transaction support (MongoDB Atlas replica sets support 
  multi-document ACID transactions) — never write the audit entry as a 
  separate, unguaranteed step

## Roles (exactly 3)
1. Surgeon — views risk profile, decides on testing, views/writes notes. 
   View-only on intake data and exam findings.
2. Nurse/Assistant — verifies intake, adds exam findings, views/acknowledges 
   alerts, generates lab orders, writes notes
3. Office Staff — uploads intake, views basic patient list + risk category 
   only (no clinical detail access, no alert visibility), exports PDFs

## Core Entities (as embedded documents within Patient, unless noted)

**User** (separate top-level collection):
id, email, full_name, role (enum: surgeon/nurse/office_staff), google_sub_id, 
created_at

**Patient** (top-level document):
id, full_name, dob, sex, surgery_date, created_at, created_by (User ref)

**intake_record** (embedded in Patient):
raw_truform_payload (dict/JSON), medical_history (dict), medications (dict), 
allergies (dict), surgical_history (dict), is_pregnant (bool), 
verification_status (enum: pending/verified), submitted_at, source (enum: 
truform/manual)

**exam_finding** (embedded in Patient):
mallampati_class (int 1-4, nullable), airway_notes (str, nullable), 
entered_by (User ref), created_at

**risk_assessment** (embedded in Patient):
asa_class (str, e.g. "III"), asa_suggested (bool), stop_bang_score (int), 
stop_bang_level (enum: low/moderate/high), rcri_score (int), rcri_level 
(enum: low/moderate/high), mets_capacity (enum: below_4/at_or_above_4/
unknown), overall_risk_category (enum: low/moderate/high), calculated_at, 
calculated_by (User ref, nullable)

**recommendation_set** (embedded in Patient):
recommended_tests (list of str, e.g. ["EKG", "CBC", "HbA1c"]), generated_at

**alerts** (embedded list in Patient, each item):
id, alert_type (enum: anticoagulant/severe_allergy/osa/airway_concern), 
message (str), severity (enum: critical/warning), acknowledged (bool), 
acknowledged_by (User ref, nullable), acknowledged_by_role (str, nullable), 
acknowledged_at (datetime, nullable), created_at

**AuditLogEntry** (separate top-level collection):
id, entity_type (str), entity_id (str), action (enum: create/update/delete), 
user_id (User ref), changes (dict — before/after diff), timestamp

## Scoring Logic (already decided — implement exactly this)

**STOP-Bang** (0-8, 1 point per yes): Snoring, Tired, Observed apnea, 
Pressure/HTN, BMI>35, Age>50, Neck>40cm, Gender=male
- 0-2 = Low, 3-4 = Moderate, 5-8 = High

**RCRI** (0-6, 1 point per factor): high-risk surgery, ischemic heart disease, 
CHF, cerebrovascular disease, insulin-dependent diabetes, creatinine >2.0
- 0 points = Low, 1 point = Moderate, 2+ points = High

**ASA**: I-II = Low, III = Moderate, IV-VI = High (clinician-suggested only, 
never auto-finalized — always requires human confirmation, never overwrite 
a clinician-confirmed value with a recalculated suggestion)

**METs**: <4 = poor functional capacity (flag for further workup), 
>=4 = adequate

**Overall risk category = WORST (highest) of ASA/STOP-Bang/RCRI levels.**
Any critical alert automatically forces overall_risk_category to "high" 
regardless of individual scores.

## Alert Trigger Rules
- **anticoagulant** (critical): patient on Warfarin, Apixaban, Rivaroxaban, 
  Dabigatran, Edoxaban, or Clopidogrel
- **severe_allergy** (critical): allergy history mentions anaphylaxis, 
  difficulty breathing, throat swelling, or hospitalization from a reaction
- **osa** (critical): stop_bang_score >= 5
- **airway_concern** (critical): mallampati_class in [3,4] OR history 
  mentions "difficult airway"
- Aspirin-only should NOT trigger a critical alert — treat as informational 
  note only

## Recommended Test Rules
- On anticoagulant → INR
- Diabetic (medical_history mentions diabetes) → HbA1c
- STOP-Bang >=5 or existing OSA diagnosis → Sleep Study
- ASA III+ or RCRI >=1 → EKG
- RCRI >=2 → CBC, CMP
- is_pregnant = true → OB clearance

## External Systems
- **Truform**: inbound only — real-world patient intake e-forms system 
  (PBHS). Sends JSON via API. Known integration fields include: patient 
  demographics, insurance, health history items, medications, allergies, 
  emergency contacts, accident information. Fields specific to our scoring 
  (BMI, neck circumference, STOP-Bang symptom questions) are NOT guaranteed 
  to be present — build the parser to gracefully handle missing fields and 
  allow manual entry as fallback. Don't hardcode assumptions about their 
  exact schema until real API docs/sample payload are available.
- **OMS Vision**: outbound only — real practice management/EHR software 
  (Henry Schein One). No public API exists for direct integration. This 
  backend's only job is to generate clean, well-formatted PDFs (risk 
  assessment report + lab order) that office staff manually attach to the 
  patient's chart in OMS Vision's own Documents section. No API calls to 
  OMS Vision are needed or possible.

## Auth
- Google login (real OAuth to be implemented in Phase 6)
- Open to any Google account — not restricted to a specific company domain 
  (unless later told otherwise)
- First-time login → user selects their role (Surgeon/Nurse/Office Staff), 
  saved to their User document. Returning users skip straight to their 
  dashboard based on saved role.

## Frontend Contract Notes
The Ember-built frontend already exists with mock data matching this shape. 
API responses from this backend must match those mock data shapes closely 
so the frontend integration is a drop-in swap, not a rewrite. When in doubt 
about field naming/casing, ask before introducing a mismatch.

## Build Process
This is being built in small, reviewed phases — do NOT jump ahead or build 
multiple phases at once, even if it seems more efficient. Wait for explicit 
go-ahead before starting the next phase. Each phase should end with a 
passing test suite and a clean git status ready to commit.

## Current Phase
Step 1.5 — supporting models (RecommendationSet, Alert, AuditLogEntry)