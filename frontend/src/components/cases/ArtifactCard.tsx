'use client'

/**
 * ArtifactCard — single artifact display in the Artifacts tab.
 *
 * Shows: subtype friendly label, filename, upload time, size, type icon, Download button.
 */

import React from 'react'
import {
  FileIcon,
  ImageIcon,
  FileTextIcon,
  CreditCardIcon,
  BarChart2Icon,
  DownloadIcon,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import type { CaseArtifactRead } from '@/lib/types'
import type { ArtifactSubtype } from '@/lib/enums'

interface ArtifactCardProps {
  artifact: CaseArtifactRead
  onDownload: (artifactId: string) => void
}

/** Human-readable labels for each subtype */
const SUBTYPE_LABELS: Record<ArtifactSubtype, string> = {
  KYC_AADHAAR: 'Aadhaar Card',
  KYC_PAN: 'PAN Card',
  KYC_VOTER: 'Voter ID',
  KYC_DL: "Driver's Licence",
  KYC_PASSPORT: 'Passport',
  RATION_CARD: 'Ration Card',
  ELECTRICITY_BILL: 'Electricity Bill',
  BANK_ACCOUNT_PROOF: 'Bank Account Proof',
  INCOME_PROOF: 'Income Proof',
  CO_APPLICANT_AADHAAR: 'Co-Applicant Aadhaar',
  CO_APPLICANT_PAN: 'Co-Applicant PAN',
  AUTO_CAM: 'AutoCAM',
  CHECKLIST: 'Checklist',
  PD_SHEET: 'PD Sheet',
  EQUIFAX_HTML: 'Equifax Report',
  CIBIL_HTML: 'CIBIL Report',
  HIGHMARK_HTML: 'Highmark Report',
  EXPERIAN_HTML: 'Experian Report',
  BANK_STATEMENT: 'Bank Statement',
  HOUSE_VISIT_PHOTO: 'House Visit Photo',
  BUSINESS_PREMISES_PHOTO: 'Business Premises Photo',
  KYC_VIDEO: 'KYC Video',
  LOAN_AGREEMENT: 'Loan Agreement',
  DPN: 'DPN',
  LAPP: 'LAPP',
  LAGR: 'LAGR',
  NACH: 'NACH',
  KFS: 'KFS',
  UDYAM_REG: 'Udyam Registration',
  UNKNOWN: 'Unknown',
  DEDUPE_REPORT: 'Dedupe Report',
  TVR_AUDIO: 'TVR Audio',
}

function ArtifactIcon({ subtype }: { subtype: string }) {
  if (subtype.includes('PHOTO') || subtype.includes('VIDEO')) {
    return <ImageIcon className="h-5 w-5 text-pfl-slate-500" aria-hidden="true" />
  }
  if (subtype.includes('EQUIFAX') || subtype.includes('CIBIL') || subtype.includes('HIGHMARK') || subtype.includes('EXPERIAN')) {
    return <CreditCardIcon className="h-5 w-5 text-pfl-slate-500" aria-hidden="true" />
  }
  if (subtype === 'BANK_STATEMENT') {
    return <BarChart2Icon className="h-5 w-5 text-pfl-slate-500" aria-hidden="true" />
  }
  if (subtype.includes('KYC') || subtype.includes('PAN') || subtype.includes('AADHAAR')) {
    return <FileTextIcon className="h-5 w-5 text-pfl-slate-500" aria-hidden="true" />
  }
  return <FileIcon className="h-5 w-5 text-pfl-slate-500" aria-hidden="true" />
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

export function ArtifactCard({ artifact, onDownload }: ArtifactCardProps) {
  const label = SUBTYPE_LABELS[artifact.artifact_type as ArtifactSubtype] ?? artifact.artifact_type

  return (
    <Card className="flex flex-col gap-0">
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 shrink-0">
            <ArtifactIcon subtype={artifact.artifact_type} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-pfl-slate-900 truncate">{label}</p>
            <p className="text-xs text-pfl-slate-500 truncate mt-0.5" title={artifact.filename}>
              {artifact.filename}
            </p>
            <div className="mt-1 flex items-center gap-2 text-xs text-pfl-slate-400">
              <span>{formatDateTime(artifact.uploaded_at)}</span>
              {artifact.size_bytes != null && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>{formatBytes(artifact.size_bytes)}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="mt-3">
          <Button
            variant="outline"
            size="sm"
            className="w-full text-xs gap-1"
            onClick={() => onDownload(artifact.id)}
          >
            <DownloadIcon className="h-3 w-3" aria-hidden="true" />
            Download
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
