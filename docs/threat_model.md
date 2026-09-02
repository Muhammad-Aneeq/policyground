# Threat model — what label-aware retrieval does and does not stop

Written because a governance feature that does not state its boundary invites the reader to assume
a larger one.

## The control

**Sensitivity labels filter inside the retriever, before scoring.** A session role maps to a set of
labels (`labels.py::ROLE_ALLOWED_LABELS`); chunks outside that set are removed from the candidate
pool before either retrieval arm runs. The `Retriever` interface has no parameter that widens the
set — no `search_all`, no `include_restricted`, no `labels` override.

## What it stops

| Threat | Stopped? | Why |
|---|---|---|
| Restricted text reaching an unprivileged model context | ✅ | It is never a retrieval candidate |
| Restricted text appearing in an answer | ✅ | It was never in context to quote |
| Instruction injection in a **question** widening access | ✅ | Nothing in the request path can change the label set; the role comes from the session |
| Instruction injection in a **retrieved passage** widening access | ✅ | The filter has already run by the time any text is read |
| Enumerating policy ids to discover which are restricted | ✅ | Forbidden and absent both return 404, byte-identical |
| A leaked chunk id used as a read primitive | ✅ | `get_chunk` is separately label-checked |
| A refusal's "closest sections" naming a restricted policy | ✅ | Suggestions are drawn from already-filtered hits |
| Restricted policies visible in the source browser | ✅ | Same rule applied in the query, not the template |
| A model fabricating a citation to restricted material | ✅ | The strip drops ids outside the retrieved set |

Each row has a corresponding assertion in `evals/test_label_leakage.py`, `evals/test_injection.py`
or `tests/test_api.py`.

## What it does NOT stop

Stated plainly, because these are the boundary.

| Threat | Status | Note |
|---|---|---|
| **A compromised or forged session role** | ❌ **Out of scope** | v1 takes the role from the request body — spec 08 §11 calls this "simulated in v1". Anyone who can call the API can claim `controller`. This is the single largest gap, and it is deliberate: wiring real identity is v2 work with a real cost. Everything downstream is already correct; only `api/deps.py::parse_role` changes. |
| Inference from *absence* | ⚠️ Partial | `withheld_count` tells a guest that passages exist which they cannot see. A deliberate trade: silently returning less teaches users the corpus is thin, while the count teaches them governance is operating. It leaks a count, never a title or an id. |
| Inference from the corpus's public half | ⚠️ Real | A restricted-*topic* question can sometimes be partially answered from adjacent public material — `docs/evals_methodology.md` §5.1 measures this. No restricted content is disclosed; the answer is simply less complete than the restricted policy would give. |
| Timing side channels | ❌ Not addressed | A refusal returns faster than an answer (no model call). Measurable, and not defended against. |
| Malicious corpus authoring | ❌ Out of scope | Someone who can edit `corpus/` can relabel a document. Ingestion verifies *consistency*, not *authority*. |
| Model extraction / training-data attacks | ❌ Out of scope | The compose model is a hosted API; this project does not fine-tune. |
| Denial of service | ⚠️ Partial | `top_k` is bounded (≤ 20) and question length capped at 2,000 characters. There is no rate limiting — spec 00's cross-project decision is "no auth on self-hosted demos". |

## The honest summary

**The label filter is a strong control against everything downstream of the role, and no control at
all over the role itself.**

In v1 the role is asserted by the caller. Every test in this repository that says "a guest cannot
see restricted content" means precisely: *a session that identifies as `guest` cannot retrieve,
read, cite, or be told the titles of restricted policies* — and says nothing about whether that
session is entitled to identify as anything else.

That gap closes at `api/deps.py::parse_role`, by reading a validated claim from an authenticated
token instead of a request field. It is one function, and it is the only function, because the role
enters the system in exactly one place.
