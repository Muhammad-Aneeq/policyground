/**
 * Types mirroring the backend schema.
 *
 * `AskResponse` is a **discriminated union on `kind`**, exactly as the backend defines it
 * (PLAN.md D-015). This is the front-end half of the guarantee that a refusal can never be
 * rendered as an answer: TypeScript narrows on `kind`, and the `Refusal` type simply has no
 * `claims` property to read. Getting it wrong is a compile error, not a styling slip.
 */

export type SensitivityLabel = 'public' | 'internal' | 'restricted'
export type Role = 'guest' | 'staff' | 'controller'

export const ROLES: readonly Role[] = ['guest', 'staff', 'controller'] as const

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  guest: 'Public policies only',
  staff: 'Public and internal policies',
  controller: 'Everything, including restricted policies',
}

export interface Claim {
  text: string
  citation_ids: string[]
}

export interface Citation {
  citation_id: string
  policy_id: string
  policy_title: string
  section_path: string
  label: SensitivityLabel
  version: string
  snippet: string
  start: number
  end: number
}

export interface ClosestSection {
  policy_id: string
  policy_title: string
  section_path: string
  score: number
}

export interface RetrievalTrace {
  backend: string
  role: Role
  top_k: number
  retrieved: number
  /** Count of passages the label filter removed from this role's top-k. Never their content. */
  withheld_count: number
  sufficiency: number
  threshold: number
  allowed_labels: SensitivityLabel[]
  embedder: string
  degraded: boolean
}

export interface Answer {
  kind: 'answer'
  query_id: string
  question: string
  claims: Claim[]
  citations: Citation[]
  trace: RetrievalTrace
  stripped_claims: number
  created_at: string
}

export interface Refusal {
  kind: 'refusal'
  query_id: string
  question: string
  message: string
  reason: 'insufficient_evidence' | 'no_surviving_claims' | 'empty_retrieval'
  closest_sections: ClosestSection[]
  trace: RetrievalTrace
  suggestion_prompt: string
  created_at: string
  // Note the absence of `claims` and `citations`. That absence is the point.
}

export type AskResponse = Answer | Refusal

export interface TraceStep {
  node: string
  detail: string
}

export interface AskTraceResponse {
  response: AskResponse
  node_path: string[]
  steps: TraceStep[]
  raw_claim_count: number
  stripped_claim_count: number
}

export interface PolicySummary {
  policy_id: string
  title: string
  label: SensitivityLabel
  version: string
  owner: string
  category: string
  effective_date: string
}

export interface PolicyList {
  role: Role
  policies: PolicySummary[]
  visible_count: number
  hidden_count: number
  hidden_labels: SensitivityLabel[]
}

export interface PolicySection {
  chunk_id: string
  section_path: string
  start: number
  end: number
}

export interface PolicyDetail {
  policy_id: string
  title: string
  label: SensitivityLabel
  version: string
  owner: string
  category: string
  effective_date: string
  markdown: string
  sections: PolicySection[]
}

export interface EvalRunPoint {
  at: string
  commit: string
  groundedness: number
  citation_validity: number
  refusal_accuracy: number
  false_refusal_rate: number
  label_leaks: number
  cases: number
  passed: boolean
  offline: boolean
  judge: string
}

export interface AdminMetrics {
  total_queries: number
  answered: number
  refused: number
  refusal_rate: number
  avg_sufficiency: number
  unanswered_unique: number
  unanswered_total_asks: number
  claims_stripped: number
  answers_with_stripped_claims: number
  queries_by_role: Record<string, number>
  refusals_by_reason: Record<string, number>
  corpus_labels: Record<string, number>
  eval_runs: EvalRunPoint[]
  degraded: boolean
  app_mode: string
}

export interface UnansweredEntry {
  id: string
  query_text: string
  times_asked: number
  role: string
  refusal_reason: string
  closest_sections: ClosestSection[]
  first_asked_at: string
  last_asked_at: string
}

export interface UnansweredLog {
  entries: UnansweredEntry[]
  total_unique: number
  total_asks: number
}

export interface Health {
  status: string
  app_mode: string
  degraded: boolean
  synthetic_corpus: boolean
  roles: Role[]
  labels: SensitivityLabel[]
}

/** Narrowing helper, so components read `isAnswer(r)` rather than comparing string literals. */
export function isAnswer(response: AskResponse): response is Answer {
  return response.kind === 'answer'
}

export function isRefusal(response: AskResponse): response is Refusal {
  return response.kind === 'refusal'
}
