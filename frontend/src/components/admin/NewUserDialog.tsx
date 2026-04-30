'use client'

/**
 * NewUserDialog — admin form to create a new user.
 *
 * Fields: email, full_name, role, password.
 * On submit: api.users.create(...) → toast → onCreated callback.
 */

import React, { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { PlusCircleIcon } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from '@/components/ui/use-toast'
import { api } from '@/lib/api'
import { UserRoles } from '@/lib/enums'

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const newUserSchema = z.object({
  email: z.string().email('Invalid email address'),
  full_name: z.string().min(1, 'Full name is required').max(255),
  role: z.enum(UserRoles as unknown as [string, ...string[]], {
    errorMap: () => ({ message: 'Select a valid role' }),
  }),
  password: z.string().min(8, 'Password must be at least 8 characters'),
})

export type NewUserFormValues = z.infer<typeof newUserSchema>

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface NewUserDialogProps {
  onCreated: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function NewUserDialog({ onCreated }: NewUserDialogProps) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewUserFormValues>({
    resolver: zodResolver(newUserSchema),
    defaultValues: { email: '', full_name: '', role: 'underwriter', password: '' },
  })

  async function onSubmit(values: NewUserFormValues) {
    setLoading(true)
    try {
      await api.users.create(values)
      toast({ title: 'User created', description: `${values.email} has been added.` })
      setOpen(false)
      reset()
      onCreated()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to create user'
      toast({ title: 'Error', description: msg, variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  function handleOpenChange(val: boolean) {
    if (!val) reset()
    setOpen(val)
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        <PlusCircleIcon className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
        New User
      </Button>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New User</DialogTitle>
            <DialogDescription>Create a new user account.</DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4 mt-2">
            {/* Email */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nu_email">
                Email <span aria-hidden="true" className="text-red-500">*</span>
              </Label>
              <Input
                id="nu_email"
                type="email"
                autoComplete="email"
                aria-invalid={!!errors.email}
                aria-describedby={errors.email ? 'nu_email_err' : undefined}
                {...register('email')}
              />
              {errors.email && (
                <p id="nu_email_err" role="alert" className="text-xs text-red-600">
                  {errors.email.message}
                </p>
              )}
            </div>

            {/* Full name */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nu_full_name">
                Full name <span aria-hidden="true" className="text-red-500">*</span>
              </Label>
              <Input
                id="nu_full_name"
                type="text"
                aria-invalid={!!errors.full_name}
                aria-describedby={errors.full_name ? 'nu_full_name_err' : undefined}
                {...register('full_name')}
              />
              {errors.full_name && (
                <p id="nu_full_name_err" role="alert" className="text-xs text-red-600">
                  {errors.full_name.message}
                </p>
              )}
            </div>

            {/* Role */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nu_role">
                Role <span aria-hidden="true" className="text-red-500">*</span>
              </Label>
              <select
                id="nu_role"
                className="flex w-full rounded border border-pfl-slate-300 bg-white px-3 py-2 text-sm text-pfl-slate-900 focus:outline-none focus:ring-2 focus:ring-pfl-blue-600 focus:ring-offset-1"
                aria-invalid={!!errors.role}
                aria-describedby={errors.role ? 'nu_role_err' : undefined}
                {...register('role')}
              >
                {UserRoles.map((r) => (
                  <option key={r} value={r}>
                    {r.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
              {errors.role && (
                <p id="nu_role_err" role="alert" className="text-xs text-red-600">
                  {errors.role.message}
                </p>
              )}
            </div>

            {/* Password */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="nu_password">
                Password <span aria-hidden="true" className="text-red-500">*</span>
              </Label>
              <Input
                id="nu_password"
                type="password"
                autoComplete="new-password"
                aria-invalid={!!errors.password}
                aria-describedby={errors.password ? 'nu_pw_err' : undefined}
                {...register('password')}
              />
              {errors.password && (
                <p id="nu_pw_err" role="alert" className="text-xs text-red-600">
                  {errors.password.message}
                </p>
              )}
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-2 pt-2">
              <DialogClose asChild>
                <Button variant="ghost" size="sm" disabled={loading}>
                  Cancel
                </Button>
              </DialogClose>
              <Button type="submit" size="sm" disabled={loading}>
                {loading ? 'Creating…' : 'Create user'}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
