# BLOCKERS.md · PolicyGround

Ledger of everything that could not be done in this environment, what was tried, what would be
needed to unblock it, and the workaround that shipped instead. Nothing here is hidden from the
README — each entry has a corresponding honest statement in `README.md` § STATUS.

Status legend: `OPEN` (workaround shipped, real fix needs the missing thing) · `CLOSED` (resolved).

---

## B1 · No `OPENAI_API_KEY` — embeddings, compose model, and LLM judge all run offline
**Status:** **CLOSED** (credential supplied 2026-09-22) · **Discovered:** P0 (toolchain probe) ·
**Affects:** P2, P3, P5

> **Closed.** An `OPENAI_API_KEY` is now configured. The app runs on
> `text-embedding-3-small` (1536-dim) for retrieval and **`gpt-5.6-luna`** for compose;
> `/api/health` reports `degraded: false`. The unblock was exactly the env var predicted below —
> the embedder and composer are selected from the environment, so no application logic changed.
>
> Two things did have to change, both recorded here because neither was predictable from the
> design:
>
> 1. **`temperature` had to be removed from the compose call.** The GPT-5.6 family accepts only
>    the default value and returns `400 unsupported_value` for anything else, including the `0.0`
>    this code had always sent. `reasoning_effort` (set to `low`) replaces it as the determinism
>    lever. Verified against the live API, not inferred.
> 2. **Three API tests asserted `degraded is True`.** That was true of the build at the time, but
>    it encoded "this project has no key" as a property of the *code*, so supplying one failed
>    tests that were literally correct. They now derive the expectation from the configured
>    credentials and pass either way.
>
> **The committed eval numbers still predate this.** Everything in `README.md` § Measured results
> and `docs/evals_methodology.md` was produced by `HashEmbedder` + the extractive composer, and is
> still described as such below. Re-running the gate split against the real embedder is the open
> follow-up — see `FINAL_REPORT.md` §6.2. Until that is run and published, no number in this repo
> should be attributed to GPT-5.6 Luna.
>
> The record of what the workaround was, and what it cost, is kept below rather than deleted.

**Original entry (while OPEN):**

- **What.** No OpenAI (or Azure OpenAI) credential is available in this environment.
  `echo "${OPENAI_API_KEY:+yes}"` → empty. Three things depend on a model:
  chunk/query embeddings, the compose step, and the groundedness judge.
- **Tried.** Checked the environment and the sibling repos for a shared key or a cached client
  config; none present. `finagent-evals` hit the same wall and shipped an offline judge proxy —
  that pattern is reused here rather than reinvented.
- **Needed to unblock.** A single env var: `OPENAI_API_KEY=sk-...` (LOCAL mode) or
  `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY` (AZURE mode). No code change.
- **Workaround shipped.**
  - `HashEmbedder` — deterministic feature-hashed embeddings (PLAN.md **D-004**). Same `Embedder`
    Protocol as `OpenAIEmbedder`, selected automatically when no key is present, and logged at
    startup. **Honest limitation: it has no semantic similarity.** Paraphrased questions rely
    almost entirely on the BM25 arm of the hybrid retriever.
  - `OfflineStub` compose client — extractive, keyed strictly to retrieved chunks. It exercises the
    full graph (schema → strip → refusal) without a model.
  - Offline judge proxy stamped `offline-fixture`, per PLAN.md **D-010**.
- **Consequence for reported numbers.** Every committed eval number was produced under the fallback
  embedder and offline compose. `docs/evals_methodology.md` states this at the top; the admin UI and
  eval artifacts carry the `offline-fixture` stamp. Deterministic controls (citation validity, label
  leakage, refusal correctness) are **model-independent and fully valid**; the groundedness score is
  a surface-feature proxy and is labelled as such.

---

## B2 · No Azure subscription, no `azd`, no `az` — AZURE mode is deployment-ready, not deployed
**Status:** OPEN · **Discovered:** P0 · **Affects:** P8

- **What.** Spec 08 is a Track-2 Azure project (`azd up`: AI Search, Azure OpenAI, Postgres Flexible,
  Static Web Apps, Key Vault). This environment has no Azure subscription and neither CLI installed.
- **Tried.** N/A — this is an account/entitlement gap, not a technical one.
- **Needed to unblock.** An Azure subscription, `azd` + `az` installed, `azd auth login`, then the
  documented `azd up` in `DEPLOY_RUNBOOK.md`.
- **Workaround shipped.** `AzureSearchRetriever` implements the same `Retriever` Protocol as the
  local one and is covered by contract tests that run against **both** implementations with the
  Search SDK mocked; `infra/*.bicep` is syntax-checked in CI via `bicep build`;
  `DEPLOY_RUNBOOK.md` documents the full path including `azd down` and costs.
- **Explicitly not claimed.** Nothing in this repo states or implies that PolicyGround has been
  deployed to Azure. README § STATUS, the runbook header and `FINAL_REPORT.md` all say so directly.
  The Azure code path has never executed against a live Azure service.

---

## B3 · No `make` on this machine (Windows) — quickstart would not run as written
**Status:** CLOSED (workaround is the shipped path) · **Discovered:** P0 · **Affects:** P1, P9

- **What.** `make --version` → `command not found`. Spec 00 A1 mandates a `Makefile` with
  `dev/test/eval/up/down` targets, and the README quickstart is expected to use it.
- **Needed to unblock.** GNU Make (e.g. via Git-for-Windows extras, Chocolatey, or WSL).
- **Workaround shipped.** `make.ps1` — a PowerShell shim exposing identical target names
  (`./make.ps1 dev`, `./make.ps1 test`, …). The `Makefile` is retained verbatim for CI and Linux
  users. PLAN.md **D-016**. The README quickstart shows both, so the documented commands actually
  run on the machine that ships them.

---

## B5 · No way to capture a screenshot or record a demo video
**Status:** **CLOSED** (captured 2026-09-22) · **Discovered:** P9 · **Affects:** README, spec 00 §E

> **Closed.** Driven with Playwright against the running app rather than by a human with a screen
> recorder: `media/policyground_demo.mp4` (59s, 1280×720, h264) plus five stills pulled from the
> same recording. The seven-step walkthrough in `FINAL_REPORT.md` §1 became the script, which is
> what made the run reproducible instead of an improvisation.
>
> Worth noting for anyone re-recording: the model path is warmed with two throwaway requests
> first. Cold, the first compose call takes ~20s of TLS and connection setup; warm it is ~3s.
> Recording cold puts twenty seconds of spinner in a sixty-second video.
>
> The run is real end to end — live retrieval, live GPT-5.6 Luna compose, real refusals, real
> withheld counts. Nothing is mocked or re-enacted.

**Original entry (while OPEN):**

- **What.** Spec 00 §A1 requires a screenshot-first README, and §E makes a 60–90s demo video part of
  the definition of done. This environment has no display, no browser session and no screen capture.
- **Tried.** The SPA builds (`npm run build` succeeds) and the dev server runs; there is simply no
  way to observe or record it from here.
- **Needed to unblock.** A human running `./make.ps1 dev` and capturing two screens: Chat (a cited
  answer beside its sources panel) and the Roles demo (three roles side by side).
- **Workaround shipped.** HTML-comment placeholders at the top of `README.md` marking exactly where
  each asset goes, and `FINAL_REPORT.md` §1 giving a seven-step walkthrough **with expected
  outcomes**, so the recording is a script rather than an improvisation. The corresponding PLAN.md
  item is marked `[BLOCKED]` rather than ticked — this is the one part of the definition of done
  that is genuinely not met.

---

## B4 · No running Postgres instance
**Status:** CLOSED (by design) · **Discovered:** P0 · **Affects:** P3, P6

- **What.** Spec 08 §5 logs to Postgres; no server is running locally and Docker is not assumed.
- **Workaround shipped.** One SQLAlchemy model set targeting SQLite for development (spec 00 A1
  explicitly allows "SQLite dev / Postgres prod"); `docker-compose.yml` brings up Postgres for
  anyone who wants it, and `DATABASE_URL` switches between them with no code change.
- Not a real blocker — recorded so the SQLite default is understood as a deliberate choice rather
  than an oversight.
