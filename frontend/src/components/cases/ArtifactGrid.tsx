'use client'

/**
 * ArtifactGrid — displays all case artifacts grouped by subtype category.
 *
 * Categories: KYC / Documents / Photos / Credit Reports / Others
 */

import React from 'react'
import { PackageOpenIcon } from 'lucide-react'
import { ArtifactCard } from './ArtifactCard'
import type { CaseArtifactRead } from '@/lib/types'

interface ArtifactGridProps {
  artifacts: CaseArtifactRead[]
  onDownload: (artifactId: string) => void
}

type Category = 'KYC' | 'Documents' | 'Photos' | 'Credit Reports' | 'Others'

function getCategory(artifactType: string): Category {
  if (
    artifactType.startsWith('KYC_') ||
    artifactType === 'CO_APPLICANT_AADHAAR' ||
    artifactType === 'CO_APPLICANT_PAN'
  ) {
    return 'KYC'
  }
  if (
    artifactType === 'EQUIFAX_HTML' ||
    artifactType === 'CIBIL_HTML' ||
    artifactType === 'HIGHMARK_HTML' ||
    artifactType === 'EXPERIAN_HTML'
  ) {
    return 'Credit Reports'
  }
  if (
    artifactType === 'HOUSE_VISIT_PHOTO' ||
    artifactType === 'BUSINESS_PREMISES_PHOTO' ||
    artifactType === 'KYC_VIDEO'
  ) {
    return 'Photos'
  }
  if (
    artifactType === 'RATION_CARD' ||
    artifactType === 'ELECTRICITY_BILL' ||
    artifactType === 'BANK_ACCOUNT_PROOF' ||
    artifactType === 'INCOME_PROOF' ||
    artifactType === 'BANK_STATEMENT' ||
    artifactType === 'AUTO_CAM' ||
    artifactType === 'CHECKLIST' ||
    artifactType === 'PD_SHEET' ||
    artifactType === 'LOAN_AGREEMENT' ||
    artifactType === 'DPN' ||
    artifactType === 'LAPP' ||
    artifactType === 'LAGR' ||
    artifactType === 'NACH' ||
    artifactType === 'KFS' ||
    artifactType === 'UDYAM_REG'
  ) {
    return 'Documents'
  }
  return 'Others'
}

const CATEGORY_ORDER: Category[] = ['KYC', 'Documents', 'Photos', 'Credit Reports', 'Others']

export function ArtifactGrid({ artifacts, onDownload }: ArtifactGridProps) {
  if (artifacts.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-pfl-slate-500">
        <PackageOpenIcon className="h-10 w-10 opacity-40" aria-hidden="true" />
        <p className="font-medium">No artifacts uploaded</p>
      </div>
    )
  }

  // Group by category
  const grouped: Record<Category, CaseArtifactRead[]> = {
    KYC: [],
    Documents: [],
    Photos: [],
    'Credit Reports': [],
    Others: [],
  }

  for (const artifact of artifacts) {
    const cat = getCategory(artifact.artifact_type)
    grouped[cat].push(artifact)
  }

  return (
    <div className="flex flex-col gap-8">
      {CATEGORY_ORDER.filter((cat) => grouped[cat].length > 0).map((cat) => (
        <section key={cat}>
          <h3 className="mb-3 text-sm font-semibold text-pfl-slate-700 uppercase tracking-wide">
            {cat}
          </h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {grouped[cat].map((artifact) => (
              <ArtifactCard key={artifact.id} artifact={artifact} onDownload={onDownload} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
