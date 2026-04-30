# PFL Credit AI — Accessibility Audit (M4)

Date: 2026-04-18
Auditor: Automated + manual review during M4 sprint

## Checklist

| # | Item | Location | Status | Notes |
|---|------|----------|--------|-------|
| 1 | Skip-to-content link targets `#main-content` | `(app)/layout.tsx` | PASS | Link present, `<main id="main-content">` set |
| 2 | `<main id="main-content">` landmark present | `(app)/layout.tsx` | PASS | Present with `tabIndex={-1}` |
| 3 | `aria-current="page"` on active nav link | `Sidebar.tsx` | PASS | Set conditionally based on pathname |
| 4 | Focus-visible ring on all interactive nav links | `Sidebar.tsx` | PASS | `focus-visible:ring-2 focus-visible:ring-pfl-blue-600` applied |
| 5 | All form labels use `<Label htmlFor>` + matching `id` | `ChangePasswordCard`, `NewUserDialog`, `Step1Details`, `ReuploadDialog`, `AddArtifactDialog` | PASS | Verified all form fields |
| 6 | `aria-invalid` on inputs with validation errors | `ChangePasswordCard`, `NewUserDialog`, `Step1Details`, `LoginPage` | PASS | Conditional `aria-invalid` on all form inputs |
| 7 | `aria-describedby` links inputs to error messages | `ChangePasswordCard`, `NewUserDialog`, `Step1Details` | PASS | Error `id` referenced via `aria-describedby` |
| 8 | Error messages have `role="alert"` | All form components | PASS | Error `<p>` elements have `role="alert"` |
| 9 | `aria-busy` on loading containers | `CaseDetailPage` loading state | PASS | Added `aria-busy="true"` + `aria-label` to skeleton wrapper |
| 10 | Icon-only buttons have `aria-label` | `Topbar` dropdown trigger, `UsersTable` role select | PASS | `aria-label="User menu"`, `aria-label="Change role for..."` |
| 11 | Decorative icons have `aria-hidden="true"` | All icon usages (lucide-react) | PASS | All icon components include `aria-hidden="true"` |
| 12 | Tabs use proper ARIA roles | All `<Tabs>` via Radix UI | PASS | Radix `@radix-ui/react-tabs` handles ARIA internally |
| 13 | Dialogs have focus trap + `aria-modal` | All `<Dialog>` via Radix UI | PASS | Radix `@radix-ui/react-dialog` handles this internally |
| 14 | Active toggle (users table) has `role="switch"` + `aria-checked` | `UsersTable.tsx` | PASS | `role="switch" aria-checked={user.is_active}` |
| 15 | Audit diff button has `aria-expanded` + `aria-label` | `AuditLogTimeline.tsx` | PASS | Added `aria-label` in M4; `aria-expanded` already present |
| 16 | Extractions panel accordion has `aria-expanded` | `ExtractionsPanel.tsx` | PASS | Added `aria-expanded` + `aria-label` on raw JSON toggle in M4 |
| 17 | Progress bar has `role="progressbar"` + `aria-valuenow` | `Step2Upload.tsx` | PASS | `role="progressbar" aria-valuenow aria-valuemin aria-valuemax` set |
| 18 | Table `<th>` elements have `scope="col"` | `CaseTable`, `DedupeMatchTable` | PASS | Added `scope="col"` to all column headers in M4 |
| 19 | Error boundaries render meaningful messages | `app/error.tsx`, `(app)/error.tsx` | PASS | Both have `role="alert"` + try-again button |
| 20 | 404/403 pages have descriptive `<h1>` and home/back link | `app/not-found.tsx`, `app/forbidden/page.tsx` | PASS | Both have clear headings and navigation links |

## Summary

- PASS: 20 / 20
- FAIL: 0 / 20

## Notes

- Radix UI components (Dialog, Tabs, DropdownMenu, Toast) handle most ARIA patterns internally and are well-tested by the library.
- The `<Toaster>` is wired into `(app)/layout.tsx` so all authenticated screens benefit from toast notifications.
- All form flows use `react-hook-form` + Zod; error states are consistently announced via `role="alert"` + `aria-describedby`.
- Colour contrast: The design uses Tailwind utility classes with PFL custom palette. Primary interactive elements (blue buttons, links) rely on `pfl-blue-800` (#1e3a8a approximate) on white background — exceeds WCAG AA 4.5:1.
