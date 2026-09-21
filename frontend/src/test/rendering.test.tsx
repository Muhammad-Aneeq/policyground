/**
 * Rendering rules that carry a guarantee, not just a look.
 *
 * The most important test in this file is
 * `a refusal renders no answer-shaped container` — spec 08 section 9 requires refusals to be
 * "styled distinctly, never like a normal answer", and asserting the *absence* of the answer
 * container is how that rule becomes checkable rather than a convention someone has to remember
 * during a redesign.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { AnswerView } from '../components/AnswerView'
import { HighlightedPassage } from '../components/HighlightedPassage'
import { RefusalCard } from '../components/RefusalCard'
import { RoleSwitcher } from '../components/RoleSwitcher'
import { SourcesPanel } from '../components/SourcesPanel'
import { makeAnswer, makeCitation, makeRefusal } from './fixtures'
import type { Role } from '../api/types'

function wrap(ui: React.ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

// ------------------------------------------------------- answer rendering --

describe('AnswerView', () => {
  it('renders one superscript per citation id, in claim order', () => {
    wrap(<AnswerView answer={makeAnswer()} activeCitation={null} onSelectCitation={() => {}} />)

    const claims = screen.getAllByTestId('claim')
    expect(claims).toHaveLength(2)

    const superscripts = screen.getAllByTestId('citation-superscript')
    expect(superscripts).toHaveLength(2)
    expect(superscripts[0]).toHaveTextContent('1')
  })

  it('numbers a citation the same way in the prose and in the sources panel', () => {
    const first = makeCitation({ citation_id: 'PG-0003::002' })
    const second = makeCitation({
      citation_id: 'PG-0007::003',
      policy_id: 'PG-0007',
      section_path: '3. Approval matrix',
    })
    const answer = makeAnswer({
      claims: [
        { text: 'Claim one.', citation_ids: ['PG-0003::002'] },
        { text: 'Claim two.', citation_ids: ['PG-0007::003'] },
      ],
      citations: [first, second],
    })

    wrap(<AnswerView answer={answer} activeCitation={null} onSelectCitation={() => {}} />)

    const superscripts = screen.getAllByTestId('citation-superscript')
    expect(superscripts[0]).toHaveAttribute('data-citation-id', 'PG-0003::002')
    expect(superscripts[0]).toHaveTextContent('1')
    expect(superscripts[1]).toHaveAttribute('data-citation-id', 'PG-0007::003')
    expect(superscripts[1]).toHaveTextContent('2')
  })

  it('reports stripped claims so the citation control is visible when it fires', () => {
    wrap(
      <AnswerView
        answer={makeAnswer({ stripped_claims: 2 })}
        activeCitation={null}
        onSelectCitation={() => {}}
      />,
    )
    expect(screen.getByText('stripped')).toBeInTheDocument()
  })

  it('exposes each superscript as a keyboard-reachable button', () => {
    wrap(<AnswerView answer={makeAnswer()} activeCitation={null} onSelectCitation={() => {}} />)
    for (const node of screen.getAllByTestId('citation-superscript')) {
      expect(node.tagName).toBe('BUTTON')
      expect(node).toHaveAccessibleName()
    }
  })

  it('calls back with the citation id when a superscript is clicked', async () => {
    const onSelect = vi.fn()
    wrap(<AnswerView answer={makeAnswer()} activeCitation={null} onSelectCitation={onSelect} />)

    await userEvent.click(screen.getAllByTestId('citation-superscript')[0]!)
    expect(onSelect).toHaveBeenCalledWith('PG-0003::002')
  })
})

// ------------------------------------------------------ refusal rendering --

describe('RefusalCard', () => {
  it('renders NO answer-shaped container', () => {
    wrap(<RefusalCard refusal={makeRefusal()} role="staff" />)

    // The rule, as an assertion: spec 08 section 9, "never styled like a normal answer".
    expect(screen.queryByTestId('answer-card')).not.toBeInTheDocument()
    expect(screen.queryByTestId('claim')).not.toBeInTheDocument()
    expect(screen.queryByTestId('citation-superscript')).not.toBeInTheDocument()
    expect(screen.getByTestId('refusal-card')).toBeInTheDocument()
  })

  it('leads with "not found" rather than with prose that reads like an answer', () => {
    wrap(<RefusalCard refusal={makeRefusal()} role="staff" />)
    expect(screen.getByTestId('refusal-chip')).toHaveTextContent(/not found in the policies/i)
  })

  it('offers closest sections as links, labelled as not-an-answer', () => {
    wrap(<RefusalCard refusal={makeRefusal()} role="staff" />)

    const list = screen.getByTestId('closest-sections')
    expect(within(list).getByRole('link', { name: /PG-0005/ })).toBeInTheDocument()
    expect(screen.getByText(/not an answer, just the nearest material/i)).toBeInTheDocument()
  })

  it('carries the "should this be a policy?" prompt that feeds the unanswered log', () => {
    wrap(<RefusalCard refusal={makeRefusal()} role="staff" />)
    expect(screen.getByText(/should this be a policy/i)).toBeInTheDocument()
  })

  it('says when passages were withheld, without naming them', () => {
    const refusal = makeRefusal({ trace: makeRefusal().trace })
    refusal.trace = { ...refusal.trace, withheld_count: 4 }

    wrap(<RefusalCard refusal={refusal} role="guest" />)

    const note = screen.getByTestId('withheld-note')
    expect(note).toHaveTextContent('4 passages were withheld')
    expect(note).toHaveTextContent('guest')
    // A count, never a policy id — naming what was withheld would be the disclosure the filter
    // exists to prevent.
    expect(note.textContent).not.toMatch(/PG-\d{4}/)
  })

  it('omits the withheld note entirely when nothing was withheld', () => {
    wrap(<RefusalCard refusal={makeRefusal()} role="staff" />)
    expect(screen.queryByTestId('withheld-note')).not.toBeInTheDocument()
  })

  it('uses a different surface treatment from an answer', () => {
    const { unmount } = wrap(<RefusalCard refusal={makeRefusal()} role="staff" />)
    const refusalClass = screen.getByTestId('refusal-card').className
    unmount()

    wrap(<AnswerView answer={makeAnswer()} activeCitation={null} onSelectCitation={() => {}} />)
    const answerClass = screen.getByTestId('answer-card').className

    expect(refusalClass).not.toEqual(answerClass)

    // Asserted against the *semantic* token, not a palette name. This test used to require the
    // literal strings "amber" and "emerald", which made a theme change look like a governance
    // regression: re-skinning the app failed the one test whose job is to prove a refusal can
    // never be mistaken for an answer. The rule being protected is that the two outcomes do not
    // share a surface — so that is what is checked.
    expect(refusalClass).toContain('caution')
    expect(answerClass).not.toContain('caution')
    expect(answerClass).toContain('accent')
  })
})

// -------------------------------------------------------- sources panel --

describe('SourcesPanel', () => {
  it('marks the active source card', () => {
    wrap(
      <SourcesPanel
        citations={[makeCitation()]}
        activeCitation="PG-0003::002"
        onSelectCitation={() => {}}
        role="staff"
        withheldCount={0}
      />,
    )
    expect(screen.getByTestId('source-card')).toHaveAttribute('data-active', 'true')
  })

  it('shows a sensitivity label on every source', () => {
    wrap(
      <SourcesPanel
        citations={[makeCitation({ label: 'restricted' })]}
        activeCitation={null}
        onSelectCitation={() => {}}
        role="controller"
        withheldCount={0}
      />,
    )
    expect(screen.getByTestId('label-restricted')).toBeInTheDocument()
  })

  it('reports withheld passages as a count in the footer', () => {
    wrap(
      <SourcesPanel
        citations={[]}
        activeCitation={null}
        onSelectCitation={() => {}}
        role="guest"
        withheldCount={3}
      />,
    )
    expect(screen.getByTestId('panel-withheld')).toHaveTextContent('3 passages withheld')
  })

  it('shows an empty state rather than an empty box before the first question', () => {
    wrap(
      <SourcesPanel
        citations={[]}
        activeCitation={null}
        onSelectCitation={() => {}}
        role="staff"
        withheldCount={0}
      />,
    )
    expect(screen.getByText(/no sources yet/i)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------- highlighting --

describe('HighlightedPassage', () => {
  const markdown = '# Policy\n\nAlpha section text.\n\nBeta section text.\n'

  it('highlights by offset, not by searching for the text', () => {
    const start = markdown.indexOf('Beta section text.')
    const end = start + 'Beta section text.'.length

    wrap(<HighlightedPassage markdown={markdown} start={start} end={end} />)

    expect(screen.getByTestId('highlight')).toHaveTextContent('Beta section text.')
  })

  it('highlights the CITED occurrence when a phrase repeats', () => {
    // The failure this guards against: a text search highlights the first match, which looks
    // entirely correct while pointing at the wrong section (PLAN.md D-017).
    const repeated = 'requires approval.\n\nMiddle.\n\nrequires approval.\n'
    const second = repeated.lastIndexOf('requires approval.')

    wrap(
      <HighlightedPassage
        markdown={repeated}
        start={second}
        end={second + 'requires approval.'.length}
      />,
    )

    const body = screen.getByTestId('policy-body')
    const mark = screen.getByTestId('highlight')
    // The highlight must start after the first occurrence, i.e. the text before it contains one.
    expect(body.textContent?.indexOf(mark.textContent ?? '')).toBeLessThan(second)
    expect(body.textContent).toEqual(repeated)
  })

  it('renders the whole policy unhighlighted when no passage is selected', () => {
    wrap(<HighlightedPassage markdown={markdown} />)

    expect(screen.queryByTestId('highlight')).not.toBeInTheDocument()
    expect(screen.getByTestId('policy-body')).toHaveTextContent('Alpha section text.')
  })

  it('ignores an out-of-range offset instead of rendering a broken slice', () => {
    wrap(<HighlightedPassage markdown={markdown} start={5} end={99999} />)
    expect(screen.queryByTestId('highlight')).not.toBeInTheDocument()
  })

  it('preserves the exact document text around the highlight', () => {
    const start = markdown.indexOf('Alpha')
    wrap(<HighlightedPassage markdown={markdown} start={start} end={start + 5} />)
    expect(screen.getByTestId('policy-body').textContent).toEqual(markdown)
  })
})

// ----------------------------------------------------------- role switch --

describe('RoleSwitcher', () => {
  function Harness() {
    const [role, setRole] = useState<Role>('controller')
    return <RoleSwitcher role={role} onChange={setRole} hiddenCount={role === 'guest' ? 20 : 0} />
  }

  it('exposes the three roles as radio options', () => {
    render(<Harness />)
    expect(screen.getAllByRole('radio')).toHaveLength(3)
    expect(screen.getByTestId('role-controller')).toHaveAttribute('aria-checked', 'true')
  })

  it('switches role and surfaces the hidden-policy count', async () => {
    render(<Harness />)
    expect(screen.queryByTestId('hidden-count')).not.toBeInTheDocument()

    await userEvent.click(screen.getByTestId('role-guest'))

    expect(screen.getByTestId('role-guest')).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByTestId('hidden-count')).toHaveTextContent('20 policies hidden')
  })
})
