# Milestone 4: Next.js 14 Frontend — Design Spec

**Project:** PFL Finance Credit AI Platform
**Milestone:** M4
**Spec date:** 2026-04-18
**Author:** Saksham Gupta (with Claude)
**Status:** Draft — pending spec review + user sign-off
**Builds on:** M3 (tag `m3-ingestion-workers`)
**Parent design:** `docs/superpowers/specs/2026-04-18-pfl-credit-audit-system-design.md`

---

## 1. Executive Summary

M4 delivers the complete Next.js 14 frontend that makes the PFL Credit AI system usable by the team.
Every screen listed in the parent spec §3 is shipped: login with TOTP support, a case list with
filters and search, a multi-tab case detail view (overview, artifacts, extractions, checklist,
dedupe, audit log), upload wizard, re-upload flow, admin reingest trigger, missing-doc upload,
dedupe snapshot management, user administration, and a profile/settings page. M4 also closes the
open security follow-up M1-C1 by migrating the backend refresh token to HttpOnly cookies and wiring
the frontend accordingly, and ships the M1-I2 user-deactivation endpoint that was deferred from M2.
By the end of M4, the team can operate the full M1–M3 pipeline through a browser; nothing is
interacted with via Postman or curl.

---

## 2. Scope

### 2.1 In scope for M4

- Next.js 14 App Router application (`frontend/` directory, new service `pfl-web` in docker-compose)
- All 10 primary screens (§6)
- Auth flow: login, TOTP challenge, MFA enroll/verify, logout, profile password change
- HttpOnly refresh-token cookie (closes M1-C1): backend patch + frontend client wired together
- User deactivation endpoint `PATCH /users/{id}/active` (closes M1-I2, admin-only, wired in `/admin/users`)
- API proxy layer at `/api/proxy/*` Route Handlers (cookie rotation, access-token-in-memory)
- `useAuth()` hook with mutex-guarded silent refresh
- SWR-based data fetching with per-screen staleness policy
- Polling on case detail when stage is in-flight (5s interval, stops on stable stage)
- Dark mode toggle (default light), persisted to localStorage
- PFL branded Tailwind theme (primary blue, slate grey, amber warning)
- WCAG 2.1 AA accessibility pass
- Playwright E2E test: login → create case → view artifacts → logout
- Vitest unit/component tests; ≥80% coverage on new frontend code
- Docker-compose `pfl-web` service (dev hot-reload + prod build)
- Lighthouse score ≥ 90 for `/login` and `/cases`
- Tag `m4-frontend`

### 2.2 Out of scope for M4

- Phase 1 decisioning UI (M5 ships new case stages; M4 shows them as read-only badges)
- Phase 2 audit output viewer (M6)
- Policy YAML editor and heuristics library (M5+)
- NPA upload form and feedback forms (M7)
- Direct bureau pull UI (v2)
- Mobile-responsive optimization (deferred per parent spec §2.3)
- i18n / multi-language (English-only for v1)
- Password-reset via email token (SMTP plumbing needed; deferred to M5 settings work)
- Storybook component catalogue (optional; deferred)

### 2.3 Non-goals

- The frontend does not make direct Anthropic API calls; all AI work stays in workers.
- The frontend does not own any database state; it is a pure API client.
- The frontend does not implement WebSocket real-time push; polling covers the M4 need.

---

## 3. Users and Screens

Roles from parent spec §3.1: `admin`, `ceo`, `credit_ho`, `ai_analyser`, `underwriter`.

| Screen | admin | ceo | credit_ho | ai_analyser | underwriter |
|---|---|---|---|---|---|
| `/login` | All | All | All | All | All |
| `/cases` | All | All | All | All | Own |
| `/cases/new` | Yes | No | No | Yes | No |
| `/cases/[id]` — Overview | All | All | All | All | Own |
| `/cases/[id]` — Artifacts | All | All | All | All | Own |
| `/cases/[id]` — Extractions | All | All | All | All | Own |
| `/cases/[id]` — Checklist | All | All | All | All | Own |
| `/cases/[id]` — Dedupe | All | All | All | All | Own |
| `/cases/[id]` — Audit Log | All | All | All | Read-only | Read-only |
| `/cases/[id]/reupload` | All | No | No | Yes | Own |
| `/cases/[id]/reingest` | Admin only | No | No | No | No |
| `/cases/[id]/add-artifact` | All | No | No | Yes | Own |
| `/admin/dedupe-snapshots` | Admin only | CEO + Credit HO (read) | CEO + Credit HO (read) | No | No |
| `/admin/users` | Admin only | No | No | No | No |
| `/settings/profile` | All | All | All | All | All |
| Error pages (403/404/500) | All | All | All | All | All |

**"Own"** means the user can access cases they uploaded (`uploaded_by = me`) plus any cases
`assigned_to` them. Admins, CEO, and Credit HO see all cases.

The backend's `list_cases` does NOT auto-filter by caller — it only applies the `uploaded_by`
query param if passed. For M4 we enforce the own-case restriction in TWO places: (1) backend
`list_cases_endpoint` inspects `current_user.role == UserRole.UNDERWRITER` and injects
`uploaded_by=current_user.id` automatically; (2) frontend hides the role-scoped filter UI. This
closes a latent security gap.

MFA requirement: admin, ceo, credit_ho must complete TOTP before reaching any authenticated screen.
ai_analyser and underwriter see MFA as optional; if they have enrolled, TOTP is required.

---

## 4. Architecture

### 4.1 App Router structure

```
frontend/
  app/
    layout.tsx                 # root layout: font, theme, toast provider
    (auth)/
      login/page.tsx
    (app)/
      layout.tsx               # sidebar + header shell; auth-gated
      cases/
        page.tsx               # /cases list (RSC)
        new/page.tsx           # /cases/new upload wizard (client)
        [id]/
          page.tsx             # /cases/[id] detail (RSC shell + client tabs)
          reupload/page.tsx
          reingest/page.tsx
          add-artifact/page.tsx
      admin/
        dedupe-snapshots/page.tsx
        users/page.tsx
      settings/
        profile/page.tsx
    api/
      proxy/
        [...path]/route.ts     # catch-all Route Handler proxy to backend
  components/
    ui/                        # shadcn/ui primitive re-exports
    custom/                    # StageBadge, CaseArtifactGrid, ExtractionPanel, …
  lib/
    api.ts                     # typed API client (calls /api/proxy/*)
    auth.ts                    # useAuth hook + AuthProvider
    swr-keys.ts                # SWR cache key constants
    enums.ts                   # TypeScript enums (synced from backend; see §12)
  middleware.ts                # auth gate + CSRF seed
  tailwind.config.ts
  next.config.ts
```

### 4.2 Server vs client component policy

| Situation | Component type | Reason |
|---|---|---|
| Page shell, initial data load | RSC (Server Component) | Zero client JS; better LCP |
| Any form, button, tab, modal | Client Component (`"use client"`) | Interactivity required |
| Sidebar, header | Client (theme toggle, active link) | State-dependent rendering |
| Case detail tabs | RSC shell + per-tab Client Components | Tabs switch client-side after initial load |
| API proxy Route Handlers | Route Handler (`app/api/proxy/`) | Server-side cookie forwarding |

### 4.3 Data fetching strategy

- **Initial page data** fetched in RSC via `fetch()` to the internal proxy (server-to-server, no
  round-trip to the browser). Cache: `{ cache: 'no-store' }` for mutable data (cases, users).
- **Client-side mutations and refetches** handled by SWR in Client Components. The SWR fetcher
  always calls `/api/proxy/*`; it never calls the backend directly.
- **Route Handlers** (`/api/proxy/[...path]`) forward requests to the FastAPI backend, inserting
  the Authorization header from the server-side access token store (§9). On 401 from backend, the
  proxy refreshes the access token via the HttpOnly cookie before retrying once.

### 4.4 Hydration pattern

RSC pages pass initial data as props to Client Component wrappers (`initialData`). SWR is
initialised with `fallbackData={initialData}`, so the page renders immediately without a
client-side loading flicker. Subsequent SWR revalidations hit the proxy and update in the
background.

---

## 5. Auth Flow

### 5.1 Login — email/password + optional TOTP

1. User submits email + password to `POST /api/proxy/auth/login`.
2. Proxy forwards to backend `POST /auth/login`.
3. If backend returns `{ mfa_required: true }` → show TOTP code field inline; re-submit with
   `mfa_code`.
4. If backend returns `{ mfa_enrollment_required: true }` → redirect to `/settings/profile#mfa`
   with a toast instructing the user to set up MFA before continuing.
5. On success: access token is stored in the `useAuth()` context (in-memory only, never
   localStorage/sessionStorage). Refresh token is in the HttpOnly cookie (set by backend, never
   readable by JS).
6. Redirect to the originally-requested URL or `/cases`.

### 5.2 MFA setup + verify

- **Enroll:** `POST /auth/mfa/enroll` → backend returns `{ secret, otpauth_uri }`. Frontend
  renders a QR code (via the `qrcode.react` library) and the raw secret for manual entry.
- **Verify:** User enters the 6-digit code; frontend `POST /auth/mfa/verify`. On success, toast
  "MFA enabled" and mark user as enrolled in auth context.
- The profile page shows current MFA status and an Enable/Disable toggle. Disabling MFA requires
  an admin (out of scope for M4 self-service; admin resets via password-reset flow).

### 5.3 Refresh token via HttpOnly cookie (closes M1-C1)

**Backend patch required in M4:**

- `POST /auth/login` response: set cookie in addition to returning access token in JSON body.
  ```
  Set-Cookie: refresh_token=<value>; HttpOnly; Secure; SameSite=Lax; Path=/auth/refresh; Max-Age=604800
  ```
  The cookie `Path` is scoped to `/auth/refresh` so it is only sent by the browser on refresh
  calls, not on every request.
- `POST /auth/refresh`: read refresh token from `request.cookies.get("refresh_token")` rather than
  the JSON body. The `RefreshRequest` body schema and the `refresh_token` field in `LoginResponse`
  remain but are deprecated (kept for backward compat with any direct API users until M5).
- `POST /auth/logout`: clear the cookie:
  ```
  Set-Cookie: refresh_token=; HttpOnly; Secure; SameSite=Lax; Path=/auth/refresh; Max-Age=0
  ```

**Cookie attributes summary:**

| Attribute | Value | Reason |
|---|---|---|
| HttpOnly | true | JS cannot read the token; XSS protection |
| Secure | true | HTTPS-only (dev: set false when `NODE_ENV=development`) |
| SameSite | Lax | CSRF protection for top-level navigation; allows redirect flows |
| Path | /auth/refresh | Cookie only sent to the refresh endpoint |
| Max-Age | 604800 (7 days) | Matches existing refresh token TTL |

**Frontend behaviour:**

The proxy Route Handler at `/api/proxy/auth/refresh` forwards the browser's cookie to the backend
transparently (no JS access needed). This means the browser automatically includes `refresh_token`
in the cookie header on calls to that path, and the proxy passes `credentials: 'include'` on the
server-fetch call.

### 5.4 Logout

1. Client calls `POST /api/proxy/auth/logout`.
2. Proxy forwards to `POST /auth/logout` with the current access token.
3. Backend revokes server-side state and returns `Set-Cookie: refresh_token=; Max-Age=0`.
4. Proxy clears the cookie by forwarding the `Set-Cookie` response header.
5. `useAuth()` clears the in-memory access token.
6. Redirect to `/login`.

### 5.5 CSRF defense — double-submit token pattern

Since the refresh cookie is `SameSite=Lax`, most cross-site refresh forgery is already blocked.
For defense-in-depth on state-mutating proxy calls (POST/PATCH/DELETE), M4 adds a double-submit
CSRF token:

1. `middleware.ts` checks for a cookie `csrf_token`. If absent, generates a random 32-byte hex
   string and sets it as a non-HttpOnly cookie (`SameSite=Strict`).
2. All mutating Route Handlers require an `X-CSRF-Token` header that must match the `csrf_token`
   cookie value.
3. Client-side `api.ts` reads `csrf_token` from `document.cookie` and adds it to every
   non-GET request header.
4. Attacker's cross-origin page cannot read the non-HttpOnly cookie, so it cannot forge the header.

CSRF enforcement lives in Next.js `middleware.ts` at the Route Handler edge (not inside each
handler). Before forwarding to the backend, middleware: (a) for non-GET methods, reads
`X-CSRF-Token` header and the `csrf_token` cookie, rejects with 403 if they don't match; (b) the
refresh endpoint `POST /api/proxy/auth/refresh` is exempt from CSRF because the refresh cookie
itself is HttpOnly + SameSite=Lax (inherent CSRF protection — the browser won't send it cross-site
for state-changing requests from 3rd-party contexts under SameSite=Lax). For clarity, always
require the CSRF token for refresh anyway, to make the flow uniform; the hook that calls refresh
reads the csrf cookie and sets the header.

This protects both the refresh endpoint and all case/user mutation proxied calls.

---

## 6. Screens — Detailed Per-Screen Spec

### 6.1 `/login`

**URL:** `/login`
**Auth required:** No (redirect to `/cases` if already authenticated)

Layout: centered card (max-w-sm), PFL logo above, "Credit AI" sub-label.

Fields:
- Email (`<input type="email">`, required)
- Password (`<input type="password">`, required, min 8 chars)
- TOTP code (`<input type="text" inputmode="numeric" maxlength="6">`) — hidden initially; shown
  if/when the server returns `mfa_required: true` after first submit attempt

Behaviour:
1. Submit → `POST /api/proxy/auth/login` with `{ email, password }`.
2. If `mfa_required`: show TOTP field, re-submit with `mfa_code` added.
3. If `mfa_enrollment_required`: show inline banner "MFA setup required for your role. Visit
   Settings → Profile to enroll."
4. On 401 (wrong credentials): show field-level error "Invalid email or password."
5. On success: navigate to the originally-requested path or `/cases`.

Validation (react-hook-form + zod):
```ts
LoginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(128),
  mfa_code: z.string().regex(/^\d{6}$/).optional(),
})
```

### 6.2 `/cases`

**URL:** `/cases`
**Auth required:** All authenticated

**Page load:** RSC fetches `GET /api/proxy/cases` with default params. Passes `initialData` to
Client Component.

**Filter bar (sticky, above table):**
- Stage dropdown (`<Select>`) — values from `CaseStage` enum; includes "All stages"
- Uploaded by dropdown (`<Select>`) — populated from `GET /users` (admin/ceo/credit_ho only; hidden
  for ai_analyser/underwriter)
- Loan ID search (`<Input type="text">`) — debounced 300ms → maps to `loan_id_prefix` query param
- Date range: From / To (`<Input type="date">`)
- "Include deleted" toggle — admin only
- Reset filters button

**Table columns:**

| Column | Source field | Notes |
|---|---|---|
| Loan ID | `loan_id` | Monospace font |
| Applicant | `applicant_name` | "—" if null |
| Stage | `current_stage` | `<StageBadge>` |
| Uploaded by | `uploaded_by` (UUID → name lookup) | Shown as full name |
| Uploaded at | `uploaded_at` | `dd MMM yyyy HH:mm` format |
| Actions | — | "View" button; admin sees "Delete" icon |

**Pagination:** offset-based. Show "Showing 1–50 of 234". Previous / Next buttons. Page size fixed
at 50 (matches backend default).

**Sort:** Default sort is `uploaded_at DESC` (backend-imposed). Column-header click re-sorts
client-side within the current page only. If multi-page sort is needed in a future milestone, add
`sort_by` + `sort_dir` query params to the backend.

**SWR config:** `refreshInterval: 10000` (10s) while this page is mounted. Stale-while-revalidate.

**Empty state:** Illustrated empty state card "No cases yet. Upload the first case." with button →
`/cases/new` (shown only to roles with upload permission).

### 6.3 `/cases/new` — Upload Wizard

**URL:** `/cases/new`
**Auth required:** ai_analyser, admin (backend `POST /cases/initiate` is gated on `AI_ANALYSER, ADMIN`; UNDERWRITER is not permitted — aligns with backend gate)

Three-step wizard. Progress indicator at top (Step 1 of 3 / Step 2 of 3 / Step 3 of 3).

**Step 1 — Case details**

Fields:
- Loan ID (`<Input>`, required, pattern `^[A-Za-z0-9-]{3,32}$`)
- Applicant name (`<Input>`, optional, max 255 chars)

On submit → `POST /api/proxy/cases/initiate` with `{ loan_id, applicant_name }`.

Success: receive `{ case_id, upload_url, upload_fields, upload_key, expires_at, reupload }`.
If `reupload: true`: show yellow banner "A case with this loan ID already exists and has been
approved for re-upload." Proceed to step 2.
If 409 (case_exists without admin approval): show error "Case already exists. Contact admin to
approve re-upload."

**Step 2 — File upload**

- Drag-and-drop zone or file picker (`.zip` only, max 500 MB label).
- On file select: `POST` directly to `upload_url` using `upload_fields` as form fields (S3
  presigned POST). The browser sends the multipart form directly to S3/LocalStack.
- Progress bar via `XMLHttpRequest.upload.onprogress`.
- On S3 response 2xx: proceed to step 3.
- On failure: show error with retry button; the presigned URL expires at `expires_at` (show
  countdown if < 5 min remain).

**Step 3 — Finalize**

- Single "Finalize Upload" button.
- On click → `POST /api/proxy/cases/{case_id}/finalize`.
- On success: toast "Case submitted for ingestion. Loan ID: {loan_id}." Navigate to
  `/cases/{case_id}`.
- On error: show message with suggestion to check network or contact admin.

### 6.4 `/cases/[id]` — Case Detail

**URL:** `/cases/[id]`
**Auth required:** All authenticated (own-case restriction for underwriter/ai_analyser)

**Page structure:** RSC shell fetches `GET /api/proxy/cases/{id}` on load. Returns `CaseRead` with
artifacts. Child components mount as Client Components for tabs and polling.

**Header section** (always visible above tabs):
- Loan ID (large, monospace)
- Applicant name
- `<StageBadge stage={current_stage} />`
- Actions bar (role-gated buttons): "Download ZIP", "Re-upload", "Add Artifact", "Reingest"
  (admin), "Delete" (admin)

**Tabs:** Overview | Artifacts | Extractions | Checklist | Dedupe | Audit Log

---

#### Tab: Overview

Fields displayed in a two-column grid:
- Case ID (UUID)
- Stage (badge)
- Uploaded by (full name)
- Uploaded at / Finalized at
- Assigned to (if set)
- Re-upload count
- Re-upload allowed until (if set)
- Is deleted (admin-visible, shown as warning banner)

**Stage transition log:** Timeline of past stages derived from the Audit Log filtered to
`entity_type=case` + `action` matching `case.stage_transition.*`. Shows: stage name, actor, time.
Fetched from `GET /api/proxy/cases/{id}` audit log sub-resource (if implemented as part of M4;
fallback: show last known stage + uploaded_at).

---

#### Tab: Artifacts

`<CaseArtifactGrid artifacts={case.artifacts} />`

Grid of cards, 3 columns, each card shows:
- Filename
- `ArtifactType` badge
- Size (human readable)
- Uploaded at
- Download button (calls presigned `download_url` from `CaseArtifactRead`)

Empty state: "No artifacts yet."

---

#### Tab: Extractions

`<ExtractionPanel caseId={id} />`

Fetches `GET /api/proxy/cases/{id}/extractions` on mount.

Grouped by `extractor_name`. Five extractor groups:

| Extractor key | Display label |
|---|---|
| `auto_cam` | Auto CAM |
| `checklist` | Checklist |
| `pd_sheet` | PD Sheet |
| `equifax` | Equifax |
| `bank_statement` | Bank Statement |

Each group renders as a collapsible `<Accordion.Item>`:
- Header: extractor label + `ExtractionStatus` badge (SUCCESS=green, PARTIAL=yellow, FAILED=red) +
  timestamp
- Body: two-pane display:
  - Left pane: friendly key-value table for known fields (rendered by extractor-specific component)
  - Right pane: raw JSON viewer (collapsible, monospace, syntax highlighted)
- If `warnings` array is non-empty: amber warning box listing warnings
- If `status=FAILED`: red error box with `error_message`

If no extractions exist yet: "Extractions not yet available — case is still in ingestion."

**Polling:** If `current_stage ∈ IN_FLIGHT_STAGES` (see §10.2; includes `CHECKLIST_VALIDATION` and
`CHECKLIST_MISSING_DOCS`), SWR polls every 5s. Polling stops when stage moves to
`CHECKLIST_VALIDATED` or `INGESTED`.

---

#### Tab: Checklist

`<ChecklistMatrix caseId={id} />`

Fetches `GET /api/proxy/cases/{id}/checklist-validation`.

Renders `ChecklistValidationResultRead`:
- Top banner: "Complete" (green) or "Incomplete — {N} documents missing" (red)
- `present_docs` list: green checkmark rows, showing `doc_type` and linked artifact name
- `missing_docs` list: red X rows, showing `doc_type` and `reason`
- Validated at timestamp

If no result yet: skeleton loader with "Checklist validation in progress..."

---

#### Tab: Dedupe

`<DedupeMatchTable caseId={id} />`

Fetches `GET /api/proxy/cases/{id}/dedupe-matches`.

Table columns:

| Column | Field |
|---|---|
| Match type | `match_type` (AADHAAR / PAN / MOBILE / DOB_NAME) |
| Score | `match_score` (0.0–1.0, rendered as percentage) |
| Customer ID | `matched_customer_id` |
| Details | Expandable row: `matched_details_json` rendered as key-value |
| Snapshot | `snapshot_id` (linked to `/admin/dedupe-snapshots` for admin) |
| Matched at | `created_at` |

If no matches: "No dedupe matches found for this case."
If `match_type=AADHAAR` or `PAN` (exact match, score=1.0): row highlighted red (high risk).
If `match_type=DOB_NAME` (fuzzy): row highlighted yellow.

---

#### Tab: Audit Log

Reads from the case audit log via `GET /api/proxy/cases/{id}/audit-log` (a new backend endpoint
added in §18). No global audit-log endpoint is exposed in M4.

Timeline format: vertical list, newest first. Each entry:
- Action (e.g., `case.stage_transition.UPLOADED→CHECKLIST_VALIDATION`)
- Actor name (resolved from user_id)
- Timestamp
- Before/after JSON (collapsible, admin only)

### 6.5 `/cases/[id]/reupload`

**URL:** `/cases/[id]/reupload`
**Auth required:** ai_analyser (own), admin

Flow:
1. Admin must first `POST /cases/{id}/approve-reupload` with a reason. This is surfaced as a
   modal on the case detail page (admin-only "Approve Re-upload" button in the actions bar). The
   modal has a "Reason" textarea (min 10 chars, max 500).
2. After approval (or if `reupload_allowed_until` is still in the future for this case), the
   uploader navigates to this page.
3. Page renders the same upload wizard as `/cases/new` Steps 2–3, but pre-filled with the
   `case_id`. Step 1 is skipped (loan_id is already known).
4. On finalize: `POST /cases/{id}/finalize` as usual; the backend handles REUPLOAD_ARCHIVE
   artifact type automatically.

### 6.6 `/cases/[id]/reingest`

**URL:** `/cases/[id]/reingest`
**Auth required:** admin only

This is not a full page — it is an action button + confirm dialog on the case detail page's
actions bar.

- Button "Reingest" is shown only to admin when `current_stage ∈ { INGESTED, CHECKLIST_VALIDATED,
  CHECKLIST_MISSING_DOCS }`.
- On click: `<Dialog>` confirm modal: "This will re-run the full ingestion pipeline for this case.
  Existing extractions will be overwritten. Continue?"
- On confirm → `POST /api/proxy/cases/{id}/reingest`.
- Optimistic update: immediately set stage badge to `CHECKLIST_VALIDATION` in local SWR cache.
- Actual stage update arrives via polling within 5s.
- On 409 (wrong stage): toast "Cannot reingest — case is in {stage}."

### 6.7 `/cases/[id]/add-artifact`

**URL:** `/cases/[id]/add-artifact`
**Auth required:** ai_analyser (own), admin

Modal or page (implemented as a modal on the case detail Artifacts tab, with a dedicated URL for
direct linking).

Fields:
- File picker (single file, any type, max 50 MB)
- Artifact type selector (`<Select>` with `ArtifactType` values; default `ADDITIONAL_FILE`)

On submit → multipart `POST /api/proxy/cases/{id}/artifacts` with `file` + `artifact_type` form
fields.

On success: toast "Artifact uploaded. If case was awaiting documents, ingestion will re-run
automatically." SWR cache for `/cases/{id}` is mutated.

### 6.8 `/admin/dedupe-snapshots`

**URL:** `/admin/dedupe-snapshots`
**Auth required:** admin (upload); admin + ceo + credit_ho (read)

**List view:**
Fetches `GET /api/proxy/dedupe-snapshots`. Table columns:

| Column | Field |
|---|---|
| Uploaded at | `uploaded_at` |
| Uploaded by | `uploaded_by` (resolved to name) |
| Row count | `row_count` |
| Active | `is_active` (green badge or —) |
| Download | Link using `download_url` |

Active snapshot shown at the top with highlighted row.

> **Note:** The `download_url` on each snapshot is a presigned URL expiring in 900s. Do not cache
> it across navigation; re-query the list endpoint when the user returns to this page.

**Upload form (admin only):**
Placed above the table. File picker (`.xlsx` only, max 50 MB). "Upload New Snapshot" button.
On submit → `POST /api/proxy/dedupe-snapshots` as multipart form.
On success: toast "New snapshot uploaded and activated. Previous snapshot deactivated." SWR cache
mutated.
On file too large (413): "File exceeds 50 MB limit."
On invalid xlsx (400): "Invalid xlsx file: {error message from backend}."

### 6.9 `/admin/users`

**URL:** `/admin/users`
**Auth required:** admin only

**User list:**
Fetches `GET /api/proxy/users`. Table columns:

| Column | Field |
|---|---|
| Name | `full_name` |
| Email | `email` |
| Role | `role` (badge, color per role) |
| MFA | `mfa_enabled` (boolean badge) |
| Active | `is_active` (green/red badge) |
| Last login | `last_login_at` (relative time) |
| Actions | Edit role / Reset password / Activate-Deactivate |

**Create user form:** Button "Add User" → slide-over panel with fields:
- Full name (required)
- Email (required)
- Password (required, complexity rules)
- Role (Select)

On submit → `POST /api/proxy/users`. On 409 (duplicate email): inline error.

**Role update:** Inline `<Select>` in the role column. On change → `PATCH /api/proxy/users/{id}/role`.

**Activate / Deactivate (closes M1-I2):**
Each row has an Activate/Deactivate toggle. On click → `PATCH /api/proxy/users/{id}/active` with
`{ is_active: true/false }`. This endpoint is added to the backend in M4 scope (it was deferred
from M2). Implementation: same pattern as role update — `require_role(ADMIN)`, audit log entry
`user.deactivated` or `user.reactivated`, return `UserRead`.

**Password reset:** "Reset Password" button → modal with `new_password` field. On submit →
`POST /api/proxy/users/{id}/password`.

### 6.10 `/settings/profile`

**URL:** `/settings/profile`
**Auth required:** All authenticated

Fetches `GET /api/proxy/users/me`.

Sections:
1. **Profile info:** Full name, email, role (read-only display). No edit in M4 (name edit deferred).
2. **Change password:** New password, confirm new password. M4 uses the existing 1-field
   `PasswordChange` schema (`{new_password: str}`). A `current_password` field may be added in a
   future milestone (security-review finding from M1 — tracked in FOLLOW_UPS.md). On submit →
   `POST /api/proxy/users/me/password`.
3. **MFA:** Shows status (enabled/disabled). "Enable MFA" button → inline enroll/verify flow
   (§5.2). If MFA required by role: "Required for your role. Cannot be disabled."
4. **Dark mode:** Toggle. Persisted to localStorage; applied via `class="dark"` on `<html>`.

### 6.11 Error States and Global UI

**Error pages:**
- `app/not-found.tsx` — 404: "Page not found" with back button
- `app/error.tsx` — 500: "Something went wrong" with retry button and error boundary
- 403 handling: `useAuth` intercepts 403 responses, shows toast "You don't have permission for
  this action" and does not redirect

**Loading skeletons:**
- Case list: `<Skeleton>` rows × 10 while SWR is loading initial data
- Case detail: `<Skeleton>` for header + three tab panels
- Extraction panel: `<Skeleton>` accordions

**Empty states:**
- Case list (no results matching filters): "No cases match your filters. Try adjusting the search."
- Extractions (not yet run): "Extractions not yet available — case is still being ingested."
- Dedupe (no matches): "No dedupe matches — this is a new customer."

**Toast notifications:** SonnerToast (or shadcn's `<Sonner>`) anchored bottom-right. Auto-dismiss
after 5s. Error toasts persist until dismissed.

---

## 7. Component Library

### 7.1 shadcn/ui primitives used

`Button`, `Input`, `Card`, `CardHeader`, `CardContent`, `Dialog`, `Tabs`, `TabsList`,
`TabsTrigger`, `TabsContent`, `Badge`, `Sonner` (toast), `Table`, `TableHeader`, `TableRow`,
`TableCell`, `Skeleton`, `Form`, `FormField`, `FormItem`, `FormLabel`, `FormMessage`, `Select`,
`SelectContent`, `SelectItem`, `Accordion`, `AccordionItem`, `AccordionTrigger`,
`AccordionContent`, `Sheet` (slide-over panel), `Alert`, `AlertTitle`, `AlertDescription`.

All installed via `npx shadcn-ui@latest add <component>`.

### 7.2 Custom components

| Component | Location | Purpose |
|---|---|---|
| `StageBadge` | `components/custom/StageBadge.tsx` | Renders `CaseStage` as a colored `<Badge>`. Color map: UPLOADED=slate, CHECKLIST_VALIDATION=blue-pulse, CHECKLIST_MISSING_DOCS=red, CHECKLIST_VALIDATED=green, INGESTED=teal, PHASE_1_*=purple, PHASE_2_*=indigo, HUMAN_REVIEW=amber, APPROVED=emerald, REJECTED=red, ESCALATED_TO_CEO=orange |
| `CaseArtifactGrid` | `components/custom/CaseArtifactGrid.tsx` | Card grid of artifacts with download links |
| `ExtractionPanel` | `components/custom/ExtractionPanel.tsx` | Accordion of extractor groups; per-extractor friendly renderers |
| `ChecklistMatrix` | `components/custom/ChecklistMatrix.tsx` | Present/missing doc table with color coding |
| `DedupeMatchTable` | `components/custom/DedupeMatchTable.tsx` | Expandable dedupe match rows with risk coloring |
| `UploadDropzone` | `components/custom/UploadDropzone.tsx` | Drag-and-drop ZIP upload with progress bar |
| `ConfirmDialog` | `components/custom/ConfirmDialog.tsx` | Reusable confirm/cancel modal |
| `RoleBadge` | `components/custom/RoleBadge.tsx` | User role as colored `<Badge>` |
| `AuditTimeline` | `components/custom/AuditTimeline.tsx` | Vertical timeline for audit log entries |

---

## 8. Routing and Middleware

### 8.1 `middleware.ts`

Runs on every request except `/_next/*`, `/favicon.ico`, and `/login`.

Logic:

```
1. Read access token from auth context (not possible in Edge; use cookie flag instead):
   - Check for presence of `pfl_auth` cookie (non-HttpOnly session flag set by Route Handler
     on successful login; value = "1"; used only as a hint, not a secret).
   - If absent → redirect to /login?next={pathname}.
2. If pfl_auth present → allow through (actual token validation happens in the proxy).
3. Seed CSRF token cookie if not present (see §5.5).
```

**Cache:** The middleware does NOT call `/users/me` on every request (too slow; adds latency to
every page load). Instead, the Route Handler proxy intercepts 401 responses from the backend and
forces a re-login. The `pfl_auth` cookie is cleared on logout.

**Role-based route protection:** Enforced primarily by the backend (403 responses). The frontend
additionally checks `user.role` from `useAuth()` in page components and shows a 403 page or
redirects to `/cases` if the user navigates to an admin-only URL without the admin role.

### 8.2 Route Handler proxy

`app/api/proxy/[...path]/route.ts`

```
For every HTTP method:
1. Read path + query from Next.js request.
2. Read Authorization: Bearer {accessToken} from in-memory store (server-side).
3. Forward request to BACKEND_INTERNAL_URL/{path}?{query} with:
   - Authorization header
   - Original Content-Type
   - Body (for POST/PATCH/PUT) streamed through
4. On 401 from backend:
   a. Call POST /auth/refresh with cookie (browser's cookie is forwarded via Next.js
      cookies() API on the server side for SSR; for client Route Handler calls, use
      the cookie jar from the incoming request).
      *This proxy behavior depends on the §18 backend patch that changes `POST /auth/refresh`
      to read the refresh token from the HttpOnly cookie instead of the JSON body. That backend
      change is an M4 prerequisite task; until it lands, the proxy must JSON-encode the cookie
      value into the body.*
   b. Store new access token in-memory.
   c. Retry original request once.
   d. If still 401: clear pfl_auth cookie, return 401 to client → client redirects to /login.
5. Copy response body + status + headers (including Set-Cookie for refresh) to client.
```

The proxy handles multipart forms by streaming the request body directly.

---

## 9. API Client

### 9.1 Access token in-memory strategy

The access token (JWT, short-lived, ~1h) is never written to storage. It lives in:
- **Server side (Route Handlers):** A module-level variable in `lib/server-auth.ts` that is
  populated on login and refreshed on 401. Node.js module scope persists across requests within
  the same process.
- **Client side:** `useAuth()` React Context stores the token in a `useRef` (not state, so it does
  not trigger re-renders) and exposes it to the proxy calls.

> **⚠️ Single-process constraint:** The module-level refresh mutex and cached access token work
> only in single-process deployments (one Next.js instance). M8 AWS deploy must either (a) deploy
> Next.js as a single ECS task (simplest) or (b) externalize token storage to Redis. Flag for M8
> planning.

Because all API calls go through `/api/proxy/*` Route Handlers (server-side), the access token
is not exposed to client JS at all in the nominal flow. The `useAuth()` context stores minimal
user metadata (id, email, role, mfa_enabled) for UI rendering, not the raw token.

### 9.2 `useAuth()` hook

```ts
// Exposes:
interface AuthContext {
  user: UserRead | null
  isLoading: boolean
  login: (email: string, password: string, mfaCode?: string) => Promise<LoginResult>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>  // re-fetches /users/me
}
```

On mount, `AuthProvider` calls `GET /api/proxy/users/me`. If 401: user is null. If 200: user
is populated.

### 9.3 Silent refresh mutex

> **⚠️ Single-process constraint:** This mutex is per-process. See §9.1 warning — it does not
> coordinate across multiple Next.js instances. M8 must address this before horizontal scaling.

When multiple concurrent requests receive a 401:
- The proxy uses a per-process `Promise` reference as a mutex.
- First 401 triggers `refresh()` and stores the in-flight promise.
- Subsequent 401s await the existing promise.
- After refresh, all pending requests are retried.

```ts
// Pseudo-code in lib/server-auth.ts
let refreshPromise: Promise<string> | null = null

async function getAccessToken(): Promise<string> {
  if (isExpired(currentToken)) {
    if (!refreshPromise) {
      refreshPromise = doRefresh().finally(() => { refreshPromise = null })
    }
    return refreshPromise
  }
  return currentToken
}
```

### 9.4 Typed API client

`lib/api.ts` — thin wrapper over `fetch('/api/proxy/...')` with typed return types matching
backend schemas:

```ts
api.cases.list(params: CaseListParams): Promise<CaseListResponse>
api.cases.get(id: string): Promise<CaseRead>
api.cases.initiate(body: CaseInitiateRequest): Promise<CaseInitiateResponse>
api.cases.finalize(id: string): Promise<CaseRead>
api.cases.addArtifact(id: string, file: File, type: ArtifactType): Promise<CaseArtifactRead>
api.cases.approveReupload(id: string, reason: string): Promise<CaseRead>
api.cases.reingest(id: string): Promise<{ detail: string }>
api.cases.delete(id: string): Promise<void>
api.cases.extractions(id: string): Promise<CaseExtractionRead[]>
api.cases.checklistValidation(id: string): Promise<ChecklistValidationResultRead>
api.cases.dedupeMatches(id: string): Promise<DedupeMatchRead[]>
api.users.list(): Promise<UserRead[]>
api.users.me(): Promise<UserRead>
api.users.create(body: UserCreate): Promise<UserRead>
api.users.updateRole(id: string, role: UserRole): Promise<UserRead>
api.users.setActive(id: string, isActive: boolean): Promise<UserRead>
api.users.resetPassword(id: string, newPassword: string): Promise<UserRead>
api.dedupeSnapshots.list(): Promise<DedupeSnapshotRead[]>
api.dedupeSnapshots.upload(file: File): Promise<DedupeSnapshotRead>
api.auth.login(body: LoginRequest): Promise<LoginResponse>          // POST /auth/login
api.auth.logout(): Promise<void>                                      // POST /auth/logout
api.auth.mfaEnroll(): Promise<MFAEnrollResponse>
api.auth.mfaVerify(code: string): Promise<{ mfa_enabled: boolean }>
```

---

## 10. State Management

### 10.1 Auth state

`AuthProvider` (React Context) wraps the entire `(app)` layout. Provides `useAuth()` hook.
Stores: `user: UserRead | null`, `isLoading: boolean`. No access token in context (kept server-side
only).

### 10.2 Server data — SWR

All data fetching uses SWR. Key constants in `lib/swr-keys.ts`:

```ts
SWR_KEYS = {
  caseList: (params) => ['/cases', params],
  case: (id) => `/cases/${id}`,
  extractions: (id) => `/cases/${id}/extractions`,
  checklistValidation: (id) => `/cases/${id}/checklist-validation`,
  dedupeMatches: (id) => `/cases/${id}/dedupe-matches`,
  users: '/users',
  me: '/users/me',
  dedupeSnapshots: '/dedupe-snapshots',
}
```

Staleness policy:

| Data | `revalidateOnFocus` | `refreshInterval` | Rationale |
|---|---|---|---|
| Case list | true | 10000ms | Team members upload; list should stay current |
| Case detail (stable stage) | true | 0 (no auto-poll) | No need to poll a finished case |
| Case detail (in-flight stage) | true | 5000ms | Poll while CHECKLIST_VALIDATION or CHECKLIST_MISSING_DOCS in progress |
| Extractions (in-flight) | true | 5000ms | Same — wait for worker |
| Users list | true | 0 | Rarely changes |
| Dedupe snapshots | false | 0 | Rarely changes |

**In-flight detection:** After fetching `CaseRead`, check `IN_FLIGHT_STAGES`:
```ts
const IN_FLIGHT_STAGES = new Set([
  CaseStage.CHECKLIST_VALIDATION,
  CaseStage.CHECKLIST_MISSING_DOCS,  // Poll during MISSING_DOCS too — user uploading a missing doc
                                      // triggers an immediate pipeline re-run that we want to show
                                      // without a page refresh
  CaseStage.PHASE_1_DECISIONING,
  CaseStage.PHASE_2_AUDITING,
])
const pollInterval = IN_FLIGHT_STAGES.has(caseData?.current_stage) ? 5000 : 0
```

M4 encounters `CHECKLIST_VALIDATION` and `CHECKLIST_MISSING_DOCS` as in-flight stages. The set is
defined broadly for M5/M6 compatibility.

### 10.3 Mutations

SWR `mutate()` is called after every mutation to immediately update the local cache:
- `mutate(SWR_KEYS.case(id))` after artifact upload, stage change, reingest trigger
- `mutate(SWR_KEYS.caseList(...))` after new case creation or deletion

---

## 11. Realtime Refresh

M4 uses polling only. WebSockets are deferred to v2.

**Polling lifecycle for case detail:**
1. Page mounts; SWR fetches case. `refreshInterval` computed from stage.
2. While `current_stage` is in `IN_FLIGHT_STAGES`: SWR polls every 5s.
3. Each poll response: if stage changed out of in-flight set, `refreshInterval` drops to 0.
4. User leaving the tab (`document.visibilityState === 'hidden'`): SWR's built-in
   `revalidateOnFocus=false` variant pauses polling.
5. On tab focus return: immediate revalidation.

**Polling lifecycle for case list:**
Fixed 10s interval while the page is mounted. No adaptive logic needed (list page is for
browsing, not monitoring a single job).

---

## 12. Validation and Enum Synchronization

### 12.1 Form validation

react-hook-form + zod for all forms. Each form has a Zod schema in the same file as the form
component. Key schemas:

```ts
CaseInitiateSchema = z.object({
  loan_id: z.string().regex(/^[A-Za-z0-9-]{3,32}$/, 'Invalid Loan ID format'),
  applicant_name: z.string().max(255).optional(),
})

UserCreateSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(128).regex(
    /^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)/,
    'Password must contain uppercase, lowercase, and a digit'
  ),
  full_name: z.string().min(1).max(255),
  role: z.nativeEnum(UserRole),
})

LoginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(128),
  mfa_code: z.string().regex(/^\d{6}$/).optional(),
})
```

### 12.2 Enum synchronization strategy

**Decision: manual sync with a helper script.**

Rationale: the backend enums are simple `StrEnum` definitions (6 enums, 59 values total:
`ArtifactSubtype` 30, `CaseStage` 14, `UserRole` 5, `ArtifactType` 3, `ExtractionStatus` 3,
`DedupeMatchType` 4). An
OpenAPI code-gen pipeline would add significant build complexity for little gain at this stage.
Instead:

- `frontend/lib/enums.ts` is hand-maintained but mirrors `backend/app/enums.py` exactly.
- A helper script `frontend/scripts/sync-enums.ts` can be run by a developer to diff the current
  `enums.ts` against the backend Python file and print a warning if they diverge.
- The script uses `ts-node` to read `backend/app/enums.py` via Node `fs.readFileSync`, parses
  `StrEnum` classes with a regex, and compares against imported TypeScript enum keys.
- CI step (GitHub Actions): run `npm run sync-enums -- --check`; fail if diff detected.

This approach keeps the build pipeline simple while ensuring divergence is caught at CI time.

Current enums to mirror:

```ts
export enum UserRole {
  ADMIN = 'admin',
  CEO = 'ceo',
  CREDIT_HO = 'credit_ho',
  AI_ANALYSER = 'ai_analyser',
  UNDERWRITER = 'underwriter',
}

export enum CaseStage {
  UPLOADED = 'UPLOADED',
  CHECKLIST_VALIDATION = 'CHECKLIST_VALIDATION',
  CHECKLIST_MISSING_DOCS = 'CHECKLIST_MISSING_DOCS',
  CHECKLIST_VALIDATED = 'CHECKLIST_VALIDATED',
  INGESTED = 'INGESTED',
  PHASE_1_DECISIONING = 'PHASE_1_DECISIONING',
  PHASE_1_REJECTED = 'PHASE_1_REJECTED',
  PHASE_1_COMPLETE = 'PHASE_1_COMPLETE',
  PHASE_2_AUDITING = 'PHASE_2_AUDITING',
  PHASE_2_COMPLETE = 'PHASE_2_COMPLETE',
  HUMAN_REVIEW = 'HUMAN_REVIEW',
  APPROVED = 'APPROVED',
  REJECTED = 'REJECTED',
  ESCALATED_TO_CEO = 'ESCALATED_TO_CEO',
}

export enum ArtifactType {
  ORIGINAL_ZIP = 'ORIGINAL_ZIP',
  ADDITIONAL_FILE = 'ADDITIONAL_FILE',
  REUPLOAD_ARCHIVE = 'REUPLOAD_ARCHIVE',
}

export enum ArtifactSubtype { /* all 27 values from enums.py */ }
export enum ExtractionStatus { SUCCESS = 'SUCCESS', PARTIAL = 'PARTIAL', FAILED = 'FAILED' }
export enum DedupeMatchType { AADHAAR = 'AADHAAR', PAN = 'PAN', MOBILE = 'MOBILE', DOB_NAME = 'DOB_NAME' }
```

---

## 13. Styling

### 13.1 Tailwind configuration

```ts
// tailwind.config.ts
theme: {
  extend: {
    colors: {
      pfl: {
        blue:    '#1e3a8a',   // primary: headers, active nav, primary buttons
        bright:  '#3b82f6',   // interactive: hover states, links, focus rings
        amber:   '#f59e0b',   // warnings: missing docs, low-score badges
        slate:   '#6b7280',   // secondary text, subtle borders (Tailwind slate-500)
      }
    },
    fontFamily: {
      sans: ['Inter', 'system-ui', 'sans-serif'],
      mono: ['JetBrains Mono', 'Menlo', 'monospace'],
    }
  }
}
```

`Inter` loaded via `next/font/google` in `app/layout.tsx`.

### 13.2 Layout

Sidebar (240px, fixed left) + main content area. Sidebar content:
- PFL logo + "Credit AI" product name at top
- Navigation links (with active state highlight):
  - Cases (`/cases`)
  - Upload (`/cases/new`) — ai_analyser + admin only
  - Dedupe Snapshots (`/admin/dedupe-snapshots`) — admin + ceo + credit_ho
  - Users (`/admin/users`) — admin only
- Bottom: user avatar + name + "Settings" link + "Logout" button

Header bar: page title (breadcrumb) + dark mode toggle.

Responsive breakpoints: sidebar collapses to hamburger menu at `md` breakpoint (768px). No
further mobile optimization per parent spec §2.3.

### 13.3 Dark mode

Implemented via Tailwind's `darkMode: 'class'` strategy. Toggle in header and profile page.
Persisted to `localStorage` under key `pfl_theme`. On mount, read from localStorage and apply
`class="dark"` to `<html>` before hydration (via inline script in `<head>` to prevent FOUC).

---

## 14. Accessibility

- **Keyboard navigation:** All interactive elements reachable via Tab. Tab order follows document
  flow. Modal dialogs trap focus and return focus to trigger on close.
- **Focus visible:** `outline: 2px solid #3b82f6` (pfl-bright) on focus-visible. Never remove
  `outline: none` without a replacement.
- **Semantic HTML:** `<main>`, `<nav>`, `<header>`, `<section>`, `<article>` used appropriately.
  Tables use `<th scope="col">`. Form fields always have associated `<label>`.
- **ARIA:** Icon-only buttons have `aria-label`. Status badges have `role="status"` and
  `aria-live="polite"` when they update dynamically (stage badge on polling). Dialogs use
  `role="dialog"` + `aria-labelledby` + `aria-describedby` (shadcn Dialog provides these).
- **Color contrast:** All text meets WCAG AA (4.5:1 normal text, 3:1 large text). PFL blue
  `#1e3a8a` on white = 10.6:1 (exceeds AAA). Amber warning badges use dark text `#78350f` on
  amber `#fef3c7` = 4.8:1.
- **Error messages:** Always associated with their field via `aria-describedby`, not just color.

---

## 15. Testing Strategy

### 15.1 Playwright E2E (required for DoD)

File: `frontend/tests/e2e/smoke.spec.ts`

Scenario: login → create case → view case → logout

```
1. Navigate to /login
2. Fill email + password of a seeded ai_analyser test user
3. Assert redirect to /cases
4. Click "Upload" in sidebar → /cases/new
5. Fill loan_id="TEST-E2E-001", applicant_name="E2E Test Applicant"
6. Upload a fixture ZIP (test asset, committed to repo)
7. Click "Finalize Upload"
8. Assert redirect to /cases/{id}
9. Assert page contains "TEST-E2E-001"
10. Assert StageBadge shows "UPLOADED" or "CHECKLIST_VALIDATION"
11. Click Artifacts tab → assert artifact card for uploaded zip
12. Click logout → assert redirect to /login
```

Test infra: Playwright runs on the CI host (not inside Docker). `docker compose up -d` brings up
backend, worker, and LocalStack on `localhost:4566`. The backend presigns S3 POST URLs using
`endpoint_url=http://localhost:4566` (matching the host Playwright runs on). Backend env var
`AWS_S3_ENDPOINT_URL` is set to `http://localhost:4566` for the CI run. This works because
LocalStack maps its default port to the host.

### 15.2 Vitest unit/component tests

- `StageBadge.test.tsx` — all 14 stages render correct color class
- `ChecklistMatrix.test.tsx` — complete/incomplete states
- `DedupeMatchTable.test.tsx` — risk highlighting logic (AADHAAR/PAN = red, DOB_NAME = yellow)
- `api.ts` — mock proxy responses, assert correct URL construction and error handling
- `useAuth.test.tsx` — login flow, 401 handling, mutex refresh logic
- `enums.ts` — all enum values match expected strings (regression guard)

Coverage target: ≥ 80% on new frontend code.

### 15.3 Storybook

Deferred to M5. Storybook setup is included in the package.json devDependencies (commented out)
so it can be activated without a deps change.

---

## 16. Docker and Local Dev

### 16.1 New `pfl-web` service

```yaml
# docker-compose.yml addition
  web:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      target: dev            # multi-stage: 'dev' or 'prod'
    container_name: pfl-web
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_BASE_URL=http://localhost:8000   # for direct browser calls (not used by proxy)
      - BACKEND_INTERNAL_URL=http://backend:8000         # proxy server-to-server
      - APP_SECRET=dev-secret-change-in-prod  # Custom auth, not NextAuth.js — generic app-wide secret for CSRF token signing
      - NEXT_PUBLIC_APP_ENV=development
    depends_on:
      backend:
        condition: service_healthy
      localstack:
        condition: service_healthy
    volumes:
      - ./frontend:/app              # dev only: hot reload
      - /app/node_modules            # anonymous volume: don't mount host node_modules
    command: npm run dev             # override in prod target
```

### 16.2 Dockerfile

```dockerfile
# frontend/Dockerfile
FROM node:20-alpine AS base
WORKDIR /app
COPY package.json package-lock.json ./

FROM base AS deps
RUN npm ci

FROM deps AS dev
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

FROM deps AS builder
COPY . .
RUN npm run build

FROM node:20-alpine AS prod
WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
ENV NODE_ENV=production
CMD ["node", "server.js"]
```

Next.js `next.config.ts` must set `output: 'standalone'` for the prod stage.

### 16.3 Environment variables

| Variable | Set in | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | docker-compose, `.env.local` | Shown in UI for debug; not used by proxy |
| `BACKEND_INTERNAL_URL` | docker-compose, `.env.local` | Server-side proxy target |
| `APP_SECRET` | `.env.local`, AWS Secrets Manager | CSRF token signing, cookie signing (custom auth — not NextAuth.js) |
| `NEXT_PUBLIC_APP_ENV` | docker-compose | Feature flag gating |
| `COOKIE_SECURE` | prod env only | Set to `true` in prod; `false` in dev for HTTP |

`.env.local` is git-ignored. A `.env.local.example` is committed with placeholder values.

### 16.4 Health check

`GET /api/health` Route Handler returns `{ ok: true }`. docker-compose healthcheck:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:3000/api/health"]
  interval: 10s
  timeout: 5s
  retries: 3
```

---

## 17. Definition of Done

M4 is complete when all of the following pass:

- [ ] All 10 screens are rendered and functional end-to-end against the docker-compose stack
- [ ] HttpOnly cookie refresh token working:
  - `POST /auth/login` sets `refresh_token` HttpOnly cookie
  - `POST /auth/refresh` reads token from cookie, not request body
  - `POST /auth/logout` clears the cookie
  - M1-C1 item marked closed in FOLLOW_UPS.md
- [ ] User activate/deactivate:
  - `PATCH /users/{id}/active` endpoint shipped in backend (M1-I2 closed)
  - Toggle in `/admin/users` calls endpoint and updates row
- [ ] Self-service password change:
  - `POST /users/me/password` endpoint shipped in backend
  - Profile page form calls it successfully
- [ ] Enum sync CI check:
  - `npm run sync-enums -- --check` exits 0 when enums match
- [ ] Playwright E2E test: login → create case (with fixture ZIP) → view artifacts tab → logout
  runs green in CI
- [ ] docker-compose `docker compose up` brings up backend + worker + web; browsing to
  `http://localhost:3000` shows the login page
- [ ] Lighthouse CI scores ≥ 90 (Performance + Accessibility) for `/login` and `/cases`
- [ ] Vitest coverage ≥ 80% on frontend new code
- [ ] Ruff + mypy clean on backend (including the M4 backend patches for cookie auth + M1-I2)
- [ ] Tag `m4-frontend` created on merge commit

---

## 18. Backend Changes Required in M4

The following backend modifications are in-scope for M4 (they unblock the frontend):

| Change | Endpoint / File | Closes |
|---|---|---|
| Refresh token → HttpOnly cookie (`POST /auth/login` sets cookie; `POST /auth/refresh` reads from cookie — **required M4 prerequisite, not optional**; `POST /auth/logout` clears cookie) | `backend/app/api/routers/auth.py` | M1-C1 |
| User deactivate/reactivate | `PATCH /users/{user_id}/active` in `routers/users.py` + `services/users.py`. Auth: `require_role(UserRole.ADMIN)`. Body: new `UserActiveUpdate` schema `{is_active: bool}`. Effect: updates `users.is_active`. Audit `user.deactivated` / `user.reactivated`. | M1-I2 |
| Self-service password change | Route: `POST /users/me/password`. Auth: `Depends(get_current_user)` — any authenticated user can change their own password. Body: existing `PasswordChange` schema (`{new_password: str}`). Effect: updates `current_user.password_hash`. Audit entry `user.password_changed_self`. | M4 need |
| CSRF token validation middleware | `backend/app/api/middleware.py` (optional: CSRF can be frontend-only) | M4 need |
| `list_cases_endpoint` injects `uploaded_by=current_user.id` for UNDERWRITER role | `backend/app/api/routers/cases.py` | M4 security hardening |
| `GET /cases/{id}/audit-log` — returns all `audit_log` rows where `entity_type='case'` and `entity_id=case_id`, ordered `at DESC`. Auth: any authenticated user (same policy as case read endpoints). Schema: `list[AuditLogRead]`. | `backend/app/api/routers/cases.py` | M4 need |

The audit-log sub-resource `GET /cases/{id}/audit-log` is a required M4 backend task (see table
above). The Audit Log tab depends on it; no fallback to a global audit-log endpoint is provided.

**Follow-up (FOLLOW_UPS.md):** The `PasswordChange` schema currently has only `new_password`. A
`current_password` field should be added in a future milestone to require the user to prove
knowledge of their existing password (security-review finding from M1). Track as M5 scope.

---

## 19. M3-F6 Authorization Review (Surface from FOLLOW_UPS.md)

M3-F6 noted that `GET /cases/{id}/extractions`, `GET /cases/{id}/checklist-validation`, and
`GET /cases/{id}/dedupe-matches` use `get_current_user` (any authenticated user) rather than
role-gated access. These endpoints expose derived PII (PAN matches, dedupe flags, Equifax data).

**M4 recommendation:** Tighten these to `require_role(AI_ANALYSER, UNDERWRITER, CREDIT_HO, CEO, ADMIN)`
— effectively all roles except none (all existing roles are in this set anyway), but this makes
the intent explicit and future-proofs against adding a guest/read-only role later. The frontend
already only shows these tabs to authenticated users; the backend change is a one-line update per
endpoint. Include this as part of the M4 backend changes.

---

## 20. Cross-Reference to Parent and Prior Milestone Specs

| Parent spec section | How M4 implements it |
|---|---|
| §3.1 Roles | Role-gated screens (§3 matrix above) |
| §3.3 Authentication | Auth flow §5; HttpOnly cookie §5.3 closes M1-C1 |
| §4.1 Next.js web app responsibility | All screens in §6 |
| §8 Audit log | Audit Log tab on case detail §6.4 |
| §9 Workflow stages | `StageBadge` covering all 14 stages; polling for in-flight §11 |
| §18 Appendix C tech stack | Next.js 14, RSC, Tailwind, shadcn/ui per §4 and §13 |
| §19 Appendix D PFL branding | Color palette §13.1 |
| M2 case endpoints | `api.ts` client covers all M2 endpoints |
| M3 extraction/checklist/dedupe endpoints | Extractions, Checklist, Dedupe tabs in §6.4 |
| FOLLOW_UPS M1-C1 | Closed by §5.3 + §18 backend changes |
| FOLLOW_UPS M1-I2 | Closed by §6.9 + §18 backend changes |
| FOLLOW_UPS M3-F6 | Surfaced in §19; tightened in M4 backend pass |

---

*End of M4 spec. Next step: spec review → writing-plans skill to produce the implementation plan.*
