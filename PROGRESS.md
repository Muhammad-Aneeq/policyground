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
