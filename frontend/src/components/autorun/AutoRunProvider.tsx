'use client'

/**
 * AutoRunProvider — client-side orchestrator for the 7-level auto-run.
 *
 * Triggered by ZIP upload success (and manual "Auto-run all" button). Fires
 * verification levels L1 → L5 sequentially via the per-level trigger
 * endpoint, then L6 via phase1Start. Emits per-step state so the modal +
 * minimized dock + cases list indicator all render from one source of truth.
 *
 * Persistence: state is mirrored to localStorage on every change. A
 * hard-navigation keeps the UI in sync (tick stays ticked), but any step
 * mid-flight at the moment of a tab close/refresh cannot finish — we mark
 * such steps `failed` with reason "interrupted" on mount and expose a
 * "Resume" action so the user can restart from the next pending step.
 *
 * Scope: single-case sequential runs, multi-case queue (one case at a time
 * per browser tab). Cross-tab coordination is out of scope for MVP.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from 'react'
import { cases as casesApi } from '@/lib/api'
import type { VerificationLevelNumber } from '@/lib/types'

// Sub-step IDs that mean "the level early-bailed because upstream data
// (an extraction, a classified artifact) wasn't available yet". When any
// of these are present on a BLOCKED result, ``rerunAll`` will re-fire the
// level — the extraction is now likely present, so re-running produces a
// real verdict instead of the same empty CRITICAL.
//
// Sub-step IDs NOT in this set (eg. ``gps_vs_aadhaar``, ``ration_owner_rule``,
// ``opus_credit_verdict`` with CRITICAL severity) represent real audit
// concerns against real data — re-running doesn't change the verdict and
// wastes tokens, so we deliberately skip those levels.
const MISSING_DATA_SUB_STEPS: ReadonlySet<string> = new Set([
  'bureau_report_missing',
  'bank_statement_missing',
  'loan_agreement_missing',
  'business_visit_gps',
  'scoring_inputs_missing',
  'credit_analyst_failed',
  'bank_analyst_failed',
  'scoring_analyst_failed',
  'house_scorer_failed',
  'business_scorer_failed',
])

// CaseStage values that mean "ingestion worker is done — extractions are
// flushed to case_extractions, verification levels are safe to fire".
// Append-only list; keep in sync with backend app/enums.py::CaseStage.
const READY_STAGES = new Set<string>([
  'INGESTED',
  'PHASE_1_DECISIONING',
  'PHASE_1_REJECTED',
  'PHASE_1_COMPLETE',
  'PHASE_2_AUDITING',
  'PHASE_2_COMPLETE',
])

/**
 * Figure out which AutoRun steps actually need re-firing on a "Re-run all"
 * click. The goal is to avoid re-paying $0.05-$0.15 on an L1.5 / L2 / L5
 * Opus call when the prior run already produced a real verdict against
 * real data.
 *
 * Returns a Set of step keys that meet any of:
 *   - No verification_result exists for the level (never ran).
 *   - Latest result is BLOCKED with at least one ``*_missing`` /
 *     ``*_failed`` sub_step_id (recoverable now that upstream data exists).
 *   - L6_DECISIONING has no DecisionResult, or the latest is PENDING /
 *     FAILED (stuck or failed — safe to re-fire).
 *
 * A level whose latest result is PASSED / PASSED_WITH_MD_OVERRIDE, or
 * BLOCKED with non-recoverable CRITICALs (real audit issues), is omitted
 * from the set and won't be re-run.
 */
async function identifyStepsNeedingRerun(
  caseId: string,
): Promise<Set<AutoRunStepKey>> {
  const needed = new Set<AutoRunStepKey>()

  let overview: Awaited<ReturnType<typeof casesApi.verificationOverview>> | null = null
  try {
    overview = await casesApi.verificationOverview(caseId)
  } catch {
    // No overview → nothing ran yet → run everything.
    return new Set(STEP_ORDER.map((s) => s.key))
  }

  // Latest result per level (overview.levels may carry multiple rows per
  // level across re-runs; keep the newest by ``completed_at``).
  const latestByLevel = new Map<string, (typeof overview.levels)[number]>()
  for (const r of overview.levels) {
    const prev = latestByLevel.get(r.level_number)
    const newer =
      !prev ||
      new Date(r.completed_at ?? r.started_at ?? 0) >
        new Date(prev.completed_at ?? prev.started_at ?? 0)
    if (newer) latestByLevel.set(r.level_number, r)
  }

  const verLevels: AutoRunStepKey[] = [
    'L1_ADDRESS',
    'L1_5_CREDIT',
    'L2_BANKING',
    'L3_VISION',
    'L4_AGREEMENT',
    'L5_SCORING',
    'L5_5_DEDUPE_TVR',
  ]
  await Promise.all(
    verLevels.map(async (step) => {
      const latest = latestByLevel.get(step)
      if (!latest) {
        needed.add(step)
        return
      }
      const status = String(latest.status).toUpperCase()
      if (status === 'PASSED' || status === 'PASSED_WITH_MD_OVERRIDE') {
        return // real verdict — skip
      }
      // BLOCKED / FAILED — fetch issues to decide.
      try {
        const detail = await casesApi.verificationLevelDetail(
          caseId,
          step as VerificationLevelNumber,
        )
        const hasRecoverable = detail.issues.some((i) =>
          MISSING_DATA_SUB_STEPS.has(i.sub_step_id),
        )
        if (hasRecoverable) needed.add(step)
        // Else: real audit-grade CRITICAL (ration_owner_rule,
        // gps_vs_aadhaar, etc.) — re-running won't change the verdict
        // and wastes tokens. Skip.
      } catch {
        // Fetching detail failed — re-run to be safe.
        needed.add(step)
      }
    }),
  )

  // L6 Decisioning: check the latest DecisionResult.
  try {
    const dr = await casesApi.phase1Get(caseId)
    const st = String((dr as { status?: string } | null)?.status ?? '').toUpperCase()
    if (!dr || st === 'PENDING' || st === 'FAILED' || st === '') {
      needed.add('L6_DECISIONING')
    }
  } catch {
    needed.add('L6_DECISIONING') // 404 → never ran
  }

  return needed
}

/**
 * Poll ``GET /cases/:id`` until ``current_stage`` is in READY_STAGES, or
 * throw on timeout. Called once at the top of ``runAll`` so a fresh upload
 * doesn't fire L1.5 / L2 / etc. before the ingestion worker has flushed
 * the bureau + bank extractions those levels depend on.
 */
async function waitForCaseReady(
  caseId: string,
  opts: { timeoutMs?: number; pollIntervalMs?: number } = {},
): Promise<void> {
  // Slow workers (heavy classifier + extractors + dedupe + checklist
  // validation) on a freshly uploaded case can run 90-150s on a busy host.
  // 120s left some legitimate ingestions failing with "Ingestion did not
  // finish within 120s"; 180s gives enough headroom without dragging on
  // genuinely-stuck cases far past where an operator would notice.
  const timeoutMs = opts.timeoutMs ?? 180_000
  const pollIntervalMs = opts.pollIntervalMs ?? 1_000
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const c = await casesApi.get(caseId)
      if (READY_STAGES.has(c.current_stage)) return
      if (c.current_stage === 'CHECKLIST_MISSING_DOCS') {
        throw new Error(
          'Checklist is missing required documents — upload them and re-trigger auto-run.',
        )
      }
    } catch (err) {
      if (
        err instanceof Error &&
        err.message.startsWith('Checklist is missing')
      ) {
        throw err
      }
      // Transient — fall through to the sleep and retry.
    }
    await new Promise((r) => setTimeout(r, pollIntervalMs))
  }
  throw new Error(
    `Ingestion did not finish within ${timeoutMs / 1000}s — check the case and resume auto-run once the stage is past CHECKLIST_*.`,
  )
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AutoRunStepKey =
  | 'L1_ADDRESS'
  | 'L1_5_CREDIT'
  | 'L2_BANKING'
  | 'L3_VISION'
  | 'L4_AGREEMENT'
  | 'L5_SCORING'
  | 'L5_5_DEDUPE_TVR'
  | 'L6_DECISIONING'

export type AutoRunStepStatus = 'pending' | 'running' | 'done' | 'failed'

export interface AutoRunStep {
  key: AutoRunStepKey
  label: string
  status: AutoRunStepStatus
  errorMessage?: string
  startedAt?: string
  completedAt?: string
}

/**
 * Why a run finished without exercising any individual step.
 *
 * `missing_docs` — the case is in `CHECKLIST_MISSING_DOCS` and `waitForCaseReady`
 *   short-circuited before the per-level loop. We surface this as its own status
 *   ("blocked") so the operator sees "upload missing docs and retry" instead of
 *   the misleading "All steps failed".
 */
export type AutoRunBlockReason = 'missing_docs'

export interface AutoRun {
  caseId: string
  loanId: string | null
  applicantName: string | null
  steps: AutoRunStep[]
  startedAt: string
  completedAt?: string
  /** Set when the run finished early due to a recoverable precondition (e.g.
   * missing required documents). When set, no steps are marked failed; the
   * UI surfaces a remediation banner instead. */
  blockReason?: AutoRunBlockReason
  /** Human-readable description of why the run was blocked. */
  blockMessage?: string
  /** User hit minimize — modal should not auto-open for this run. */
  minimized: boolean
}

interface AutoRunState {
  runs: Record<string, AutoRun>
  /** Which caseId's run is currently being shown in the modal. */
  modalCaseId: string | null
}

const STEP_ORDER: { key: AutoRunStepKey; label: string }[] = [
  { key: 'L1_ADDRESS', label: 'L1 · Address' },
  { key: 'L1_5_CREDIT', label: 'L1.5 · Credit' },
  { key: 'L2_BANKING', label: 'L2 · Banking' },
  { key: 'L3_VISION', label: 'L3 · Vision' },
  { key: 'L4_AGREEMENT', label: 'L4 · Agreement' },
  { key: 'L5_SCORING', label: 'L5 · Scoring' },
  // L5.5 must run between L5 (scoring) and L6 (decisioning) so the dedupe +
  // TVR + NACH + PDC checks have a chance to flag/MD-override before the L6
  // synthesis runs against the gate-clean artifact set.
  { key: 'L5_5_DEDUPE_TVR', label: 'L5.5 · Dedupe + TVR + NACH + PDC' },
  { key: 'L6_DECISIONING', label: 'L6 · Decisioning' },
]

const LS_KEY = 'pfl:autorun:v1'

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type Action =
  | {
      type: 'START'
      caseId: string
      loanId: string | null
      applicantName: string | null
    }
  | { type: 'STEP_START'; caseId: string; key: AutoRunStepKey }
  | { type: 'STEP_DONE'; caseId: string; key: AutoRunStepKey }
  | {
      type: 'STEP_FAILED'
      caseId: string
      key: AutoRunStepKey
      errorMessage: string
    }
  | { type: 'RUN_COMPLETE'; caseId: string }
  | {
      type: 'RUN_BLOCKED'
      caseId: string
      reason: AutoRunBlockReason
      message: string
    }
  | { type: 'MINIMIZE'; caseId: string }
  | { type: 'OPEN_MODAL'; caseId: string }
  | { type: 'CLOSE_MODAL' }
  | { type: 'DISMISS'; caseId: string }
  | { type: 'HYDRATE'; next: AutoRunState }

function reducer(state: AutoRunState, action: Action): AutoRunState {
  switch (action.type) {
    case 'HYDRATE':
      return action.next
    case 'START': {
      const now = new Date().toISOString()
      const steps: AutoRunStep[] = STEP_ORDER.map((s) => ({
        key: s.key,
        label: s.label,
        status: 'pending',
      }))
      return {
        ...state,
        runs: {
          ...state.runs,
          [action.caseId]: {
            caseId: action.caseId,
            loanId: action.loanId,
            applicantName: action.applicantName,
            steps,
            startedAt: now,
            minimized: false,
          },
        },
        modalCaseId: action.caseId,
      }
    }
    case 'STEP_START': {
      const run = state.runs[action.caseId]
      if (!run) return state
      const steps = run.steps.map((s) =>
        s.key === action.key
          ? { ...s, status: 'running' as const, startedAt: new Date().toISOString() }
          : s,
      )
      return {
        ...state,
        runs: { ...state.runs, [action.caseId]: { ...run, steps } },
      }
    }
    case 'STEP_DONE': {
      const run = state.runs[action.caseId]
      if (!run) return state
      const steps = run.steps.map((s) =>
        s.key === action.key
          ? { ...s, status: 'done' as const, completedAt: new Date().toISOString() }
          : s,
      )
      return {
        ...state,
        runs: { ...state.runs, [action.caseId]: { ...run, steps } },
      }
    }
    case 'STEP_FAILED': {
      const run = state.runs[action.caseId]
      if (!run) return state
      const steps = run.steps.map((s) =>
        s.key === action.key
          ? {
              ...s,
              status: 'failed' as const,
              errorMessage: action.errorMessage,
              completedAt: new Date().toISOString(),
            }
          : s,
      )
      return {
        ...state,
        runs: { ...state.runs, [action.caseId]: { ...run, steps } },
      }
    }
    case 'RUN_COMPLETE': {
      const run = state.runs[action.caseId]
      if (!run) return state
      return {
        ...state,
        runs: {
          ...state.runs,
          [action.caseId]: { ...run, completedAt: new Date().toISOString() },
        },
      }
    }
    case 'RUN_BLOCKED': {
      const run = state.runs[action.caseId]
      if (!run) return state
      // Reset every step back to pending — none of them got to run, so showing
      // them as 'failed' would be misleading. The blockReason on the run itself
      // is what drives the UI's "blocked" status badge + banner.
      const steps = run.steps.map((s) => ({
        ...s,
        status: 'pending' as const,
        errorMessage: undefined,
        startedAt: undefined,
        completedAt: undefined,
      }))
      return {
        ...state,
        runs: {
          ...state.runs,
          [action.caseId]: {
            ...run,
            steps,
            blockReason: action.reason,
            blockMessage: action.message,
            completedAt: new Date().toISOString(),
          },
        },
      }
    }
    case 'MINIMIZE': {
      const run = state.runs[action.caseId]
      if (!run) return state
      return {
        ...state,
        runs: { ...state.runs, [action.caseId]: { ...run, minimized: true } },
        modalCaseId: state.modalCaseId === action.caseId ? null : state.modalCaseId,
      }
    }
    case 'OPEN_MODAL':
      return { ...state, modalCaseId: action.caseId }
    case 'CLOSE_MODAL':
      return { ...state, modalCaseId: null }
    case 'DISMISS': {
      const { [action.caseId]: _dropped, ...rest } = state.runs
      return {
        ...state,
        runs: rest,
        modalCaseId: state.modalCaseId === action.caseId ? null : state.modalCaseId,
      }
    }
    default:
      return state
  }
}

const initialState: AutoRunState = { runs: {}, modalCaseId: null }

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface AutoRunContextValue {
  state: AutoRunState
  startAutoRun: (args: {
    caseId: string
    loanId?: string | null
    applicantName?: string | null
  }) => void
  resume: (caseId: string) => void
  /**
   * Force-re-run every level from scratch, ignoring any prior "done"
   * status. Used by the header "Re-run all" button when the operator
   * wants a clean re-pass after fixing an upstream issue (re-uploaded
   * bureau report, extractor re-ran, etc.).
   */
  rerunAll: (args: {
    caseId: string
    loanId?: string | null
    applicantName?: string | null
  }) => void
  minimize: (caseId: string) => void
  openModal: (caseId: string) => void
  closeModal: () => void
  dismiss: (caseId: string) => void
  /** Progress ratio 0..1 for a case; null if no run. */
  getProgress: (caseId: string) => number | null
  /** Convenience status summary for a case (used by cases-list indicator). */
  getStatus: (
    caseId: string,
  ) => 'idle' | 'running' | 'done' | 'done_with_errors' | 'failed' | 'blocked'
}

const AutoRunContext = createContext<AutoRunContextValue | null>(null)

export function useAutoRun(): AutoRunContextValue {
  const ctx = useContext(AutoRunContext)
  if (!ctx) throw new Error('useAutoRun must be used inside <AutoRunProvider>')
  return ctx
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AutoRunProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  // Tracks caseIds we've already kicked off in this tab so hot-reload /
  // React-StrictMode double-mount doesn't double-fire the run.
  const inFlight = useRef<Set<string>>(new Set())

  // Hydrate from localStorage on mount + fix up any in-flight steps (they
  // cannot have survived a tab reload).
  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      const raw = window.localStorage.getItem(LS_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as AutoRunState
      if (!parsed || typeof parsed !== 'object' || !parsed.runs) return
      // Mark any previously-running step as failed with "interrupted" so the
      // UI isn't stuck on a fake spinner.
      for (const r of Object.values(parsed.runs)) {
        r.steps = r.steps.map((s) =>
          s.status === 'running'
            ? { ...s, status: 'failed', errorMessage: 'Interrupted by navigation' }
            : s,
        )
      }
      // On mount we never auto-open the modal — user should re-engage.
      parsed.modalCaseId = null
      dispatch({ type: 'HYDRATE', next: parsed })
    } catch {
      // corrupt localStorage — clear
      window.localStorage.removeItem(LS_KEY)
    }
  }, [])

  // Persist after every change.
  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(LS_KEY, JSON.stringify(state))
    } catch {
      // quota / private mode — drop silently
    }
  }, [state])

  // The runner — invoked by startAutoRun/resume. Walks STEP_ORDER, calls the
  // relevant API for each, updates reducer. Continues past failures so a
  // broken level doesn't strand the others.
  const runAll = useCallback(
    async (
      caseId: string,
      opts: { force?: boolean; onlyKeys?: ReadonlySet<AutoRunStepKey> } = {},
    ) => {
    if (inFlight.current.has(caseId)) return
    inFlight.current.add(caseId)
    try {
      // Fresh-upload dance: startAutoRun fires immediately after finalize /
      // reingest returns, but the async ingestion worker (classifier +
      // checklist validator + extractors) may still be running for another
      // ~5-30 s. L1.5 in particular depends on the ``equifax`` extraction
      // existing in ``case_extractions``; firing it before the extractor
      // flushes produces a spurious ``bureau_report_missing`` CRITICAL.
      //
      // Poll the case stage until it's past INGESTED. Do nothing visible if
      // the case is already ingested (resume / rerun path) — the first poll
      // returns immediately.
      try {
        await waitForCaseReady(caseId)
      } catch (err) {
        const msg =
          err instanceof Error
            ? err.message
            : 'Ingestion did not complete in time'
        // Distinguish "missing required documents" (a recoverable precondition
        // — user uploads the files, the stage auto-flips, retry works) from a
        // genuine pipeline failure. The former gets its own status so the
        // operator isn't told "All steps failed" when nothing actually ran.
        if (msg.startsWith('Checklist is missing')) {
          dispatch({
            type: 'RUN_BLOCKED',
            caseId,
            reason: 'missing_docs',
            message: msg,
          })
          return
        }
        for (const step of STEP_ORDER) {
          dispatch({
            type: 'STEP_FAILED',
            caseId,
            key: step.key,
            errorMessage: msg,
          })
        }
        dispatch({ type: 'RUN_COMPLETE', caseId })
        return
      }

      // Track L6 firing in a local — the belt-and-braces below used to
      // re-read localStorage to decide whether to fire L6, but ``dispatch``
      // + the persistence ``useEffect`` are async, so the snapshot lagged
      // the in-loop dispatch and L6 was firing TWICE on every normal run
      // (wasting ~30-60s and an Opus call per case).
      let l6FiredInLoop = false

      for (const step of STEP_ORDER) {
        // Smart-rerun: when ``onlyKeys`` is passed, skip any level that's
        // not in the set. Mark the skipped ones as ``done`` so the modal
        // reflects "we looked at this, nothing to do" rather than stuck
        // on "pending". Keeps token spend bounded on Re-run all clicks.
        if (opts.onlyKeys && !opts.onlyKeys.has(step.key)) {
          dispatch({ type: 'STEP_DONE', caseId, key: step.key })
          if (step.key === 'L6_DECISIONING') l6FiredInLoop = true
          continue
        }

        // Re-read state from localStorage since the reducer is closed over.
        // On a plain resume, skip steps already done. On a force-re-run,
        // ignore the prior status and fire every step.
        if (!opts.force) {
          const raw = window.localStorage.getItem(LS_KEY)
          const snap = raw ? (JSON.parse(raw) as AutoRunState) : null
          const current = snap?.runs[caseId]?.steps.find((s) => s.key === step.key)
          if (current?.status === 'done') {
            if (step.key === 'L6_DECISIONING') l6FiredInLoop = true
            continue
          }
        }

        dispatch({ type: 'STEP_START', caseId, key: step.key })
        try {
          if (step.key === 'L6_DECISIONING') {
            await casesApi.phase1Start(caseId)
          } else {
            await casesApi.verificationTrigger(caseId, step.key)
          }
          dispatch({ type: 'STEP_DONE', caseId, key: step.key })
          if (step.key === 'L6_DECISIONING') l6FiredInLoop = true
        } catch (err) {
          const msg = err instanceof Error ? err.message : 'Request failed'
          dispatch({
            type: 'STEP_FAILED',
            caseId,
            key: step.key,
            errorMessage: msg,
          })
          // A failed L6 attempt is still a "fired" attempt for the purpose
          // of the belt-and-braces below — re-firing immediately would
          // just re-hit the same backend error. The user re-triggers.
          if (step.key === 'L6_DECISIONING') l6FiredInLoop = true
        }
      }

      // Belt-and-braces for L6: only fires if the main loop never reached
      // the L6_DECISIONING iteration (e.g. an older STEP_ORDER snapshot
      // that didn't include L6, or a future early-return path). The
      // ``l6FiredInLoop`` flag is the source of truth — re-reading
      // localStorage here used to lag the reducer dispatch and double-fire
      // L6 on every normal run.
      const l6AllowedByFilter = !opts.onlyKeys || opts.onlyKeys.has('L6_DECISIONING')
      if (l6AllowedByFilter && !l6FiredInLoop) {
        try {
          dispatch({ type: 'STEP_START', caseId, key: 'L6_DECISIONING' })
          await casesApi.phase1Start(caseId)
          dispatch({ type: 'STEP_DONE', caseId, key: 'L6_DECISIONING' })
        } catch (err) {
          const msg = err instanceof Error ? err.message : 'Request failed'
          dispatch({
            type: 'STEP_FAILED',
            caseId,
            key: 'L6_DECISIONING',
            errorMessage: msg,
          })
        }
      }
      dispatch({ type: 'RUN_COMPLETE', caseId })
    } finally {
      inFlight.current.delete(caseId)
    }
  }, [])

  const startAutoRun = useCallback(
    (args: { caseId: string; loanId?: string | null; applicantName?: string | null }) => {
      dispatch({
        type: 'START',
        caseId: args.caseId,
        loanId: args.loanId ?? null,
        applicantName: args.applicantName ?? null,
      })
      void runAll(args.caseId)
    },
    [runAll],
  )

  const resume = useCallback(
    (caseId: string) => {
      dispatch({ type: 'OPEN_MODAL', caseId })
      void runAll(caseId)
    },
    [runAll],
  )

  const rerunAll = useCallback(
    (args: { caseId: string; loanId?: string | null; applicantName?: string | null }) => {
      // Smart re-run: fetch the current verification snapshot, pick only
      // the levels that genuinely need re-firing (missing extraction
      // recoverables, never-ran levels, stuck L6), and skip anything
      // with a real verdict. Keeps token spend bounded when the operator
      // clicks "Re-run all" on a case where only one upstream artefact
      // has changed.
      dispatch({
        type: 'START',
        caseId: args.caseId,
        loanId: args.loanId ?? null,
        applicantName: args.applicantName ?? null,
      })
      void (async () => {
        const needed = await identifyStepsNeedingRerun(args.caseId)
        await runAll(args.caseId, { force: true, onlyKeys: needed })
      })()
    },
    [runAll],
  )

  const getProgress = useCallback(
    (caseId: string): number | null => {
      const run = state.runs[caseId]
      if (!run) return null
      const total = run.steps.length
      const done = run.steps.filter(
        (s) => s.status === 'done' || s.status === 'failed',
      ).length
      return total === 0 ? 0 : done / total
    },
    [state.runs],
  )

  const getStatus = useCallback(
    (
      caseId: string,
    ): 'idle' | 'running' | 'done' | 'done_with_errors' | 'failed' | 'blocked' => {
      const run = state.runs[caseId]
      if (!run) return 'idle'
      const anyRunning = run.steps.some((s) => s.status === 'running')
      if (anyRunning) return 'running'
      if (run.completedAt) {
        if (run.blockReason) return 'blocked'
        const anyFailed = run.steps.some((s) => s.status === 'failed')
        const allFailed = run.steps.every((s) => s.status === 'failed')
        if (allFailed) return 'failed'
        return anyFailed ? 'done_with_errors' : 'done'
      }
      // No completed_at yet but not running → paused (interrupted)
      return 'running'
    },
    [state.runs],
  )

  const value = useMemo<AutoRunContextValue>(
    () => ({
      state,
      startAutoRun,
      resume,
      rerunAll,
      minimize: (caseId) => dispatch({ type: 'MINIMIZE', caseId }),
      openModal: (caseId) => dispatch({ type: 'OPEN_MODAL', caseId }),
      closeModal: () => dispatch({ type: 'CLOSE_MODAL' }),
      dismiss: (caseId) => dispatch({ type: 'DISMISS', caseId }),
      getProgress,
      getStatus,
    }),
    [state, startAutoRun, resume, rerunAll, getProgress, getStatus],
  )

  return <AutoRunContext.Provider value={value}>{children}</AutoRunContext.Provider>
}
