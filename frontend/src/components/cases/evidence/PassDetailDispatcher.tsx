'use client'
/**
 * `PassDetailDispatcher` — renders the expanded pass-detail card for a
 * passing rule. Wraps every dispatched smart-card in an EvidenceTwoColumn
 * so the layout (claim left, source right) is identical to the fire-path
 * concern rendering. Falls through to GenericEvidenceTable when no card
 * is registered for the rule.
 */

import {
  EvidenceTwoColumn,
  GenericEvidenceTable,
} from './EvidenceTwoColumn'
import { extractSourceArtifactRefs } from './_format'
import {
  BUREAU_ACCOUNT_RULE_IDS,
  isBureauAccountRule,
  lookupCard,
} from './registry'

// Re-export so existing imports in VerificationPanel.tsx keep working.
export { BUREAU_ACCOUNT_RULE_IDS, isBureauAccountRule }

export function PassDetailDispatcher({
  subStepId,
  evidence,
  caseId,
}: {
  subStepId: string
  evidence: Record<string, unknown>
  caseId: string
}) {
  const card = lookupCard(subStepId, evidence)
  const sources = extractSourceArtifactRefs(evidence)

  if (card) {
    return (
      <EvidenceTwoColumn
        caseId={caseId}
        left={card.body}
        sources={sources}
        verdict="pass"
        headline={card.headline}
      />
    )
  }

  return (
    <EvidenceTwoColumn
      caseId={caseId}
      left={<GenericEvidenceTable evidence={evidence} />}
      sources={sources}
      verdict="pass"
    />
  )
}
