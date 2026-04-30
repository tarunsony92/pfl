'use client'

import { useEffect } from 'react'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Log to error reporting service in production
    console.error('[GlobalError]', error)
  }, [error])

  return (
    <html lang="en">
      <body className="min-h-screen bg-white font-sans">
        <main
          id="main-content"
          className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 text-center"
          role="alert"
          aria-live="assertive"
        >
          <div className="flex flex-col items-center gap-2">
            <span className="text-5xl font-bold text-red-200 select-none">500</span>
            <h1 className="text-2xl font-semibold text-pfl-slate-800">Something went wrong</h1>
            <p className="max-w-sm text-sm text-pfl-slate-500">
              An unexpected error occurred. Please try again, or contact support if the problem
              persists.
            </p>
            {error.digest && (
              <p className="mt-1 font-mono text-xs text-pfl-slate-400">
                Error ID: {error.digest}
              </p>
            )}
          </div>
          <button
            onClick={reset}
            className="rounded-md bg-pfl-blue-800 px-4 py-2 text-sm font-medium text-white hover:bg-pfl-blue-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600 focus-visible:ring-offset-2"
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  )
}
