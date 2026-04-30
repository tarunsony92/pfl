'use client'

import { useRouter } from 'next/navigation'
import { ChevronDownIcon, LogOutIcon, UserIcon } from 'lucide-react'
import { useAuth } from '@/components/auth/useAuth'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { NotificationsBell } from './NotificationsBell'
import { RoleBadge } from './RoleBadge'

export function Topbar() {
  const { user, logout } = useAuth()
  const router = useRouter()

  const handleLogout = async () => {
    await logout()
    router.push('/login')
  }

  return (
    <header className="flex h-14 items-center justify-end gap-2 border-b border-pfl-slate-200 bg-white px-6">
      {user && <NotificationsBell />}
      {user && (
        <DropdownMenu>
          <DropdownMenuTrigger
            className="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm text-pfl-slate-700 hover:bg-pfl-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600"
            aria-label="User menu"
          >
            <span className="hidden sm:block">{user.email}</span>
            <RoleBadge role={user.role} />
            <ChevronDownIcon className="h-4 w-4 text-pfl-slate-400" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Account</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => router.push('/settings/profile')}
            >
              <UserIcon className="mr-2 h-4 w-4" />
              Profile
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={handleLogout}
              className="text-red-600 focus:bg-red-50 focus:text-red-700"
            >
              <LogOutIcon className="mr-2 h-4 w-4" />
              Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </header>
  )
}
