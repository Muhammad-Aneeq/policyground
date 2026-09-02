# PROGRESS.md · PolicyGround

Per-phase log. One entry per phase, appended when the phase's tests are green and the commit lands.
Phase definitions, acceptance criteria and test plans live in `PLAN.md`.

---

## P0 · Plan — **DONE**

**Did.** Read the three ground-truth documents in full (`spec_00_shared_foundations.md`,
`spec_08_policyground.md`, `ten_projects_technical_plans.md`). Surveyed sibling repos in
`../` for patterns worth reusing rather than reinventing:

- `finagent-evals/src/finagent/graders/judge.py` → the pinned + content-addressed + `cache_only`
  judge pattern, and its offline deterministic proxy (adopted as PLAN.md **D-010**)
- `finxpia/corpus/attacks.yaml` → the injection case taxonomy shape
  (`{id, vector, goal, severity, expected_behavior, tags}`) (adopted as **D-014**)
- `trace2evals/frontend/src/components/aurora/` → aurora tokens and the local-barrel approach to
  the design system in a standalone repo (adopted as **D-002**)

Probed the toolchain: Python 3.12.10, uv 0.11.23, Node 24.14.1, npm 11.11.0, git 2.53.
**Absent: `make`, `OPENAI_API_KEY`, Azure CLI/subscription** — all three shape the plan rather than
being discovered mid-build.

**Wrote.** `PLAN.md` (5-line summary · full file map · 10 phases with spec-quoted acceptance criteria,
per-phase test plans and risk notes · external dependencies + fallbacks · 19-entry decisions log ·
cross-cutting risk register). `BLOCKERS.md` with the four known blockers pre-registered.

**Decided (highlights, full log in PLAN.md §5).** LangGraph over Agent Framework, resolving a genuine
conflict between the two ground-truth documents in favour of spec 00 §F which declares itself final
(**D-001**). Labels filter *inside* the retriever so "never enters context" is a property of
retrieval, not caller discipline (**D-003**). Citation check drops fabricated citation ids as well as
absent ones (**D-007**). Canary strings make label-leak testing an exact assertion (**D-018**).
Question bank split calibration/gate so the sufficiency threshold is not tuned on the test set
(**D-019**).

**Notable.** Two ground-truth documents disagree on Track-2 orchestration. Rather than pick silently,
the conflict and its resolution are recorded in the decisions log — spec 00 §F ("STACK LOCK (final,
applies everywhere)") specifies LangGraph on both tracks, and spec 08 §4 F3 describes a
LangGraph-shaped graph, so `ten_projects`' Agent Framework header is the outlier.

**Next.** P1 — scaffold, then author the 30-policy corpus against `corpus/constants.yaml` with an
automated consistency check.

---

## P1 · Scaffold + corpus authoring + consistency pass — **DONE**

**Did.** Scaffolded the repo (uv/hatchling src layout, ruff, mypy strict, CI with separately-named
eval gates, MIT licence, `.gitattributes` normalising to LF so content hashes do not churn between
Windows and CI). Authored the corpus and built the machinery that keeps it honest.

**Corpus.** 30 policies, **21,797 words**, **256 sections**, labelled **10 public / 14 internal /
6 restricted**. Coverage per spec 08 F1: capitalisation thresholds (PG-0003/0004/0005), expense and
T&E rules (PG-0006/0010), approval matrices (PG-0007/0008), revenue recognition (PG-0011–0014), plus
close and control (PG-0015–0020), leases, receivables, inventory and impairment (PG-0027–0030). The
revenue policies are generic principles in the authors' own words — no standard text is reproduced.
The six restricted policies each state a distribution list and *why* they are restricted, so the
label reads as a property of the content rather than a flag applied at random.

**The consistency machinery.** `corpus/constants.yaml` declares 41 shared facts once each, with a
regex. `pg corpus check` enforces AGREEMENT, COVERAGE and NO-ORPHAN across all 30 policies, plus
canary uniqueness and cross-reference integrity. It passed on the first run.

**Notable.** The mutation tests matter more than the passing check. Eight of them copy the corpus to
a temp directory, break it one way each — drift a threshold, delete a reference, quote a shared
number without registering it, duplicate a canary, remove one, dangle a `PG-00xx` reference — and
assert the checker catches it. Two further tests assert what must *not* fail it: a phrase wrapped
across lines at the 100-character margin, and `USD 5000` versus `USD 5,000`. Without those, the
check would be either vacuous or so brittle that authors would learn to ignore it.

**Next.** P2 — chunking, ingestion, and the label-aware hybrid retriever.

---

## P2 · Chunking + ingestion + local hybrid retriever with labels — **DONE**

**Did.** Section-aware chunking (256 chunks, one per authored section — none needed splitting at the
1,400-character cap, longest is 1,375), the `Retriever` Protocol, `LocalHybridRetriever`
(BM25 + vector + RRF), the deterministic `HashEmbedder` fallback, index persistence with provenance,
and `pg ingest --rebuild` as the one-command rebuild.

**The label filter.** Applied to the candidate set *before* either arm scores anything. The
Protocol has no `search_all`, no `include_restricted` flag and no `labels` override — the bypass an
injection attempt would look for does not exist. `get_chunk` is separately label-checked, so a
leaked chunk id is not a read primitive around the retriever, and it returns `None` for both
"forbidden" and "absent" so the two are indistinguishable.

**Two retrieval problems found by smoke-testing rather than assumed away.** Both were invisible to
the tests as first written, and both would have shown up later as a bad false-refusal rate:

1. The two arms indexed different text. A section headed *"4. Accommodation"* was nearly unfindable,
   because policy prose rarely repeats its own subject. Both arms now index `Chunk.indexable_text`
   (title + section path + body) — one definition, four callers (**D-020**).
2. `"How much can I claim for a hotel per night?"` ranked *§5 Meals* above *§4 Accommodation*, purely
   because §5 says "per" more often ("per diem", "per full day"). Query-side stopword filtering fixed
   it; document tokens are left intact so BM25's length normalisation stays honest (**D-021**).

After both, five of six probe questions hit the correct section at rank 1.

**`withheld_count` was rewritten.** The obvious implementation — count disallowed chunks sharing a
term with the query — reported ~50 of 256 for *every* question and communicated nothing. It now
fuses the unfiltered ranking and counts how many of its top-k the role may not see, which answers
the question the roles demo is actually asking (**D-022**). A guest asking about capitalisation gets
0; a guest asking about executive severance gets 4, and the controller gets PG-0021 directly. That
is the roles demo, working.

**Landed early from P8.** `AzureSearchRetriever` and the AI Search index schema, because the shared
contract test needs both implementations to exist. `tests/test_retriever_contract.py` runs the same
assertions against both, using a fake client that *honours* the OData filter — a bare Mock would
record that `filter=` was passed while happily returning restricted documents, making every leak
assertion pass vacuously. The Azure label filter is an allow-list, not a deny-list, so a label added
tomorrow is invisible until access is granted deliberately. **None of it has run against live
Azure** (BLOCKERS.md B2), and the test module says so in its own docstring.

**Notable.** The index records the embedder that built it and refuses to load under a different one.
Without that guard, adding an API key and restarting without re-ingesting would embed queries with
OpenAI against hash-embedder vectors — no error, just quietly meaningless retrieval and a rising
refusal rate that no log would explain.

**Numbers.** 164 tests green; ruff clean; mypy strict clean across 21 modules.

**Next.** P3 — the LangGraph graph, the claims schema, the citation strip, and the refusal path.
