/**
 * Minimal login layout — no sidebar, just the page content centered.
 */

import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Sign In — PFL Credit AI',
}

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-pfl-slate-50">
      {children}
    </div>
  )
}
