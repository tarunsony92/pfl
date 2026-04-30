/**
 * E2E tests — Authentication flow
 *
 * Prerequisites (see e2e/README.md):
 *   1. Backend running at http://localhost:8000
 *   2. Seed admin user exists: admin@pfl.com / Admin123!
 *
 * The beforeAll block performs a lightweight probe against the login API
 * and skips the entire suite if the backend is unreachable or the seed user
 * does not exist — so CI passes even when the backend is not wired up.
 */

import { test, expect } from '@playwright/test'
import { TEST_USER, loginViaUI } from './fixtures/auth'

// ---------------------------------------------------------------------------
// Skip guard — probe backend before running any tests
// ---------------------------------------------------------------------------

test.beforeAll(async ({ request }) => {
  let reachable = false
  try {
    const resp = await request.post('/api/proxy/auth/login', {
      data: { email: TEST_USER.email, password: TEST_USER.password },
      timeout: 5_000,
    })
    // 200 = success, 401 = bad creds, 422 = validation error
    // Any response from the backend means it is reachable
    reachable = resp.status() !== 502 && resp.status() !== 503 && resp.status() !== 0
    if (resp.status() === 401) {
      // Backend reachable but seed user absent
      test.skip(
        true,
        'Seed admin user not found (401). Run: cd backend && poetry run python -m app.cli seed-admin --email admin@pfl.com --password Admin123! --full-name "E2E Admin"',
      )
    }
  } catch {
    reachable = false
  }

  if (!reachable) {
    test.skip(true, 'Backend not reachable at http://localhost:8000 — skipping E2E suite')
  }
})

// ---------------------------------------------------------------------------
// Test 1: Unauthenticated redirect
// ---------------------------------------------------------------------------

test('unauthenticated user is redirected to /login', async ({ page }) => {
  await page.goto('/cases')
  // Middleware should redirect with ?from=%2Fcases
  await expect(page).toHaveURL(/\/login\?from=%2Fcases/, { timeout: 10_000 })
})

// ---------------------------------------------------------------------------
// Test 2: Invalid login shows error
// ---------------------------------------------------------------------------

test('invalid login shows error', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email address').fill('notauser@pfl.com')
  await page.getByLabel('Password').fill('wrongpassword')
  await page.getByRole('button', { name: /sign in/i }).click()

  // Error banner has role="alert" — wait for it to appear
  const errorAlert = page.getByRole('alert')
  await expect(errorAlert).toBeVisible({ timeout: 10_000 })

  // Should still be on /login (no redirect)
  await expect(page).toHaveURL(/\/login/)
})

// ---------------------------------------------------------------------------
// Test 3: Happy path — login → cases list → logout → back to /login
// ---------------------------------------------------------------------------

test('happy path: login → cases list renders → logout → back to /login', async ({
  page,
}) => {
  // 1. Log in via UI helper
  await loginViaUI(page)

  // 2. Cases list should be visible — page heading "Cases"
  await expect(page.getByRole('heading', { name: /cases/i })).toBeVisible({
    timeout: 10_000,
  })

  // 3. Open the user dropdown and click Logout
  await page.getByRole('button', { name: /user menu/i }).click()
  await page.getByRole('menuitem', { name: /logout/i }).click()

  // 4. Should redirect back to /login
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 })
})
