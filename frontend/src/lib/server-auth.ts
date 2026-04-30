/**
 * Server-side access-token store.
 *
 * Module-level singleton — single-flight refresh mutex prevents stampede.
 *
 * NOTE (spec §9.1): This is intentionally in-process only. In a multi-instance
 * deployment each process holds its own token; token sharing would require an
 * external store (Redis, etc.). Acceptable for M4; revisit in M8.
 */

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.BACKEND_INTERNAL_URL || 'http://backend:8000'

let _accessToken: string | null = null
let _refreshPromise: Promise<{ token: string; setCookies: string[] } | null> | null = null

export function getAccessToken(): string | null {
  return _accessToken
}

export function setAccessToken(tok: string | null): void {
  _accessToken = tok
}

/**
 * Single-flight refresh.
 *
 * Returns `{ token, setCookies }` so the proxy can forward Set-Cookie headers
 * from the refresh response back to the browser, keeping the HttpOnly refresh
 * cookie in sync.
 */
export async function refreshAccessToken(
  cookieHeader: string,
): Promise<{ token: string; setCookies: string[] } | null> {
  // If a refresh is already in progress, piggyback on it.
  if (_refreshPromise) return _refreshPromise

  _refreshPromise = (async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/auth/refresh`, {
        method: 'POST',
        headers: { cookie: cookieHeader, 'content-type': 'application/json' },
        body: '{}',
      })

      if (!res.ok) {
        _accessToken = null
        return null
      }

      const data = await res.json()
      const token: string = data.access_token || null
      _accessToken = token

      // Collect Set-Cookie headers to forward to the browser.
      const setCookies: string[] = []
      res.headers.forEach((value, name) => {
        if (name.toLowerCase() === 'set-cookie') {
          setCookies.push(value)
        }
      })

      if (!token) {
        _accessToken = null
        return null
      }

      return { token, setCookies }
    } catch {
      _accessToken = null
      return null
    }
  })()

  try {
    return await _refreshPromise
  } finally {
    _refreshPromise = null
  }
}
