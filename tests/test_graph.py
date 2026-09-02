"""The LangGraph graph: node sequence, both refusal paths, and the answer/refusal type split.

Spec 08 §4 F3 draws the graph as
``retrieve → assess_sufficiency → [insufficient: refuse] → compose → citation_check → return``.
``test_node_path_matches_the_spec_diagram`` asserts that against recorded state, so the claim
"implemented per the spec" is checked rather than asserted.

The LLM is mocked by default (per the brief); ``@pytest.mark.live`` covers the real-model variant
and is deselected everywhere.
"""

from __future__ import annotations

import pytest

from policyground.answers.schema import Answer, Claim, Refusal
from policyground.graph.build import (
    EXPECTED_ANSWER_PATH,
    EXPECTED_REFUSAL_PATH,
    PolicyGroundGraph,
)
from policyground.graph.llm import OfflineComposer, parse_claims
from policyground.labels import Label, Role
from policyground.retrieval.base import Chunk

ANSWERABLE = "What is the capitalisation threshold for IT equipment?"
OFF_CORPUS = "What is our policy on cryptocurrency custody and staking rewards?"
RESTRICTED_TOPIC = "How do we account for executive severance and retention awards?"


class ScriptedComposer:
    """A composer that returns exactly what a test tells it to.

    This is how the citation control is exercised end-to-end through the real graph: a real model
    cannot be made to fabricate an id on demand, and the extractive offline composer cannot
    fabricate one at all.
    """

    name = "scripted"

    def __init__(self, claims: list[Claim] | Exception) -> None:
        self._claims = claims

    def compose(self, question: str, chunks: list[Chunk]) -> list[Claim]:
        if isinstance(self._claims, Exception):
            raise self._claims
        return list(self._claims)


@pytest.fixture
def graph(retriever, settings, vocabulary):  # type: ignore[no-untyped-def]
    return PolicyGroundGraph(
        retriever=retriever,
        client=OfflineComposer(),
        threshold=settings.sufficiency_threshold,
        default_top_k=settings.retrieval_top_k,
        embedder_name="hash-embedder-v1",
        degraded=True,
        vocabulary=vocabulary,
    )


def scripted_graph(retriever, settings, vocabulary, claims):  # type: ignore[no-untyped-def]
    return PolicyGroundGraph(
        retriever=retriever,
        client=ScriptedComposer(claims),
        threshold=settings.sufficiency_threshold,
        default_top_k=settings.retrieval_top_k,
        embedder_name="hash-embedder-v1",
        degraded=True,
        vocabulary=vocabulary,
    )


# ------------------------------------------------------------ graph shape --


def test_node_path_matches_the_spec_diagram(graph: PolicyGroundGraph) -> None:
    """Spec 08 §8's sequence, asserted rather than assumed."""
    answered = graph.run_state(ANSWERABLE, role=Role.STAFF)
    assert answered["node_path"] == EXPECTED_ANSWER_PATH

    refused = graph.run_state(OFF_CORPUS, role=Role.STAFF)
    assert refused["node_path"] == EXPECTED_REFUSAL_PATH


def test_the_refusal_path_never_calls_the_model(retriever, settings, vocabulary) -> None:  # type: ignore[no-untyped-def]
    """The economy of refusing: an off-corpus question costs one retrieval and no model call.

    Enforced by scripting a composer that raises — if it is ever reached, the test fails.
    """
    exploding = scripted_graph(
        retriever, settings, vocabulary, RuntimeError("compose must not run on the refusal path")
    )
    response = exploding.ask(OFF_CORPUS, role=Role.STAFF)

    assert isinstance(response, Refusal)
    assert "compose" not in response.trace.model_dump()  # sanity: no compose in the trace


# ----------------------------------------------------------- answer branch --


def test_an_answerable_question_returns_a_cited_answer(graph: PolicyGroundGraph) -> None:
    response = graph.ask(ANSWERABLE, role=Role.STAFF)

    assert isinstance(response, Answer)
    assert response.kind == "answer"
    assert response.claims
    assert all(claim.citation_ids for claim in response.claims)


def test_every_rendered_citation_id_resolves_to_a_returned_citation(
    graph: PolicyGroundGraph,
) -> None:
    """A superscript with no matching source card is a broken UI and a broken promise."""
    response = graph.ask(ANSWERABLE, role=Role.STAFF)
    assert isinstance(response, Answer)

    available = {citation.citation_id for citation in response.citations}
    assert response.cited_ids <= available


def test_only_cited_chunks_become_citations(graph: PolicyGroundGraph) -> None:
    """Returning all of top_k would fill the sources panel with passages supporting nothing."""
    response = graph.ask(ANSWERABLE, role=Role.STAFF)
    assert isinstance(response, Answer)
    assert {c.citation_id for c in response.citations} == response.cited_ids


# ---------------------------------------------------------- refusal branch --


def test_an_off_corpus_question_refuses_with_closest_sections(graph: PolicyGroundGraph) -> None:
    """Spec 08 §4 F4: refusal + closest sections + the "should this be a policy?" prompt."""
    response = graph.ask(OFF_CORPUS, role=Role.STAFF)

    assert isinstance(response, Refusal)
    assert response.kind == "refusal"
    assert response.reason == "insufficient_evidence"
    assert response.closest_sections
    assert "can't find this in the policies" in response.message
    assert "Should this be a policy?" in response.suggestion_prompt


def test_a_refusal_has_no_claims_field_at_all(graph: PolicyGroundGraph) -> None:
    """PLAN.md D-015: a refusal carries nothing the UI could render in answer shape.

    This is the structural half of spec 08 §9's "never styled like a normal answer".
    """
    response = graph.ask(OFF_CORPUS, role=Role.STAFF)
    payload = response.model_dump()

    assert "claims" not in payload
    assert "citations" not in payload
    assert payload["kind"] == "refusal"


def test_closest_sections_are_deduplicated_by_policy(graph: PolicyGroundGraph) -> None:
    response = graph.ask(OFF_CORPUS, role=Role.STAFF)
    assert isinstance(response, Refusal)
    ids = [section.policy_id for section in response.closest_sections]
    assert len(ids) == len(set(ids))


def test_closest_sections_never_name_a_policy_the_role_cannot_see(
    graph: PolicyGroundGraph, chunks: list[Chunk]
) -> None:
    """A "did you mean?" list is a real disclosure channel, and this closes it.

    Suggestions are drawn from already-filtered hits, so a guest refused on a restricted topic is
    never told which restricted policy would have answered.
    """
    labels = {chunk.policy_id: chunk.label for chunk in chunks}

    for role in (Role.GUEST, Role.STAFF):
        response = graph.ask(RESTRICTED_TOPIC, role=role)
        if not isinstance(response, Refusal):
            continue
        for section in response.closest_sections:
            assert labels[section.policy_id] is not Label.RESTRICTED


# --------------------------------------- the second refusal path (post-model) --


def test_a_model_that_cites_nothing_produces_a_refusal_not_an_empty_answer(
    retriever, settings, vocabulary
) -> None:  # type: ignore[no-untyped-def]
    """Retrieval was fine; the model failed to ground itself. The result must still be a refusal.

    This is the path that makes spec 08 §11's "no answer without citations, by construction" true
    even when the sufficiency check passed.
    """
    graph = scripted_graph(
        retriever,
        settings,
        vocabulary,
        [Claim(text="The threshold is USD 5,000.", citation_ids=[])],
    )
    response = graph.ask(ANSWERABLE, role=Role.STAFF)

    assert isinstance(response, Refusal)
    assert response.reason == "no_surviving_claims"


def test_a_model_that_fabricates_every_id_produces_a_refusal(
    retriever, settings, vocabulary
) -> None:  # type: ignore[no-untyped-def]
    graph = scripted_graph(
        retriever,
        settings,
        vocabulary,
        [Claim(text="Confident but invented.", citation_ids=["PG-9999::001"])],
    )
    response = graph.ask(ANSWERABLE, role=Role.STAFF)

    assert isinstance(response, Refusal)
    assert response.reason == "no_surviving_claims"


def test_partial_fabrication_yields_an_answer_with_the_bad_claim_stripped(
    retriever, settings, vocabulary
) -> None:  # type: ignore[no-untyped-def]
    state_graph = scripted_graph(
        retriever,
        settings,
        vocabulary,
        [
            Claim(text="Grounded claim.", citation_ids=["__REAL__"]),
            Claim(text="Invented claim.", citation_ids=["PG-9999::001"]),
        ],
    )
    # Substitute a genuinely retrieved id for the placeholder.
    real_id = state_graph.retriever.search(ANSWERABLE, role=Role.STAFF, top_k=3).chunk_ids[0]
    state_graph.client = ScriptedComposer(  # type: ignore[assignment]
        [
            Claim(text="Grounded claim.", citation_ids=[real_id]),
            Claim(text="Invented claim.", citation_ids=["PG-9999::001"]),
        ]
    )
    state_graph.__post_init__()

    response = state_graph.ask(ANSWERABLE, role=Role.STAFF)

    assert isinstance(response, Answer)
    assert [c.text for c in response.claims] == ["Grounded claim."]
    assert response.stripped_claims == 1


def test_a_compose_failure_degrades_to_a_refusal_not_a_crash(
    retriever, settings, vocabulary
) -> None:  # type: ignore[no-untyped-def]
    """An API error mid-demo should be an honest refusal, not a stack trace."""
    graph = scripted_graph(retriever, settings, vocabulary, RuntimeError("API is down"))
    response = graph.ask(ANSWERABLE, role=Role.STAFF)

    assert isinstance(response, Refusal)


# ------------------------------------------------------ roles through the graph --


def test_the_same_question_refuses_for_a_guest_and_answers_for_a_controller(
    graph: PolicyGroundGraph,
) -> None:
    """The roles demo, end to end through the whole graph."""
    guest = graph.ask(RESTRICTED_TOPIC, role=Role.GUEST)
    controller = graph.ask(RESTRICTED_TOPIC, role=Role.CONTROLLER)

    assert isinstance(guest, Refusal)
    assert guest.trace.withheld_count > 0

    assert isinstance(controller, Answer)
    assert any(c.label is Label.RESTRICTED for c in controller.citations)


def test_no_answer_ever_cites_a_chunk_the_role_may_not_see(graph: PolicyGroundGraph) -> None:
    from policyground.labels import allowed_labels

    for role in Role:
        for question in (ANSWERABLE, RESTRICTED_TOPIC, "approval limits for expenditure"):
            response = graph.ask(question, role=role)
            if isinstance(response, Answer):
                for citation in response.citations:
                    assert citation.label in allowed_labels(role)


# ------------------------------------------------------------------- trace --


def test_the_trace_reports_the_degraded_fallbacks_honestly(graph: PolicyGroundGraph) -> None:
    """Every response says which embedder produced it and whether a model was involved."""
    response = graph.ask(ANSWERABLE, role=Role.STAFF)
    assert response.trace.embedder == "hash-embedder-v1"
    assert response.trace.degraded is True
    assert response.trace.backend == "local-hybrid"


def test_the_trace_records_sufficiency_against_the_threshold(graph: PolicyGroundGraph) -> None:
    answered = graph.ask(ANSWERABLE, role=Role.STAFF)
    refused = graph.ask(OFF_CORPUS, role=Role.STAFF)

    assert answered.trace.sufficiency >= answered.trace.threshold
    assert refused.trace.sufficiency < refused.trace.threshold


def test_raw_claims_are_retained_for_audit(retriever, settings, vocabulary) -> None:  # type: ignore[no-untyped-def]
    """What the model tried to say is kept, even when none of it survived."""
    graph = scripted_graph(
        retriever,
        settings,
        vocabulary,
        [Claim(text="Invented.", citation_ids=["PG-9999::001"])],
    )
    state = graph.run_state(ANSWERABLE, role=Role.STAFF)

    assert len(state["raw_claims"]) == 1
    assert state["claims"] == []
    assert state["unknown_citation_ids"] == ["PG-9999::001"]


def test_asking_is_deterministic(graph: PolicyGroundGraph) -> None:
    first = graph.ask(ANSWERABLE, role=Role.STAFF)
    second = graph.ask(ANSWERABLE, role=Role.STAFF)

    assert isinstance(first, Answer) and isinstance(second, Answer)
    assert [c.text for c in first.claims] == [c.text for c in second.claims]
    assert first.trace.sufficiency == second.trace.sufficiency


# ------------------------------------------------------------ model parsing --


def test_parse_claims_handles_a_markdown_fenced_response() -> None:
    """Models wrap JSON in a fence despite being told not to. Recoverable, so recover."""
    payload = '```json\n{"claims": [{"text": "A.", "citation_ids": ["X"]}]}\n```'
    assert parse_claims(payload) == [Claim(text="A.", citation_ids=["X"])]


def test_parse_claims_drops_malformed_entries_but_keeps_good_ones() -> None:
    payload = """{"claims": [
        {"text": "Good.", "citation_ids": ["X"]},
        {"text": "", "citation_ids": ["Y"]},
        {"citation_ids": ["Z"]},
        {"text": "No ids field"},
        "not an object"
    ]}"""
    assert parse_claims(payload) == [Claim(text="Good.", citation_ids=["X"])]


def test_parse_claims_never_invents_an_empty_citation_list() -> None:
    """A claim missing ``citation_ids`` is dropped, not defaulted.

    Defaulting would convert a *parse* failure into a *stripped-claim* failure, and the two are
    counted separately in the eval.
    """
    assert parse_claims('{"claims": [{"text": "Ungrounded."}]}') == []


def test_parse_claims_survives_garbage() -> None:
    for payload in ["", "not json", "[]", "null", '{"claims": "nope"}']:
        assert parse_claims(payload) == []


@pytest.mark.live
def test_live_model_produces_grounded_claims(retriever, settings, vocabulary) -> None:  # type: ignore[no-untyped-def]
    """Deselected by default; requires OPENAI_API_KEY. Absent in this build (BLOCKERS.md B1)."""
    if not settings.has_openai_key:
        pytest.skip("no OPENAI_API_KEY")

    from policyground.graph.llm import build_chat_client

    graph = PolicyGroundGraph(
        retriever=retriever,
        client=build_chat_client(settings),
        threshold=settings.sufficiency_threshold,
        default_top_k=settings.retrieval_top_k,
        embedder_name="live",
        degraded=False,
        vocabulary=vocabulary,
    )
    response = graph.ask(ANSWERABLE, role=Role.STAFF)
    assert isinstance(response, Answer)
    assert all(c.citation_ids for c in response.claims)
