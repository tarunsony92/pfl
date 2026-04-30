import type { UserRead } from '@/lib/types'

export type AuthState = {
  user: UserRead | null
  loading: boolean
  login: (
    email: string,
    password: string,
    mfaCode?: string,
  ) => Promise<{ mfaRequired?: boolean; mfaEnrollmentRequired?: boolean }>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
}
