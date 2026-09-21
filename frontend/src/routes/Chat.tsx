import { useState } from 'react'
import { useAsk } from '../api/client'
import { isAnswer, type AskTraceResponse, type Role } from '../api/types'
import { AnswerView } from '../components/AnswerView'
import { RefusalCard } from '../components/RefusalCard'
import { SourcesPanel } from '../components/SourcesPanel'
import { Card, EmptyState, StatBadge, TraceTimeline } from '../components/aurora'

/**
 * Screen 1 (spec 08 section 9): chat with inline citation superscripts, a sources side panel, and
 * refusals styled distinctly.
 *
 * The branch on `kind` is the whole design. There is no shared "response card" that gets restyled
 * when something goes wrong — `AnswerView` and `RefusalCard` are separate components rendering
 * separate types, so a refusal cannot inherit an answer's styling by accident.
 */

const SUGGESTIONS = [
  { text: 'What is the capitalisation threshold for IT equipment?', hint: 'answerable' },
  { text: 'How much can I claim for a hotel per night?', hint: 'answerable' },
  { text: 'When are sub-ledgers closed at month end?', hint: 'answerable' },
  { text: 'How do we account for cryptocurrency holdings?', hint: 'off-corpus → refusal' },
  {
    text: 'How do we account for executive severance and retention awards?',
    hint: 'restricted → depends on role',
  },
]

export function Chat({ role, onRoleChange: _onRoleChange }: { role: Role; onRoleChange?: (r: Role) => void }) {
  const [question, setQuestion] = useState('')
  const [activeCitation, setActiveCitation] = useState<string | null>(null)
  const [result, setResult] = useState<AskTraceResponse | null>(null)
  const [showTrace, setShowTrace] = useState(false)

  const askMutation = useAsk()

  function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed || askMutation.isPending) return

    setActiveCitation(null)
    askMutation.mutate(
      { question: trimmed, role },
      { onSuccess: (data) => setResult(data) },
    )
  }

  function selectCitation(citationId: string) {
    setActiveCitation(citationId)
    document
      .getElementById(`source-${citationId}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  const response = result?.response ?? null
  const citations = response && isAnswer(response) ? response.citations : []

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="space-y-4">
        <Card as="section">
          <form
            onSubmit={(event) => {
              event.preventDefault()
              submit(question)
            }}
            className="flex gap-2"
          >
            <label htmlFor="question" className="sr-only">
              Ask the policy manual
            </label>
            <input
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask the policy manual…"
              autoComplete="off"
              className="flex-1 rounded-lg border border-line bg-surface px-3.5 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
            />
            <button
              type="submit"
              disabled={askMutation.isPending || question.trim().length === 0}
              className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-card transition-colors hover:bg-accent-fg disabled:opacity-40"
            >
              {askMutation.isPending ? 'Asking…' : 'Ask'}
            </button>
          </form>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion.text}
                type="button"
                onClick={() => {
                  setQuestion(suggestion.text)
                  submit(suggestion.text)
                }}
                title={suggestion.hint}
                className="rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] text-ink-muted transition-colors hover:border-accent-line hover:bg-accent-wash hover:text-accent-fg"
              >
                {suggestion.text}
              </button>
            ))}
          </div>
        </Card>

        {askMutation.isError ? (
          <Card className="border-danger-line bg-danger-wash text-sm text-danger-fg">
            Could not reach the API. Is it running? Try{' '}
            <code className="rounded bg-surface px-1 font-mono">./make.ps1 api</code>.
          </Card>
        ) : null}

        {response === null && !askMutation.isPending ? (
          <EmptyState title="Every claim will carry a citation" icon="§">
            Ask something the manual covers and you get a cited answer. Ask something it does not,
            and you get an explicit refusal with the closest sections — never a guess.
          </EmptyState>
        ) : null}

        {response !== null &&
          (isAnswer(response) ? (
            <AnswerView
              answer={response}
              activeCitation={activeCitation}
              onSelectCitation={selectCitation}
            />
          ) : (
            <RefusalCard refusal={response} role={role} />
          ))}

        {result !== null ? (
          <Card as="section" className="p-4">
            <button
              type="button"
              onClick={() => setShowTrace((current) => !current)}
              className="flex w-full items-center justify-between text-left"
            >
              <span className="pg-eyebrow">How this answer was produced</span>
              <span className="text-xs font-medium text-accent-fg">
                {showTrace ? 'hide' : 'show'}
              </span>
            </button>

            {showTrace ? (
              <div className="mt-3 space-y-3">
                <div className="flex flex-wrap gap-2">
                  <StatBadge label="drafted" value={result.raw_claim_count} />
                  <StatBadge
                    label="stripped"
                    value={result.stripped_claim_count}
                    tone={result.stripped_claim_count > 0 ? 'warn' : 'neutral'}
                    title="Claims removed because they cited nothing, or cited a passage that does not exist"
                  />
                  <StatBadge label="retrieved" value={response?.trace.retrieved ?? 0} />
                  <StatBadge
                    label="withheld"
                    value={response?.trace.withheld_count ?? 0}
                    tone={(response?.trace.withheld_count ?? 0) > 0 ? 'warn' : 'neutral'}
                  />
                  <StatBadge label="embedder" value={response?.trace.embedder ?? '—'} />
                </div>
                <TraceTimeline steps={result.steps} />
              </div>
            ) : null}
          </Card>
        ) : null}
      </div>

      <div className="lg:sticky lg:top-4 lg:h-[calc(100vh-8rem)]">
        <SourcesPanel
          citations={citations}
          activeCitation={activeCitation}
          onSelectCitation={selectCitation}
          role={role}
          withheldCount={response?.trace.withheld_count ?? 0}
        />
      </div>
    </div>
  )
}
