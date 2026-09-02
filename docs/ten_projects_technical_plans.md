# FEATURE & TECHNICAL PLANS · ALL 10 PROJECTS
### Stack policy (locked): Python everywhere · FastAPI backends · Vite + React SPA frontends · OpenAI API (agnostic track) · Azure OpenAI via Foundry (Microsoft track) · LangGraph (agnostic orchestration) · Microsoft Agent Framework (Azure orchestration) · FastMCP 3.x (MCP) · No LangChain-classic.

---

## SHARED FOUNDATIONS (build once, week 0-1, reuse in all 10)

**Repo template (`ax-template`):**
- `backend/` FastAPI + Pydantic v2 + uv package manager + SQLite (dev) / Postgres via SQLAlchemy (prod-ready)
- `frontend/` Vite + React + TypeScript + Tailwind + shadcn/ui + Recharts + TanStack Query
- `evals/` folder in EVERY repo (your signature): pytest-based, golden cases as JSONL
- OpenTelemetry wiring (traces from day one; FastMCP 3 and Agent Framework both emit OTel natively)
- Docker Compose, GitHub Actions CI (lint + tests + evals gate), MIT license, README skeleton (screenshot-first, architecture diagram, demo video link, "all data synthetic" banner, "built by an ex-accountant" line)

**Design system (`aurora-ui`):** small shared React package: dark navy/emerald theme tokens, frosted-glass Card, StatBadge, ConfidencePill, TraceTimeline, EvidencePanel components. Every project imports it: every screenshot recognizably yours.

**Synthetic data engine (`ledgerfab`):** one Python lib used by projects 1, 2, 4, 6, 7, 10: generates companies, chart of accounts, invoices, bank transactions, GL entries with configurable messiness (partial payments %, missing-reference %, duplicate %, date-format chaos, currency noise). Seeded = reproducible datasets.

---

# TRACK 1 · AGNOSTIC (Python + OpenAI + LangGraph)

## PROJECT 1 · Reconciliation Exception Workbench

**MVP features:**
1. Import unmatched transactions + context pack (CSV upload or pull from Project 2's MCP server)
2. Per-exception AI investigation: LangGraph graph gathers context (related invoices, prior txns, counterparty history) → produces 1-3 root-cause hypotheses, EACH with evidence references (doc IDs, txn IDs) and a confidence score
3. Review queue UI: exception list → detail view (hypotheses + clickable evidence panel) → one-click verdict: Confirm / Correct (pick other hypothesis or write own) / Reject
4. Resolution log: every verdict stored with who/when/why
5. Pattern library v1: confirmed resolutions grouped by root-cause type, surfaced as "seen 4 times before" hints on new exceptions

**v2 features:** bulk-confirm similar exceptions; export resolutions report (PDF); pattern-based pre-classification; feedback loop into eval cases.

**Architecture:**
- FastAPI: `/exceptions`, `/exceptions/{id}/investigate`, `/exceptions/{id}/verdict`, `/patterns`
- LangGraph investigation graph: `load_exception → gather_context (parallel tool calls) → hypothesize → self-check (grounding: every claim must cite an evidence ID) → rank`
- Grounding rule enforced in code: hypothesis JSON schema requires `evidence: [ids]`; hypotheses with no evidence are dropped (never shown)
- DB tables: exceptions, evidence_items, hypotheses, verdicts, patterns
- Evals: 30 seeded exception cases with known root causes; measure top-1 hypothesis accuracy + evidence validity

**Key decisions/risks:** hypothesis quality depends on context richness → ship with ledgerfab-generated context packs so the demo always has meat. Keep the investigation graph ≤5 nodes; resist agent sprawl.
**Milestones (5 wks):** W1 data model + ledgerfab integration · W2 LangGraph investigation + grounding schema · W3 review UI · W4 patterns + evals · W5 polish, demo video, README.

---

## PROJECT 2 · Ledger MCP Server

**MVP features:**
1. FastMCP 3.x server, Streamable HTTP transport (stdio for local), 7 tools MAX (tool-bloat kills agent performance): `get_bank_transactions`, `get_gl_entries`, `get_invoice`, `search_counterparty`, `propose_match`, `flag_exception`, `get_period_summary`
2. Configurable messiness profiles (clean / realistic / nightmare) via ledgerfab, seeded for reproducibility
3. Stateful sessions: proposed matches and flags persist per session; agents can build on prior work
4. Live Viewer web page: browse the synthetic books + real-time feed of tool calls (WebSocket) — the demo magic
5. One-line connect docs for Claude Desktop, ChatGPT, LangGraph, Agent Framework

**v2:** scenario packs (month-end, audit, fraud-seeded); auth (FastMCP granular authorization); hosted public demo instance with rate limits.

**Architecture:**
- FastMCP 3 server (decorators, Pydantic schemas per tool, OTel on) + FastAPI sidecar for the viewer API + WebSocket event bus (tool-call events published to viewer)
- SQLite per session (cheap isolation); ledgerfab seeds on session create
- Versioned tool names on breaking changes (`propose_match_v2` pattern)
- Evals: contract tests per tool + a scripted LangGraph client that must complete a full reconciliation on the "realistic" profile in CI

**Risks:** hosting a public instance invites abuse → v1 ships self-host-first (docker compose up), public demo later with auth. MCP Inspector used throughout dev.
**Milestones (4 wks):** W1 ledgerfab + tool schemas · W2 tools + sessions · W3 live viewer · W4 clients docs, CI client-run, demo video.

---

## PROJECT 3 · Trace2Evals

**MVP features:**
1. Importers: OpenTelemetry JSON, LangSmith export JSONL (two formats only in v1: do them well)
2. Normalizer → unified TraceRun model (steps: model calls, tool calls, handoffs, outcome)
3. Labeling UI: run list → step-by-step timeline (aurora TraceTimeline component) → label Right / Wrong / Partial + failure-tag taxonomy (wrong-tool, bad-args, ungrounded, no-escalation)
4. Export: versioned JSONL eval cases (input, expected behavior, tags) + pytest runner stub
5. CLI: `t2e import`, `t2e export`, `t2e stats` for CI use

**v2:** Foundry trace importer; auto-suggest labels via LLM (human confirms); dedupe similar failures.

**Architecture:** FastAPI + SQLite; pure-Python parsers (no vendor SDKs needed for file imports); React labeling app. Honest README positioning: "the portable, cross-format companion to platform-locked trace-to-dataset features (Langfuse/LangSmith/Foundry have theirs; this one is yours to keep)."
**Evals:** parser fixtures for both formats; golden exports snapshot-tested.
**Milestones (4 wks):** W1 parsers + model · W2 labeling UI · W3 export + CLI + pytest stub · W4 docs, demo on Project 1's traces.

---

## PROJECT 4 · FinAgent-Evals

**MVP features:**
1. Task suite v1: bank reconciliation only, 100 cases across 4 difficulty tiers (generated by ledgerfab, human-audited answers committed to repo)
2. Agent adapter interface (one Python class: `run(case) -> AgentResult(actions, matches, escalations, transcript)`) + two reference adapters: LangGraph, OpenAI Agents SDK
3. Graders: exact-match scoring on matches, escalation-quality rubric (LLM-judge with pinned model + rubric, plus deterministic checks), tool-path validation
4. pass^k: every case run k=4 times; report consistency separately from accuracy
5. Leaderboard SPA: overall scores, per-tier drill-down, failure gallery (worst cases with transcripts), run-vs-run comparison

**v2:** invoice-matching task pack; Foundry/Agent Framework adapter; community-submitted runs via PR with results JSON.

**Architecture:** runner = plain Python (asyncio, budget caps per run); results as JSON artifacts committed per run; leaderboard is a static-friendly SPA reading artifacts (no backend needed for public site: deploy on GitHub Pages). LLM-judge calls pinned to a fixed model+version and cached: reproducibility is the product.
**Honesty in README:** positioned as agent-level complement to DualEntry Labs' model-level benchmark (cited).
**Risks:** judge reliability → every rubric judgment double-scored (judge + deterministic proxy) on a 20-case calibration set; publish judge-agreement stats.
**Milestones (5 wks):** W1 case generation + audit · W2 runner + adapters · W3 graders + calibration · W4 leaderboard · W5 baseline runs published + launch README.

---

## PROJECT 5 · Finance XPIA Corpus

**MVP features:**
1. Attack corpus (~60 cases): instructions hidden in invoice memo fields, poisoned CSV headers/cells, malicious vendor names, trapped remittance PDFs, HTML-comment payloads: each tagged by vector, goal (exfiltrate / misroute / auto-approve), and severity
2. Benign twin corpus (~60 legitimate lookalikes) so false-positive rate is a first-class metric (the gap reviewers flag in existing tools)
3. Promptfoo plugin package (their plugin/dataset format) + PyRIT-compatible dataset export
4. Report dashboard SPA: attack-success heatmap by category, FPR panel, per-attack replay view
5. Responsible-use README: documented patterns only, defensive framing, disclosure guidance

**Architecture:** corpus = YAML cases + generator scripts (parameterized templates so payload strings can be regenerated/varied); thin Python lib exposes corpus to Promptfoo/PyRIT; dashboard reads runner output JSON. No standalone runner: the plugins ARE the delivery mechanism.
**Evals of the evals:** benign corpus must pass a vanilla GPT pipeline with <5% FPR before release (proves twins are genuinely benign).
**Milestones (4 wks):** W1 taxonomy + templates · W2 corpora + benign validation · W3 promptfoo plugin + PyRIT export · W4 dashboard + demo vs. a naive invoice agent (use Project 2 data).

---

# TRACK 2 · MICROSOFT (Python + Agent Framework + Foundry + azd)

**Shared Track-2 foundations:** every project scaffolds with `azd ai agent init` and deploys with `azd up` (Bicep IaC in repo); Microsoft Agent Framework v1.0 for orchestration; Azure OpenAI models kept small/cheap; `azd down` teardown documented in every README; cost table per repo.

## PROJECT 6 · LedgerGuard (flagship)

**MVP = the 7 checks, each demoable in isolation:**
1. Reconciliation agent (Agent Framework) consuming Project 2's MCP server (Foundry supports MCP tools) with `propose_match` etc.
2. Check 1+6 Evals & floor: Project 4 adapter runs in GitHub Actions; deploy job blocked if accuracy < floor (branch protection)
3. Check 2 Human gate: low-confidence matches → Logic App → Teams Adaptive Card (approve/correct) → callback endpoint resumes the run
4. Check 3 Reasons: match JSON schema requires `reason` + `evidence_ids`; unreasoned outputs rejected in code
5. Check 4 Traces: OTel → Foundry tracing; Reviewer Console links every decision to its trace
6. Check 5 Escalation: confidence thresholds in config, abstention path tested by eval cases that SHOULD escalate
7. Check 7 Rollback: agent config versioned (the azd agent manifest); `make rollback VERSION=n` redeploys prior version
8. Entra Agent ID + Foundry guardrails on; Project 5 corpus run against it with results published
9. Reviewer Console SPA: match queue (ConfidencePill), approve/correct, per-decision TraceTimeline, accuracy-floor status bar

**v2:** memory (procedural rules learned from corrections); multi-account; A2A endpoint exposure (feeds Project 10).

**Architecture:** hosted agent (zip deploy for the Docker-less inner loop; container for prod) · FastAPI companion service for Console API + Logic Apps callbacks · Postgres (Azure Flexible Server, burstable tier) for verdicts/state · frontend on Azure Static Web Apps.
**Risks:** Logic Apps↔agent resume plumbing is the 3x-longer part: prototype the approval callback in week 1, not week 6. Foundry surface moves fast: pin SDK versions, note doc dates in README.
**Milestones (9 wks):** W1 azd scaffold + approval-callback spike · W2-3 agent + MCP tools + reason schema · W4 traces + console read-only · W5 human gate end-to-end · W6 evals gate in CI + floor · W7 rollback + guardrails + XPIA run · W8 console complete · W9 7 demo videos + launch.

---

## PROJECT 7 · InvoiceOps

**MVP features:**
1. Intake: blob upload (and email-folder simulation) → Azure AI Document Intelligence prebuilt-invoice model → fields + confidence per field
2. Policy engine: YAML rules (amount limits by category, duplicate detection, PO match against ledgerfab POs, vendor allow-list) evaluated deterministically; LLM only for fuzzy vendor normalization
3. Tiered routing: auto-record / needs-approval / rejected, thresholds configurable
4. Teams Adaptive Card approvals (Logic Apps), with the REASON it was stopped on the card
5. Ops dashboard SPA: intake feed, confidence distributions, exception queue, per-invoice audit trail (extract → checks → route → verdict → post-stub)
6. Full audit log; azd one-command deploy; cost-per-invoice measured and published

**Honesty note in README:** cite Microsoft's serverless Expense Processor sample; this project = the governed, dashboarded, human-gated production version.
**Architecture:** Azure Functions (queue-driven) for pipeline stages + Document Intelligence + small Azure OpenAI model for normalization only + Postgres + Static Web Apps dashboard.
**Risks:** Document Intelligence quota/cost → batch demo docs, cache extractions in repo for UI dev.
**Milestones (7 wks):** W1 intake + DI · W2 policy engine · W3 routing + Teams gate · W4-5 dashboard · W6 audit + evals (extraction accuracy vs. ledgerfab ground truth) · W7 azd polish + demo.

---

## PROJECT 8 · PolicyGround

**MVP features:**
1. Corpus: synthetic accounting-policy manual (you author ~30 policies: cap thresholds, expense rules, approval matrices) + ingestion to Azure AI Search (chunking, metadata incl. sensitivity labels)
2. Answering service: retrieve → compose ONLY from retrieved chunks → every claim carries a citation ID → empty/weak retrieval returns explicit refusal with "closest sections" suggestions
3. Groundedness evals in CI: question set with known-answerable/known-unanswerable split; measure citation validity, refusal correctness, groundedness score (Foundry evaluators + own deterministic checks)
4. Chat SPA: answer pane + citations side panel (click claim → highlighted source passage); admin dashboard: groundedness trends, refusal rate, unanswered-questions log (the "what policies are missing" goldmine)
5. Label-aware retrieval demo: restricted-label docs invisible to unprivileged sessions

**Architecture:** FastAPI RAG service (Azure OpenAI + AI Search hybrid retrieval) · Postgres for logs · Static Web Apps. Citation enforcement structural: answer JSON schema `claims:[{text, citation_ids[]}]`, uncited claims stripped before render.
**Milestones (7 wks):** W1 corpus + ingestion · W2 retrieval + citation schema · W3 refusal logic · W4 chat UI + citations panel · W5 evals suite · W6 admin dashboard · W7 label-aware demo + launch.

---

## PROJECT 9 · FinSight

**MVP features:**
1. Fabric Lakehouse with ledgerfab finance data + semantic model (star schema: GL facts, cost-center/account/period dims)
2. Fabric Data Agent configured on the model (read-only), with tested example questions (variance >10%, top movers, trend by cost center)
3. Copilot Studio agent as front end, consuming the Data Agent (connected agents / MCP-A2A pattern)
4. Governance transparency page (small SPA): exactly what the agent can see, permission model, live config
5. Answer-accuracy eval: 25 questions with SQL-computed ground truth from the same model; publish the score
6. THE DELIVERABLE THAT MATTERS: brutally complete setup docs: licensing, tenant, capacity (F2+), publishing gotchas, costs

**Risks:** licensing/trial availability is the gating factor: verify BEFORE starting (doc'd fallback: Foundry IQ knowledge variant). Integration quirks ARE the content: log every gotcha as you hit it.
**Milestones (6 wks):** W1 Fabric setup + data · W2 semantic model + Data Agent · W3 Copilot Studio wiring · W4 eval set + accuracy run · W5 transparency page · W6 the docs + demo video.

---

## PROJECT 10 · CloseOps (capstone)

**MVP features:**
1. Close checklist definition (YAML): tasks, dependencies, risk tier, gate requirements
2. Orchestrator agent (Agent Framework workflows): reads checklist, dispatches specialists, tracks state, retries idempotently, NEVER self-approves
3. Specialists over A2A: LedgerGuard (Project 6, exposed as A2A endpoint) · accruals-checklist agent (new, simple: verifies recurring accruals against ledgerfab schedules) · variance drafter (grounded via Project 9's Data Agent or its Foundry IQ fallback)
4. Logic Apps schedule trigger (simulated month-end) + Teams gates at every risk-tier boundary
5. Close Board SPA: live checklist advancing (WebSocket), exception lane, human-gate queue, full close-trace timeline
6. The demo: a synthetic month closed end-to-end on camera, with one planted anomaly escalating properly

**Architecture:** orchestrator = hosted Foundry agent; A2A incoming/outgoing (Foundry supports both); state in Postgres (checklist runs, task states, gate verdicts); idempotency keys on every dispatch (the duplicate-entry failure mode from research, engineered away and blogged about).
**Risks:** A2A across three agents is the 3x zone → integrate ONE specialist end-to-end first (week 2), add others after. Scope discipline: 3 specialists max in v1.
**Milestones (10 wks):** W1 checklist model + orchestrator skeleton · W2 LedgerGuard via A2A end-to-end · W3-4 accruals agent + gates · W5 variance drafter · W6-7 Close Board · W8 idempotency + failure drills · W9 full-close rehearsals + evals (gate correctness, completion) · W10 the on-camera close + launch.

---

## CROSS-PROJECT TECH DECISIONS (final answers)
- **Agent frameworks:** LangGraph (Track 1) · Microsoft Agent Framework (Track 2) · OpenAI Agents SDK only as a FinAgent-Evals adapter · no LangChain-classic anywhere
- **LLMs:** OpenAI API (gpt-5-mini-class for volume, one strong model for judging: pinned + cached) on Track 1 · Azure OpenAI on Track 2 · every repo has a MODEL_COSTS.md
- **Auth (v1):** none on self-hosted demos, simple key on anything public; FastMCP granular auth when the MCP server goes public
- **Testing bar:** every repo ships `evals/` + CI gate: this IS the brand; a repo about trustworthy AI with no evals folder would be self-refuting
- **Order of first three builds:** ax-template + aurora-ui + ledgerfab (week 0-1) → Project 2 (MCP server) → Project 1 (Workbench). NOTE: building the MCP server FIRST (swapped vs. v4 sequence) because Project 1 demos best against it: confirm you're OK with this swap.
