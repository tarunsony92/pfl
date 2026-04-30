'use client'

/**
 * /cases/new — Upload Wizard
 *
 * Three-step wizard:
 *   Step 1: Case details (loan_id, applicant_name, loan_amount, tenure, co-applicant)
 *   Step 2: Upload ZIP to presigned S3 URL
 *   Step 3: Finalize — auto-calls api.cases.finalize → redirect
 */

import React, { useState } from 'react'
import { Step1Details } from '@/components/wizard/Step1Details'
import { Step2Upload } from '@/components/wizard/Step2Upload'
import { Step3Finalize } from '@/components/wizard/Step3Finalize'
import type { CaseInitiateResponse } from '@/lib/types'
import type { Step1Values } from '@/components/wizard/Step1Details'

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <nav aria-label="Wizard progress" className="flex items-center gap-2 mb-6">
      {Array.from({ length: total }, (_, i) => {
        const step = i + 1
        const isActive = step === current
        const isDone = step < current
        return (
          <React.Fragment key={step}>
            {i > 0 && (
              <div
                className={`flex-1 h-0.5 ${isDone ? 'bg-pfl-blue-600' : 'bg-pfl-slate-200'}`}
                aria-hidden="true"
              />
            )}
            <div
              className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold flex-shrink-0
                ${isActive ? 'bg-pfl-blue-800 text-white ring-2 ring-pfl-blue-400 ring-offset-2' : ''}
                ${isDone ? 'bg-pfl-blue-600 text-white' : ''}
                ${!isActive && !isDone ? 'bg-pfl-slate-200 text-pfl-slate-600' : ''}
              `}
              aria-current={isActive ? 'step' : undefined}
            >
              {step}
            </div>
          </React.Fragment>
        )
      })}
    </nav>
  )
}

// ---------------------------------------------------------------------------
// State shape
// ---------------------------------------------------------------------------

type WizardState =
  | { step: 1 }
  | { step: 2; presigned: CaseInitiateResponse; caseId: string; formValues: Step1Values }
  | { step: 3; caseId: string }

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function NewCasePage() {
  const [state, setState] = useState<WizardState>({ step: 1 })

  return (
    <div className="mx-auto max-w-2xl py-8">
      <h1 className="text-2xl font-bold text-pfl-slate-900 mb-6">New Case</h1>

      <StepIndicator current={state.step} total={3} />

      {state.step === 1 && (
        <Step1Details
          onNext={({ presigned, caseId, formValues }) =>
            setState({ step: 2, presigned, caseId, formValues })
          }
        />
      )}

      {state.step === 2 && (
        <Step2Upload
          presigned={state.presigned}
          onNext={() => setState({ step: 3, caseId: state.caseId })}
          onBack={() => setState({ step: 1 })}
        />
      )}

      {state.step === 3 && (
        <Step3Finalize caseId={state.caseId} />
      )}
    </div>
  )
}
