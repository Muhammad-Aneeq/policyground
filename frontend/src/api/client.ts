/**
 * API client and TanStack Query hooks.
 *
 * **The one rule in this file:** every query key that depends on the session role includes the
 * role. The roles demo (spec 08 section 9, screen 4) is a live toggle — flip from controller to
 * guest and restricted content must disappear immediately. A cache key that omitted the role would
 * serve the controller's cached policy list to a guest, and the demo would silently show the
 * opposite of what it claims. That is a governance bug wearing a caching bug's clothes.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type {
  AdminMetrics,
  AskResponse,
  AskTraceResponse,
  Health,
  PolicyDetail,
  PolicyList,
  Role,
  UnansweredLog,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // Non-JSON error body; the status text is the best we have.
    }
    throw new ApiError(detail, response.status)
  }

  return (await response.json()) as T
}

// ------------------------------------------------------------------ ask --

export interface AskInput {
  question: string
  role: Role
}

export function ask(input: AskInput): Promise<AskResponse> {
  return request<AskResponse>('/ask', { method: 'POST', body: JSON.stringify(input) })
}

export function askWithTrace(input: AskInput): Promise<AskTraceResponse> {
  return request<AskTraceResponse>('/ask/trace', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function useAsk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: askWithTrace,
    onSuccess: () => {
      // A refusal changes the unanswered log and the refusal rate, so the admin views are stale
      // the moment an ask completes.
      void queryClient.invalidateQueries({ queryKey: ['admin'] })
    },
  })
}

// -------------------------------------------------------------- corpus --

export function usePolicies(role: Role) {
  return useQuery({
    // `role` in the key: see the module docstring.
    queryKey: ['policies', role],
    queryFn: () => request<PolicyList>(`/policies?role=${role}`),
  })
}

export function usePolicy(policyId: string | undefined, role: Role) {
  return useQuery({
    queryKey: ['policy', policyId, role],
    queryFn: () => request<PolicyDetail>(`/policies/${policyId}?role=${role}`),
    enabled: Boolean(policyId),
    // A 404 here is the label filter working as designed, not a transient failure. Retrying it
    // would delay the "this is not available at your role" message for no reason.
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status === 404 ? false : failureCount < 2,
  })
}

// --------------------------------------------------------------- admin --

export function useAdminMetrics() {
  return useQuery({
    queryKey: ['admin', 'metrics'],
    queryFn: () => request<AdminMetrics>('/admin/metrics'),
  })
}

export function useUnanswered() {
  return useQuery({
    queryKey: ['admin', 'unanswered'],
    queryFn: () => request<UnansweredLog>('/admin/unanswered'),
  })
}

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => request<Health>('/health'),
    staleTime: 60_000,
  })
}

export function useReindex() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => request<{ policies: number; chunks: number }>('/admin/reindex', {
      method: 'POST',
    }),
    onSuccess: () => {
      // Everything derived from the corpus is now stale — including every policy list, which is
      // keyed by role.
      void queryClient.invalidateQueries()
    },
  })
}

export const unansweredCsvUrl = `${BASE}/admin/unanswered.csv`
