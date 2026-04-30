'use client'

/**
 * Error boundary inside the authenticated app group.
 * Preserves the app layout (sidebar + topbar remain visible).
 */

import { useEffect } from 'react'

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('[AppError]', error)
  }, [error])

  return (
    <div
      className="flex flex-col items-center justify-center gap-6 px-4 py-16 text-center"
      role="alert"
      aria-live="assertive"
    >
      <div className="flex flex-col items-center gap-2">
        <span className="text-5xl font-bold text-red-200 select-none">Error</span>
        <h2 className="text-xl font-semibold text-pfl-slate-800">Something went wrong</h2>
        <p className="max-w-sm text-sm text-pfl-slate-500">
          An unexpected error occurred in this section. You can try again or navigate elsewhere.
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
    </div>
  )
}
