'use client'

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useAuth } from '@/components/auth/useAuth'

// ---------------------------------------------------------------------------
// Validation schemas
// ---------------------------------------------------------------------------

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
})

const mfaSchema = z.object({
  mfaCode: z
    .string()
    .regex(/^\d{6}$/, 'Enter the 6-digit code from your authenticator app'),
})

type LoginFields = z.infer<typeof loginSchema>
type MfaFields = z.infer<typeof mfaSchema>

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return (
    <p className="mt-1 text-sm text-red-600" role="alert">
      {message}
    </p>
  )
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  )
}

function LoginForm() {
  const { login } = useAuth()
  const router = useRouter()
  const searchParams = useSearchParams()

  /** Where to redirect after successful login. */
  const redirectTo = searchParams.get('from') || '/cases'

  /** 'credentials' | 'mfa' */
  const [step, setStep] = useState<'credentials' | 'mfa'>('credentials')

  /** Stored credentials so we can re-submit with MFA code. */
  const [pendingEmail, setPendingEmail] = useState('')
  const [pendingPassword, setPendingPassword] = useState('')

  /** Top-level error message (e.g. "Invalid credentials"). */
  const [serverError, setServerError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const {
    register: registerLogin,
    handleSubmit: handleLoginSubmit,
    formState: { errors: loginErrors },
  } = useForm<LoginFields>({
    resolver: zodResolver(loginSchema),
  })

  const {
    register: registerMfa,
    handleSubmit: handleMfaSubmit,
    formState: { errors: mfaErrors },
    setFocus: setMfaFocus,
  } = useForm<MfaFields>({
    resolver: zodResolver(mfaSchema),
  })

  // Auto-focus MFA field when step changes.
  useEffect(() => {
    if (step === 'mfa') {
      setMfaFocus('mfaCode')
    }
  }, [step, setMfaFocus])

  // ------------------------------------------------------------------
  // Handlers
  // ------------------------------------------------------------------

  const onCredentialsSubmit = async ({ email, password }: LoginFields) => {
    setServerError(null)
    setIsSubmitting(true)
    try {
      const result = await login(email, password)

      if (result.mfaRequired) {
        setPendingEmail(email)
        setPendingPassword(password)
        setStep('mfa')
        return
      }

      if (result.mfaEnrollmentRequired) {
        // In a full app we'd redirect to MFA enrollment; for now show a message.
        setServerError('MFA enrollment required. Please contact your administrator.')
        return
      }

      // Success
      router.push(redirectTo)
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : 'Login failed. Check your email and password.'
      setServerError(msg)
    } finally {
      setIsSubmitting(false)
    }
  }

  const onMfaSubmit = async ({ mfaCode }: MfaFields) => {
    setServerError(null)
    setIsSubmitting(true)
    try {
      const result = await login(pendingEmail, pendingPassword, mfaCode)

      if (result.mfaRequired || result.mfaEnrollmentRequired) {
        setServerError('MFA verification failed. Try again.')
        return
      }

      router.push(redirectTo)
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : 'MFA verification failed.'
      setServerError(msg)
    } finally {
      setIsSubmitting(false)
    }
  }

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-16">
      <div className="w-full max-w-md rounded-lg bg-white p-8 shadow-md">
        {/* Logo / brand */}
        <div className="mb-8 text-center">
          <span className="inline-block rounded bg-pfl-blue-900 px-3 py-1 text-sm font-semibold uppercase tracking-widest text-white">
            PFL Credit
          </span>
          <h1 className="mt-4 text-2xl font-bold text-pfl-slate-900">
            {step === 'mfa' ? 'Two-factor authentication' : 'Sign in to your account'}
          </h1>
          {step === 'mfa' && (
            <p className="mt-2 text-sm text-pfl-slate-500">
              Enter the 6-digit code from your authenticator app.
            </p>
          )}
        </div>

        {/* Server-level error banner */}
        {serverError && (
          <div
            role="alert"
            className="mb-4 rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            {serverError}
          </div>
        )}

        {/* ---- Step 1: email + password ---- */}
        {step === 'credentials' && (
          <form
            onSubmit={handleLoginSubmit(onCredentialsSubmit)}
            noValidate
            aria-label="Sign in form"
          >
            {/* Email */}
            <div className="mb-5">
              <label
                htmlFor="email"
                className="mb-1.5 block text-sm font-medium text-pfl-slate-700"
              >
                Email address
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                aria-invalid={loginErrors.email ? 'true' : 'false'}
                className={[
                  'w-full rounded border px-3 py-2 text-sm text-pfl-slate-900',
                  'outline-none transition-colors',
                  'focus:ring-2 focus:ring-pfl-blue-600 focus:ring-offset-1',
                  loginErrors.email
                    ? 'border-red-400 bg-red-50'
                    : 'border-pfl-slate-300 bg-white hover:border-pfl-slate-400',
                ].join(' ')}
                {...registerLogin('email')}
              />
              <FieldError message={loginErrors.email?.message} />
            </div>

            {/* Password */}
            <div className="mb-6">
              <label
                htmlFor="password"
                className="mb-1.5 block text-sm font-medium text-pfl-slate-700"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                aria-invalid={loginErrors.password ? 'true' : 'false'}
                className={[
                  'w-full rounded border px-3 py-2 text-sm text-pfl-slate-900',
                  'outline-none transition-colors',
                  'focus:ring-2 focus:ring-pfl-blue-600 focus:ring-offset-1',
                  loginErrors.password
                    ? 'border-red-400 bg-red-50'
                    : 'border-pfl-slate-300 bg-white hover:border-pfl-slate-400',
                ].join(' ')}
                {...registerLogin('password')}
              />
              <FieldError message={loginErrors.password?.message} />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className={[
                'w-full rounded px-4 py-2 text-sm font-semibold text-white',
                'transition-colors focus:outline-none focus:ring-2 focus:ring-pfl-blue-600 focus:ring-offset-2',
                isSubmitting
                  ? 'cursor-not-allowed bg-pfl-blue-700 opacity-60'
                  : 'bg-pfl-blue-800 hover:bg-pfl-blue-900',
              ].join(' ')}
            >
              {isSubmitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        )}

        {/* ---- Step 2: MFA code ---- */}
        {step === 'mfa' && (
          <form
            onSubmit={handleMfaSubmit(onMfaSubmit)}
            noValidate
            aria-label="Two-factor authentication form"
          >
            <div className="mb-6">
              <label
                htmlFor="mfaCode"
                className="mb-1.5 block text-sm font-medium text-pfl-slate-700"
              >
                Authenticator code
              </label>
              <input
                id="mfaCode"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="000000"
                aria-invalid={mfaErrors.mfaCode ? 'true' : 'false'}
                className={[
                  'w-full rounded border px-3 py-2 text-center text-lg tracking-widest text-pfl-slate-900',
                  'outline-none transition-colors',
                  'focus:ring-2 focus:ring-pfl-blue-600 focus:ring-offset-1',
                  mfaErrors.mfaCode
                    ? 'border-red-400 bg-red-50'
                    : 'border-pfl-slate-300 bg-white hover:border-pfl-slate-400',
                ].join(' ')}
                {...registerMfa('mfaCode')}
              />
              <FieldError message={mfaErrors.mfaCode?.message} />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className={[
                'w-full rounded px-4 py-2 text-sm font-semibold text-white',
                'transition-colors focus:outline-none focus:ring-2 focus:ring-pfl-blue-600 focus:ring-offset-2',
                isSubmitting
                  ? 'cursor-not-allowed bg-pfl-blue-700 opacity-60'
                  : 'bg-pfl-blue-800 hover:bg-pfl-blue-900',
              ].join(' ')}
            >
              {isSubmitting ? 'Verifying…' : 'Verify code'}
            </button>

            <button
              type="button"
              onClick={() => {
                setStep('credentials')
                setServerError(null)
              }}
              className="mt-3 w-full text-sm text-pfl-slate-500 underline-offset-2 hover:text-pfl-slate-700 hover:underline"
            >
              Back to sign in
            </button>
          </form>
        )}
      </div>
    </main>
  )
}
