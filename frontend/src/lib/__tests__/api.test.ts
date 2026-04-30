/**
 * Tests for api.ts typed client.
 *
 * Mocks http.ts so no real fetch calls are made.
 * Verifies that each api method calls the correct HTTP verb + path.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ---------------------------------------------------------------------------
// Mock http module
// ---------------------------------------------------------------------------

const mockHttpGet = vi.fn()
const mockHttpPost = vi.fn()
const mockHttpPatch = vi.fn()
const mockHttpDelete = vi.fn()

vi.mock('../http', () => ({
  httpGet: (...args: unknown[]) => mockHttpGet(...args),
  httpPost: (...args: unknown[]) => mockHttpPost(...args),
  httpPatch: (...args: unknown[]) => mockHttpPatch(...args),
  httpDelete: (...args: unknown[]) => mockHttpDelete(...args),
  HTTPError: class HTTPError extends Error {
    constructor(public status: number, public detail: string) {
      super(detail)
    }
  },
}))

import { auth, users, cases, dedupeSnapshots } from '../api'

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('api.auth', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHttpPost.mockResolvedValue({ access_token: 'tok', refresh_token: 'ref', token_type: 'bearer' })
  })

  it('login posts to /auth/login with email + password', async () => {
    await auth.login('user@example.com', 'secret')
    expect(mockHttpPost).toHaveBeenCalledWith('/auth/login', { email: 'user@example.com', password: 'secret', mfa_code: undefined })
  })

  it('login includes mfa_code when provided', async () => {
    await auth.login('user@example.com', 'secret', '123456')
    expect(mockHttpPost).toHaveBeenCalledWith('/auth/login', { email: 'user@example.com', password: 'secret', mfa_code: '123456' })
  })

  it('logout posts to /auth/logout', async () => {
    mockHttpPost.mockResolvedValue(undefined)
    await auth.logout()
    expect(mockHttpPost).toHaveBeenCalledWith('/auth/logout')
  })

  it('refresh posts to /auth/refresh', async () => {
    await auth.refresh()
    expect(mockHttpPost).toHaveBeenCalledWith('/auth/refresh')
  })
})

describe('api.users', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHttpGet.mockResolvedValue([])
    mockHttpPost.mockResolvedValue({ id: 'u1' })
    mockHttpPatch.mockResolvedValue({ id: 'u1' })
  })

  it('me calls GET /users/me', async () => {
    mockHttpGet.mockResolvedValue({ id: 'u1', email: 'a@b.com' })
    await users.me()
    expect(mockHttpGet).toHaveBeenCalledWith('/users/me')
  })

  it('list calls GET /users/', async () => {
    await users.list()
    expect(mockHttpGet).toHaveBeenCalledWith('/users/')
  })

  it('create posts to /users/ with payload', async () => {
    await users.create({ email: 'a@b.com', password: 'pw', full_name: 'Alice', role: 'admin' })
    expect(mockHttpPost).toHaveBeenCalledWith('/users/', { email: 'a@b.com', password: 'pw', full_name: 'Alice', role: 'admin' })
  })

  it('updateRole patches /users/:id/role', async () => {
    await users.updateRole('u1', 'admin')
    expect(mockHttpPatch).toHaveBeenCalledWith('/users/u1/role', { role: 'admin' })
  })

  it('updateActive patches /users/:id/active', async () => {
    await users.updateActive('u1', false)
    expect(mockHttpPatch).toHaveBeenCalledWith('/users/u1/active', { is_active: false })
  })

  it('changePasswordSelf patches /users/me/password', async () => {
    mockHttpPatch.mockResolvedValue(undefined)
    await users.changePasswordSelf('newpass123')
    expect(mockHttpPatch).toHaveBeenCalledWith('/users/me/password', { new_password: 'newpass123' })
  })
})

describe('api.cases', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHttpGet.mockResolvedValue({ cases: [], total: 0, limit: 10, offset: 0 })
    mockHttpPost.mockResolvedValue({ id: 'c1' })
    mockHttpDelete.mockResolvedValue(undefined)
  })

  it('list calls GET /cases', async () => {
    await cases.list()
    expect(mockHttpGet).toHaveBeenCalledWith('/cases', expect.objectContaining({ params: {} }))
  })

  it('list passes filters as params', async () => {
    await cases.list({ stage: 'INGESTED', limit: 5 })
    expect(mockHttpGet).toHaveBeenCalledWith('/cases', expect.objectContaining({ params: expect.objectContaining({ stage: 'INGESTED', limit: 5 }) }))
  })

  it('get calls GET /cases/:id', async () => {
    mockHttpGet.mockResolvedValue({ id: 'c1', loan_id: 'LOAN-001' })
    await cases.get('c1')
    expect(mockHttpGet).toHaveBeenCalledWith('/cases/c1')
  })

  it('reingest posts to /cases/:id/reingest', async () => {
    mockHttpPost.mockResolvedValue(undefined)
    await cases.reingest('c1')
    expect(mockHttpPost).toHaveBeenCalledWith('/cases/c1/reingest')
  })

  it('approveReupload posts to /cases/:id/approve-reupload', async () => {
    mockHttpPost.mockResolvedValue(undefined)
    await cases.approveReupload('c1', 'Docs unclear')
    expect(mockHttpPost).toHaveBeenCalledWith('/cases/c1/approve-reupload', { reason: 'Docs unclear' })
  })

  it('delete calls httpDelete /cases/:id', async () => {
    await cases.delete('c1')
    expect(mockHttpDelete).toHaveBeenCalledWith('/cases/c1')
  })

  it('extractions calls GET /cases/:id/extractions', async () => {
    mockHttpGet.mockResolvedValue([])
    await cases.extractions('c1')
    expect(mockHttpGet).toHaveBeenCalledWith('/cases/c1/extractions')
  })

  it('auditLog calls GET /cases/:id/audit-log', async () => {
    mockHttpGet.mockResolvedValue([])
    await cases.auditLog('c1')
    expect(mockHttpGet).toHaveBeenCalledWith('/cases/c1/audit-log')
  })

  it('dedupeMatches calls GET /cases/:id/dedupe-matches', async () => {
    mockHttpGet.mockResolvedValue([])
    await cases.dedupeMatches('c1')
    expect(mockHttpGet).toHaveBeenCalledWith('/cases/c1/dedupe-matches')
  })
})

describe('api.dedupeSnapshots', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHttpGet.mockResolvedValue([])
    mockHttpPost.mockResolvedValue({ id: 's1', row_count: 100 })
  })

  it('list calls GET /dedupe-snapshots/', async () => {
    await dedupeSnapshots.list()
    expect(mockHttpGet).toHaveBeenCalledWith('/dedupe-snapshots/')
  })

  it('active calls GET /dedupe-snapshots/active', async () => {
    mockHttpGet.mockResolvedValue(null)
    await dedupeSnapshots.active()
    expect(mockHttpGet).toHaveBeenCalledWith('/dedupe-snapshots/active')
  })
})
