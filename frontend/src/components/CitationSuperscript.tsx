/**
 * The inline citation marker (spec 08 section 9: "answer with inline citation superscripts").
 *
 * It is a `<button>`, not a `<sup>` with a click handler. Citations are the primary navigation of
 * this product — clicking one moves the reader to the evidence — so it must be reachable by
 * keyboard and announced as interactive. A styled span would look identical and be unusable
 * without a mouse.
 */
export function CitationSuperscript({
  index,
  citationId,
  active,
  onSelect,
}: {
  index: number
  citationId: string
  active: boolean
  onSelect: (citationId: string) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(citationId)}
      data-testid="citation-superscript"
      data-citation-id={citationId}
      aria-label={`Source ${index}: ${citationId}`}
      title={citationId}
      className={`mx-0.5 -translate-y-1 rounded px-1 align-super text-[10px] font-bold tabular-nums transition-colors ${
        active
          ? 'bg-accent text-white'
          : 'bg-accent-wash text-accent-fg ring-1 ring-inset ring-accent-line hover:bg-accent/20'
      }`}
    >
      {index}
    </button>
  )
}
