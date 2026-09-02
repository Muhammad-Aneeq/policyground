# Architecture

## The shape of the thing

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  FRONTEND — Vite + React + aurora components                                  │
│                                                                               │
│  Chat            Source Viewer      Admin              Roles demo             │
│  ─────           ─────────────      ─────              ──────────             │
│  claims with     full policy,       groundedness       one question,          │
│  superscripts    passage            trend · refusal    three roles,           │
│  + sources       highlighted by     rate · unanswered  side by side           │
│  side panel      CHAR OFFSET        log + CSV export                          │
│                                                                               │
│  Answer and Refusal are SEPARATE COMPONENTS rendering SEPARATE TYPES.          │
│  A refusal has no `claims` field to render.                                   │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │  POST /api/ask {question, role}
┌───────────────────────────────▼──────────────────────────────────────────────┐
│  FastAPI                                                                      │
│    /api/ask · /api/answer/{id} · /api/policies[/{id}] · /api/admin/*          │
│    role parsed HERE and nowhere else (simulated session, spec 08 §11)         │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────────┐
│  LangGraph — spec 08 §8, asserted by test_node_path_matches_the_spec_diagram  │
│                                                                               │
│   retrieve ──► assess_sufficiency ──┬── below threshold ──► refuse ──► END    │
│      │               (deterministic)│                          │              │
│      │                              └── sufficient ──► compose │              │
│      │                                                    │    │              │
│      │                                            citation_check              │
│      │                                                    │                   │
│      │                                     ┌── nothing survived ──► refuse    │
│      │                                     └── claims kept ──► answer ──► END │
└──────┼───────────────────────────────────────────────────────────────────────┘
       │
┌──────▼───────────────────────────────────────────────────────────────────────┐
│  Retriever (Protocol) — search(query, *, role, top_k)                         │
│                                                                               │
│  NO search_all. NO include_restricted. NO labels override.                    │
│  The label filter is not something a caller does; it is what retrieval IS.    │
└──────┬──────────────────────────────────────────┬────────────────────────────┘
       │ APP_MODE=local                           │ APP_MODE=azure
┌──────▼──────────────────────┐       ┌───────────▼──────────────────────────┐
│ LocalHybridRetriever         │       │ AzureSearchRetriever                 │
│                              │       │                                      │
│ label filter → candidates    │       │ OData filter (allow-list) sent with  │
│   ├── BM25 (rank-bm25)       │       │ every query; AI Search applies it     │
│   └── vector (numpy)         │       │ server-side, before returning         │
│         └── RRF fusion k=60  │       │   search_text + vector_queries        │
│                              │       │   fused server-side by RRF k=60       │
│ ✅ runs, tested              │       │ 🟡 compiles, contract-tested, NEVER   │
│                              │       │    DEPLOYED (BLOCKERS.md B2)          │
└──────────────────────────────┘       └──────────────────────────────────────┘
       │                                            │
       └────────────► logs ◄────────────────────────┘
              SQLite (dev) / Postgres (prod)
        documents · chunks · queries · answers · unanswered · eval_runs
```

---

## The four load-bearing decisions

### 1. The label filter is a retrieval predicate, not a post-filter

`Retriever.search` takes a `role` and has no way to ask for unfiltered results. In
`LocalHybridRetriever`, the permitted candidate set is computed *before* either arm scores anything.

Why it matters: a post-filter satisfies a leak test on the final answer while restricted text has
already been loaded, ranked, logged and traced. Filtering first means the text is never read.

There is a second, quieter benefit. Retrieve-then-filter silently returns fewer than `top_k` results
to unprivileged roles, so a guest gets a thinner evidence set and refuses more — which reads as poor
retrieval rather than as the governance behaviour it actually is.

### 2. Citations are enforced after the model, not requested before it

`answers/citation_check.py::strip_uncited` is a pure function over plain data. It drops **two**
classes:

- claims with no citations
- claims citing an id that is not in the retrieved set

The second is the dangerous one. A fabricated id renders as a superscript identical to a real one;
the reader sees evidence-backed prose and has no way to tell. An implementation handling only the
first class lets the more convincing failure through.

Because it is pure, it is tested against **hand-written adversarial model output** rather than
against whatever the composer happened to emit — which matters here, since the offline composer is
extractive and structurally incapable of the failures the strip exists to catch.

### 3. Answer and Refusal are different types

`Refusal` has no `claims` field. Not an empty list — no field. Spec 08 §9 requires refusals to be
"styled distinctly, never like a normal answer"; with one response type carrying `refused: bool`
that is a convention the UI must remember. With two types it is something the UI *cannot get
wrong*, in Python and in TypeScript, and a test asserts a refusal renders no answer-shaped
container.

### 4. `APP_MODE` is read in exactly one function

`retrieval/factory.py::build_retriever`. Everything downstream receives a `Retriever` and cannot
tell which one it got. If a second `if settings.app_mode == ...` ever appears elsewhere, the claim
that the two modes behave identically has quietly stopped being structural.

`tests/test_retriever_contract.py` runs the same assertions against both implementations, using a
fake Search client that *honours* the OData filter — a bare Mock would record that `filter=` was
passed while returning restricted documents anyway, making every leak assertion pass vacuously.

---

## Data flow for one question

```
"What is the capitalisation threshold for IT equipment?"  role=staff
   │
   ├─ retrieve       6 chunks, all label ∈ {public, internal}; 0 withheld
   ├─ assess         IDF-weighted coverage 1.00 · BM25 0.87 · agreement 0.80 → 0.944
   │                 0.944 ≥ 0.80 threshold → sufficient
   ├─ compose        4 draft claims, each citing a chunk id
   ├─ citation_check 4 kept, 0 stripped, 0 unknown ids
   └─ Answer         claims[] + citations[] + trace{sufficiency, withheld, embedder, degraded}
                     → persisted to queries + answers
```

```
"How do we account for executive severance?"  role=guest
   │
   ├─ retrieve       6 chunks, all public; 6 withheld by the label filter
   ├─ assess         coverage 0.29 (severance/retention unmatched) → 0.340
   │                 0.340 < 0.80 → insufficient
   ├─ refuse         ← compose is NEVER CALLED. Zero tokens.
   └─ Refusal        message + closest_sections + withheld_count=6
                     → persisted to queries + unanswered (folded onto one row by times_asked)
```

Same question at `role=controller`: sufficiency 0.997, answered, citations carry `label: restricted`.

---

## Where each guarantee is implemented

| Guarantee | Module | Test |
|---|---|---|
| Uncited claims stripped | `answers/citation_check.py` | `tests/test_citation_check.py` |
| Fabricated ids stripped | same, `ALL_CITATIONS_UNKNOWN` branch | same |
| Zero claims → refusal | `graph/nodes.py::citation_check` | `tests/test_graph.py` |
| Restricted never in context | `retrieval/local_retriever.py::_permitted_indices` | `evals/test_label_leakage.py` |
| Forbidden ≡ absent (404, not 403) | `api/routes_corpus.py` | `tests/test_api.py` |
| Refusal not styled as answer | `answers/schema.py` + `components/RefusalCard.tsx` | `frontend/src/test/rendering.test.tsx` |
| Highlight points at the cited passage | char offsets from `corpus/loader.py` | `tests/test_chunker.py` + frontend test |
| Corpus is self-consistent | `corpus/consistency.py` | `tests/test_corpus_consistency.py` (8 mutation tests) |
| Index matches its embedder | `retrieval/vector_store.py::load_index` | `tests/test_ingest_and_index.py` |
| Graph matches the spec diagram | `graph/build.py` | `tests/test_graph.py` |

---

## What is deliberately absent

- **No re-ranker.** On 256 chunks, hybrid RRF ranks well enough, and a cross-encoder would add
  per-query cost for a gain the eval could not distinguish from noise at this corpus size.
- **No semantic ranker in AI Search.** Same reason, plus it is a per-query charge and spec 00 §D is
  explicit about keeping spend small.
- **No incremental ingest.** `pg ingest --rebuild` always builds the whole index. A second code path
  could produce a *different* index from the same corpus, and every guarantee downstream rests on
  the index matching the policies. Embedding the whole corpus costs $0.001.
- **No migrations.** v1 has no upgrade path worth preserving; a schema change means deleting a
  rebuildable dev database. Real migrations belong with the first real deployment, and the runbook
  says so rather than pretending otherwise.
- **No admin authentication.** Spec 00's cross-project decision is "no auth on self-hosted demos".
  The role switch is a *simulation* of an authenticated session and the UI says so — what is real is
  that the role travels to the retriever and the filter runs there.
