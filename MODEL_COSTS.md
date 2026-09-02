# MODEL_COSTS.md — what PolicyGround costs to run

Required by spec 00 §D ("every repo publishes MODEL_COSTS.md with a realistic monthly estimate +
a 'keep it cheap' section").

> **These are estimates from published list prices, not measurements.** No model call and no Azure
> resource has been billed in this build — there is no API key and no subscription
> (`BLOCKERS.md` B1, B2). The corpus token counts *are* measured; everything downstream of them is
> arithmetic.

---

## 1. Measured corpus size

Counted by `corpus/chunker.py` over the committed corpus, not estimated:

| | |
|---|---|
| Policies | 30 |
| Sections / chunks | 256 (one chunk per authored section; none needed splitting) |
| Words | 21,811 |
| Characters indexed | 169,136 |
| **Tokens indexed** | **≈ 42,300** (at ~4 chars/token for English prose) |
| Average chunk | 661 chars ≈ **165 tokens** |

The indexed text is `Chunk.indexable_text` — policy title + section path + body — which is what
both retrieval arms see and what gets embedded.

---

## 2. One-time: building the index

`text-embedding-3-small` at **$0.02 per 1M tokens**:

```
42,300 tokens ÷ 1,000,000 × $0.02 = $0.00085
```

**≈ $0.001 to embed the entire corpus.** Rounded up to a cent, a full rebuild costs one cent.

This is worth stating plainly because it changes how you think about the corpus: **re-embedding
everything is free.** There is no incremental-ingest optimisation in this project and there does not
need to be — `pg ingest --rebuild` always builds the whole index, which removes a second code path
that could produce a *different* index from the same corpus. The seconds it saves were never worth
the risk, and at $0.001 neither was the money.

---

## 3. Per query

One question, at `RETRIEVAL_TOP_K=6`:

| Step | Tokens | Model | Cost |
|---|---|---|---|
| Embed the question | ~20 in | `text-embedding-3-small` | $0.0000004 |
| Compose — system prompt | ~520 in | `gpt-4o-mini` | |
| Compose — 6 passages | ~990 in | | |
| Compose — question + framing | ~60 in | | |
| Compose — output | ~180 out | | |
| **Input total** | **~1,570** | @ $0.15/1M | $0.000236 |
| **Output total** | **~180** | @ $0.60/1M | $0.000108 |
| | | **Per answered query** | **≈ $0.00035** |

### A refused query costs a fraction of that

The graph refuses **before** calling the compose model — `refuse` terminates immediately rather
than falling through:

| | Tokens | Cost |
|---|---|---|
| Embed the question | ~20 | $0.0000004 |
| Sufficiency assessment | 0 (deterministic) | $0 |
| **Per refused query** | | **≈ $0.0000004** |

**A refusal is roughly 900× cheaper than an answer.** That is not an accident of the design, and it
is worth noticing: the questions you least want a confident answer to are the ones you pay almost
nothing to decline. The economics and the correctness argument point the same way.

### At volume

| Queries / month | Assuming 25% refused | Cost |
|---|---|---|
| 1,000 | 750 answered | **$0.26** |
| 10,000 | 7,500 answered | **$2.63** |
| 100,000 | 75,000 answered | **$26.30** |

**Model cost is not the interesting number in this project.** Infrastructure is.

---

## 4. The eval suite

| Run | Composition | Cost |
|---|---|---|
| Gate split (55 cases, 73 runs) | ~40 answered + ~33 refused | **≈ $0.014** |
| Full bank (84 cases, 112 runs) | | **≈ $0.021** |
| Threshold sweep (21 thresholds × 29 cases) | retrieval only, no compose | **≈ $0.0001** |
| LLM judge, if enabled (40 judged runs, `gpt-4.1`) | ~1,400 in / 60 out each | **≈ $0.14** |

The judge is the most expensive part of the suite and the only part that is cached. That is why:
judgements are content-addressed and committed, so CI re-scores from disk and a run costs **$0**.
Re-pinning the judge invalidates the cache deliberately — a re-pin should be a visible cost, not a
silent reinterpretation of old scores.

---

## 5. Azure infrastructure (AZURE mode)

List prices, East US, at the tiers in `infra/main.bicep`:

| Resource | Tier | Monthly if left running | While torn down |
|---|---|---|---|
| **AI Search** | Basic | **$73.73** | $0 |
| Postgres Flexible | B1ms burstable | $12.41 | $0 |
| Postgres storage | 32 GB | $3.68 | $0 |
| Azure OpenAI | GlobalStandard | $0 idle + tokens | $0 |
| Static Web App | Free | $0 | $0 |
| Key Vault | Standard | ~$0.03 | $0 |
| Log Analytics | PerGB2018 | ~$0 (under 5 GB free) | $0 |
| **Total** | | **≈ $89.85/month** | **$0** |

### The number that matters

| Scenario | Cost |
|---|---|
| **A 2-hour recorded demo, torn down after** | **≈ $0.13** infra + <$0.01 tokens |
| **Left provisioned for a month** | **≈ $90** |

**Roughly 700× difference, and AI Search is ~82% of it — billed by the hour whether you query it or
not.** This is the entire argument for spec 00 §D's demo-then-down discipline, and it is why
`azd down --purge` appears three times in `DEPLOY_RUNBOOK.md`.

It also exceeds the $75/month ceiling spec 00 §D sets, on its own, if left running. That is not a
reason to pick a smaller tier — Basic is the cheapest AI Search tier that supports vector search —
it is a reason to tear down.

---

## 6. Keeping it cheap

1. **`azd down --purge` after every demo.** One line, and it is 99.9% of the bill. Without
   `--purge`, the Key Vault and OpenAI account are soft-deleted, hold their names, and block the
   next deploy.
2. **Run LOCAL mode for development.** It costs nothing and exercises identical logic — the two
   modes differ only in which `Retriever` is constructed. The whole product, including the UI and
   all five eval gates, runs offline.
3. **Refusals are nearly free, so do not tune the threshold down to look better.** Lowering it to
   reduce false refusals converts $0.0000004 refusals into $0.00035 ungrounded answers. That is the
   wrong trade in both directions at once.
4. **The judge cache is committed.** CI scores from disk. A cache miss is a hard failure rather than
   a network call, so an eval run cannot quietly start costing money.
5. **Keep the compose model small.** `gpt-4o-mini` is sized for the task: the compose step
   summarises supplied passages into cited claims. It is not doing the reasoning — the retriever
   found the evidence and the strip enforces the grounding.
6. **Set a budget alert as a backstop** (spec 00 §D):
   ```bash
   az consumption budget create --budget-name policyground-cap --amount 75 \
     --time-grain Monthly --category Cost
   ```

---

## 7. This build's actual spend

**$0.00.**

No model call has been made and no Azure resource provisioned. The corpus was embedded with a
deterministic hash embedder, compose ran as an extractive stub, and groundedness was scored by an
offline proxy (`BLOCKERS.md` B1). The prices above are what it *would* cost with credentials
attached.

*Prices as published October 2025; verify before quoting. Azure and OpenAI both change list prices
without much notice.*
