import { test as base, type Page } from '@playwright/test'

// ---------------------------------------------------------------------------
// Test credentials — seeded via `poetry run python -m app.cli seed-admin`
// ---------------------------------------------------------------------------

export const TEST_USER = {
  email: 'admin@pfl.com',
  password: 'Admin123!',
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Log in via the UI (fills the sign-in form, submits, waits for /cases).
 * Returns the authenticated page.
 */
export async function loginViaUI(page: Page): Promise<Page> {
  await page.goto('/login')
  await page.getByLabel('Email address').fill(TEST_USER.email)
  await page.getByLabel('Password').fill(TEST_USER.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  // Wait until we land on the cases list (redirect after login)
  await page.waitForURL(/\/cases/, { timeout: 15_000 })
  return page
}

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

type AuthFixtures = {
  /** A page already authenticated as the seed admin. */
  authenticatedPage: Page
}

/**
 * Extend Playwright's base `test` with an `authenticatedPage` fixture.
 *
 * Usage:
 *   import { test } from './fixtures/auth'
 *   test('my test', async ({ authenticatedPage }) => { ... })
 */
export const test = base.extend<AuthFixtures>({
  authenticatedPage: async ({ page }, use) => {
    await loginViaUI(page)
    await use(page)
  },
})

export { expect } from '@playwright/test'
