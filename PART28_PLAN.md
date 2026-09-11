# PART 28 — Security, Audit & AI Governance — Implementation Plan

> **Status: ✅ COMPLETE (2026-09-08).** All six phases implemented and verified.
> Full backend suite: **412 passed**; ruff clean; live backend up on :8000 with
> security headers, rate limiting (5/min login → 429 on burst), docs gated when
> DEBUG=false, and `/media` behind signed-token/Bearer gate (1F). Audit hooks
> wired for auth, complaint create/triage, work-order dispatch/approve/assign/
> reassign/escalate/reject, and routing/priority/department overrides. Migration
> `e4f5a6b7c8d9` applied (ai_decision_logs, evidence_checks, human_overrides).

## Phase 1: Security Hardening

### 1A. Rate Limiting (slowapi + Redis)
- Add `slowapi` to dependencies
- `app/middleware/rate_limit.py`: configure slowapi limiter (storage://redis://)
- Apply per-route limits: login 5/min, register 3/min, password-reset 3/min, file-upload 10/min, general API 60/min
- Exempt health endpoint

### 1B. Security Headers Middleware
- `app/middleware/security_headers.py`: X-Content-Type-Options=nosniff, X-Frame-Options=DENY, Referrer-Policy=strict-origin-when-cross-origin, Permissions-Policy, X-XSS-Protection=0, HSTS (15768000)
- Add to main.py middleware stack

### 1C. Access Token Blacklist (Redis)
- `app/core/blacklist.py`: `is_blacklisted(jti)` / `blacklist_token(jti, exp)` using Redis TTL
- Hook into logout (blacklist current access token), disable-user, password-reset
- Modify `get_current_user` in deps.py to check blacklist before decode

### 1D. CORS Hardening
- Restrict `allow_methods` to GET,POST,PATCH,PUT,DELETE,OPTIONS
- Restrict `allow_headers` to Authorization, Content-Type, Accept, X-Request-ID
- Add docs URL behind auth (or disable in production)

### 1E. API Docs Protection
- Conditionally disable /docs and /redoc in production (when DEBUG=false)

### 1F. Media File Serving Auth
- Add a signed-URL or bearer-token gate on /media serving for complaint evidence
- Or: add query-param token with short TTL

## Phase 2: Extended Audit Trail

### 2A. New Action Constants in audit_service.py
- ACTION_LOGIN, ACTION_LOGOUT, ACTION_REGISTER, ACTION_PASSWORD_RESET
- ACTION_COMPLAINT_CREATE, ACTION_COMPLAINT_TRIAGE
- ACTION_WORK_ORDER_DISPATCH, ACTION_WORK_ORDER_APPROVE, ACTION_WORK_ORDER_ASSIGN
- ACTION_WORK_ORDER_REASSIGN, ACTION_WORK_ORDER_ESCALATE, ACTION_WORK_ORDER_REJECT
- ACTION_PRIORITY_OVERRIDE, ACTION_DEPARTMENT_OVERRIDE, ACTION_ROUTING_OVERRIDE

### 2B. Auth Audit
- `app/api/v1/auth.py`: add record_audit after login, logout, register, reset-password
- Pass IP via request.client.host

### 2C. Complaint Audit
- `app/api/v1/complaints.py`: add record_audit after create, triage, correlate, routing override

### 2D. Work Order Audit
- `app/api/v1/work_orders.py`: add record_audit after dispatch, approve, assign, reassign, escalate, reject

## Phase 3: AI Governance

### 3A. AI Decision Log Model
- `app/models/ai_decision_log.py`: id, complaint_id, agent_name, model_name, prompt_version, input_summary, output_summary, confidence, tool_calls(JSONB), result(JSONB), duration_ms, created_at
- Migration

### 3B. AI Governance Service
- `app/services/ai_governance_service.py`: `log_ai_decision(db, complaint_id, agent, model, prompt_version, input_summary, output, confidence, tool_calls, duration_ms)` → flush + return
- `get_ai_decisions(db, complaint_id)` → list

### 3C. Hook into Agents
- triage_agent.py: after structured_completion, log decision with confidence
- dispatch_agent.py: after agent run, log decision with confidence
- priority_service.py: after priority scoring, log decision
- vision_service.py: after image analysis, log decision

### 3D. AI Governance API
- `app/api/v1/governance.py`:
  - GET /ai-decisions?complaint_id=X → list decisions for a complaint
  - GET /ai-decisions/{id} → single decision detail

## Phase 4: Evidence Validation

### 4A. Evidence Check Model
- `app/models/evidence_check.py`: id, complaint_id, decision_id, claim_type, claim_value, actual_value, source, is_match, discrepancy_pct, notes, created_at
- Migration

### 4B. Evidence Validation Service
- `app/services/evidence_validation_service.py`:
  - `validate_distance_claim(db, complaint_id, decision_id, claim_type, claimed_km, facility_lat, facility_lon)` → EvidenceCheck
  - `validate_category_match(db, complaint_id, decision_id, claimed_category, actual_category)` → EvidenceCheck
  - `run_evidence_checks(db, complaint_id)` → list[EvidenceCheck]

### 4C. Hook into AI decisions
- After triage, validate category claim against GIS data
- After routing, validate department match against category-department mapping

## Phase 5: Human Override

### 5A. Human Override Model
- `app/models/human_override.py`: id, complaint_id, decision_id, override_type, original_value, new_value, reason, user_id, created_at
- Migration

### 5B. Override Service
- `app/services/override_service.py`:
  - `record_override(db, complaint_id, decision_id, override_type, original, new, reason, user_id)` → HumanOverride
  - `get_overrides(db, complaint_id)` → list

### 5C. Override API
- Extend complaints.py or new governance.py:
  - POST /complaints/{id}/override → record an override (OFFICER/ADMIN only)
  - GET /complaints/{id}/overrides → list overrides

## Phase 6: Tests

### 6A. Security Tests (tests/test_security.py)
- Test rate limiting on login (burst > limit → 429)
- Test unauthorized API access (no token → 401, wrong role → 403)
- Test invalid file upload (bad magic bytes → 415)
- Test CORS headers
- Test security headers present
- Test token blacklist (logout → old access token rejected)
- Test password strength validation

### 6B. Audit Tests (tests/test_audit_extended.py)
- Test login audit recorded
- Test logout audit recorded
- Test complaint create audit recorded
- Test work order dispatch audit recorded
- Test override audit recorded

### 6C. AI Governance Tests (tests/test_governance.py)
- Test AI decision logged after triage
- Test AI decision logged after dispatch
- Test evidence validation flags mismatch
- Test human override stored correctly
- Test governance API returns decisions

## Migration
- Single new migration: e4f5a6b7c8d9_security_governance.py
- Creates: ai_decision_logs, evidence_checks, human_overrides tables
- Adds indexes

## Files to Create (new)
- app/middleware/security_headers.py
- app/middleware/rate_limit.py
- app/core/blacklist.py
- app/models/ai_decision_log.py
- app/models/evidence_check.py
- app/models/human_override.py
- app/services/ai_governance_service.py
- app/services/evidence_validation_service.py
- app/services/override_service.py
- app/api/v1/governance.py
- app/schemas/governance.py
- tests/test_security.py
- tests/test_audit_extended.py
- tests/test_governance.py

## Files to Modify
- main.py (middleware stack, CORS, docs toggle)
- app/api/v1/auth.py (audit logging)
- app/api/v1/complaints.py (audit + evidence + overrides)
- app/api/v1/work_orders.py (audit + overrides)
- app/services/audit_service.py (new action constants)
- app/api/deps.py (blacklist check)
- app/services/ai_service.py (governance hook)
- app/agents/triage_agent.py (governance hook)
- app/agents/dispatch_agent.py (governance hook)
- app/services/priority_service.py (governance hook)
- app/models/__init__.py (new model exports)
- app/schemas/__init__.py (new schema exports)
- app/api/v1/__init__.py (register governance router)
- pyproject.toml (add slowapi)
- alembic head (migration)
