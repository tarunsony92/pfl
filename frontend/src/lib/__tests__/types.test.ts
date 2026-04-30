/**
 * Tests for lib/types.ts Zod schemas.
 *
 * Verifies that schemas parse valid inputs correctly and reject invalid ones.
 */

import { describe, it, expect } from 'vitest'
import {
  UserReadSchema,
  CaseReadSchema,
  CaseArtifactReadSchema,
  CaseListResponseSchema,
  CaseInitiateRequestSchema,
  LoginResponseSchema,
} from '../types'

// ---------------------------------------------------------------------------
// LoginResponseSchema
// ---------------------------------------------------------------------------

describe('LoginResponseSchema', () => {
  it('parses valid login response', () => {
    const result = LoginResponseSchema.parse({
      access_token: 'abc',
      refresh_token: 'def',
      token_type: 'bearer',
      mfa_required: false,
      mfa_enrollment_required: false,
    })
    expect(result.access_token).toBe('abc')
  })

  it('defaults token_type to bearer when missing', () => {
    const result = LoginResponseSchema.parse({
      access_token: 'abc',
      refresh_token: 'def',
    })
    expect(result.token_type).toBe('bearer')
  })

  it('rejects missing access_token', () => {
    expect(() =>
      LoginResponseSchema.parse({ refresh_token: 'def', token_type: 'bearer' }),
    ).toThrow()
  })
})

// ---------------------------------------------------------------------------
// UserReadSchema
// ---------------------------------------------------------------------------

describe('UserReadSchema', () => {
  it('parses valid user', () => {
    const result = UserReadSchema.parse({
      id: '00000000-0000-0000-0000-000000000001',
      email: 'user@example.com',
      full_name: 'Alice Smith',
      role: 'admin',
      mfa_enabled: true,
      is_active: true,
      last_login_at: null,
      created_at: '2026-01-01T00:00:00+00:00',
    })
    expect(result.email).toBe('user@example.com')
  })

  it('rejects invalid email', () => {
    expect(() =>
      UserReadSchema.parse({
        id: '00000000-0000-0000-0000-000000000001',
        email: 'not-an-email',
        full_name: 'Alice',
        role: 'admin',
        mfa_enabled: false,
        is_active: true,
        last_login_at: null,
        created_at: '2026-01-01T00:00:00+00:00',
      }),
    ).toThrow()
  })
})

// ---------------------------------------------------------------------------
// CaseArtifactReadSchema
// ---------------------------------------------------------------------------

describe('CaseArtifactReadSchema', () => {
  it('parses valid artifact', () => {
    const result = CaseArtifactReadSchema.parse({
      id: '00000000-0000-0000-0000-000000000002',
      filename: 'aadhaar.pdf',
      artifact_type: 'KYC_AADHAAR',
      size_bytes: 1024,
      content_type: 'application/pdf',
      uploaded_at: '2026-01-01T10:00:00+00:00',
      download_url: null,
    })
    expect(result.filename).toBe('aadhaar.pdf')
  })

  it('allows null size_bytes', () => {
    const result = CaseArtifactReadSchema.parse({
      id: '00000000-0000-0000-0000-000000000002',
      filename: 'doc.pdf',
      artifact_type: 'UNKNOWN',
      size_bytes: null,
      content_type: null,
      uploaded_at: '2026-01-01T10:00:00+00:00',
    })
    expect(result.size_bytes).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// CaseInitiateRequestSchema
// ---------------------------------------------------------------------------

describe('CaseInitiateRequestSchema', () => {
  it('parses valid request', () => {
    const result = CaseInitiateRequestSchema.parse({
      loan_id: 'PFL-2026-001',
      applicant_name: 'Alice',
    })
    expect(result.loan_id).toBe('PFL-2026-001')
  })

  it('rejects loan_id with invalid characters', () => {
    expect(() =>
      CaseInitiateRequestSchema.parse({ loan_id: 'invalid id!', applicant_name: 'A' }),
    ).toThrow()
  })
})

// ---------------------------------------------------------------------------
// CaseReadSchema
// ---------------------------------------------------------------------------

describe('CaseReadSchema', () => {
  it('parses a minimal valid case', () => {
    const result = CaseReadSchema.parse({
      id: '00000000-0000-0000-0000-000000000003',
      loan_id: 'LOAN-001',
      applicant_name: 'Alice',
      uploaded_by: '00000000-0000-0000-0000-000000000004',
      uploaded_at: '2026-01-01T10:00:00+00:00',
      finalized_at: null,
      current_stage: 'INGESTED',
      assigned_to: null,
      reupload_count: 0,
      reupload_allowed_until: null,
      is_deleted: false,
      created_at: '2026-01-01T10:00:00+00:00',
      updated_at: '2026-01-01T10:00:00+00:00',
      artifacts: [],
    })
    expect(result.loan_id).toBe('LOAN-001')
    expect(result.artifacts).toEqual([])
  })

  it('defaults artifacts to empty array when omitted', () => {
    const result = CaseReadSchema.parse({
      id: '00000000-0000-0000-0000-000000000003',
      loan_id: 'LOAN-001',
      applicant_name: null,
      uploaded_by: '00000000-0000-0000-0000-000000000004',
      uploaded_at: '2026-01-01T10:00:00+00:00',
      finalized_at: null,
      current_stage: 'UPLOADED',
      assigned_to: null,
      reupload_count: 0,
      reupload_allowed_until: null,
      is_deleted: false,
      created_at: '2026-01-01T10:00:00+00:00',
      updated_at: '2026-01-01T10:00:00+00:00',
    })
    expect(result.artifacts).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// CaseListResponseSchema
// ---------------------------------------------------------------------------

describe('CaseListResponseSchema', () => {
  it('parses valid list response', () => {
    const result = CaseListResponseSchema.parse({
      cases: [],
      total: 0,
      limit: 10,
      offset: 0,
    })
    expect(result.total).toBe(0)
  })
})
