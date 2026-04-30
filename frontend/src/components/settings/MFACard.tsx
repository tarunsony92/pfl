'use client'

/**
 * MFACard — Two-factor authentication setup / status.
 *
 * If mfa_enabled → show "Enabled" badge + "Disable" button (stub — backend has no disable endpoint yet).
 * Else → "Enable" button → enroll → show QR URI + TOTP input → verify → refresh user.
 *
 * FOLLOW_UPS: M4-F2 — Backend has no MFA disable endpoint. Disable button is non-functional stub.
 */

import React, { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { toast } from '@/components/ui/use-toast'
import { api } from '@/lib/api'
import type { UserRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MFACardProps {
  user: UserRead
  onRefresh: () => Promise<void>
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MFACard({ user, onRefresh }: MFACardProps) {
  const [enrolling, setEnrolling] = useState(false)
  const [otpauthUri, setOtpauthUri] = useState<string>('')
  const [secret, setSecret] = useState<string>('')
  const [totpCode, setTotpCode] = useState('')
  const [verifying, setVerifying] = useState(false)

  async function handleEnable() {
    try {
      const resp = await api.auth.mfaEnroll()
      setOtpauthUri(resp.otpauth_uri)
      setSecret(resp.secret)
      setEnrolling(true)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to start MFA enrollment'
      toast({ title: 'Error', description: msg, variant: 'destructive' })
    }
  }

  async function handleVerify() {
    if (totpCode.length !== 6) {
      toast({ title: 'Enter a 6-digit code', variant: 'destructive' })
      return
    }
    setVerifying(true)
    try {
      await api.auth.mfaVerify(totpCode)
      toast({ title: 'MFA enabled', description: 'Two-factor authentication is now active.' })
      setEnrolling(false)
      setTotpCode('')
      setOtpauthUri('')
      setSecret('')
      await onRefresh()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Verification failed'
      toast({ title: 'Verification failed', description: msg, variant: 'destructive' })
    } finally {
      setVerifying(false)
    }
  }

  function handleDisable() {
    // FOLLOW_UPS: M4-F2 — Backend does not yet expose a MFA disable endpoint.
    // This button is a stub until the endpoint is implemented.
    toast({
      title: 'Not available',
      description: 'MFA disable requires admin action. Please contact your administrator.',
      variant: 'destructive',
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Two-Factor Authentication</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {user.mfa_enabled ? (
          /* Already enabled state */
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <Badge variant="success">Enabled</Badge>
              <p className="text-sm text-pfl-slate-600">
                Your account is protected with TOTP-based two-factor authentication.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDisable}
              className="border-red-300 text-red-600 hover:bg-red-50"
            >
              Disable
            </Button>
          </div>
        ) : !enrolling ? (
          /* Not enrolled state */
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <Badge variant="outline">Not enabled</Badge>
              <p className="text-sm text-pfl-slate-600">
                Add an extra layer of security to your account.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={handleEnable}>
              Enable
            </Button>
          </div>
        ) : (
          /* Enrollment in progress */
          <div className="flex flex-col gap-5">
            <p className="text-sm text-pfl-slate-700">
              Scan the QR code below with your authenticator app (Google Authenticator, Authy, etc.),
              then enter the 6-digit code to confirm.
            </p>

            {/* QR code — rendered as a styled link / text since qrcode.react is not installed */}
            <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-4 flex flex-col gap-2">
              <p className="text-xs font-medium text-pfl-slate-600 uppercase tracking-wide">OTPAuth URI</p>
              <p
                className="break-all text-xs font-mono text-pfl-blue-700 select-all"
                aria-label="OTP Auth URI — copy into your authenticator app"
              >
                {otpauthUri}
              </p>
              {secret && (
                <>
                  <p className="text-xs font-medium text-pfl-slate-600 uppercase tracking-wide mt-2">
                    Manual secret
                  </p>
                  <p className="break-all text-xs font-mono text-pfl-slate-800 select-all">{secret}</p>
                </>
              )}
            </div>

            {/* TOTP verification */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="totp_code">
                6-digit verification code <span aria-hidden="true" className="text-red-500">*</span>
              </Label>
              <div className="flex gap-2">
                <Input
                  id="totp_code"
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  placeholder="123456"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  aria-label="TOTP verification code"
                  className="max-w-xs"
                />
                <Button
                  onClick={handleVerify}
                  disabled={verifying || totpCode.length !== 6}
                >
                  {verifying ? 'Verifying…' : 'Verify'}
                </Button>
              </div>
            </div>

            <Button
              variant="ghost"
              size="sm"
              className="self-start"
              onClick={() => {
                setEnrolling(false)
                setOtpauthUri('')
                setSecret('')
                setTotpCode('')
              }}
            >
              Cancel
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
