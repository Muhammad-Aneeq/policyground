"""The groundedness rubric, and what it can and cannot measure.

Spec 08 §10 asks for a groundedness score; spec 08 §14 says to treat the judge as **secondary** to
deterministic checks and to "publish agreement". This module holds the rubric text and the scoring
scale so both the live judge and the offline proxy score the same dimensions on the same scale.

## What "groundedness" means here, precisely

Given a set of retrieved passages and the claims rendered from them: **is every claim supported by
the passages, and only by the passages?** Not "is the claim true" — a claim can be factually
correct and still ungrounded, which is exactly the failure spec 08 §8 forbids (the compose step is
"forbidden from using non-retrieved knowledge"). Truth is not the test. Provenance is.

## Why the rubric is versioned

``RUBRIC_VERSION`` is part of every cache key. Changing the rubric is therefore a cache miss rather
than a silent reinterpretation of scores that were assigned under different instructions — the
failure that makes a groundedness trend chart meaningless.
"""

from __future__ import annotations

RUBRIC_VERSION = "1"

#: The three dimensions, each scored 0-3.
DIMENSIONS = ("support", "fidelity", "scope")
MAX_PER_DIMENSION = 3

RUBRIC_TEXT = """\
You are grading whether an answer is GROUNDED in the passages it was given. You are not grading
whether the answer is correct, well written, or complete. A factually correct statement that is not
in the passages scores ZERO on support — that is the failure this grading exists to detect.

You will receive:
  - PASSAGES: the only material the answer was allowed to use, each with an id
  - CLAIMS: the rendered answer, each claim with the passage ids it cites

Score three dimensions, each 0-3.

SUPPORT — is each claim actually stated by the passages it cites?
  0  No claim is supported by its cited passage.
  1  Some claims are supported; at least one asserts something its passage does not say.
  2  All claims are supported, but at least one cites a passage that is only tangentially related.
  3  Every claim is stated by, or follows directly from, the passage it cites.

FIDELITY — are figures, thresholds, dates and names reproduced exactly?
  0  A figure or threshold is wrong or invented.
  1  A figure is rounded, converted, or restated in a way that changes it.
  2  Figures are exact, but a qualifier is dropped ("above X" rendered as "at X").
  3  Every figure, threshold, date and role name matches the passage exactly.

SCOPE — does the answer stay inside the passages?
  0  The answer introduces substantial material not in the passages.
  1  The answer adds general knowledge as if it came from the policy.
  2  The answer stays inside the passages but overstates how completely they answer the question.
  3  The answer stays inside the passages, and says plainly where they do not cover the question.

Return JSON only, exactly:
{"support": <0-3>, "fidelity": <0-3>, "scope": <0-3>, "note": "<one sentence>"}
"""


def normalised(scores: dict[str, int]) -> float:
    """Mean of the three dimensions, scaled to 0-1.

    Missing dimensions score 0 rather than being skipped. A judge that returned two of three
    dimensions has not produced a complete judgement, and averaging only what it returned would
    quietly inflate the score.
    """
    total = sum(int(scores.get(dimension, 0)) for dimension in DIMENSIONS)
    return round(total / (len(DIMENSIONS) * MAX_PER_DIMENSION), 4)
