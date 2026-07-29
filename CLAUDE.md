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
id, full_name, dob, sex, surgery_date, notes (str, nullable — clinician
notes; surgeon/nurse can write, per Roles section), created_at, created_by
(User ref)

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
  (PBHS). API defaults to JSON (per PBHS's own docs: "you can choose JSON 
  (default) or XML"; our PRD also specifies JSON) — a submission is a 
  property containing a list of key/value pairs. Integration is 
  POLL-based: our backend periodically asks Truform "any new 
  submissions?" — Truform never calls us, we call them. Forms are 
  dynamic — a field the patient left blank is omitted entirely, never 
  assume a fixed schema. Known integration fields include: patient 
  demographics, insurance, health history items, medications, allergies, 
  emergency contacts, accident information. Fields specific to our scoring 
  (BMI, neck circumference, STOP-Bang symptom questions) are NOT 
  guaranteed to be present — build the parser to gracefully handle 
  missing fields and allow manual entry as fallback. Real PBHS field 
  names confirmed for scoring-relevant fields — see 
  app/services/truform_parser.py.
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
Phase 1 (data model layer) is complete: User, Patient, and AuditLogEntry
documents, all embedded clinical sub-documents (intake_record, exam_finding,
risk_assessment, recommendation_set, alerts), unique constraints verified
against live Atlas, and a full CRUD round-trip smoke test passing against
the real dev database.

Phase 2 (scoring engine) is complete: pure-function implementations of
STOP-Bang, RCRI, ASA suggestion, METs classification, overall-risk
worst-of logic, alert generation, and recommended-test generation, all in
app/services/, with no DB calls or routes — fully unit tested.

Phase 3 (API routes) is complete: app/schemas/patient.py (PatientCreate,
PatientRead, PatientListItem, and the per-endpoint update schemas) and
app/routers/patients.py wire the Phase 2 service layer to real HTTP
endpoints (create/list/get patient, update intake/exam-finding, calculate
risk, acknowledge alert, update notes). Every mutating endpoint writes its
AuditLogEntry inside the same MongoDB transaction as the Patient update,
per the Data Modeling Approach section above. Added Patient.notes (was
missing from the Phase 1 model, per the PRD's Roles section). Verified via
/docs that all endpoints and schemas render correctly.

Phase 4 (recommendations & alerts) is deferred/merged: that rules-engine
logic was already built as pure services in Phase 2, and Phase 3 wired it
into routes — there is no separate Phase 4 work remaining.

Phase 5 (Truform ingestion parser) is complete: app/services/truform_parser.py
maps real PBHS XML field names (researched, not generic guesses) into
ParsedIntakeData, always flagging permanently-missing scoring fields
(tired_during_day, observed_apnea, neck_circumference_cm, mallampati_class)
and any unrecognized fields in the payload; never raises on malformed
input. app/services/truform_client.py's fetch_pending_submissions() is a
stub pending real Truform API credentials. POST /patients/from-truform
(manual/test payload submission) and POST /patients/poll-truform (calls
the stub, currently always creates zero patients) both require
surgery_date and created_by as explicit inputs, since Truform's fields
cover clinical/demographic data only — a scheduled surgery date and the
staff member doing the import aren't things Truform sends and aren't
guessed at.

Phase 6 (Google auth + role-based access) is complete: app/auth/
google_oauth.py verifies Google Sign-In ID tokens against Google's public
keys (google-auth library, never trusts unverified claims);
app/auth/jwt_handler.py issues/verifies our own short-lived session JWTs
(pyjwt) carrying user_id + role; app/auth/dependencies.py provides
get_current_user (401 if missing/invalid/inactive) and the require_role
factory (403 if role doesn't match) for future route protection.
app/routers/auth.py: POST /auth/google (find-or-create User by
google_sub_id, issue JWT), POST /auth/select-role (one-time, 409 if
already set), GET /auth/me. Applied as a working example to two Phase 3
routes: PATCH /patients/{id}/exam-finding now requires nurse role;
GET /patients requires any authenticated user (all 3 roles) — response
filtering by role is a schema concern (PatientListItem) already handled
in Phase 3, not an auth concern. JWT_SECRET_KEY auto-generates per
process for local dev — production must set a real, stable value (see
app/config.py). Manually verified: hitting /auth/google via /docs with a
fabricated token correctly returns 401, confirming Google verification
actually runs.

Phase 7 (PDF exports) is complete: app/services/pdf/risk_report.py and
app/services/pdf/lab_order.py generate PDFs via reportlab (pure Python —
no Cairo/Pango system dependency to complicate the Docker/Render
deployment), covering the fields OMS Vision's manual-upload workflow and
the lab-order spec need. GET /patients/{id}/export/risk-report is
accessible to all 3 roles (office staff explicitly export PDFs per the
Roles section); POST /patients/{id}/export/lab-order is nurse-only
("Generate Lab Order"). Both write an AuditLogEntry (new
AuditAction.PDF_GENERATED) inside the existing transaction pattern. Two
real rendering bugs were caught and fixed before shipping: (1) HTML-
escaping text meant for reportlab Table cells (as opposed to Paragraph,
which actually interprets markup) made entities like `&amp;` show up
literally instead of decoding; (2) the Unicode em-dash isn't in
reportlab's default standard-14 fonts and rendered as a missing-glyph
box — replaced with a plain ASCII hyphen throughout. Manually verified
end-to-end against the real dev database: started uvicorn, downloaded
both PDFs via authenticated requests through /docs's schema, rendered
each to an image and visually confirmed clean, correct, non-blank output,
and confirmed both AuditLogEntry writes landed before cleaning up all
test data.

Phase 8 (audit logging completion pass) is complete: this was a review
pass, not a rewrite — went through every mutating endpoint in
app/routers/patients.py and app/routers/auth.py and confirmed each writes
a transactional, meaningful AuditLogEntry. update_intake,
update_exam_finding, update_notes, and both PDF exports were already
correct (real before/after diffs, real ActorSnapshot actors) and left
untouched. Found and fixed four real gaps: (1) create_patient and the
shared _create_patient_from_truform helper only captured full_name in the
audit "after" diff — now also capture dob/sex/surgery_date/
patient_identifier; (2) calculate_risk hardcoded "before": None and never
included alerts in the diff at all, even though recalculating risk can
change asa_class/scores/alerts together — now snapshots the patient's
prior risk_assessment/recommendation_set/alerts before mutating, and
includes alerts in both before and after; (3) acknowledge_alert hardcoded
"before": {"acknowledged": False} instead of reading the alert's actual
prior acknowledged/acknowledged_by/acknowledged_at state; (4)
app/routers/auth.py had zero audit logging — select_role (one-time role
assignment) and new-user creation inside login_with_google now write a
transactional AuditLogEntry (entity_type="User") using the same
run_in_transaction/record_audit_entry pattern as patients.py. Added
GET /patients/{id}/audit-log (surgeon/nurse only, per the Roles section —
office staff get no clinical/audit detail access) as the first way to
actually read the audit trail back, ordered newest-first;
app/schemas/audit.py::AuditLogEntryRead is the response schema. Also
confirmed the established test pattern of mocking AuditLogEntry.insert
can't assert on audit *content* (AsyncMock doesn't bind self, so the
constructed entry is never visible to the mock) — added a
record_audit_entry-patching helper to both test files so tests can assert
directly on entity_type/action/actor/changes.

## Phase 1-8 Summary (quick reference)

- **Phase 1** — Data model layer: User, Patient, and AuditLogEntry
  documents, plus all embedded clinical sub-documents.
- **Phase 2** — Scoring engine: STOP-Bang, RCRI, ASA suggestion, METs,
  overall-risk worst-of logic, alert generation, recommended tests — pure
  functions, no DB, fully unit tested.
- **Phase 3** — API routes: patient CRUD plus intake/exam-finding/
  calculate-risk/alert-acknowledge/notes endpoints; established the
  transactional audit-logging pattern every later phase reuses.
- **Phase 4** — Deferred/merged: recommendations & alerts logic was
  already delivered by Phases 2-3, no separate work needed.
- **Phase 5** — Truform ingestion parser: tolerant field mapping,
  missing-scoring-field flagging, manual and poll-based ingestion
  endpoints.
- **Phase 6** — Google auth + role-based access: Google ID token
  verification, our own session JWTs, get_current_user/require_role
  dependencies.
- **Phase 7** — PDF exports: risk report and lab order generation via
  reportlab, audited as AuditAction.PDF_GENERATED.
- **Phase 8** — Audit logging completion pass: filled shallow/missing
  audit diffs (patient creation, calculate-risk, alert acknowledgment),
  added User-entity audit logging to auth.py, added the
  GET /patients/{id}/audit-log read endpoint.

Current: Backend feature-complete — next: deploy to Render, then connect
Ember frontend to real API