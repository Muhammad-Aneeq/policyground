import type { Answer, Citation, Refusal, RetrievalTrace } from '../api/types'

export function makeTrace(overrides: Partial<RetrievalTrace> = {}): RetrievalTrace {
  return {
    backend: 'local-hybrid',
    role: 'staff',
    top_k: 6,
    retrieved: 6,
    withheld_count: 0,
    sufficiency: 0.94,
    threshold: 0.45,
    allowed_labels: ['public', 'internal'],
    embedder: 'hash-embedder-v1',
    degraded: true,
    ...overrides,
  }
}

export function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    citation_id: 'PG-0003::002',
    policy_id: 'PG-0003',
    policy_title: 'Capitalisation Thresholds',
    section_path: '2. Thresholds',
    label: 'public',
    version: '3.4',
    snippet: 'The general capitalisation threshold of USD 5,000 applies to items of PP&E.',
    start: 100,
    end: 400,
    ...overrides,
  }
}

export function makeAnswer(overrides: Partial<Answer> = {}): Answer {
  return {
    kind: 'answer',
    query_id: 'q-1',
    question: 'What is the capitalisation threshold?',
    claims: [
      { text: 'The general capitalisation threshold is USD 5,000.', citation_ids: ['PG-0003::002'] },
      { text: 'IT equipment capitalises from USD 1,000.', citation_ids: ['PG-0003::002'] },
    ],
    citations: [makeCitation()],
    trace: makeTrace(),
    stripped_claims: 0,
    created_at: '2026-09-03T10:00:00Z',
    ...overrides,
  }
}

export function makeRefusal(overrides: Partial<Refusal> = {}): Refusal {
  return {
    kind: 'refusal',
    query_id: 'q-2',
    question: 'What is our cryptocurrency custody policy?',
    message: "I can't find this in the policies.",
    reason: 'insufficient_evidence',
    closest_sections: [
      {
        policy_id: 'PG-0005',
        policy_title: 'Intangible Assets and Internally Developed Software',
        section_path: '4. Cloud and subscription arrangements',
        score: 0.031,
      },
    ],
    trace: makeTrace({ sufficiency: 0.28 }),
    suggestion_prompt: 'Should this be a policy? This question has been logged.',
    created_at: '2026-09-03T10:01:00Z',
    ...overrides,
  }
}
