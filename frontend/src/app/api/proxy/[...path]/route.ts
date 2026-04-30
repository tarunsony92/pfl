/**
 * Catch-all Route Handler proxy.
 *
 * Forwards every request to the backend under BACKEND_INTERNAL_URL,
 * injecting the browser's HttpOnly cookies + a server-side Bearer token.
 *
 * Special cases:
 *  - POST /auth/login  → stash returned access_token in server-side store
 *  - POST /auth/refresh → same
 *  - POST /auth/logout  → clear server-side store
 *  - 401 from backend  → attempt single-flight token refresh, then replay
 */

import type { NextRequest} from 'next/server';
import { NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import {
  getAccessToken,
  setAccessToken,
  refreshAccessToken,
} from '@/lib/server-auth'

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL!;

// Headers we must not forward to the backend.
const HOP_BY_HOP = new Set([
  'host',
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailers',
  'transfer-encoding',
  'upgrade',
])

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildCookieHeader(_req: NextRequest): string {
  const cookieStore = cookies()
  const refresh = cookieStore.get('refresh_token')?.value
  const csrf = cookieStore.get('csrf_token')?.value
  const parts: string[] = []
  if (refresh) parts.push(`refresh_token=${refresh}`)
  if (csrf) parts.push(`csrf_token=${csrf}`)
  return parts.join('; ')
}

function buildBackendHeaders(
  req: NextRequest,
  cookieHeader: string,
  accessToken: string | null,
): Record<string, string> {
  const headers: Record<string, string> = {}

  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      headers[key] = value
    }
  })

  // Override cookie with our composed value (refresh + csrf only).
  if (cookieHeader) {
    headers['cookie'] = cookieHeader
  }

  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`
  }

  return headers
}

async function proxyRequest(
  req: NextRequest,
  pathSegments: string[],
  accessToken: string | null,
  bodyBuffer: ArrayBuffer | undefined,
): Promise<Response> {
  const backendPath = pathSegments.join('/')
  const backendUrl = new URL(`${BACKEND_URL}/${backendPath}`)

  // Forward query string.
  req.nextUrl.searchParams.forEach((value, key) => {
    backendUrl.searchParams.set(key, value)
  })

  const cookieHeader = buildCookieHeader(req)
  const headers = buildBackendHeaders(req, cookieHeader, accessToken)

  const backendResponse = await fetch(backendUrl.toString(), {
    method: req.method,
    headers,
    body: bodyBuffer && bodyBuffer.byteLength > 0 ? bodyBuffer : undefined,
    // Do NOT follow redirects automatically — we return them to the client.
    redirect: 'manual',
  })

  return backendResponse
}

function buildClientResponse(
  backendResponse: Response,
  extraSetCookies: string[] = [],
): NextResponse {
  const response = new NextResponse(backendResponse.body, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
  })

  // Forward response headers (especially Set-Cookie).
  backendResponse.headers.forEach((value, key) => {
    if (key.toLowerCase() === 'set-cookie' || key.toLowerCase() === 'content-type') {
      response.headers.append(key, value)
    }
  })

  // Append any extra Set-Cookie headers from a token refresh.
  for (const sc of extraSetCookies) {
    response.headers.append('set-cookie', sc)
  }

  return response
}

// ---------------------------------------------------------------------------
// Route handler core
// ---------------------------------------------------------------------------

async function handle(
  req: NextRequest,
  { params }: { params: { path: string[] } },
): Promise<NextResponse> {
  try {
    const pathSegments = params.path ?? []
    const joinedPath = pathSegments.join('/')
    const method = req.method.toUpperCase()

    let accessToken = getAccessToken()
    let extraSetCookies: string[] = []

    // Buffer the request body ONCE up front. NextRequest.body is a ReadableStream
    // which can only be consumed once; if the first attempt returns 401 and we
    // retry, we need the same bytes on the replay. Skip the read for GET/HEAD.
    let bodyBuffer: ArrayBuffer | undefined
    if (!['GET', 'HEAD'].includes(method)) {
      try {
        bodyBuffer = await req.arrayBuffer()
      } catch {
        // no body available
      }
    }

    // First attempt.
    let backendResponse = await proxyRequest(req, pathSegments, accessToken, bodyBuffer)

    // Handle 401: attempt refresh (unless we are already on the refresh endpoint).
    if (backendResponse.status === 401 && joinedPath !== 'auth/refresh') {
      const cookieHeader = buildCookieHeader(req)
      const refreshResult = await refreshAccessToken(cookieHeader)

      if (refreshResult) {
        accessToken = refreshResult.token
        extraSetCookies = refreshResult.setCookies

        // Replay the original request with the new token + buffered body.
        backendResponse = await proxyRequest(req, pathSegments, accessToken, bodyBuffer)
      }
      // If refresh failed, fall through and return the 401.
    }

    // Post-process specific auth endpoints to update server-side store.
    if (backendResponse.ok) {
      if (method === 'POST' && (joinedPath === 'auth/login' || joinedPath === 'auth/refresh')) {
        try {
          // Clone before consuming.
          const cloned = backendResponse.clone()
          const data = await cloned.json()
          console.log('[PROXY] LOGIN/REFRESH RESPONSE:', { status: backendResponse.status, data })
          if (data.access_token) {
            setAccessToken(data.access_token)
            console.log('[PROXY] ACCESS TOKEN STORED:', data.access_token.substring(0, 20) + '...')
          } else {
            console.error('[PROXY] NO ACCESS_TOKEN IN RESPONSE:', data)
          }
        } catch (e) {
          // JSON parse failure — leave store unchanged.
          console.error('[PROXY] LOGIN/REFRESH JSON PARSE FAILED:', e)
        }
      } else if (method === 'POST' && joinedPath === 'auth/logout') {
        setAccessToken(null)
      }
    }

    return buildClientResponse(backendResponse, extraSetCookies)
  } catch (error) {
    console.error('[PROXY] HANDLER ERROR:', error instanceof Error ? error.message : String(error), error)
    return NextResponse.json(
      { detail: `Proxy error: ${error instanceof Error ? error.message : String(error)}` },
      { status: 500 }
    )
  }
}

// ---------------------------------------------------------------------------
// Export all HTTP methods
// ---------------------------------------------------------------------------

export const GET = handle
export const POST = handle
export const PATCH = handle
export const PUT = handle
export const DELETE = handle
