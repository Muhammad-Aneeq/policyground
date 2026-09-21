import { useEffect, useRef } from 'react'

/**
 * Renders a policy with one passage highlighted (spec 08 section 9, screen 2).
 *
 * The highlight is applied by **character offset**, never by searching for the passage text
 * (PLAN.md D-017). The distinction matters: a policy repeats phrases like "requires Finance
 * Director approval" many times, so a text search would highlight the first occurrence rather than
 * the cited one — and it would look perfectly correct while pointing at the wrong section. The
 * offsets were recorded at ingest against the exact string the API serves, so they cannot drift.
 *
 * The markdown is rendered as pre-formatted text rather than converted to HTML. That is what keeps
 * offsets valid: any transformation to HTML would change the character positions and silently
 * invalidate every citation.
 */
export function HighlightedPassage({
  markdown,
  start,
  end,
}: {
  markdown: string
  start?: number
  end?: number
}) {
  const markRef = useRef<HTMLElement>(null)

  const hasHighlight =
    start !== undefined &&
    end !== undefined &&
    start >= 0 &&
    end > start &&
    end <= markdown.length

  useEffect(() => {
    if (hasHighlight && markRef.current) {
      markRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [hasHighlight, start, end])

  const body = 'whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-ink-muted'

  if (!hasHighlight) {
    return (
      <pre className={body} data-testid="policy-body">
        {markdown}
      </pre>
    )
  }

  return (
    <pre className={body} data-testid="policy-body">
      {markdown.slice(0, start)}
      <mark ref={markRef} className="pg-highlight" data-testid="highlight">
        {markdown.slice(start, end)}
      </mark>
      {markdown.slice(end)}
    </pre>
  )
}
