import { cn } from '@/lib/cn'
import type { UserRole } from '@/lib/enums'

const roleColors: Record<UserRole, string> = {
  user: 'bg-pfl-slate-100 text-pfl-slate-700',
  admin: 'bg-red-100 text-red-700',
  ceo: 'bg-purple-100 text-purple-700',
  credit_ho: 'bg-blue-100 text-blue-700',
  ai_analyser: 'bg-indigo-100 text-indigo-700',
  underwriter: 'bg-green-100 text-green-700',
}

const roleLabels: Record<UserRole, string> = {
  user: 'User',
  admin: 'Admin',
  ceo: 'CEO',
  credit_ho: 'Credit HO',
  ai_analyser: 'AI Analyser',
  underwriter: 'Underwriter',
}

interface RoleBadgeProps {
  role: string
  className?: string
}

export function RoleBadge({ role, className }: RoleBadgeProps) {
  const color = roleColors[role as UserRole] ?? 'bg-pfl-slate-100 text-pfl-slate-700'
  const label = roleLabels[role as UserRole] ?? role
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold',
        color,
        className,
      )}
    >
      {label}
    </span>
  )
}
