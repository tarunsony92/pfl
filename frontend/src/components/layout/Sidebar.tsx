'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  BriefcaseIcon,
  SettingsIcon,
  UsersIcon,
  DatabaseIcon,
  ScaleIcon,
  ClipboardCheckIcon,
  BrainIcon,
  RefreshCwIcon,
  MapPinOffIcon,
  AlertTriangleIcon,
} from 'lucide-react'
import { useMDQueue, useAssessorQueue } from '@/lib/useVerification'
import { useAuth } from '@/components/auth/useAuth'
import { cn } from '@/lib/cn'

interface NavItem {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  adminOnly?: boolean
  mdOnly?: boolean
  assessorOnly?: boolean
  showBadge?: 'md' | 'assessor'
}

const navItems: NavItem[] = [
  { href: '/cases', label: 'Cases', icon: BriefcaseIcon },
  {
    href: '/admin/approvals',
    label: 'MD Approvals',
    icon: ScaleIcon,
    mdOnly: true,
    showBadge: 'md',
  },
  {
    href: '/assessor/queue',
    label: 'Assessor Queue',
    icon: ClipboardCheckIcon,
    assessorOnly: true,
    showBadge: 'assessor',
  },
  { href: '/settings/profile', label: 'Settings', icon: SettingsIcon },
  { href: '/admin/users', label: 'Users', icon: UsersIcon, adminOnly: true },
  {
    href: '/admin/dedupe-snapshots',
    label: 'Dedupe Snapshots',
    icon: DatabaseIcon,
    adminOnly: true,
  },
  {
    href: '/admin/learning-rules',
    label: 'Learning Rules',
    icon: BrainIcon,
    adminOnly: true,
  },
  {
    href: '/admin/mrp-catalogue',
    label: 'MRP Catalogue',
    icon: DatabaseIcon,
    adminOnly: true,
  },
  {
    href: '/admin/l3-rerun',
    label: 'L3 Bulk Rerun',
    icon: RefreshCwIcon,
    adminOnly: true,
  },
  {
    href: '/admin/negative-areas',
    label: 'Negative Areas',
    icon: MapPinOffIcon,
    adminOnly: true,
  },
  {
    href: '/admin/incomplete-autoruns',
    label: 'Incomplete Auto-Runs',
    icon: AlertTriangleIcon,
    adminOnly: true,
  },
]

export function Sidebar() {
  const { user } = useAuth()
  const pathname = usePathname()
  const isAdmin = user?.role === 'admin'
  const isMD = user?.role === 'admin' || user?.role === 'ceo'
  const isAssessor =
    user?.role === 'ai_analyser' ||
    user?.role === 'underwriter' ||
    user?.role === 'credit_ho' ||
    user?.role === 'admin'

  const visibleItems = navItems.filter((item) => {
    if (item.adminOnly && !isAdmin) return false
    if (item.mdOnly && !isMD) return false
    if (item.assessorOnly && !isAssessor) return false
    return true
  })

  // Only fetch queues for the roles that need them — avoids needless network.
  const { data: mdQueue } = useMDQueue(isMD)
  const mdPending =
    (mdQueue?.total_open ?? 0) + (mdQueue?.total_awaiting_md ?? 0)
  const { data: assessorQueue } = useAssessorQueue(isAssessor)
  const assessorPending = assessorQueue?.total_open ?? 0

  return (
    <aside className="flex h-full w-64 flex-shrink-0 flex-col border-r border-pfl-slate-200 bg-white">
      {/* Logo / wordmark */}
      <div className="flex h-14 items-center px-6 border-b border-pfl-slate-200">
        <span className="inline-block rounded bg-pfl-blue-900 px-2 py-0.5 text-xs font-semibold uppercase tracking-widest text-white">
          PFL
        </span>
        <span className="ml-2 text-sm font-semibold text-pfl-slate-800">Credit AI</span>
      </div>

      {/* Navigation */}
      <nav aria-label="Primary" className="flex-1 overflow-y-auto py-4">
        <ul className="space-y-1 px-3">
          {visibleItems.map((item) => {
            const Icon = item.icon
            const isActive =
              pathname === item.href || pathname.startsWith(item.href + '/')
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={isActive ? 'page' : undefined}
                  className={cn(
                    'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600',
                    isActive
                      ? 'bg-pfl-blue-50 text-pfl-blue-800'
                      : 'text-pfl-slate-600 hover:bg-pfl-slate-50 hover:text-pfl-slate-900',
                  )}
                >
                  <Icon className="h-4 w-4 flex-shrink-0" />
                  <span className="flex-1">{item.label}</span>
                  {item.showBadge === 'md' && mdPending > 0 && (
                    <span
                      className="inline-flex items-center justify-center min-w-[20px] px-1.5 py-0.5 rounded-full text-[10px] font-bold tabular-nums bg-red-800 text-white"
                      aria-label={`${mdPending} pending`}
                    >
                      {mdPending}
                    </span>
                  )}
                  {item.showBadge === 'assessor' && assessorPending > 0 && (
                    <span
                      className="inline-flex items-center justify-center min-w-[20px] px-1.5 py-0.5 rounded-full text-[10px] font-bold tabular-nums bg-amber-600 text-white"
                      aria-label={`${assessorPending} to triage`}
                    >
                      {assessorPending}
                    </span>
                  )}
                </Link>
              </li>
            )
          })}
        </ul>
      </nav>
    </aside>
  )
}
