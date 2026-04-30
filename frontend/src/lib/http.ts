/**
 * Thin fetch wrapper used by api.ts.
 *
 * Exports:
 *   httpGet<T>(path, opts?)
 *   httpPost<T>(path, body?, opts?)
 *   httpPatch<T>(path, body?, opts?)
 *   httpDelete<T>(path, opts?)
 *   httpPut<T>(path, body?, opts?)
 *
 * All requests are routed through the Next.js Route Handler proxy at
 * /api/proxy/* so that HttpOnly cookies remain opaque to client JS and
 * the server-side Bearer token is injected transparently.
 *
 * Throws HTTPError for non-2xx responses.
 */

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class HTTPError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly raw?: unknown,
  ) {
    super(`HTTP ${status}: ${detail}`)
    this.name = 'HTTPError'
  }
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

/**
 * Returns the base URL for all API calls.
 *
 * Client-side: always use the same origin so cookies are included
 *   automatically via `credentials: 'include'`.
 * Server-side (SSR/RSC): use NEXT_PUBLIC_SITE_URL if set, otherwise
 *   fall back to localhost (dev only; in production SSR calls should not
 *   happen through the proxy).
 */
function getBaseUrl(): string {
  if (typeof window !== 'undefined') {
    // Client-side: same-origin proxy
    return ''
  }
  // Server-side fallback (should rarely be reached; prefer direct backend calls)
  return process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000'
}

/** Proxy prefix prepended to every backend path. */
const PROXY_PREFIX = '/api/proxy'

/** Read CSRF token from cookie (for mutating requests). */
function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------

export interface RequestOptions extends Omit<RequestInit, 'body' | 'method'> {
  /** Override the base URL for this request. */
  baseUrl?: string
  /** Query parameters appended to the URL. */
  params?: Record<string, string | number | boolean | null | undefined>
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts: RequestOptions = {},
): Promise<T> {
  const { baseUrl, params, headers: extraHeaders, ...restOpts } = opts

  // Build URL — always route through /api/proxy so the server-side Route
  // Handler injects cookies + Bearer token.
  const base = (baseUrl ?? getBaseUrl()).replace(/\/$/, '')
  const proxyPath = `${PROXY_PREFIX}${path.startsWith('/') ? '' : '/'}${path}`
  const rawUrl = `${base}${proxyPath}`
  // Use URL constructor only if we have a full URL (has protocol), otherwise
  // treat as a relative path string and build the URLSearchParams manually.
  let url: URL | null = null
  try {
    url = new URL(rawUrl)
  } catch {
    // rawUrl is a relative path (client-side same-origin); create a dummy base
    // just so we can manipulate searchParams, then discard the base.
    url = new URL(rawUrl, 'http://localhost')
  }
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v != null) url.searchParams.set(k, String(v))
    }
  }

  // Build headers
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(extraHeaders as Record<string, string> | undefined),
  }

  if (body !== undefined && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }

  // Attach CSRF token for state-mutating methods.
  const mutating = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase())
  if (mutating) {
    const csrf = getCsrfToken()
    if (csrf) headers['X-CSRF-Token'] = csrf
  }

  // When base is empty (client same-origin), strip the dummy http://localhost
  // prefix so we send a relative URL to fetch(), which resolves against the
  // current page origin.
  const fetchUrl =
    base === ''
      ? url.pathname + (url.search || '')
      : url.toString()

  const response = await fetch(fetchUrl, {
    method,
    credentials: 'include',
    headers,
    body:
      body !== undefined
        ? body instanceof FormData
          ? body
          : JSON.stringify(body)
        : undefined,
    ...restOpts,
  })

  if (!response.ok) {
    let detail = response.statusText
    try {
      const errBody = (await response.json()) as { detail?: unknown }
      const raw = errBody?.detail
      if (typeof raw === 'string') {
        detail = raw
      } else if (Array.isArray(raw)) {
        // FastAPI / Pydantic validation error shape: list of {loc, msg, ...}
        detail = raw
          .map((e) => {
            if (e && typeof e === 'object' && 'msg' in e) {
              const loc = 'loc' in e && Array.isArray((e as { loc: unknown[] }).loc)
                ? (e as { loc: unknown[] }).loc.join('.')
                : undefined
              const msg = (e as { msg: unknown }).msg
              return loc ? `${loc}: ${msg}` : String(msg)
            }
            return JSON.stringify(e)
          })
          .join('; ')
      } else if (raw && typeof raw === 'object') {
        // Structured FastAPI detail (e.g. ``{reason, message,
        // pending_discrepancies}`` from ``start_phase1``). Prefer
        // ``message`` > ``detail`` > the whole dict so error toasts /
        // banners surface the human-readable string instead of a JSON blob
        // the user can't parse.
        const obj = raw as Record<string, unknown>
        if (typeof obj.message === 'string') {
          detail = obj.message
        } else if (typeof obj.detail === 'string') {
          detail = obj.detail
        } else {
          detail = JSON.stringify(raw)
        }
      } else if (raw !== undefined && raw !== null) {
        detail = String(raw)
      } else {
        detail = JSON.stringify(errBody)
      }
    } catch {
      // ignore parse failure — detail stays as statusText
    }
    throw new HTTPError(response.status, detail)
  }

  // 204 No Content
  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Public helpers
// ---------------------------------------------------------------------------

export function httpGet<T>(path: string, opts?: RequestOptions): Promise<T> {
  return request<T>('GET', path, undefined, opts)
}

export function httpPost<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
  return request<T>('POST', path, body, opts)
}

export function httpPatch<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
  return request<T>('PATCH', path, body, opts)
}

export function httpDelete<T>(path: string, opts?: RequestOptions): Promise<T> {
  return request<T>('DELETE', path, undefined, opts)
}

export function httpPut<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
  return request<T>('PUT', path, body, opts)
}
