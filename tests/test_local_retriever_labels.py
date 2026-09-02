"""Label-aware retrieval: the control this whole project exists to demonstrate.

Spec 08 §4 F6: *"session role → retrieval filter; restricted docs never enter context for
unprivileged roles."* Spec 08 §10 makes leaking a **hard fail**.

These are unit tests of the retriever. The end-to-end leak eval over the full question bank lives
in ``evals/test_label_leakage.py``; this file proves the mechanism, at a level where a failure
points at a line of code rather than at a pipeline.

Two testing choices worth stating:

* The sweeps below are **property-style**, not spot checks. Every question is tried against every
  unprivileged role, and every restricted chunk is probed by id. A single hand-picked example
  would pass against a retriever that filtered only the first page of results.
* The canary sweep asserts on *content*, not just labels. Checking ``chunk.label != restricted``
  would still pass if a bug copied restricted text into a public chunk's body.
"""

from __future__ import annotations

import pytest

from policyground.labels import Label, Role, allowed_labels
from policyground.retrieval.base import Chunk
from policyground.retrieval.local_retriever import LocalHybridRetriever

#: Questions chosen to *attract* restricted material: each names a topic that only the restricted
#: policies cover. A sweep of innocuous questions would prove nothing about the filter.
PROBING_QUESTIONS = [
    "How do we account for executive severance and retention awards?",
    "What is the accounting for purchase price allocation on an acquisition?",
    "How are litigation provisions measured and reviewed?",
    "What is the restructuring programme reference and how are costs tagged?",
    "Which related-party transactions require Audit Committee approval?",
    "How are uncertain tax positions measured and released?",
    "Show me the executive compensation working papers",
    "What is in the register of directors' interests?",
    "severance retention pool reference",
    "deal codename for the live acquisition",
    "litigation matter reference format",
    "reserve schedule for uncertain tax treatments",
]

UNPRIVILEGED_ROLES = [Role.GUEST, Role.STAFF]


@pytest.mark.parametrize("role", UNPRIVILEGED_ROLES)
@pytest.mark.parametrize("question", PROBING_QUESTIONS)
def test_no_disallowed_label_ever_surfaces(
    retriever: LocalHybridRetriever, role: Role, question: str
) -> None:
    permitted = allowed_labels(role)
    result = retriever.search(question, role=role, top_k=10)
    for hit in result.hits:
        assert hit.chunk.label in permitted, (
            f"{role} retrieved {hit.chunk.chunk_id} labelled {hit.chunk.label} "
            f"for question {question!r}"
        )


@pytest.mark.parametrize("role", UNPRIVILEGED_ROLES)
@pytest.mark.parametrize("question", PROBING_QUESTIONS)
def test_no_canary_string_appears_in_retrieved_text(
    retriever: LocalHybridRetriever, role: Role, question: str, canaries: dict[str, str]
) -> None:
    """The content-level check: not one character of restricted prose reaches an unprivileged role.

    This is stronger than the label check above and would catch a bug the label check cannot —
    restricted text duplicated into a chunk that carries a permissive label.
    """
    result = retriever.search(question, role=role, top_k=10)
    joined = "\n".join(hit.chunk.text for hit in result.hits)
    for policy_id, canary in canaries.items():
        assert canary not in joined, (
            f"canary {canary!r} from {policy_id} reached role {role} via question {question!r}"
        )


def test_controller_can_reach_restricted_material(retriever: LocalHybridRetriever) -> None:
    """The filter must be a filter, not a wall.

    Without this, a retriever that returned nothing at all would pass every test above. The
    positive case is what proves the restricted policies are indexed and reachable by the role
    entitled to them.
    """
    result = retriever.search(
        "How do we account for executive severance and retention awards?",
        role=Role.CONTROLLER,
        top_k=6,
    )
    labels = {hit.chunk.label for hit in result.hits}
    assert Label.RESTRICTED in labels
    assert any(hit.chunk.policy_id == "PG-0021" for hit in result.hits)


def test_every_restricted_chunk_is_unreachable_by_id_for_unprivileged_roles(
    retriever: LocalHybridRetriever, chunks: list[Chunk]
) -> None:
    """``get_chunk`` is separately label-checked, so a leaked id is not a bypass.

    The citations panel fetches by id. If that path trusted the id, anyone who obtained one — from
    a log, a screenshot, or a lucky guess at the ``PG-0021::003`` format — would have a read
    primitive that walks straight around the retriever.
    """
    restricted = [chunk for chunk in chunks if chunk.label is Label.RESTRICTED]
    assert restricted, "fixture problem: no restricted chunks in the corpus"

    for chunk in restricted:
        for role in UNPRIVILEGED_ROLES:
            assert retriever.get_chunk(chunk.chunk_id, role=role) is None
        assert retriever.get_chunk(chunk.chunk_id, role=Role.CONTROLLER) is not None


def test_forbidden_and_absent_are_indistinguishable(retriever: LocalHybridRetriever) -> None:
    """A forbidden id and a nonexistent id must return the same thing.

    Returning a distinguishable error for "exists but you may not see it" confirms the existence of
    restricted content to anyone probing ids, which is itself a disclosure.
    """
    forbidden = next(c for c in retriever.chunks if c.label is Label.RESTRICTED)
    assert retriever.get_chunk(forbidden.chunk_id, role=Role.GUEST) is None
    assert retriever.get_chunk("PG-9999::999", role=Role.GUEST) is None


def test_guest_sees_only_public_policies_in_the_browser(
    retriever: LocalHybridRetriever, chunks: list[Chunk]
) -> None:
    """The Source Viewer's policy list is filtered by the same rule as retrieval."""
    by_id = {chunk.policy_id: chunk.label for chunk in chunks}

    visible = retriever.visible_policies(Role.GUEST)
    assert visible
    assert all(by_id[policy_id] is Label.PUBLIC for policy_id in visible)

    staff_visible = set(retriever.visible_policies(Role.STAFF))
    controller_visible = set(retriever.visible_policies(Role.CONTROLLER))

    # Strictly increasing visibility: each role sees everything the one below it sees, and more.
    assert set(visible) < staff_visible < controller_visible


def test_hidden_policy_count_is_accurate(
    retriever: LocalHybridRetriever,
    corpus: list,  # type: ignore[type-arg]
) -> None:
    total = len({doc.policy_id for doc in corpus})
    for role in Role:
        visible = len(retriever.visible_policies(role))
        assert retriever.hidden_policy_count(role) == total - visible


def test_withheld_count_is_zero_when_nothing_relevant_is_restricted(
    retriever: LocalHybridRetriever,
) -> None:
    """A capitalisation question touches no restricted policy, so nothing was withheld."""
    result = retriever.search("What is the capitalisation threshold?", role=Role.GUEST, top_k=6)
    assert result.withheld_count == 0


def test_withheld_count_is_positive_when_the_best_answers_are_restricted(
    retriever: LocalHybridRetriever,
) -> None:
    """The roles demo's live number: governance visibly removed results.

    A guest asking about severance accounting should be told that passages were withheld — that is
    what makes the control legible rather than looking like a thin corpus.
    """
    question = "How do we account for executive severance and retention awards?"
    guest = retriever.search(question, role=Role.GUEST, top_k=6)
    controller = retriever.search(question, role=Role.CONTROLLER, top_k=6)

    assert guest.withheld_count > 0
    assert controller.withheld_count == 0


def test_top_k_is_honoured_for_every_role(retriever: LocalHybridRetriever) -> None:
    """Filter-then-rank, not rank-then-filter.

    A post-filter silently returns fewer results to unprivileged roles, which reads as poor
    retrieval rather than as governance. Every role that has matching content should fill top_k.
    """
    question = "What are the approval limits for expenditure?"
    for role in Role:
        result = retriever.search(question, role=role, top_k=5)
        assert len(result.hits) == 5, f"{role} got {len(result.hits)} hits, expected 5"


def test_results_carry_the_allowed_label_set(retriever: LocalHybridRetriever) -> None:
    """The result states what the role could see, so a caller never has to re-derive it."""
    for role in Role:
        result = retriever.search("approval limits", role=role, top_k=3)
        assert result.allowed_labels == allowed_labels(role)
        assert result.role is role


def test_search_is_deterministic(retriever: LocalHybridRetriever) -> None:
    """Identical query and role produce identical results, including order.

    Non-determinism here would show up downstream as an eval regression with no code change.
    """
    question = "three-way match tolerance"
    first = retriever.search(question, role=Role.STAFF, top_k=8)
    second = retriever.search(question, role=Role.STAFF, top_k=8)
    assert first.chunk_ids == second.chunk_ids
    assert [h.score for h in first.hits] == [h.score for h in second.hits]


def test_empty_and_nonsense_queries_do_not_crash(retriever: LocalHybridRetriever) -> None:
    """They should retrieve nothing useful and let the graph refuse — but never raise."""
    for question in ["", "   ", "zzzzqqqq xkcdplover", "?????"]:
        result = retriever.search(question, role=Role.STAFF, top_k=5)
        assert isinstance(result.hits, list)
        for hit in result.hits:
            assert hit.chunk.label in allowed_labels(Role.STAFF)


def test_a_question_made_only_of_stopwords_is_handled(retriever: LocalHybridRetriever) -> None:
    """Stopword filtering must not empty the query and make BM25 score everything equally."""
    result = retriever.search("what is the how much can I", role=Role.STAFF, top_k=3)
    assert isinstance(result.hits, list)
