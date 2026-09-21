# PolicyGround — Overview

A short, plain-English guide. For the deep version see `README.md`, `PLAN.md` and
`docs/evals_methodology.md`.

---

## 1. What it is

A chatbot for a company's **finance & accounting policy manual**.

You ask a question in normal English — *"What's the capitalisation threshold for IT equipment?"* —
and it answers from 30 internal policy documents, with a clickable citation on every sentence.

All 30 policies are **synthetic**, written for this project. No real company's policy is included.

---

## 2. What it does

Four things a normal "chat with your documents" tool doesn't do:

| | |
|---|---|
| **Cites everything** | Every sentence carries a superscript. Click it and the exact passage highlights in the source panel, then in the full policy document. |
| **Refuses** | Ask something the manual doesn't cover and you get an explicit "I can't answer this" card — never a confident guess. Refusals are the feature, not the bug. |
| **Enforces access** | Documents are labelled public / internal / restricted. A guest literally cannot retrieve restricted text. Same question, different role, different answer. |
| **Logs the gaps** | Every refused question lands in an admin log with a repeat counter — a ranked list of policies the company still needs to write. |

---

## 3. Why it exists (the purpose)

Enterprise RAG projects stall for one reason: **nobody can trust the answer.** A fluent,
well-formatted, completely made-up answer looks identical to a correct one.

PolicyGround's argument is that trust comes from three guarantees you can *prove*, not promise:

1. **No answer without a citation** — enforced in code after the model replies, not asked for in a prompt.
2. **Restricted content is unreachable** — filtered inside the retriever, before scoring, so it never
   enters a prompt or a log.
3. **"I don't know" is a valid, cheap answer** — the system refuses *before* calling the model, so an
   off-topic question costs zero tokens.

---

## 4. How it works

```
You ask a question
        │
        ▼
  RETRIEVE        keyword search (BM25) + meaning search (embeddings), merged
        │         ⚠ your role's label filter is applied HERE, before anything is scored
        ▼
  IS THIS ENOUGH? a score from: how much of your question the passages cover,
        │         match strength, and whether both searches agree
        │
        ├── below 0.80 ──► REFUSE  (no model call, logged for admin)
        ▼
  COMPOSE         GPT-5.6 Luna writes claims, each tagged with the passage it came from
        │
        ▼
  CITATION CHECK  any claim citing nothing — or citing an ID that was never retrieved — is deleted.
        │         If nothing survives, the answer becomes a refusal.
        ▼
  Answer + sources panel
```

**The pieces:**

- **Backend** — Python, FastAPI, LangGraph (the box diagram above *is* the graph), SQLite.
- **Frontend** — React + Vite + Tailwind. Four screens: Chat, Source viewer, Admin, Roles demo.
- **Retrieval** — one `Retriever` interface with two implementations: local (runs offline, no cloud)
  and Azure AI Search. Everything downstream can't tell which one it got.
- **Model** — OpenAI `gpt-5.6-luna` for composing answers, `text-embedding-3-small` for search.
  With no API key the whole app still runs on deterministic offline fallbacks.

---

## 5. How to run it

```powershell
./make.ps1 install     # install Python + Node dependencies   (~2 min first time)
./make.ps1 ingest      # index the 30 policies → 256 chunks   (~3 s)
./make.ps1 dev         # API on :8000, UI on :5173
```

On macOS / Linux use `make install && make ingest && make dev`.

Open **http://localhost:5173**.

---

## 6. How to test it

### Click-through test (60 seconds)

1. Ask **"What is the capitalisation threshold for IT equipment?"**
   → a cited answer. Click a superscript → the source card highlights. Click through → the full
   policy opens with that exact passage highlighted.
2. Ask **"How do we account for cryptocurrency holdings?"**
   → an amber refusal card, plus the nearest sections labelled *"not an answer"*.
3. Open **Admin** → that question is in the unanswered log. Ask it twice more → it folds into one
   row showing `3×`. CSV export works.
4. Open **Roles demo** → ask about executive severance.
   `controller` gets a cited answer from a restricted policy.
   `guest` and `staff` get a refusal telling them *how many* passages were withheld — never which.

Step 4 is the whole pitch: same question, same code, only the role changed.

### Automated tests

```powershell
./make.ps1 test        # unit tests (model mocked)
./make.ps1 eval        # the 5 quality gates on a held-out question set
./make.ps1 check       # lint + typecheck + tests + evals — the full CI gate
uv run pg corpus check # checks the 30 policies don't contradict each other
```

**What the gates enforce** (these fail the build, they aren't dashboards):

| Gate | Bar |
|---|---|
| Citation validity | must be exactly 1.0 — zero uncited claims |
| Label leaks | must be exactly 0 |
| Restricted answered for controller | must be 1.0 (proves the filter isn't just "deny everything") |
| Refuses the unanswerable | floor 0.70 |
| False refusals | ceiling 0.28 |
| Prompt injection | all 13 cases × 2 roles must pass |

---

## 7. Honest status

| | |
|---|---|
| Local mode | ✅ Complete, running, tested |
| Azure mode | 🟡 Code + infrastructure written and contract-tested — **never actually deployed** |
| Corpus | ✅ 30 policies, ~22k words, consistency enforced in CI |
| Model | ✅ Live on `gpt-5.6-luna` |
| Citations & access control | ✅ Fully working — these are code properties, not model behaviour |
| The gate numbers above | ⚠️ Measured *before* the model was connected (hash embedder + extractive compose). Not yet re-run against Luna. |

Known gap worth naming: **the user's role arrives in the request body**, so anyone calling the API
directly could claim to be a controller. The access filter is strong over everything downstream of
the role, and no control at all over the role itself. Fixing it is one function
(`api/deps.py::parse_role` reading a validated token instead) — see `docs/threat_model.md`.
