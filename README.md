# PolicyGround

> **Governed finance RAG: every claim cited, weak retrieval refuses, labels govern what is
> retrievable, groundedness gated in CI.**

⚠️ **All content in this repository is synthetic.** The 30-policy accounting manual under
`corpus/` was authored for this project. It is not any organisation's real policy.

---

## STATUS — read this first

🚧 **Under construction.** This README is filled out in the final phase; see `PLAN.md` for the
phase plan and `PROGRESS.md` for what has landed. Two honest statements hold from the start and
will not change:

- **LOCAL mode is a complete, running, tested product.** Hybrid retrieval (BM25 + vector + RRF
  fusion) is implemented locally, with no cloud dependency.
- **AZURE mode is deployment-ready and has never been deployed.** There is no Azure subscription
  in this build environment (`BLOCKERS.md` B2). The Bicep compiles in CI and the retriever is
  covered by contract tests with the SDK mocked. Nothing here claims otherwise.

There is also no model API key in this environment (`BLOCKERS.md` B1), so embeddings, the compose
step and the groundedness judge run on documented deterministic fallbacks. The controls this
project is actually about — citation validity, label leakage, refusal correctness — are
deterministic and fully valid offline.

---

Built by an ex-accountant turned AI engineer.
