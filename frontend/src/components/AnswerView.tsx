import type { Answer } from '../api/types'
import { Card, ConfidencePill, StatBadge } from './aurora'
import { CitationSuperscript } from './CitationSuperscript'

/**
 * A cited answer.
 *
 * Every claim carries at least one superscript, because the backend guarantees it: uncited claims
 * were stripped before this component ever saw them. The UI therefore has no "citation missing"
 * branch — if one were reachable, the control upstream would already have failed.
 */
export function AnswerView({
  answer,
  activeCitation,
  onSelectCitation,
}: {
  answer: Answer
  activeCitation: string | null
  onSelectCitation: (citationId: string) => void
}) {
  // Stable numbering: source [1] is the same passage in the prose and in the side panel.
  const numbering = new Map(answer.citations.map((c, i) => [c.citation_id, i + 1]))

  return (
    <Card
      // The accent edge is the answer's signature, opposite the refusal's tinted surface.
      className="border-l-4 border-l-accent"
      data-testid="answer-card"
      aria-label="Cited answer"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="rounded bg-accent px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
          Answer
        </span>
        <ConfidencePill score={answer.trace.sufficiency} threshold={answer.trace.threshold} />
        {answer.stripped_claims > 0 ? (
          <StatBadge
            label="stripped"
            value={answer.stripped_claims}
            tone="warn"
            title="Claims removed by the citation check: uncited, or citing a passage that does not exist"
          />
        ) : null}
        {answer.trace.withheld_count > 0 ? (
          <StatBadge
            label="withheld"
            value={answer.trace.withheld_count}
            tone="warn"
            title="Passages the label filter removed from your results at this role"
          />
        ) : null}
      </div>

      <div className="space-y-3 leading-relaxed">
        {answer.claims.map((claim, claimIndex) => (
          <p key={claimIndex} data-testid="claim" className="text-ink">
            {claim.text}
            {claim.citation_ids.map((citationId) => (
              <CitationSuperscript
                key={citationId}
                index={numbering.get(citationId) ?? 0}
                citationId={citationId}
                active={activeCitation === citationId}
                onSelect={onSelectCitation}
              />
            ))}
          </p>
        ))}
      </div>
    </Card>
  )
}
