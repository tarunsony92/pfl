# Follow-ups

Tracks deferred work surfaced during milestone implementations. Entries are tagged by milestone and a short slug (e.g. `M4-F2`).

## M4-F2: Backend MFA disable endpoint missing

`frontend/src/components/settings/MFACard.tsx` line ~74 has a stub Disable button that shows a toast rather than calling the backend, because no `DELETE`/`POST /auth/mfa/disable` endpoint exists in `backend/app/api/routers/auth.py`. This needs to be implemented in the backend before wiring up the frontend.
