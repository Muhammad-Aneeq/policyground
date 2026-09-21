import { Link } from 'react-router-dom'
import type { Citation, Role } from '../api/types'
import { EmptyState, EvidencePanel, RiskTag } from './aurora'

/**
 * The citations side panel (spec 08 section 9: "side panel shows sources").
 *
 * Clicking a superscript in the answer marks the matching card active here; clicking the card's
 * link opens the Source Viewer with that passage highlighted. Each card shows its sensitivity
 * label, so a reader can see what an answer is resting on without leaving the chat.
 */
export function SourcesPanel({
  citations,
  activeCitation,
  onSelectCitation,
  role,
  withheldCount,
}: {
  citations: Citation[]
  activeCitation: string | null
  onSelectCitation: (citationId: string) => void
  role: Role
  withheldCount: number
}) {
  return (
    <EvidencePanel
      title="Sources"
      count={citations.length}
      footer={
        withheldCount > 0 ? (
          <p className="text-xs font-medium text-caution-fg" data-testid="panel-withheld">
            {withheldCount} passage{withheldCount === 1 ? '' : 's'} withheld at the {role} role.
          </p>
        ) : (
          <p className="text-xs text-ink-muted">
            Every claim above cites one of these passages. Uncited claims are removed before render.
          </p>
        )
      }
    >
      {citations.length === 0 ? (
        <EmptyState title="No sources yet">
          Ask a question. Sources appear here as soon as an answer cites them.
        </EmptyState>
      ) : (
        citations.map((citation, index) => {
          const active = activeCitation === citation.citation_id
          return (
            <article
              key={citation.citation_id}
              id={`source-${citation.citation_id}`}
              data-testid="source-card"
              data-active={active}
              onClick={() => onSelectCitation(citation.citation_id)}
              className={`cursor-pointer rounded-lg border p-3 transition-all ${
                active
                  ? 'border-accent bg-accent-wash shadow-lift'
                  : 'border-line bg-surface hover:border-line-strong hover:shadow-card'
              }`}
            >
              <header className="mb-1.5 flex items-center gap-2">
                <span
                  className={`rounded px-1.5 text-[10px] font-bold tabular-nums ${
                    active ? 'bg-accent text-white' : 'bg-accent-wash text-accent-fg'
                  }`}
                >
                  {index + 1}
                </span>
                <span className="font-mono text-xs text-ink-muted">{citation.policy_id}</span>
                <RiskTag label={citation.label} />
                <span className="ml-auto text-[10px] text-ink-faint">v{citation.version}</span>
              </header>

              <div className="text-xs font-semibold text-ink">{citation.policy_title}</div>
              <div className="text-[11px] text-ink-soft">{citation.section_path}</div>

              <p className="mt-2 line-clamp-4 text-xs leading-relaxed text-ink-muted">
                {citation.snippet}
              </p>

              <Link
                to={`/sources/${citation.policy_id}?highlight=${encodeURIComponent(citation.citation_id)}`}
                className="mt-2 inline-block text-[11px] font-medium text-accent-fg underline underline-offset-2 hover:text-accent"
                onClick={(event) => event.stopPropagation()}
              >
                Open full policy with this passage highlighted →
              </Link>
            </article>
          )
        })
      )}
    </EvidencePanel>
  )
}
