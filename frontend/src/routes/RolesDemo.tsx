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
        <h1 className="font-display text-lg text-slate-100">Same question. Three roles.</h1>
        <p className="mt-1 text-sm text-slate-400">
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
                  ? 'border-emerald-brand/40 bg-emerald-brand/10 text-emerald-300'
                  : 'border-white/10 text-slate-400 hover:border-white/25 hover:text-slate-200'
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
          className="mt-3 rounded-lg bg-emerald-brand/20 px-4 py-2 text-sm font-medium text-emerald-300 transition-colors hover:bg-emerald-brand/30 disabled:opacity-40"
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
                    ? 'border-emerald-brand/30 bg-emerald-brand/[0.06]'
                    : 'border-amber-400/40 bg-amber-400/[0.08]'
              }
            >
              <header className="mb-2 flex items-center justify-between">
                <h2 className="font-display text-sm capitalize text-slate-200">{role}</h2>
                <StatBadge
                  label="policies visible"
                  value={counts[role] ?? '—'}
                  tone={role === 'controller' ? 'good' : 'neutral'}
                />
              </header>

              {response === null ? (
                <p className="text-xs text-slate-500">
                  {running ? 'Asking…' : 'Run the question to compare outcomes.'}
                </p>
              ) : answered ? (
                <div>
                  <span className="rounded bg-emerald-brand/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                    Answered
                  </span>
                  <p className="mt-2 line-clamp-4 text-xs leading-relaxed text-slate-300">
                    {response.claims[0]?.text}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {[...new Set(response.citations.map((c) => c.label))].map((label) => (
                      <RiskTag key={label} label={label} />
                    ))}
                  </div>
                  <p className="mt-2 text-[11px] text-slate-500">
                    {response.citations.length} source
                    {response.citations.length === 1 ? '' : 's'} · sufficiency{' '}
                    {response.trace.sufficiency.toFixed(2)}
                  </p>
                </div>
              ) : (
                <div>
                  <span className="rounded bg-amber-400/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                    Refused
                  </span>
                  <p className="mt-2 text-xs leading-relaxed text-amber-100/80">
                    Not found in the policies at this role.
                  </p>
                  {response.trace.withheld_count > 0 ? (
                    <p
                      className="mt-2 text-[11px] text-amber-300/80"
                      data-testid={`withheld-${role}`}
                    >
                      {response.trace.withheld_count} passage
                      {response.trace.withheld_count === 1 ? '' : 's'} withheld by the label filter.
                    </p>
                  ) : null}
                  <p className="mt-2 text-[11px] text-slate-500">
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
        <h2 className="font-display text-sm uppercase tracking-wide text-slate-400">
          The source browser vanishes too
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Filtering only retrieval would leave the documents readable through the policy list. Both
          surfaces apply the same rule.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {ROLES.map((role) => {
            const query = { guest: guestPolicies, staff: staffPolicies, controller: controllerPolicies }[
              role
            ]
            return (
              <div key={role} className="rounded-lg border border-white/10 p-3">
                <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">{role}</div>
                <div className="font-display text-2xl tabular-nums text-slate-100">
                  {query.data?.visible_count ?? '—'}
                  <span className="text-sm text-slate-500"> / 30</span>
                </div>
                {query.data && query.data.hidden_count > 0 ? (
                  <div className="mt-1 text-[11px] text-amber-300/80">
                    {query.data.hidden_count} hidden ({query.data.hidden_labels.join(', ')})
                  </div>
                ) : (
                  <div className="mt-1 text-[11px] text-emerald-300/80">nothing hidden</div>
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
