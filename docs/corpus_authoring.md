# Corpus authoring — how 30 policies stay consistent

## The problem

A synthetic policy manual is only credible if it does not contradict itself. If PG-0003 says the
capitalisation threshold is USD 5,000 and PG-0007 says USD 6,000, both read perfectly well and a
reader believes whichever they hit first. Proof-reading does not scale to 30 documents and does not
survive edits.

Worse, for this project specifically: an inconsistent corpus produces a **confidently cited wrong
answer** — the exact failure the whole product exists to prevent.

## The mechanism

`corpus/constants.yaml` declares every number appearing in more than one policy — 41 of them — once,
with a regex:

```yaml
capitalisation_threshold_general:
  value: 5000
  unit: USD
  pattern: 'general capitalisation threshold of USD ([\d,]+)'
  referenced_by: [PG-0003, PG-0004, PG-0007, PG-0015]
```

`pg corpus check` enforces three invariants across all 30 policies:

| Invariant | What it catches |
|---|---|
| **AGREEMENT** | Every match of `pattern` anywhere in the corpus captures exactly `value`. A threshold drifting between two policies becomes a failing test. |
| **COVERAGE** | Every policy in `referenced_by` still contains the phrase — catches a reference deleted during an edit. |
| **NO-ORPHAN** | Every policy where the pattern matches is registered, so a new reference joins the agreement check instead of escaping it. |

Plus canary uniqueness (each restricted policy contains its tripwire exactly once and nowhere else)
and cross-reference integrity (every `PG-00xx` mentioned in prose resolves to a real policy).

Matching is case-insensitive and whitespace-normalised, so a phrase may wrap across lines at the
100-character margin. `USD 5000` and `USD 5,000` compare equal.

## Proving the checker works

A checker that never fails proves nothing. `tests/test_corpus_consistency.py` builds a deliberately
broken corpus in a temp directory — eight ways, one per test:

1. Drift a threshold in PG-0007 → AGREEMENT fires.
2. Delete a registered reference → COVERAGE fires.
3. Quote a shared number without registering it → NO-ORPHAN fires.
4. Duplicate a canary into another policy → canary check fires.
5. Edit a canary out of its own policy → canary check fires.
6. Point a cross-reference at PG-0099 → cross-reference check fires.
7. Break two things at once → **both** are reported, not just the first.
8. Two negative controls: a wrapped phrase and `USD 5000` must **not** fail.

Without (7), an author fixing a corpus gets one failure per run. Without (8), the check is brittle
enough that authors learn to ignore it. Both matter as much as the positive cases.

## Ingestion refuses an inconsistent corpus

`ingest/pipeline.py` runs the check before building an index and raises if it fails. A drifted
threshold cannot become a cited answer, because it cannot become an index.

## Authoring a new policy

1. **Front-matter:** `policy_id`, `title`, `label`, `version` (quoted — `version: 3.10` parses as
   the float 3.1 and would look like a regression), `owner`, `effective_date`, `category`, `tags`.
   Unknown keys are rejected, so a misspelled `label` fails loudly rather than silently defaulting a
   restricted document to something permissive.
2. **Filename starts with the policy id**, so a citation resolves to a file without a lookup table.
3. **At least three `##` sections.** Sections are the chunking and citation unit — a citation should
   read "PG-0003 §2", not "chunk 47".
4. **Shared numbers go in `constants.yaml` first**, then into the prose using the declared phrasing.
5. **`label: restricted` requires three things:** a canary in `canaries.yaml`, a **Distribution:**
   line, and a *"Why this policy is restricted"* section. All three are asserted by
   `tests/test_corpus_frontmatter.py` — a restricted policy that reads like a public one fails.
6. `uv run pg corpus check && uv run pg ingest --rebuild`.

## Content rules

- **Own words only.** The revenue-recognition policies (PG-0011 to PG-0014) summarise generic
  principles the way a working manual would. No accounting-standard text is reproduced.
- **Plausible to a practitioner.** The corpus includes the errors real manuals warn about —
  under-absorbed fixed overhead in a bad quarter, splitting a commitment to duck an approval band,
  a provision used for the wrong matter, a supplier bank-detail change. A manual with no failure
  modes reads as generated.
- **Restricted means restricted for a reason.** Each of the six explains *why*: personal data,
  price-sensitive information, legal privilege, or a map of where a tax authority might enquire.
- **Vocabulary matters more than it looks.** Retrieval is lexical in this build, so a section headed
  "4. Accommodation" whose body never says "hotel" is nearly unfindable. That is not a reason to
  stuff keywords — it is a reason to write the way the policy's readers would ask about it.
