import { useState } from 'react'
import { ask, usePolicies } from '../api/client'
import { ROLES, type AskResponse, type Role, isAnswer } from '../api/types'
import { Card, EmptyState, RiskTag, StatBadge } from '../components/aurora'

/**
 * Screen 4 (spec 08 section 9): "toggle role → watch restricted content vanish".
 *
 * This screen asks **one question at all three roles at once** and shows the three outcomes side
 * by side, rather than making the viewer flip a toggle and remember what the previous state looked
 * like. Same question, same corpus, same code — the only variable is the session role, which is
 * what makes the control legible.
 *
 * Two things vanish together, and that pairing is the point: passages disappear from *retrieval*
 * (so the answer becomes a refusal), and policies disappear from the *source browser* (so they
 * cannot be read around the retriever either).
 */

const DEMO_QUESTIONS = [
  {
    text: 'How do we account for executive severance and retention awards?',
    note: 'Restricted (PG-0021). Only a controller can answer this.',
  },
  {
    text: 'What is the accounting for purchase price allocation on an acquisition?',
    note: 'Restricted (PG-0022).',
  },
  {
    text: 'How are litigation provisions measured?',
    note: 'Restricted (PG-0023).',
  },
  {
    text: 'What is the capitalisation threshold for IT equipment?',
    note: 'Public (PG-0003). Every role answers this identically.',
  },
]

type RoleOutcome = { role: Role; response: AskResponse | null; error: boolean }

export function RolesDemo() {
  const [question, setQuestion] = useState(DEMO_QUESTIONS[0]!.text)
  const [outcomes, setOutcomes] = useState<RoleOutcome[] | null>(null)
  const [running, setRunning] = useState(false)

  const guestPolicies = usePolicies('guest')
  const staffPolicies = usePolicies('staff')
  const controllerPolicies = usePolicies('controller')

  async function runAllRoles(text: string) {
    setRunning(true)
    setOutcomes(null)
    try {
      const results = await Promise.all(
        ROLES.map(async (role): Promise<RoleOutcome> => {
          try {
            return { role, response: await ask({ question: text, role }), error: false }
          } catch {
            return { role, response: null, error: true }
          }
        }),
      )
      setOutcomes(results)
    } finally {
      setRunning(false)
    }
  }

  const counts: Record<Role, number | undefined> = {
    guest: guestPolicies.data?.visible_count,
    staff: staffPolicies.data?.visible_count,
    controller: controllerPolicies.data?.visible_count,
  }

  return (
    <div className="space-y-4">
      <Card as="section">
        <h1 className="font-display text-xl font-semibold text-ink">Same question. Three roles.</h1>
        <p className="mt-1 text-sm text-ink-muted">
          The label filter runs <strong>inside the retriever</strong>, so restricted passages never
          enter model context for an unprivileged role. They are not retrieved and then hidden —
          they are never read.
        </p>

        <div className="mt-4 flex flex-wrap gap-1.5">
          {DEMO_QUESTIONS.map((candidate) => (
            <button
              key={candidate.text}
              type="button"
              title={candidate.note}
              onClick={() => {
                setQuestion(candidate.text)
                void runAllRoles(candidate.text)
              }}
              className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                question === candidate.text
                  ? 'border-accent-line bg-accent-wash font-medium text-accent-fg'
                  : 'border-line bg-surface text-ink-muted hover:border-accent-line hover:text-accent-fg'
              }`}
            >
              {candidate.text}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => void runAllRoles(question)}
          disabled={running}
          className="mt-3 rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-card transition-colors hover:bg-accent-fg disabled:opacity-40"
          data-testid="run-all-roles"
        >
          {running ? 'Asking at all three roles…' : 'Ask at all three roles'}
        </button>
      </Card>

      <div className="grid gap-3 lg:grid-cols-3">
        {ROLES.map((role) => {
          const outcome = outcomes?.find((candidate) => candidate.role === role)
          const response = outcome?.response ?? null
          const answered = response !== null && isAnswer(response)

          return (
            <Card
              key={role}
              as="section"
              data-testid={`role-column-${role}`}
              className={
                response === null
                  ? ''
                  : answered
                    ? 'border-l-4 border-l-accent'
                    : 'border-caution-line bg-caution-wash'
              }
            >
              <header className="mb-2 flex items-center justify-between">
                <h2 className="font-display text-sm font-semibold capitalize text-ink">{role}</h2>
                <StatBadge
                  label="policies visible"
                  value={counts[role] ?? '—'}
                  tone={role === 'controller' ? 'good' : 'neutral'}
                />
              </header>

              {response === null ? (
                <p className="text-xs text-ink-soft">
                  {running ? 'Asking…' : 'Run the question to compare outcomes.'}
                </p>
              ) : answered ? (
                <div>
                  <span className="rounded bg-accent px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                    Answered
                  </span>
                  <p className="mt-2 line-clamp-4 text-xs leading-relaxed text-ink">
                    {response.claims[0]?.text}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {[...new Set(response.citations.map((c) => c.label))].map((label) => (
                      <RiskTag key={label} label={label} />
                    ))}
                  </div>
                  <p className="mt-2 text-[11px] text-ink-soft">
                    {response.citations.length} source
                    {response.citations.length === 1 ? '' : 's'} · sufficiency{' '}
                    {response.trace.sufficiency.toFixed(2)}
                  </p>
                </div>
              ) : (
                <div>
                  <span className="rounded bg-caution px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                    Refused
                  </span>
                  <p className="mt-2 text-xs font-medium leading-relaxed text-caution-fg">
                    Not found in the policies at this role.
                  </p>
                  {response.trace.withheld_count > 0 ? (
                    <p
                      className="mt-2 text-[11px] font-medium text-caution-fg/80"
                      data-testid={`withheld-${role}`}
                    >
                      {response.trace.withheld_count} passage
                      {response.trace.withheld_count === 1 ? '' : 's'} withheld by the label filter.
                    </p>
                  ) : null}
                  <p className="mt-2 text-[11px] text-ink-soft">
                    sufficiency {response.trace.sufficiency.toFixed(2)} · threshold{' '}
                    {response.trace.threshold.toFixed(2)}
                  </p>
                </div>
              )}
            </Card>
          )
        })}
      </div>

      <Card as="section">
        <h2 className="pg-eyebrow">The source browser vanishes too</h2>
        <p className="mt-1 text-sm text-ink-muted">
          Filtering only retrieval would leave the documents readable through the policy list. Both
          surfaces apply the same rule.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {ROLES.map((role) => {
            const query = { guest: guestPolicies, staff: staffPolicies, controller: controllerPolicies }[
              role
            ]
            return (
              <div key={role} className="rounded-lg border border-line bg-surface-sunken p-3">
                <div className="pg-eyebrow mb-1">{role}</div>
                <div className="font-display text-2xl font-semibold tabular-nums text-ink">
                  {query.data?.visible_count ?? '—'}
                  <span className="text-sm font-normal text-ink-soft"> / 30</span>
                </div>
                {query.data && query.data.hidden_count > 0 ? (
                  <div className="mt-1 text-[11px] font-medium text-caution-fg">
                    {query.data.hidden_count} hidden ({query.data.hidden_labels.join(', ')})
                  </div>
                ) : (
                  <div className="mt-1 text-[11px] font-medium text-accent-fg">nothing hidden</div>
                )}
              </div>
            )
          })}
        </div>
      </Card>

      {outcomes === null && !running ? (
        <EmptyState title="Nothing to compare yet" icon="⇄">
          Pick a question above and run it. Restricted topics answer for a controller and refuse for
          everyone else.
        </EmptyState>
      ) : null}
    </div>
  )
}
