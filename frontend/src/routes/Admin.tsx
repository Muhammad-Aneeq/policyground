import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { unansweredCsvUrl, useAdminMetrics, useReindex, useUnanswered } from '../api/client'
import { Card, EmptyState, MetricTile, StatBadge, tokens } from '../components/aurora'

/**
 * Screen 3 (spec 08 section 9): groundedness trend, refusal rate, and the exportable unanswered log.
 *
 * Two framing decisions:
 *
 * 1. **Refusal rate is presented as a neutral operating metric, not a failure count.** A refusal is
 *    the system working. What matters is the trend and the reason mix, so the tile shows the rate
 *    beside the split between "the corpus has a gap" and "the model failed to ground itself".
 * 2. **The offline badge is not optional.** Where the groundedness figures came from a
 *    deterministic proxy rather than a pinned judge, the chart says so. A trend line that implies a
 *    model scored these runs when none did would be the exact dishonesty this project argues
 *    against.
 */
export function Admin() {
  const metrics = useAdminMetrics()
  const unanswered = useUnanswered()
  const reindex = useReindex()

  const data = metrics.data
  const runs = data?.eval_runs ?? []
  const offlineRuns = runs.filter((run) => run.offline).length

  const chartData = runs.map((run, index) => ({
    name: run.commit ? run.commit.slice(0, 7) : `run ${index + 1}`,
    groundedness: run.groundedness,
    citation_validity: run.citation_validity,
    refusal_accuracy: run.refusal_accuracy,
  }))

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile
          label="Questions asked"
          value={data?.total_queries ?? '—'}
          caption={`${data?.answered ?? 0} answered · ${data?.refused ?? 0} refused`}
        />
        <MetricTile
          label="Refusal rate"
          value={data ? `${(data.refusal_rate * 100).toFixed(0)}%` : '—'}
          caption="A refusal is the system working, not failing"
        />
        <MetricTile
          label="Claims stripped"
          value={data?.claims_stripped ?? 0}
          tone={data && data.claims_stripped > 0 ? 'warn' : 'good'}
          caption={`across ${data?.answers_with_stripped_claims ?? 0} answer(s)`}
        />
        <MetricTile
          label="Unanswered questions"
          value={data?.unanswered_unique ?? 0}
          caption={`${data?.unanswered_total_asks ?? 0} asks — the policies to write`}
        />
      </div>

      <Card as="section">
        <header className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="pg-eyebrow">Groundedness trend</h2>
          {offlineRuns > 0 ? (
            <StatBadge
              label="offline proxy"
              value={`${offlineRuns}/${runs.length}`}
              tone="warn"
              title="Scored by the deterministic offline proxy, not by a pinned LLM judge. No live judge has scored these runs."
            />
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {data?.degraded ? <StatBadge label="mode" value="degraded" tone="warn" /> : null}
            <StatBadge label="APP_MODE" value={data?.app_mode ?? '—'} />
          </div>
        </header>

        {chartData.length === 0 ? (
          <EmptyState title="No eval runs recorded yet" icon="↗">
            Run <code className="rounded bg-surface-sunken px-1 font-mono">./make.ps1 eval</code> to
            populate the trend. CI writes a row per run.
          </EmptyState>
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: -20 }}>
                <CartesianGrid stroke={tokens.line} />
                <XAxis dataKey="name" stroke="#8A8581" fontSize={11} tickLine={false} />
                <YAxis
                  domain={[0, 1]}
                  stroke="#8A8581"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  contentStyle={{
                    background: tokens.surface,
                    border: `1px solid ${tokens.line}`,
                    borderRadius: 8,
                    fontSize: 12,
                    color: tokens.ink,
                    boxShadow: '0 2px 4px rgba(28,25,23,0.04), 0 4px 12px rgba(28,25,23,0.08)',
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="citation_validity"
                  stroke={tokens.accent}
                  strokeWidth={2}
                  dot={false}
                  name="Citation validity"
                />
                <Line
                  type="monotone"
                  dataKey="groundedness"
                  stroke="#0284C7"
                  strokeWidth={2}
                  dot={false}
                  name="Groundedness"
                />
                <Line
                  type="monotone"
                  dataKey="refusal_accuracy"
                  stroke={tokens.caution}
                  strokeWidth={2}
                  dot={false}
                  name="Refusal accuracy"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <Card as="section">
          <header className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="pg-eyebrow">Unanswered log</h2>
              <p className="mt-1 text-xs text-ink-muted">
                What people asked that the manual could not answer — ranked by how often, because
                that ranking is what makes it a roadmap rather than a list.
              </p>
            </div>
            <a
              href={unansweredCsvUrl}
              download
              className="shrink-0 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-muted shadow-card transition-colors hover:border-accent-line hover:text-accent-fg"
              data-testid="export-csv"
            >
              Export CSV
            </a>
          </header>

          {unanswered.data && unanswered.data.entries.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="pg-eyebrow">
                  <tr>
                    <th className="pb-2 pr-3">Asked</th>
                    <th className="pb-2 pr-3">Question</th>
                    <th className="pb-2">Closest sections</th>
                  </tr>
                </thead>
                <tbody className="align-top">
                  {unanswered.data.entries.map((entry) => (
                    <tr key={entry.id} className="border-t border-line">
                      <td className="py-2 pr-3">
                        <span className="rounded-full bg-caution-wash px-2 py-0.5 text-xs font-semibold tabular-nums text-caution-fg">
                          {entry.times_asked}×
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-ink">{entry.query_text}</td>
                      <td className="py-2 font-mono text-xs text-ink-soft">
                        {entry.closest_sections.map((s) => s.policy_id).join(', ') || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="Nothing unanswered yet" icon="✓">
              Ask something off-corpus in the Chat screen and it appears here.
            </EmptyState>
          )}
        </Card>

        <div className="space-y-4">
          <Card as="section">
            <h2 className="pg-eyebrow mb-2">Refusals by reason</h2>
            {data && Object.keys(data.refusals_by_reason).length > 0 ? (
              <ul className="space-y-1.5 text-sm">
                {Object.entries(data.refusals_by_reason).map(([reason, count]) => (
                  <li key={reason} className="flex justify-between gap-3">
                    <span className="font-mono text-xs text-ink-muted">{reason}</span>
                    <span className="font-semibold tabular-nums text-ink">{count}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-ink-soft">No refusals recorded yet.</p>
            )}
          </Card>

          <Card as="section">
            <h2 className="pg-eyebrow mb-2">Corpus</h2>
            <ul className="space-y-1.5 text-sm">
              {Object.entries(data?.corpus_labels ?? {}).map(([label, count]) => (
                <li key={label} className="flex justify-between gap-3">
                  <span className="capitalize text-ink-muted">{label}</span>
                  <span className="font-semibold tabular-nums text-ink">{count}</span>
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={() => reindex.mutate()}
              disabled={reindex.isPending}
              className="mt-3 w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-muted shadow-card transition-colors hover:border-accent-line hover:text-accent-fg disabled:opacity-40"
            >
              {reindex.isPending ? 'Rebuilding…' : 'Rebuild index from corpus'}
            </button>
          </Card>
        </div>
      </div>
    </div>
  )
}
