# FINAL_REPORT.md — PolicyGround

---

## 1. What is demoable right now

Everything in LOCAL mode, offline, with no API key and no cloud account.

```powershell
./make.ps1 install     # uv sync + npm install          (~2 min first time)
./make.ps1 ingest      # 30 policies → 256 chunks       (~3 s)
./make.ps1 dev         # API :8000 · SPA :5173
```

`make install && make ingest && make dev` on macOS/Linux. `make` is not installed on the Windows
machine this was built on, which is why `make.ps1` exists (`BLOCKERS.md` B3).

### The 60-second walkthrough, with expected outcomes

| Step | Do this | You should see |
|---|---|---|
| 1 | Ask **"What is the capitalisation threshold for IT equipment?"** | A cited answer. 4 claims, every one carrying a superscript. |
| 2 | Click a superscript | The matching source card highlights in the side panel. |
| 3 | Click "Open full policy with this passage highlighted" | PG-0003 opens with **§2. Thresholds** highlighted — located by stored character offset, not by searching for the text. |
| 4 | Ask **"How do we account for cryptocurrency holdings?"** | An **amber** refusal card. Not a hedged answer. Closest sections listed as *"not an answer, just the nearest material"*. |
| 5 | Open **Admin** | The question is in the unanswered log. Ask it twice more — it folds onto one row with `3×`. Export CSV works. |
| 6 | Open **Roles demo**, run the severance question | `controller` answers, citing PG-0021 with a red `restricted` tag. `guest` and `staff` refuse, each told **6 passages were withheld** — never which. |
| 7 | Watch the policy counts on the same screen | `10 / 24 / 30` of 30. Content vanishes from the source browser too, not just from retrieval. |

Step 6 is the demo. Same question, same corpus, same code — the only variable is the session role.

### Verified end to end just now

```
ingest      256 chunks from 256 sections across 30 policies
corpus      consistent: no problems found (30 policies)
answerable  answer · 4 claims · 2 citations · highlight → '## 2. Thresholds…'
off-corpus  refusal · insufficient_evidence · no `claims` field at all · logged
roles       guest refusal/withheld=6/browser 10-of-30
            staff refusal/withheld=6/browser 24-of-30
            controller answer/withheld=0/browser 30-of-30
```

---

## 2. Exact commands

```bash
# Verification
./make.ps1 check              # lint + typecheck + 254 unit tests + 5 eval gates
./make.ps1 test               # unit tests only (LLM mocked)
./make.ps1 eval               # the gates, judge cache-only
uv run pg corpus check        # cross-policy consistency, canaries, cross-references
uv run pg corpus stats        # 30 policies · 256 sections · 21,811 words

# Evals
uv run python evals/build_bank.py                          # regenerate cases.jsonl
uv run python evals/build_injection.py                     # regenerate injection_cases.jsonl
uv run python -m evals.harness --split gate --write-cache  # run + write artifact
OFFLINE=1 uv run pg eval --split gate                      # run + record for the admin trend

# Frontend
cd frontend && npm run test && npm run typecheck && npm run build

# Postgres path (optional)
docker compose up -d
```

---

## 3. Results

**Gate split — 55 cases, 73 runs, never used to tune the threshold.**

| Metric | Result | Bar | |
|---|---|---|---|
| Citation validity | **1.0000** (160 claims, 0 unsupported) | 1.0 absolute | ✅ |
| Label leaks | **0** | 0 absolute | ✅ |
| Restricted answered for controller | **1.0000** | 1.0 absolute (positive control) | ✅ |
| Refuses the unanswerable | 0.7742 | 0.70 floor | ✅ |
| False refusal rate | 0.2143 | 0.28 ceiling | ✅ |
| Groundedness (offline proxy) | 1.0000 | baseline − 0.05 | ✅ |
| Injection | 13/13 × 2 roles | all pass | ✅ |

**377 tests green** (254 unit + 100 eval + 23 frontend). ruff clean, mypy strict clean across 42
modules, `tsc --noEmit` clean, production build succeeds.

Full derivation, the calibration sweep, and a per-case failure analysis:
**`docs/evals_methodology.md`**.

---

## 4. Human steps required for Azure

**AZURE mode has never been deployed** (`BLOCKERS.md` B2). What exists: `AzureSearchRetriever`
implementing the same `Retriever` interface, contract-tested against the same assertions as LOCAL
with the SDK mocked; `infra/main.bicep` compiling in CI; and the index schema emitted from the same
code that reads it back.

**→ `DEPLOY_RUNBOOK.md`** has the full path. The steps only a human can do:

1. **Check Azure OpenAI quota first.** This is the usual blocker and it is per-subscription.
   Provisioning succeeds and the model deployment fails, leaving a half-built resource group.
2. `az login` / `azd auth login`, select a subscription.
3. **Role assignments need Owner or User Access Administrator**, not Contributor. Three RBAC
   assignments in the template will fail otherwise.
4. Open the Postgres firewall for your IP for the one-off ingestion run — **and remove it after**.
5. Set `EMBEDDING_DIM=1536`. A mismatch between the index vector field and the running embedder does
   not error; it returns meaningless results and raises the refusal rate for reasons no log explains.
6. Run the five smoke queries in runbook §5. Each has a stated expected outcome.
7. **`azd down --purge --force`.** AI Search is ~$74/month billed whether queried or not — a 2-hour
   demo costs ~$0.13, a month left running costs ~$90 (`MODEL_COSTS.md`).

---

## 5. Blockers, each with a one-line fix

| | Blocker | One-line fix |
|---|---|---|
| ~~**B1**~~ | ~~No `OPENAI_API_KEY`~~ — **CLOSED.** Live on `gpt-5.6-luna` + `text-embedding-3-small`. | Was `export OPENAI_API_KEY=sk-…` then `pg ingest --rebuild` — and it was exactly that; no application logic changed. Two caveats surfaced: GPT-5.6 rejects `temperature` outright (`reasoning_effort` replaces it), and three tests hard-coded `degraded is True`. See `BLOCKERS.md` B1. |
| **B2** | No Azure subscription — AZURE mode never deployed | Follow `DEPLOY_RUNBOOK.md`; `azd up` with quota confirmed. |
| **B3** | No `make` on Windows | Use `./make.ps1 <target>` — identical target names. *(Closed: the shim is the shipped path.)* |
| **B4** | No Postgres running | `docker compose up -d` and set `DATABASE_URL`. *(Closed by design: SQLite is a documented dev target.)* |

Only B1 and B2 remain open, and both are credentials rather than code.

**What B1 actually costs, precisely.** The two headline controls — citation validity and label
leakage — are structural and completely unaffected: they are properties of the code, verified by
tests that never touch a model. What is affected is retrieval quality, and therefore refusal
correctness: 0.774 / 0.214 are floors produced by a lexical stand-in, not the system's ceiling. The
groundedness 1.0000 is close to vacuous against extractive output, and `docs/evals_methodology.md`
§6.2 says so rather than letting the number stand unqualified.

---

## 6. Three next things

**1. Wire real identity — the largest honest gap.**
`docs/threat_model.md` states it plainly: the label filter is a strong control over everything
downstream of the role and *no control at all over the role itself*. In v1 the role arrives in the
request body, so anyone who can call the API can claim `controller`. Every test that says "a guest
cannot see restricted content" means "a session identifying as guest cannot" — and says nothing
about entitlement to that identity. The fix is one function: `api/deps.py::parse_role` reads a
validated token claim instead of a request field. It is one function precisely because the role
enters the system in exactly one place.

**2. ~~Re-calibrate against a real embedder and publish both curves.~~ DONE — see
`docs/evals_methodology.md` §3a.**
The prediction was right and the consequence was bigger than expected. With
`text-embedding-3-small` the calibrated optimum moves from 0.80 to **0.51**, and the false refusal
rate on the gate split falls from **0.2143 to 0.0476** — nine wrongly-refused questions down to
two. Both absolute gates hold.

Two findings that were not predicted. **At 0.80 with real embeddings the positive control breaks**:
a controller is refused on restricted material, dropping `restricted_answered_for_controller` to
0.8889 against an absolute bar of 1.0. And **the threshold is not portable** — 0.51 against the hash
embedder refuses only 0.355 of the unanswerable cases, far under the 0.70 floor. It is a property of
the retrieval stack, so the committed default stays at 0.80 and 0.51 is configured alongside a real
embedder.

The remaining open item is the judge: these runs are still scored by the offline proxy, and the
groundedness figure fell from a near-vacuous 1.0000 to 0.83 simply because an abstractive composer
gives the proxy something to measure. That number needs a live pinned judge before it means much,
and the stored baseline needs replacing rather than defending.

**3. Split "over-answering" from "leaking" as a first-class metric.**
The failure analysis found that 5 of 7 missed refusals are restricted-*topic* questions answered
from adjacent **public** material with zero leakage. That is a materially different and milder
failure than disclosure, and the current metric counts them identically. A separate
`partial_answer_on_restricted_topic` rate would let the gate hold leakage at zero while tracking
over-answering as its own trend — and it is the metric a real deployment would actually argue
about, because it is where "helpful" and "governed" genuinely trade off.

---

## 7. Honest status

| | |
|---|---|
| LOCAL mode | ✅ Complete, running, tested |
| AZURE mode | 🟡 Deployment-ready, compiles, contract-tested — **never deployed** |
| Corpus | ✅ 30 policies, 21,811 words, consistency enforced in CI |
| Model credential | ✅ Live: `gpt-5.6-luna` compose, `text-embedding-3-small` retrieval (B1 closed) |
| Structural controls | ✅ Citation validity 1.0, label leaks 0, both gated absolutely |
| Statistical controls | ⚠️ Measured and gated as regression floors; limits published |
| **Numbers in §3** | ⚠️ **Produced before the credential existed** — hash embedder + extractive compose. Not re-measured against GPT-5.6 Luna. |
| Groundedness judge | ⚠️ Offline deterministic proxy — **no live LLM judge has scored these runs** |
| Screenshot / demo video | ✅ `media/policyground_demo.mp4` (59s) + 5 stills, recorded against the live system (B5 closed) |
| `PLAN.md` | ✅ All phases ticked; every deviation recorded in the decisions log |

Nothing in this repository claims to have been deployed, and no number is quoted without saying what
produced it.
