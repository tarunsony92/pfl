'use client'

/**
 * Step 1 — Case details form.
 *
 * Fields: loan_id, applicant_name, loan_amount, loan_tenure_months, co_applicant_name.
 * On submit: calls api.cases.initiate() and passes response to onNext.
 */

import React, { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { toast } from '@/components/ui/use-toast'
import { api } from '@/lib/api'
import type { CaseInitiateResponse } from '@/lib/types'

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const step1Schema = z.object({
  loan_id: z
    .string()
    .transform((v) => v.trim())
    .pipe(
      z
        .string()
        .min(3, 'Loan ID must be at least 3 characters')
        .max(32, 'Loan ID must be at most 32 characters')
        .regex(/^[A-Za-z0-9-]{3,32}$/, 'Only letters, digits and hyphens allowed'),
    ),
  applicant_name: z
    .string()
    .transform((v) => v.trim())
    .pipe(z.string().min(1, 'Applicant name is required').max(255)),
  loan_amount: z
    .number({ invalid_type_error: 'Must be a number' })
    .min(50000, 'Minimum loan amount is ₹50,000')
    .max(150000, 'Maximum loan amount is ₹1,50,000'),
  loan_tenure_months: z
    .number({ invalid_type_error: 'Must be a number' })
    .int('Must be a whole number')
    .min(12, 'Minimum tenure is 12 months')
    .max(36, 'Maximum tenure is 36 months'),
  co_applicant_name: z.string().max(255).optional().or(z.literal('')),
  // Free-text applicant occupation. Surfaced to the L1 commute judge as
  // one input in the profile bundle. Optional — judges tolerate null.
  occupation: z.string().max(255).optional().or(z.literal('')),
})

export type Step1Values = z.infer<typeof step1Schema>

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface Step1DetailsProps {
  onNext: (data: { presigned: CaseInitiateResponse; caseId: string; formValues: Step1Values }) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Step1Details({ onNext }: Step1DetailsProps) {
  const [loading, setLoading] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Step1Values>({
    resolver: zodResolver(step1Schema),
    defaultValues: {
      loan_id: '',
      applicant_name: '',
      loan_amount: undefined,
      loan_tenure_months: undefined,
      co_applicant_name: '',
      occupation: '',
    },
  })

  async function onSubmit(values: Step1Values) {
    setLoading(true)
    try {
      const resp = await api.cases.initiate({
        loan_id: values.loan_id,
        applicant_name: values.applicant_name,
        loan_amount: values.loan_amount,
        loan_tenure_months: values.loan_tenure_months,
        co_applicant_name: values.co_applicant_name || undefined,
        occupation: values.occupation || undefined,
      })
      onNext({ presigned: resp, caseId: resp.case_id, formValues: values })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to initiate case'
      toast({ title: 'Error', description: msg, variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Step 1 — Case Details</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          {/* Loan ID */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="loan_id">
              Loan ID <span aria-hidden="true" className="text-red-500">*</span>
            </Label>
            <Input
              id="loan_id"
              type="text"
              placeholder="e.g. PFL-2026-001"
              aria-invalid={!!errors.loan_id}
              aria-describedby={errors.loan_id ? 'loan_id_err' : undefined}
              {...register('loan_id')}
            />
            {errors.loan_id && (
              <p id="loan_id_err" role="alert" className="text-xs text-red-600">
                {errors.loan_id.message}
              </p>
            )}
          </div>

          {/* Applicant Name */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="applicant_name">
              Applicant Name <span aria-hidden="true" className="text-red-500">*</span>
            </Label>
            <Input
              id="applicant_name"
              type="text"
              placeholder="Full name"
              aria-invalid={!!errors.applicant_name}
              aria-describedby={errors.applicant_name ? 'applicant_name_err' : undefined}
              {...register('applicant_name')}
            />
            {errors.applicant_name && (
              <p id="applicant_name_err" role="alert" className="text-xs text-red-600">
                {errors.applicant_name.message}
              </p>
            )}
          </div>

          {/* Loan Amount */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="loan_amount">
              Loan Amount (₹) <span aria-hidden="true" className="text-red-500">*</span>
            </Label>
            <Input
              id="loan_amount"
              type="number"
              placeholder="50000 – 150000"
              min={50000}
              max={150000}
              aria-invalid={!!errors.loan_amount}
              aria-describedby={errors.loan_amount ? 'loan_amount_err' : undefined}
              {...register('loan_amount', { valueAsNumber: true })}
            />
            {errors.loan_amount && (
              <p id="loan_amount_err" role="alert" className="text-xs text-red-600">
                {errors.loan_amount.message}
              </p>
            )}
          </div>

          {/* Loan Tenure */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="loan_tenure_months">
              Loan Tenure (months) <span aria-hidden="true" className="text-red-500">*</span>
            </Label>
            <Input
              id="loan_tenure_months"
              type="number"
              placeholder="12 – 36"
              min={12}
              max={36}
              aria-invalid={!!errors.loan_tenure_months}
              aria-describedby={errors.loan_tenure_months ? 'tenure_err' : undefined}
              {...register('loan_tenure_months', { valueAsNumber: true })}
            />
            {errors.loan_tenure_months && (
              <p id="tenure_err" role="alert" className="text-xs text-red-600">
                {errors.loan_tenure_months.message}
              </p>
            )}
          </div>

          {/* Co-applicant Name (optional) */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="co_applicant_name">Co-applicant Name (optional)</Label>
            <Input
              id="co_applicant_name"
              type="text"
              placeholder="Leave blank if not applicable"
              {...register('co_applicant_name')}
            />
          </div>

          {/* Occupation (optional) — feeds the L1 commute judge */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="occupation">Applicant Occupation (optional)</Label>
            <Input
              id="occupation"
              type="text"
              placeholder="e.g. tailor, wholesale grain dealer, dairy farmer"
              {...register('occupation')}
            />
          </div>

          <div className="flex justify-end pt-2">
            <Button type="submit" disabled={loading}>
              {loading ? 'Creating case…' : 'Next: Upload ZIP'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
