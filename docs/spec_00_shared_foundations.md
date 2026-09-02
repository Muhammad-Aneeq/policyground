# SPEC 00 · SHARED FOUNDATIONS & PORTFOLIO RULES
### Read first. All 10 project specs depend on this. Build the three foundations before Project 02.

---

## A. THE THREE SHARED FOUNDATIONS (build in week 0-1, before any project)

### A1 · `ax-template` — the repo skeleton
Every project is instantiated from this. Contents:
- `backend/`: FastAPI + Pydantic v2, uv package manager, SQLAlchemy (SQLite dev / Postgres prod), OpenTelemetry pre-wired, structured logging, settings via env (pydantic-settings)
- `frontend/`: Vite + React + TypeScript, Tailwind, shadcn/ui, Recharts, TanStack Query, imports `aurora-ui`
- `evals/`: pytest harness + `cases.jsonl` convention + CI eval-gate job (EVERY repo has this; it is the brand)
- `.github/workflows/ci.yml`: lint (ruff) + typecheck (mypy/pyright) + tests + evals gate
- `docker-compose.yml`, `Makefile` (dev, test, eval, up, down), `LICENSE` (MIT), `README` skeleton
- README skeleton sections (mandatory order): screenshot → one-line pitch → architecture diagram → demo video link → "⚠️ All data synthetic" banner → quickstart → "Built by an ex-accountant turned AI engineer" line
Acceptance: `make up` runs a hello dashboard; `make eval` runs an empty pass; CI green on a fresh clone.

### A2 · `aurora-ui` — the shared design system (React package)
Local workspace package imported by all frontends. Tokens: dark navy `#0B1E3B`, emerald `#10B981`, frosted-glass surfaces, Space Grotesk / Inter. Components: `Card` (frosted), `StatBadge`, `ConfidencePill` (0-1 → color+label), `EvidencePanel`, `TraceTimeline` (step list for agent runs), `RiskTag`, `MetricTile`, `EmptyState`, `SyntheticDataBanner`.
Acceptance: Storybook (or a demo route) renders every component; one import line in any project yields the shared look. This is why every screenshot across 10 repos is recognizably yours.

### A3 · `ledgerfab` — the synthetic finance data engine (Python lib)
Used by Projects 01, 02, 04, 06, 07, 09, 10. Generates: companies, chart of accounts, counterparties (with aliases), invoices (with POs), bank transactions, GL entries, recurring-accrual schedules.
Config knobs: `partial_payment_rate`, `missing_reference_rate`, `duplicate_rate`, `date_format_chaos`, `amount_noise`, `alias_rate`, `fx_rate` (flag-only in v1). Presets: `clean` / `realistic` / `nightmare`. **Seeded → reproducible** (same seed+profile = identical dataset, hash-verifiable).
Also ships: ground-truth emitter (for every generated world, the correct matches/exceptions/answers, so Projects 01/04/06/07 get labels for free).
Acceptance: `ledgerfab.generate(profile, seed)` returns a typed World; `world.ground_truth` gives correct matches; determinism test passes.

**Build order of foundations:** ax-template → aurora-ui → ledgerfab (each ~2-4 days at 10h/wk; ~1 week total before Project 02 kicks off).

---

## B. HARD DEPENDENCY GRAPH (respect this build order)

```
FOUNDATIONS (ax-template, aurora-ui, ledgerfab)
   │
   ├─ 02 Ledger MCP Server ──────────────┐
   │        │                            │
   ├─ 01 Exception Workbench (uses 02)   │
   ├─ 05 XPIA Corpus (uses 02 for demo)  │
   ├─ 04 FinAgent-Evals (uses ledgerfab) │
   │        │                            │
   │        └──────── gates ────► 06 LedgerGuard (uses 02 data, 04 gate, 05 attack)
   │                                      │
   ├─ 03 Trace2Evals (dogfoods 01 traces)│
   │                                      │
   └─ 07 InvoiceOps (uses ledgerfab, reuses 06's Teams-callback pattern)
                                          │
        09 FinSight (independent; cost-gated; FALLBACK = Foundry IQ variant)
                                          │
        08 PolicyGround (independent Azure project)
                                          │
        10 CloseOps (COMPOSES 06 + 09-or-fallback; capstone, last)
```
Rules: never start a project whose upstream isn't built. 06 cannot pass CI until 04's suite exists. 10 cannot integrate its variance drafter until 09 (or its fallback) exists.

---

## C. NDA / EMPLOYMENT SAFETY (applies to ALL 10 — do this before repo #1)
- Confirm your employment agreement permits public open-source side projects. Get it in writing if unclear.
- Everything here is built on PUBLIC docs + SYNTHETIC data, independent of any employer system, architecture, or dataset.
- Never reference employer-internal architectures, prompts, datasets, customers, or numbers in any repo, commit, or post.
- Keep a clean separation: personal GitHub org, personal Azure subscription, personal machine or clearly-personal cloud env.
- If any project idea starts to resemble employer work, change it until it doesn't. This protects eight months of effort.

---

## D. PORTFOLIO COST DISCIPLINE (how side-project Azure bills stay small)
- **One Azure project running at a time.** Build Track-2 projects sequentially; `azd down` when moving on. Never leave multiple hosted agents + Postgres + Fabric capacity running in parallel.
- **Demo-then-down:** Azure projects are deployed for development sessions and recorded demos, then torn down. Every Track-2 README ships an `azd down` note and a "run only during a demo" pattern.
- **Small everything:** mini-class models, burstable Postgres, F2 (not higher) Fabric capacity, pause capacity when idle.
- **Monthly ceiling:** set a personal Azure budget alert (e.g., $75/mo) and a hard cap; if a project would exceed it, use the documented cheaper fallback (FinSight → Foundry IQ; hosted agents → local containers for dev).
- **Every repo publishes `MODEL_COSTS.md`** with a realistic monthly estimate + a "keep it cheap" section. (Cost transparency is also content enterprises love.)
- Track-1 (agnostic) projects are near-free (OpenAI mini-class + static sites); front-loading them keeps spend at ~$0 for the first ~4 months.

---

## E. UNIVERSAL DEFINITION OF DONE (every project)
A project is "launch-ready" only when: screenshot-first README ✓ · architecture diagram ✓ · 60-90s demo video ✓ · `evals/` folder with a CI gate ✓ · synthetic-data banner ✓ · `MODEL_COSTS.md` (Track 2) or "runs ~free" note (Track 1) ✓ · `azd down` / teardown documented (Track 2) ✓ · one launch post drafted ✓.

---

## F. STACK LOCK (final, applies everywhere)
Python everywhere · FastAPI backends · Vite+React+TS frontends (aurora-ui) · **LangChain + LangGraph** for agent orchestration on BOTH tracks · Track-2 packages LangGraph agents as Foundry **hosted containers** (Foundry provides identity/tracing/evals/guardrails/A2A around your LangGraph brain) · OpenAI API (Track 1) / Azure OpenAI (Track 2) · FastMCP 3.x for MCP · OpenAI Agents SDK appears ONLY as a FinAgent-Evals comparison adapter · no LangChain-classic chains (LCEL/LangGraph only). Exception: FinSight (09) uses native Fabric Data Agent + Copilot Studio by design; your value there is the finance example + evals + docs, not custom agent code.
