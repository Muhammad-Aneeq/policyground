import '@testing-library/jest-dom/vitest'

/**
 * jsdom implements no layout, so `Element.prototype.scrollIntoView` does not exist.
 *
 * Stubbed here rather than guarded inside the components, because the absence is a property of the
 * test environment and not of the product: every real browser has it, and adding a
 * `typeof el.scrollIntoView === 'function'` check to production code to satisfy a test double
 * would be the test dictating the implementation.
 *
 * Two components rely on it — `HighlightedPassage` (scroll the cited passage into view) and
 * `Chat` (scroll the matching source card into view when a superscript is clicked).
 */
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {
    /* no-op: jsdom has no layout engine */
  }
}
