import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { httpGet, httpPost, HTTPError } from '../http'

// ---------------------------------------------------------------------------
// Mock global fetch
// ---------------------------------------------------------------------------

const mockFetch = vi.fn()

// Vitest with jsdom provides globalThis.fetch but we replace it per-test
beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch)
})

afterEach(() => {
  vi.restoreAllMocks()
  mockFetch.mockReset()
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: async () => body,
  } as unknown as Response
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('httpGet — happy path', () => {
  it('returns parsed JSON body on 200', async () => {
    const data = { id: '123', name: 'Alice' }
    mockFetch.mockResolvedValueOnce(makeResponse(data))

    const result = await httpGet<typeof data>('/users/123')

    expect(result).toEqual(data)

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/users/123')
    expect(init.method).toBe('GET')
    expect(init.credentials).toBe('include')
  })
})

describe('httpPost — error handling', () => {
  it('throws HTTPError with status + detail on non-2xx', async () => {
    mockFetch.mockResolvedValueOnce(
      makeResponse({ detail: 'Unauthorized' }, 401),
    )

    await expect(httpPost('/auth/login', { email: 'x', password: 'y' })).rejects.toMatchObject({
      name: 'HTTPError',
      status: 401,
      detail: 'Unauthorized',
    })
  })

  it('throws HTTPError even when response body is not parseable JSON', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => { throw new SyntaxError('not json') },
    } as unknown as Response)

    let caught: HTTPError | undefined
    try {
      await httpPost('/some/endpoint', {})
    } catch (err) {
      caught = err as HTTPError
    }

    expect(caught).toBeInstanceOf(HTTPError)
    expect(caught?.status).toBe(500)
    // detail falls back to statusText when JSON parse fails
    expect(caught?.detail).toBe('Internal Server Error')
  })
})
