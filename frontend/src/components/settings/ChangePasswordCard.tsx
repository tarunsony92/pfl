'use client'

/**
 * ChangePasswordCard — allows the current user to change their own password.
 */

import React, { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from '@/components/ui/use-toast'
import { api } from '@/lib/api'

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const passwordSchema = z
  .object({
    new_password: z
      .string()
      .min(8, 'Password must be at least 8 characters'),
    confirm_password: z.string(),
  })
  .refine((v) => v.new_password === v.confirm_password, {
    message: 'Passwords do not match',
    path: ['confirm_password'],
  })

type PasswordFormValues = z.infer<typeof passwordSchema>

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChangePasswordCard() {
  const [loading, setLoading] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<PasswordFormValues>({
    resolver: zodResolver(passwordSchema),
  })

  async function onSubmit(values: PasswordFormValues) {
    setLoading(true)
    try {
      await api.users.changePasswordSelf(values.new_password)
      toast({ title: 'Password updated', description: 'Your password has been changed successfully.' })
      reset()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to update password'
      toast({ title: 'Error', description: msg, variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change Password</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          {/* New Password */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new_password">
              New Password <span aria-hidden="true" className="text-red-500">*</span>
            </Label>
            <Input
              id="new_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!errors.new_password}
              aria-describedby={errors.new_password ? 'new_pw_err' : undefined}
              {...register('new_password')}
            />
            {errors.new_password && (
              <p id="new_pw_err" role="alert" className="text-xs text-red-600">
                {errors.new_password.message}
              </p>
            )}
          </div>

          {/* Confirm Password */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="confirm_password">
              Confirm New Password <span aria-hidden="true" className="text-red-500">*</span>
            </Label>
            <Input
              id="confirm_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!errors.confirm_password}
              aria-describedby={errors.confirm_password ? 'confirm_pw_err' : undefined}
              {...register('confirm_password')}
            />
            {errors.confirm_password && (
              <p id="confirm_pw_err" role="alert" className="text-xs text-red-600">
                {errors.confirm_password.message}
              </p>
            )}
          </div>

          <div className="flex justify-end pt-1">
            <Button type="submit" disabled={loading}>
              {loading ? 'Updating…' : 'Update password'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
