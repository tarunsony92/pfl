# Follow-up items from M1 code review

## Deferred to M4 (frontend integration)

### C1: Refresh tokens should be delivered via HttpOnly cookies

**Current state:** `/auth/login` and `/auth/refresh` return both `access_token` and `refresh_token` in the JSON body. The refresh token is accessible to JavaScript, defeating HttpOnly XSS protection.

**Spec reference:** §3.3 — "session-based, HTTPS-only cookies, 8-hour idle timeout"

**Fix plan (M4):**
- Issue refresh token via `response.set_cookie("refresh_token", value, httponly=True, secure=True, samesite="lax", max_age=<7d_in_s>)`
- Read from `request.cookies.get("refresh_token")` in `/auth/refresh`, not the request body
- Access token can remain in JSON body for short-lived bearer use
- Update frontend auth client accordingly
- Add CSRF token defense for the cookie-based refresh endpoint (double-submit or SameSite=strict)

## Deferred to M2 (or early fix)

### I2: Add user deactivation endpoint

`PATCH /users/{user_id}/active` accepting `{"is_active": false}`, gated to `require_role(UserRole.ADMIN)`, with audit log entry `user.deactivated` / `user.reactivated`. Backend model already has `is_active` and auth already blocks inactive users.

### I3, I4: AuditLog schema drift from spec §8

Spec §8 defines `audit_log — id, user_id, action, entity_type, entity_id, before_json, after_json, at`. Current model uses:
- `actor_user_id` instead of `user_id` (more precise but drifts from spec)
- Inherits `created_at` + `updated_at` from TimestampMixin; should be a single immutable `at` column

**Fix plan:**
- Add `at` column with `default=utcnow, nullable=False`, tz-aware
- Drop `created_at` / `updated_at` (or keep `created_at` as an alias and deprecate)
- Rename `actor_user_id` → `user_id` (or update spec to match — pick one)
- Alembic migration to rename and restructure

### I7: Remove dead `check_password` from users_svc

Function defined but unused. Either:
- Replace the inline `security.verify_password(...)` call in `auth_svc.authenticate` with `users_svc.check_password(user, password)` to centralize the policy, OR
- Delete `check_password` from `users_svc`

## Minor / nice-to-have

### M2: Document the flush-before-audit pattern in routers

Add an inline comment in `users.py::create_user` explaining why `await session.flush()` is needed before the audit log write (so `user.id` is populated).

### M3: Add `updated_at` to `UserRead` schema

For optimistic locking when frontend (M4) and workers (M5+) both modify user state.

### M4 (of review): Add audit-readback tests

`test_audit.py` currently only verifies `log_action` directly. Add tests that:
1. Make a POST /users request as admin
2. Read `audit_log` rows and verify `action="user.created"`, `actor_user_id=<admin id>`, `after_json={...}` is correct

### M5 (of review): Comment the asyncio.run pattern in conftest.py

Add a comment in `setup_database` fixture explaining why `asyncio.run()` is used inside a sync session-scoped fixture (to create a DB schema loop independent of the per-test loops).

---

## Deferred from M3

### M3-F1: AutoCamExtractor doesn't parse co-applicant fields

Current extractor only populates `system_cam.applicant_name / pan / date_of_birth`. The pipeline's dedupe step (`_run_dedupe_and_persist` in `app/worker/pipeline.py`) hard-codes `co_applicant=None` as a result. Once AutoCamExtractor 2.0 extracts co-applicant cells (spec §4.4.1 lists them), project them via a twin of `_extract_auto_cam_applicant` and pass both subjects to `run_dedupe`.

### M3-F2: T3 migration models have pre-existing ruff violations ✅ FIXED (T16)

`app/models/case_extraction.py` and `app/models/dedupe_match.py` from commit `91d5e74` had `I001` (unsorted imports) and `N811` (constant-alias naming — `ENUM as PgEnum`). Fixed in T16 by splitting the combined import in `dedupe_match.py` and adding `# noqa: N811`. `case_extraction.py` was already correct.

### M3-F4: Unify reingest stage sets ✅ FIXED (pre-merge)

Router used a narrower 3-stage set; pipeline pre-flight used a 4-stage set including `CHECKLIST_VALIDATION`. Added an explanatory comment to the router constant clarifying why they differ (router gates admin manual reingest; pipeline handles the add_artifact re-trigger path that lands in VALIDATION). Consider consolidating into `app/services/stages.py` in a future M4 refactor.

### M3-F5: Remove PII from pipeline log ✅ FIXED (pre-merge)

`_send_missing_docs_email_if_needed` was logging `uploader.email` at INFO level. Replaced with `uploader.id`.

### M3-F6: Authorization review for case read endpoints

`GET /cases/{id}/extractions|extractions/{name}|checklist-validation|dedupe-matches` currently use `get_current_user` (any authenticated user). Consider tightening to `require_role(AI_ANALYSER, UNDERWRITER, CREDIT_HO, CEO, ADMIN)` once M4 frontend scopes the user base — these endpoints expose derived PII (PAN matches, dedupe flags). Matches M2 precedent on `GET /cases/{id}` so consistent for now.

### M4-F3: No visible entry point to upload wizard from case list ✅ FIXED (this session)

Added a `+ New Case` button to the case list page header, gated on `user.role in {ai_analyser, admin}` (matching backend `POST /cases/initiate` permission). Without this, the only way to reach `/cases/new` was typing the URL directly.

### M4-F4: LocalStack presigned URLs unreachable from host browser ✅ FIXED (this session)

Added `aws_s3_public_endpoint_url` config + `StorageService._public_client()` — presigned upload + download URLs now use the public host (`http://localhost:4566` in dev), while all other S3 operations keep using the internal `http://localstack:4566`. Set via new `AWS_S3_PUBLIC_ENDPOINT_URL` env in docker-compose for backend + worker + decisioning-worker.

### M4-F1: Proxy body-replay on 401 refresh retry ✅ FIXED

`frontend/src/app/api/proxy/[...path]/route.ts` now buffers the request body into an `ArrayBuffer` at the top of `handle()` once, then passes the same buffer to both the first attempt and the 401 replay. Commit: the one after `af5bde4`.

### M3-F7: Rename `reset_email_service` to match project convention

Storage service uses `reset_storage_for_tests()`. Email service's `reset_email_service()` in `app/services/email.py` should be renamed to `reset_email_service_for_tests()` for consistency. Update 5 call sites in `tests/integration/test_email_service.py` and any other test files.

### M3-F3: Mypy errors in M3 files ✅ FIXED (T16)

Three type errors introduced in M3 were resolved in T16:
- `app/worker/checklist_validator.py:134` — `present_docs` list literal inferred as `list[dict[str, int | str]]`; fixed by explicit annotation `list[dict[str, object]]`.
- `app/services/cases.py:474` — `payload` dict literal inferred as `dict[str, str]`; fixed by annotating as `dict[str, object]`.
- `app/worker/pipeline.py:398` — variable `body_bytes` reused for a `.get()` return (typed `bytes | None`) after being assigned `bytes` earlier in the same loop; fixed by renaming to `artifact_bytes: bytes | None` with explicit annotation.

Mypy now reports: `Success: no issues found in 58 source files`.

## Tracking

These items will be incorporated into the relevant milestone plans when they are drafted (M2 for I2/I3/I4/I7, M4 for C1, M3-F1 in M4/M5, rest opportunistically).
