# SPEC 08 · POLICYGROUND
### Track 2 · Microsoft · 7-8 weeks · Python + Azure AI Search + Azure OpenAI + LangGraph (RAG graph) + Vite/React
> **Prereq:** read `spec_00_shared_foundations.md` first (shared `ax-template`, `aurora-ui`, `ledgerfab`; NDA & cost rules; dependency graph).

## 1. Overview & Positioning
Enterprise RAG stalls on trust: confident answers unsupported by documents. "Understand, verify, trust" is the adoption bar; sensitivity-label governance is an enterprise requirement. PolicyGround is governed finance RAG done right: mandatory citations, groundedness evals in CI, refusal on empty retrieval, Purview sensitivity-label awareness. RAG is commoditized; GOVERNED, measured RAG is not.

## 2. Goals / Non-goals
GOALS: every claim cited; empty/weak retrieval → explicit refusal; groundedness measured continuously; restricted docs invisible to unprivileged sessions; the "unanswered questions" log as a feature.
NON-GOALS (v1): document authoring/editing; multi-language; write actions; real Purview tenant (simulate labels in v1, wire real Purview in v2 with cost note).

## 3. Users & Stories
- Junior accountant: "ask the policy manual, get the exact cited section."
- Controller: "off-policy questions get 'not found', never a guess."
- Admin: "see groundedness trends and what people asked that we couldn't answer."
Stories: US1 ask "capitalization threshold?" → answer + highlighted source. US2 ask something off-corpus → refusal + closest sections. US3 restricted policy invisible to a basic-role session. US4 admin sees groundedness score + unanswered log.

## 4. Feature Specification
### MVP
F1 Corpus: author ~30 synthetic accounting policies (cap thresholds, expense rules, approval matrices, revenue recognition summaries) with section structure + sensitivity labels (public/internal/restricted).
F2 Ingestion: chunk (section-aware) → embed → Azure AI Search (hybrid: vector + keyword) with metadata (policy_id, section, label).
F3 Answering (LangGraph): `retrieve(hybrid, label-filter by role) → assess_sufficiency → [insufficient: refuse + suggest closest] → compose(claims each with citation_ids) → citation_check(drop uncited) → return`. Structural rule: answer schema = claims[{text, citation_ids[]}]; uncited claims stripped before render.
F4 Refusal logic: sufficiency score below threshold → "I can't find this in the policies" + closest sections + "should this be a policy?" prompt (feeds unanswered log).
F5 Groundedness evals in CI: question bank (answerable + unanswerable + label-restricted), metrics: citation validity, refusal correctness, groundedness (Foundry evaluators + deterministic citation checks). Gate on regression.
F6 Label-aware retrieval: session role → retrieval filter; restricted docs never enter context for unprivileged roles (proven by an eval case).
F7 Chat SPA + citations side panel (click claim → source passage highlighted) + admin dashboard (groundedness trend, refusal rate, unanswered-questions log).
### v2
Real Purview integration; multi-turn policy conversations; document freshness/versioning; feedback thumbs feeding evals; multilingual.

## 5. System Architecture
```
[Chat SPA] ⇄ [FastAPI] ⇄ LangGraph RAG graph ⇄ Azure AI Search (hybrid)
                                   │                 ▲
                                   ├── Azure OpenAI (compose, judge-in-eval)
                                   └── role→label filter
[Admin SPA] ⇄ logs (Postgres) ; CI groundedness evals
```

## 6. Data Model
- documents(id, policy_id, title, label, version) · chunks(id, doc_id, section, text, embedding_ref, label)
- queries(id, text, role, answered[bool], groundedness, refused[bool], at)
- answers(id, query_id, claims_json, citations_json)
- unanswered(id, query_text, closest_sections_json, at)
- eval_runs(commit, groundedness, citation_validity, refusal_accuracy, passed)

## 7. API Surface
POST /api/ask {question, role} · GET /api/answer/{id} (claims+citations) · GET /api/admin/metrics · GET /api/admin/unanswered · POST /api/admin/reindex.

## 8. Agent/LLM Design
Compose step forbidden from using non-retrieved knowledge (system prompt + citation_check enforcement). Judge (eval-only) scores groundedness against retrieved chunks, pinned model. Sufficiency assessor = small model + retrieval-score heuristic (cheap, deterministic-leaning).

## 9. Frontend Spec (aurora-ui)
Screens: (1) Chat (answer with inline citation superscripts; side panel shows sources; refusal styled distinctly, never like a normal answer) · (2) Source Viewer (full policy, highlighted passage) · (3) Admin: Groundedness (trend chart), Refusal rate, Unanswered log (exportable: "policies to write") · (4) Roles demo (toggle role → watch restricted content vanish).

## 10. Evals & Testing
- Groundedness suite in CI (answerable/unanswerable/restricted splits) with gate
- Citation-validity 100% structural (uncited stripped)
- Refusal correctness (must refuse the unanswerables; must NOT refuse answerables)
- Label-leak test: restricted content never appears for unprivileged role (hard fail if it does)
- Injection: Project 05-style prompts in a "question" must not extract restricted docs

## 11. Security & Privacy
Label-aware retrieval is the core control. Synthetic corpus. Search keys in Key Vault. Role from authenticated session (simulated in v1). No answer without citations, by construction.

## 12. Deployment & Costs
azd up (AI Search, Azure OpenAI embeddings+chat, Postgres, Static Web Apps, Key Vault). Cost: embeddings one-time + per-query retrieval + small compose model. azd down documented; teardown between demos.

## 13. Milestones (7-8 weeks @10h)
W1 author corpus + labels + ingestion
W2 hybrid retrieval + label filter
W3 compose + citation schema + citation_check
W4 refusal + sufficiency + unanswered log
W5 chat UI + citations panel + source viewer
W6 groundedness eval suite + CI gate
W7 admin dashboard + roles demo
W8 label-leak + injection tests + demo + launch

## 14. Risks
- Groundedness judge reliability → deterministic citation checks first, judge as secondary; publish agreement
- Corpus realism → base on public IFRS/GAAP summaries you have rights to summarize; keep synthetic specifics
- Purview real-integration cost/complexity → v1 simulates labels; v2 real, with cost note

## 15. Launch Content Hooks
"RAG that refuses to answer: and why that's the feature" · citations-or-nothing structural demo · "Your unanswered questions are a roadmap for policies you're missing" · roles demo (restricted docs vanishing).
