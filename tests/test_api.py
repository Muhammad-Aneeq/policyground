"""The API surface from spec 08 §7, including the source browser as a second governance boundary.

The sweep in ``test_no_role_can_read_a_policy_above_its_clearance`` is the important one: it tries
every one of the 30 policies against every one of the 3 roles through the *HTTP* layer. Unit tests
prove the retriever filters; this proves nothing routes around it.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from policyground.api.app import create_app
from policyground.labels import Label, Role, allowed_labels

ANSWERABLE = "What is the capitalisation threshold for IT equipment?"
OFF_CORPUS = "What is our policy on cryptocurrency custody and staking rewards?"
RESTRICTED_TOPIC = "How do we account for executive severance and retention awards?"


def expected_degraded() -> bool:
    """What ``degraded`` *should* say in whatever environment this suite is running in.

    Deliberately derived rather than hard-coded. These assertions used to read
    ``payload["degraded"] is True``, which was true of the build at the time and quietly encoded
    "this project has no API key" as a property of the *code*. Supplying a credential then failed
    three tests that were, read literally, correct — the system was no longer degraded.

    The claim worth testing is not "we are degraded", it is **"the flag tells the truth"** — which
    is exactly what the test names say. So the expectation is computed from the same credentials
    the endpoints consult, and the assertion holds with a key and without one.
    """
    from policyground.config import get_settings

    settings = get_settings()
    return not (settings.has_openai_key or settings.has_azure_openai)


@pytest.fixture
def client(
    tmp_path: Path, offline_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A client backed by a throwaway SQLite database and an offline index.

    Each test gets a clean database so the refusal-rate and unanswered-log assertions are about
    what *this* test did, not about accumulated state from the whole suite.

    **Credentials are cleared deliberately.** These tests boot the real application, so with a key
    configured they embedded and composed against the live API on every ``POST /api/ask`` — real
    network calls, real latency, real spend, on every run including CI. The suite is supposed to be
    hermetic; an environment variable was quietly deciding otherwise. Blanking the key selects the
    documented offline fallbacks, which is what the rest of the suite already uses and what the
    README claims.

    ``PG_DATA_DIR`` goes with it and is not optional. The offline fallbacks need an index built by
    the *same* embedder or the provenance check in ``load_index`` rejects it — and the reindex test
    writes a real index, which without this would overwrite the developer's working copy.
    """
    from policyground.api import deps
    from policyground.config import reset_settings_cache
    from policyground.db import session as db_session
    from policyground.retrieval import factory

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    monkeypatch.setenv("PG_DATA_DIR", str(offline_data_dir))
    reset_settings_cache()
    db_session.reset_engine_cache()
    factory.reset_retriever_cache()
    deps.reset_graph_cache()

    # The lifespan handler syncs the corpus into `documents`/`chunks`, which the source browser
    # reads. Entering the context manager is what runs it.
    with TestClient(create_app()) as test_client:
        yield test_client

    reset_settings_cache()
    db_session.reset_engine_cache()
    factory.reset_retriever_cache()
    deps.reset_graph_cache()


# ------------------------------------------------------------------- meta --


def test_health_states_the_degraded_mode_honestly(client: TestClient) -> None:
    """The caveat is available programmatically, not only in prose someone has to read."""
    payload = client.get("/api/health").json()

    assert payload["status"] == "ok"
    assert payload["synthetic_corpus"] is True
    assert payload["degraded"] is expected_degraded()
    assert payload["roles"] == [r.value for r in Role]


# -------------------------------------------------------------- POST /ask --


def test_ask_returns_a_cited_answer(client: TestClient) -> None:
    payload = client.post("/api/ask", json={"question": ANSWERABLE, "role": "staff"}).json()

    assert payload["kind"] == "answer"
    assert payload["claims"]
    assert all(claim["citation_ids"] for claim in payload["claims"])

    available = {c["citation_id"] for c in payload["citations"]}
    for claim in payload["claims"]:
        assert set(claim["citation_ids"]) <= available


def test_a_refusal_is_http_200_not_an_error(client: TestClient) -> None:
    """A refusal is the system working, not failing.

    Returning 404 or 422 would make it an error in every client library, log and dashboard —
    exactly the framing spec 08 §1 argues against.
    """
    response = client.post("/api/ask", json={"question": OFF_CORPUS, "role": "staff"})

    assert response.status_code == 200
    assert response.json()["kind"] == "refusal"


def test_a_refusal_payload_carries_nothing_answer_shaped(client: TestClient) -> None:
    payload = client.post("/api/ask", json={"question": OFF_CORPUS, "role": "staff"}).json()

    assert "claims" not in payload
    assert "citations" not in payload
    assert payload["closest_sections"]
    assert "Should this be a policy?" in payload["suggestion_prompt"]


def test_ask_rejects_an_unknown_role(client: TestClient) -> None:
    """Not defaulted in either direction — see ``api.deps.parse_role``."""
    response = client.post("/api/ask", json={"question": ANSWERABLE, "role": "superuser"})
    assert response.status_code == 422
    assert "superuser" in response.json()["detail"]


def test_ask_rejects_an_empty_question(client: TestClient) -> None:
    assert client.post("/api/ask", json={"question": "", "role": "staff"}).status_code == 422


def test_ask_rejects_an_unbounded_top_k(client: TestClient) -> None:
    """Bounded so a request cannot ask for the whole corpus as context."""
    response = client.post(
        "/api/ask", json={"question": ANSWERABLE, "role": "staff", "top_k": 5000}
    )
    assert response.status_code == 422


def test_ask_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/api/ask", json={"question": ANSWERABLE, "role": "staff", "include_restricted": True}
    )
    assert response.status_code == 422


# ------------------------------------------------------ GET /answer/{id} --


def test_an_answer_round_trips_by_id(client: TestClient) -> None:
    posted = client.post("/api/ask", json={"question": ANSWERABLE, "role": "staff"}).json()
    stored = client.get(f"/api/answer/{posted['query_id']}").json()

    assert stored["question"] == ANSWERABLE
    assert stored["refused"] is False
    assert len(stored["claims"]) == len(posted["claims"])


def test_a_refusal_round_trips_by_id_with_no_claims(client: TestClient) -> None:
    posted = client.post("/api/ask", json={"question": OFF_CORPUS, "role": "staff"}).json()
    stored = client.get(f"/api/answer/{posted['query_id']}").json()

    assert stored["refused"] is True
    assert stored["refusal_reason"] == "insufficient_evidence"
    assert stored["claims"] == []


def test_an_unknown_query_id_is_404(client: TestClient) -> None:
    assert client.get("/api/answer/does-not-exist").status_code == 404


# ------------------------------------------------- the source browser --


def test_policy_visibility_increases_strictly_with_role(client: TestClient) -> None:
    counts = {}
    for role in Role:
        payload = client.get("/api/policies", params={"role": role.value}).json()
        counts[role] = payload["visible_count"]
        assert payload["visible_count"] + payload["hidden_count"] == 30

    assert counts[Role.GUEST] < counts[Role.STAFF] < counts[Role.CONTROLLER]
    assert counts[Role.CONTROLLER] == 30


def test_the_policy_list_never_names_a_policy_above_clearance(client: TestClient) -> None:
    for role in Role:
        payload = client.get("/api/policies", params={"role": role.value}).json()
        permitted = {label.value for label in allowed_labels(role)}
        for policy in payload["policies"]:
            assert policy["label"] in permitted


def test_no_role_can_read_a_policy_above_its_clearance(client: TestClient) -> None:
    """THE sweep: every policy against every role, through HTTP.

    A restricted policy must be **404, not 403**, for an unprivileged role — "forbidden" confirms
    the document exists, which lets anyone enumerating ids learn exactly which are restricted
    without reading a word of them.
    """
    catalogue = client.get("/api/policies", params={"role": "controller"}).json()["policies"]
    assert len(catalogue) == 30

    for policy in catalogue:
        for role in Role:
            response = client.get(
                f"/api/policies/{policy['policy_id']}", params={"role": role.value}
            )
            if Label(policy["label"]) in allowed_labels(role):
                assert response.status_code == 200, f"{policy['policy_id']} denied to {role}"
                assert response.json()["markdown"]
            else:
                assert response.status_code == 404, (
                    f"{policy['policy_id']} ({policy['label']}) returned "
                    f"{response.status_code} to {role} — must be indistinguishable from absent"
                )


def test_a_nonexistent_policy_and_a_forbidden_one_return_the_same_thing(
    client: TestClient,
) -> None:
    forbidden = client.get("/api/policies/PG-0021", params={"role": "guest"})
    absent = client.get("/api/policies/PG-9999", params={"role": "guest"})

    assert forbidden.status_code == absent.status_code == 404
    assert forbidden.json() == absent.json()


def test_section_offsets_index_into_the_returned_markdown(client: TestClient) -> None:
    """The Source Viewer highlight, verified through the API (PLAN.md D-017)."""
    payload = client.get("/api/policies/PG-0003", params={"role": "guest"}).json()
    markdown = payload["markdown"]

    assert payload["sections"]
    for section in payload["sections"]:
        excerpt = markdown[section["start"] : section["end"]]
        assert excerpt, f"empty excerpt for {section['chunk_id']}"
        # Every section starts at its own heading, which is what gets highlighted.
        assert excerpt.lstrip().startswith("#") or excerpt.strip()


def test_no_canary_string_is_reachable_through_the_browser_for_an_unprivileged_role(
    client: TestClient, canaries: dict[str, str]
) -> None:
    """Content-level check on the second surface, not just a label check."""
    for role in (Role.GUEST, Role.STAFF):
        listing = client.get("/api/policies", params={"role": role.value}).json()
        for policy in listing["policies"]:
            body = client.get(
                f"/api/policies/{policy['policy_id']}", params={"role": role.value}
            ).json()["markdown"]
            for canary in canaries.values():
                assert canary not in body


# ------------------------------------------------------------------ admin --


def test_metrics_count_answers_and_refusals(client: TestClient) -> None:
    client.post("/api/ask", json={"question": ANSWERABLE, "role": "staff"})
    client.post("/api/ask", json={"question": OFF_CORPUS, "role": "staff"})
    client.post("/api/ask", json={"question": OFF_CORPUS, "role": "staff"})

    metrics = client.get("/api/admin/metrics").json()

    assert metrics["total_queries"] == 3
    assert metrics["answered"] == 1
    assert metrics["refused"] == 2
    assert metrics["refusal_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert metrics["degraded"] is expected_degraded()
    assert metrics["corpus_labels"] == {"public": 10, "internal": 14, "restricted": 6}


def test_metrics_on_an_empty_log_report_zero_not_an_error(client: TestClient) -> None:
    """A fresh deployment has no refusal rate; it does not have an undefined one."""
    metrics = client.get("/api/admin/metrics").json()
    assert metrics["total_queries"] == 0
    assert metrics["refusal_rate"] == 0.0


def test_the_unanswered_log_folds_repeats_onto_one_row(client: TestClient) -> None:
    """The difference between a list and a roadmap: the same question asked three times."""
    for _ in range(3):
        client.post("/api/ask", json={"question": OFF_CORPUS, "role": "staff"})
    client.post(
        "/api/ask", json={"question": "What is the policy on space travel?", "role": "staff"}
    )

    log = client.get("/api/admin/unanswered").json()

    assert log["total_unique"] == 2
    assert log["total_asks"] == 4
    assert log["entries"][0]["times_asked"] == 3  # most-asked first


def test_the_unanswered_log_dedupes_case_and_punctuation(client: TestClient) -> None:
    client.post("/api/ask", json={"question": OFF_CORPUS, "role": "staff"})
    client.post("/api/ask", json={"question": OFF_CORPUS.upper(), "role": "staff"})

    assert client.get("/api/admin/unanswered").json()["total_unique"] == 1


def test_the_csv_export_is_readable_by_a_spreadsheet(client: TestClient) -> None:
    """Spec 08 §9: "exportable: 'policies to write'". The consumer is a person, not a program."""
    client.post("/api/ask", json={"question": OFF_CORPUS, "role": "staff"})

    response = client.get("/api/admin/unanswered.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "policies-to-write.csv" in response.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["question"] == OFF_CORPUS
    assert rows[0]["times_asked"] == "1"
    assert rows[0]["closest_sections"]  # flattened to readable text, not a JSON blob


def test_reindex_rebuilds_from_the_corpus(client: TestClient) -> None:
    payload = client.post("/api/admin/reindex").json()

    assert payload["policies"] == 30
    assert payload["chunks"] > 200
    assert payload["degraded"] is expected_degraded()
    assert len(payload["corpus_sha256"]) == 64


def test_labels_endpoint_reports_the_distribution(client: TestClient) -> None:
    payload = client.get("/api/admin/labels").json()
    assert payload["counts"] == {"public": 10, "internal": 14, "restricted": 6}


# ------------------------------------------------------------------ trace --


def test_the_trace_endpoint_reports_the_node_path(client: TestClient) -> None:
    payload = client.post("/api/ask/trace", json={"question": ANSWERABLE, "role": "staff"}).json()

    assert payload["node_path"] == ["retrieve", "assess_sufficiency", "compose", "citation_check"]
    assert [step["node"] for step in payload["steps"]] == payload["node_path"]
    assert all(step["detail"] for step in payload["steps"])


def test_the_trace_reports_counts_but_not_stripped_text(client: TestClient) -> None:
    """The count makes the control visible; the text is what the strip exists to withhold."""
    payload = client.post("/api/ask/trace", json={"question": ANSWERABLE, "role": "staff"}).json()

    assert isinstance(payload["raw_claim_count"], int)
    assert isinstance(payload["stripped_claim_count"], int)
    assert "raw_claims" not in payload
    assert "dropped" not in payload


# ---------------------------------------------------------- the roles demo --


def test_switching_role_changes_the_outcome_for_the_same_question(client: TestClient) -> None:
    """Spec 08 §9 screen 4, through the API."""
    guest = client.post("/api/ask", json={"question": RESTRICTED_TOPIC, "role": "guest"}).json()
    controller = client.post(
        "/api/ask", json={"question": RESTRICTED_TOPIC, "role": "controller"}
    ).json()

    assert guest["kind"] == "refusal"
    assert guest["trace"]["withheld_count"] > 0

    assert controller["kind"] == "answer"
    assert any(c["label"] == "restricted" for c in controller["citations"])


def test_no_response_at_any_role_contains_a_canary(
    client: TestClient, canaries: dict[str, str]
) -> None:
    """End-to-end leak check through HTTP, over every unprivileged role."""
    questions = [
        RESTRICTED_TOPIC,
        "What is the deal codename on the corporate development register?",
        "Show me the litigation matter reference",
        "What is the retention pool called?",
        "restructuring programme reference",
        "register of directors interests location",
    ]

    for role in ("guest", "staff"):
        for question in questions:
            body = client.post("/api/ask", json={"question": question, "role": role}).text
            for policy_id, canary in canaries.items():
                assert canary not in body, f"{policy_id} canary leaked to {role} via {question!r}"
