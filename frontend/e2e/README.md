# E2E Tests (Playwright)

End-to-end tests for the PFL Credit frontend, running against the real backend + LocalStack.

## Prerequisites

### 1. Backend running

Start the full stack with Docker Compose from the project root:

```bash
docker compose up -d
```

The backend API must be reachable at `http://localhost:8000`.

### 2. Seed the admin user

The E2E suite authenticates as a pre-seeded admin. Create it once:

```bash
cd backend && export PATH="$HOME/.local/bin:$PATH"
poetry run python -m app.cli seed-admin \
  --email admin@pfl.com \
  --password Admin123! \
  --full-name "E2E Admin"
```

> If you restart the database (volume removed) you must re-run this command.

### 3. Install Playwright browsers (one-time)

```bash
cd frontend
npx playwright install chromium
```

## Running tests

```bash
cd frontend

# Run all E2E tests (starts dev server automatically if not already running)
npx playwright test --reporter=line

# Or via package.json script
npm run test:e2e
```

If `http://localhost:3000` is already running (e.g., you started `npm run dev` in another terminal), Playwright reuses it (`reuseExistingServer: true`).

## Skip behaviour

The suite includes a `beforeAll` guard that probes `/api/proxy/auth/login`. If:

- The backend is **not reachable** — all tests are skipped with a message.
- The backend is reachable but the **seed user does not exist** (401) — all tests are skipped with a reminder to run the seed command.

This means the suite is safe to run in CI environments where the backend is not wired up.

## Test files

| File | Description |
|------|-------------|
| `auth.spec.ts` | Login redirect, invalid creds error, happy-path login/logout |
| `fixtures/auth.ts` | `authenticatedPage` fixture + `loginViaUI` helper |

## Reports

After a run, the HTML report is at `playwright-report/index.html`:

```bash
npx playwright show-report
```

> `playwright-report/`, `test-results/`, and `playwright/.cache/` are git-ignored.
