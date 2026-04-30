/**
 * Next.js Edge Middleware.
 *
 * Responsibilities:
 *  1. CSRF double-submit validation on mutating /api/proxy requests.
 *  2. Auth gate: redirect unauthenticated users to /login for non-public app routes.
 */

import type { NextRequest} from 'next/server';
import { NextResponse } from 'next/server'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MUTATING_METHODS = new Set(['POST', 'PATCH', 'PUT', 'DELETE'])

/**
 * Proxy paths exempt from CSRF check.
 * login + refresh set the csrf_token cookie themselves (browser hasn't received
 * it yet) so they cannot include it in the request header.
 */
const CSRF_EXEMPT_PATHS = new Set(['/api/proxy/auth/login', '/api/proxy/auth/refresh'])

/**
 * App-level paths that do NOT require authentication.
 * Prefix-matched: any path starting with one of these passes through.
 */
const PUBLIC_PATH_PREFIXES = [
  '/login',
  '/api/',      // all API routes (proxy handles its own auth)
  '/_next',
  '/favicon.ico',
]

// ---------------------------------------------------------------------------
// Middleware
// ---------------------------------------------------------------------------

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl

  // ------------------------------------------------------------------
  // 1. CSRF validation on mutating /api/proxy/** requests
  // ------------------------------------------------------------------
  if (pathname.startsWith('/api/proxy') && MUTATING_METHODS.has(req.method)) {
    if (!CSRF_EXEMPT_PATHS.has(pathname)) {
      const headerTok = req.headers.get('x-csrf-token')
      const cookieTok = req.cookies.get('csrf_token')?.value

      if (!headerTok || !cookieTok || headerTok !== cookieTok) {
        return NextResponse.json({ detail: 'CSRF token mismatch' }, { status: 403 })
      }
    }
  }

  // ------------------------------------------------------------------
  // 2. Auth gate on app routes (non-API)
  //    Check refresh_token cookie presence — actual JWT validity is
  //    enforced server-side on every API call.
  // ------------------------------------------------------------------
  const isPublic = PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))

  if (!isPublic) {
    if (!req.cookies.get('refresh_token')) {
      const loginUrl = new URL('/login', req.url)
      loginUrl.searchParams.set('from', pathname)
      return NextResponse.redirect(loginUrl)
    }
  }

  return NextResponse.next()
}

// ---------------------------------------------------------------------------
// Matcher: run on every route except static assets
// ---------------------------------------------------------------------------

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
