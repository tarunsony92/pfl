import React from 'react'
import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'
import { Toaster } from '@/components/ui/toaster'
import { AutoRunProvider } from '@/components/autorun/AutoRunProvider'
import { AutoRunModal } from '@/components/autorun/AutoRunModal'
import { AutoRunDock } from '@/components/autorun/AutoRunDock'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AutoRunProvider>
      {/* Skip-to-content accessibility link */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-pfl-blue-800 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white focus:outline-none focus:ring-2 focus:ring-pfl-blue-600"
      >
        Skip to main content
      </a>

      <div className="flex h-screen overflow-hidden">
        <Sidebar />

        <div className="flex flex-1 flex-col overflow-hidden">
          <Topbar />
          <main
            id="main-content"
            className="flex-1 overflow-auto p-8"
            tabIndex={-1}
          >
            {children}
          </main>
        </div>
      </div>

      {/* Global toast notifications */}
      <Toaster />

      {/* Auto-run pipeline UI — modal shows by default, dock shows once
          the user minimizes a run */}
      <AutoRunModal />
      <AutoRunDock />
    </AutoRunProvider>
  )
}
