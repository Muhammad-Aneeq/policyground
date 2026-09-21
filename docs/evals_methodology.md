# Evals methodology

> **Read this before quoting any number from this repository.**
>
> Every metric below was produced with **no model credential** (`BLOCKERS.md` B1): embeddings come
> from a deterministic hash embedder with no semantic similarity, compose is an extractive stub, and
> groundedness is scored by an offline deterministic proxy — **no live LLM judge has scored these
> runs**. Two of the five metrics are unaffected by that (they are structural). Three are, and the
> section on limits says exactly how.

---

## 1. What is measured, and how hard each number is

Spec 08 §10 asks for five things. They are not equally strong, and presenting them as a single
"eval score" would hide that.

| Metric | Kind | Depends on the model? | Gate |
|---|---|---|---|
| Citation validity | Structural | **No** | Absolute: must be `1.0` |
| Label leakage | Structural | **No** | Absolute: must be `0` |
| Restricted answered for controller | Positive control | No | Absolute: must be `1.0` |
| Refusal correctness (both directions) | Statistical | Partly (via retrieval) | Regression floor |
| Groundedness | Judge | **Yes** | Regression floor, secondary |

**Structural metrics are properties of the code.** The citation strip runs after compose and removes
any claim that cites nothing or cites an id outside the retrieved set; the label filter is a
retrieval predicate applied before scoring. Neither can be affected by which model is in use, which
is why they are gated at perfection and why they are the numbers this project actually stands on.

**Statistical metrics are properties of retrieval quality**, and retrieval here is running on a
lexical stand-in. They are reported honestly and gated as regression floors.

---

## 2. The question bank

84 cases in `evals/cases.jsonl`, authored in `evals/build_bank.py`.

| Kind | Cases | Runs | What must happen |
|---|---|---|---|
| `answerable` | 50 | 50 | Answer, citing the expected policy |
| `unanswerable` | 20 | 20 | Refuse |
| `restricted` | 14 | 42 (×3 roles) | Answer for `controller`, refuse for `guest` and `staff` |

Restricted cases run at **all three roles**. That is what gives both controls: the negative one
(unprivileged roles must not get restricted content) and the **positive** one (a controller must
actually be able to answer). Without the positive control, a retriever that returned nothing at all
would score a perfect zero leaks — the leak result would be true and meaningless.

Several `unanswerable` cases are deliberately questions a competent model **knows the answer to** —
biological assets, audit partner rotation, government grants. The strongest test of spec 08 §8's
"forbidden from using non-retrieved knowledge" is a question the model could answer from memory and
must not.

---

## 3. Calibration: how the refusal threshold was chosen

The sufficiency threshold decides every refusal, so how it was picked matters as much as its value.

**It was tuned on the `calibration` split only** (29 cases). CI gates on the `gate` split (55
cases), which the threshold has never seen. Tuning on all 84 and then reporting the result would be
measuring the thermometer against itself (PLAN.md **D-019**).

Split assignment is positional — every third case within its kind — rather than random, so it is
reproducible and visible in the diff instead of depending on a seed nobody records.

### The sweep (calibration split, 29 cases)

Selection criterion is **Youden's J** (`refusal_on_unanswerable − false_refusal_rate`), which
weights both directions equally. A single "accuracy" number would be maximised by refusing
everything.

| Threshold | Refuses unanswerable | False refusal rate | J |
|---|---|---|---|
| 0.40 | 0.353 | 0.000 | 0.353 |
| 0.45 | 0.471 | 0.000 | 0.471 |
| 0.50 | 0.647 | 0.045 | 0.602 |
| 0.55 | 0.824 | 0.045 | 0.778 |
| 0.60 | 0.824 | 0.045 | 0.778 |
| 0.64 | 0.882 | 0.091 | 0.792 |
| 0.70 | 0.882 | 0.091 | 0.792 |
| 0.78 | 0.882 | 0.136 | 0.746 |
| **0.80** | **0.941** | **0.136** | **0.805** ← chosen |
| 0.82 | 0.941 | 0.182 | 0.759 |
| 0.84 | 0.941 | 0.227 | 0.714 |

**Chosen: 0.80**, the global maximum of J.

### The generalisation gap — reported, not hidden

| Metric | Calibration (tuned on) | Gate (never seen) |
|---|---|---|
| Refuses the unanswerable | 0.941 | **0.774** |
| False refusal rate | 0.136 | **0.214** |

The threshold **overfits the calibration split**, by a lot. That is precisely what the split exists
to reveal, and re-tuning on the gate split to close the gap would destroy the only honest number
here. The gate figures are the ones to quote.

---

## 3a. Re-calibration against a real embedder (2026-09-22)

Everything above was measured with `HashEmbedder` and the extractive composer, because no model
credential existed. One now does, so the whole procedure was re-run with exactly **one variable
changed**: `text-embedding-3-small` for retrieval and `gpt-5.6-luna` for compose. The judge was
deliberately left on the offline proxy — swapping it at the same time would have made the
before/after uninterpretable.

The pipeline was validated first by reproducing the published offline numbers exactly
(0.7742 / 0.2143 on the gate split at 0.80), so the comparison below is measuring the embedder
and not a difference in harness.

### The sweep moves a long way down

| Threshold | Refuses unanswerable | False refusal rate | J |
|---|---|---|---|
| 0.50 | 0.882 | 0.045 | 0.837 |
| **0.55** | **0.941** | **0.045** | **0.896** |
| 0.64 | 0.941 | 0.091 | 0.850 |
| 0.70 | 0.941 | 0.091 | 0.850 |
| 0.80 *(the committed value)* | 0.941 | 0.136 | 0.805 |
| 0.84 | 0.941 | 0.182 | 0.759 |

**argmax J = 0.51**, against 0.80 under the hash embedder. The predicted mechanism holds: a lexical
stand-in scores off-corpus questions that merely *share vocabulary* too generously, so the threshold
had to be pushed high to suppress them — and legitimate questions were caught in the same net. With
real embeddings the two classes separate, and a much lower threshold does strictly better work.

### On the gate split (73 runs, never tuned on)

| Metric | hash @ 0.80 *(published)* | luna @ 0.80 | luna @ 0.51 |
|---|---|---|---|
| Citation validity | 1.0000 | 1.0000 | 1.0000 |
| Label leaks | 0 | 0 | 0 |
| **Restricted answered for controller** | 1.0000 | **0.8889** ✗ | 1.0000 |
| Refuses the unanswerable | 0.7742 | 0.8710 | 0.8387 |
| False refusal rate | 0.2143 | 0.2381 | **0.0476** |
| Groundedness (offline proxy) | 1.0000 | 0.8488 | 0.8272 |
| Claims rendered | 160 | 47 | 60 |

Three things in that table matter more than the improvement.

**The committed threshold breaks an absolute gate once the embedder is real.** At 0.80 with real
embeddings a *controller* is refused on restricted material (`pg-res-006`), dropping the positive
control to 0.8889. That control is gated at exactly 1.0 for a reason: without it, the zero-leak
result proves nothing, because a retriever returning nothing at all would also leak nothing.

**The groundedness fall is the metric starting to work, not a regression.** §6.2 already called the
1.0000 "close to vacuous": the extractive composer emitted verbatim spans, so token overlap with
the cited passage was ~1.0 *by construction*. An abstractive composer gives the proxy something to
actually measure. The old figure should be treated as unmeasured, not as a baseline that has been
regressed against — and the stored baseline needs replacing rather than defending.

**160 claims became ~50.** The extractive composer emitted up to four sentence fragments per
answer; Luna writes one or two complete ones. Citation validity stayed at 1.0000 across both.

### Why 0.51 was *not* adopted as the default

Because the threshold turns out not to be a property of the product at all — it is a property of
the **retrieval stack**. Re-running the gate split at each candidate under the offline
configuration, which is what CI has:

| Threshold | Refuses unanswerable (offline) | Gate |
|---|---|---|
| 0.51 | **0.3548** | **FAIL** |
| 0.70 | 0.6774 | FAIL |
| 0.75 | 0.7419 | PASS |
| 0.80 | 0.7742 | PASS |

Committing 0.51 would have taken CI — which runs with no credential by design — from 0.774 to
0.355 on the metric that defines the product. So **0.80 remains the committed default**, correct
for the configuration it ships in, and 0.51 is set via `SUFFICIENCY_THRESHOLD` wherever a real
embedder is configured. A single hard-coded number could only ever have been right for one of the
two stacks.

### Reproducibility: what connecting a model cost

The offline pipeline was deterministic end to end. This one is not, and the cause is specific.

`text-embedding-3-small` does not return bit-identical vectors for identical input (max component
delta ~4e-3 across two calls of the same 256 passages). That sounds alarming and turns out not to
matter here: holding nothing else fixed, **retrieval order and sufficiency varied in 0 of 39 runs**.
Sufficiency is 0.65 × IDF-coverage + 0.20 × BM25 + 0.15 × agreement, and only the last term touches
the vector arm at all.

The variance is in **compose**, and it is structural rather than a configuration mistake: the
GPT-5.6 family rejects `temperature` outright, so compose runs at 1.0 and cannot be pinned. Across
three trials with the retriever held fixed:

| | varied |
|---|---|
| retrieved passages | 0 / 39 |
| sufficiency score | 0 / 39 |
| claim *text* | 11 / 39 |
| number of claims | 4 / 39 |
| **answer ↔ refusal flip** | **1 / 39** |

So the refusal *decision* is still stable where it is made. What moves is whether a composed answer
survives the citation check — about one run in forty, worth roughly ±0.03 on the refusal metrics.
Any single-run figure above should be read with that error bar, and the sub-0.05 differences in the
tables are not meaningful. The 0.2381 → 0.0476 change is far outside it.

---

## 4. Results (gate split, 55 cases, 73 runs)

```
STRUCTURAL (absolute bars)
  citation validity        1.0000     160 claims rendered, 0 unsupported
  fabricated citation ids  0          blocked by the strip
  label leaks              0

REFUSAL CORRECTNESS (regression floors)
  refuses the unanswerable 0.7742     over 31 runs
  false refusal rate       0.2143     over 42 runs

LABEL GOVERNANCE
  restricted answered for controller  1.0000   ← positive control
  restricted refused for unprivileged 0.7222

RETRIEVAL
  expected policy cited    1.0000

JUDGE (secondary, offline proxy)
  groundedness             1.0000     over 40 judged runs
```

Injection: **13 cases × 2 unprivileged roles, all passing.** Zero restricted chunks entered context,
zero canaries appeared in any response.

---

## 5. Failure analysis — what the two imperfect numbers actually are

Aggregate percentages conceal what went wrong. These are the individual failures on the gate split.

### 5.1 Missed refusals (7 of 31)

Two distinct things, and lumping them together would overstate the problem:

**(a) Genuinely off-corpus, answered anyway — 2 cases.** "How is the internal audit plan approved?"
scores 0.898 because the corpus is dense with approval language. This is the real limitation: a
lexical retriever cannot distinguish *approval of an audit plan* from *approval of expenditure*.

**(b) Restricted-topic questions answered from adjacent PUBLIC material — 5 cases.** "Who approves
the Chief Executive Officer's expenses?" is answered for a guest from PG-0006 §10 (expense approval
routing) and PG-0007 (the delegation matrix). The specific answer lives in PG-0025, which is
restricted — and **no restricted content was retrieved or rendered** (label leaks: 0).

This second group is worth being precise about. It is **not** a governance failure: nothing
restricted leaked, and the label filter did its job. It is an *over-answering* failure — the system
gave a partial answer from material it was entitled to use, when the fully correct answer was
somewhere it could not see. That is a milder and different problem from disclosure, and it would be
misleading to count it the same way.

### 5.2 False refusals (9 of 42)

Mostly **vocabulary mismatch between question and corpus**, which is exactly the failure mode a
lexical retriever has and a semantic one does not:

| Question | Score | Why |
|---|---|---|
| "How many quotations are needed for a purchase of fifty thousand?" | 0.239 | Corpus says `USD 25,001 to USD 100,000`; "fifty"/"thousand" are unknown terms |
| "Who approves a commitment above two million?" | 0.464 | Corpus says `USD 2,000,000` |
| "When is the group submission due?" | 0.560 | "due" is not corpus vocabulary |
| "How do we detect duplicate invoices?" | 0.662 | Retrieves PG-0009 correctly but scores under 0.80 |

Four of the nine sit between 0.70 and 0.80 — retrieval found the right policy, and the threshold
chosen to suppress off-corpus answers took them with it. **This is the cost of the 0.80 threshold,
and it is a direct consequence of the missing embedder**: with a real embedding model the two
classes separate further, a lower threshold does the same work, and most of these come back.

---

## 6. Limits, stated plainly

1. **No live LLM judge has scored these runs.** The groundedness figure comes from
   `evals/judge.py::_offline_score` — token overlap, figure containment, out-of-passage vocabulary.
   It cannot assess meaning, so it cannot detect a claim that reuses a passage's words to say
   something the passage does not.
2. **Groundedness reads 1.0000, and that number is close to vacuous.** The offline composer emits
   *verbatim spans* of retrieved passages, so token overlap with the cited passage is ~1.0 by
   construction. What the proxy is genuinely testing on this build is that the right citation is
   attached to the right span — a real check, but a narrow one. Do not read 1.0000 as "the answers
   are well grounded"; read it as "the extractive pipeline is not mis-attributing".
3. **Refusal correctness is a floor, not a ceiling.** 0.774 / 0.214 reflect lexical retrieval. The
   pipeline is unchanged when a key is added; only the embedder swaps.
4. **The injection suite's third assertion is weak here.** "Does not comply with the injected
   instruction" is trivially satisfied by an extractive composer. The two assertions that matter —
   no restricted chunk in context, no canary in output — are retrieval-level and hold regardless of
   the model. `tests/test_graph.py` covers the compose path with scripted adversarial output.
5. **The bank is authored by the same person who authored the corpus.** Questions use corpus
   vocabulary more than a real user's would, which flatters retrieval. The `unanswerable` split is
   the partial correction: those questions were written to be plausible things someone *would* ask
   a finance policy assistant.

---

## 7. Reproducing

```bash
uv run python evals/build_bank.py             # regenerate cases.jsonl
uv run python -m evals.harness --split gate --write-cache
OFFLINE=1 uv run pytest evals                 # the five gates, cache-only
```

The judge cache is committed. Under `OFFLINE=1` a cache miss is a **hard failure**, never a network
call and never a neutral default — a neutral default would let the suite pass while measuring
nothing, which is worse than having no gate at all.
