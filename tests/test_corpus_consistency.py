"""The 30 policies agree with each other, and the check that proves it actually works.

Two halves, and the second matters as much as the first. Asserting "the corpus is consistent"
against a checker that never fails proves nothing, so every invariant here is also exercised
against a deliberately broken corpus built in a temp directory. If the mutation tests stop
failing the corpus, the guarantee has quietly evaporated (PLAN.md **D-011**, **D-018**).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from policyground.corpus.consistency import check_corpus, load_canaries, load_shared_facts
from policyground.corpus.loader import load_corpus
from policyground.corpus.models import PolicyDoc
from policyground.labels import Label

# ------------------------------------------------------- the real corpus is consistent --


def test_real_corpus_is_consistent(
    corpus: list[PolicyDoc], constants_path: Path, canaries_path: Path
) -> None:
    report = check_corpus(corpus, constants_path=constants_path, canaries_path=canaries_path)
    assert report.ok, report.render()


def test_shared_facts_are_actually_shared(constants_path: Path) -> None:
    """A "shared" fact referenced by one policy is just a number; the registry is for agreement.

    Single-reference entries are allowed (they still get the AGREEMENT and NO-ORPHAN guarantees),
    but the corpus should be genuinely cross-referenced, so most facts must span two or more
    policies for the registry to be doing its job.
    """
    facts = load_shared_facts(constants_path)
    multi = [f for f in facts if len(f.referenced_by) >= 2]
    assert len(multi) >= len(facts) // 2, (
        "most declared constants should be referenced by 2+ policies; "
        "otherwise the corpus is not genuinely cross-referenced"
    )


def test_every_constant_pattern_has_exactly_one_capture_group(constants_path: Path) -> None:
    """Enforced at load time — this test documents the contract and pins the error."""
    facts = load_shared_facts(constants_path)
    assert facts
    for fact in facts:
        assert fact.pattern.groups == 1


def test_canaries_cover_every_restricted_policy(
    corpus: list[PolicyDoc], canaries_path: Path
) -> None:
    """A restricted policy with no canary is invisible to the label-leak eval."""
    canaries = load_canaries(canaries_path)
    restricted = {doc.policy_id for doc in corpus if doc.label is Label.RESTRICTED}
    assert restricted == set(canaries), (
        f"canary coverage mismatch: restricted={sorted(restricted)} canaries={sorted(canaries)}"
    )


def test_canaries_do_not_appear_in_unrestricted_policies(
    corpus: list[PolicyDoc], canaries_path: Path
) -> None:
    canaries = load_canaries(canaries_path)
    for doc in corpus:
        if doc.label is Label.RESTRICTED:
            continue
        for policy_id, canary in canaries.items():
            assert canary not in doc.body, (
                f"canary {canary!r} for {policy_id} leaked into {doc.policy_id} ({doc.label})"
            )


def test_canaries_are_not_guessable_boilerplate(canaries_path: Path) -> None:
    """A canary a model could plausibly emit without having seen the chunk proves nothing."""
    for policy_id, canary in load_canaries(canaries_path).items():
        assert len(canary) >= 12, f"{policy_id}: canary {canary!r} is too short to be distinctive"
        lowered = canary.lower()
        assert "canary" not in lowered and "token" not in lowered, (
            f"{policy_id}: canary {canary!r} announces itself and would be stripped as junk"
        )


# ----------------------------------------------- the checker catches what it claims to --


@pytest.fixture
def broken_corpus(tmp_path: Path, settings) -> Path:  # type: ignore[no-untyped-def]
    """A writable copy of the real corpus, for mutation tests."""
    dest = tmp_path / "corpus"
    shutil.copytree(settings.corpus_dir, dest)
    return dest


def _check(corpus_dir: Path):  # type: ignore[no-untyped-def]
    docs = load_corpus(corpus_dir / "policies")
    return check_corpus(
        docs,
        constants_path=corpus_dir / "constants.yaml",
        canaries_path=corpus_dir / "canaries.yaml",
    )


def test_mutation_drifting_a_threshold_is_caught(broken_corpus: Path) -> None:
    """THE test. Change one threshold in one policy; the corpus must stop being consistent.

    This is the failure the registry exists to prevent: PG-0003 says 5,000 and PG-0007 says
    6,000, both read plausibly, and a human proof-read would very likely miss it.
    """
    target = broken_corpus / "policies" / "PG-0007-delegation-of-authority.md"
    text = target.read_text(encoding="utf-8")
    mutated = text.replace(
        "general capitalisation threshold of USD 5,000",
        "general capitalisation threshold of USD 6,000",
    )
    assert mutated != text, "fixture drifted: the phrase under test is no longer in PG-0007"
    target.write_text(mutated, encoding="utf-8")

    report = _check(broken_corpus)
    assert not report.ok
    assert any("6,000" in problem for problem in report.disagreements)


def test_mutation_deleting_a_reference_is_caught(broken_corpus: Path) -> None:
    """COVERAGE: a registered reference silently removed during an edit."""
    target = broken_corpus / "policies" / "PG-0004-ppe-recognition-depreciation.md"
    text = target.read_text(encoding="utf-8")
    mutated = text.replace("buildings are depreciated over 40 years", "buildings are long-lived")
    assert mutated != text
    target.write_text(mutated, encoding="utf-8")

    report = _check(broken_corpus)
    assert not report.ok
    assert any("useful_life_buildings_years" in p for p in report.missing_references)


def test_mutation_unregistered_reference_is_caught(broken_corpus: Path) -> None:
    """NO-ORPHAN: a policy quoting a shared number without joining the agreement check."""
    target = broken_corpus / "policies" / "PG-0029-inventory-valuation.md"
    text = target.read_text(encoding="utf-8")
    target.write_text(
        text + "\n\nStorage equipment follows the general capitalisation threshold of "
        "USD 5,000 in PG-0003.\n",
        encoding="utf-8",
    )

    report = _check(broken_corpus)
    assert not report.ok
    assert any("PG-0029" in p for p in report.orphan_references)


def test_mutation_duplicated_canary_is_caught(broken_corpus: Path) -> None:
    """A canary appearing twice, or in the wrong policy, breaks the leak test's precision."""
    canaries = load_canaries(broken_corpus / "canaries.yaml")
    canary = canaries["PG-0024"]
    target = broken_corpus / "policies" / "PG-0016-month-end-close-calendar.md"
    target.write_text(
        target.read_text(encoding="utf-8") + f"\n\nSee also {canary}.\n", encoding="utf-8"
    )

    report = _check(broken_corpus)
    assert not report.ok
    assert any("PG-0016" in p for p in report.canary_problems)


def test_mutation_missing_canary_is_caught(broken_corpus: Path) -> None:
    """A restricted policy whose canary was edited out would silently drop out of the leak eval."""
    canaries_file = broken_corpus / "canaries.yaml"
    data = yaml.safe_load(canaries_file.read_text(encoding="utf-8"))
    canary = data["canaries"]["PG-0023"]

    target = broken_corpus / "policies" / "PG-0023-litigation-and-contingencies.md"
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace(canary, "the register code"), encoding="utf-8")

    report = _check(broken_corpus)
    assert not report.ok
    assert any("PG-0023" in p and "exactly once" in p for p in report.canary_problems)


def test_mutation_dangling_cross_reference_is_caught(broken_corpus: Path) -> None:
    target = broken_corpus / "policies" / "PG-0015-accruals-prepayments-cutoff.md"
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace("PG-0003", "PG-0099", 1), encoding="utf-8")

    report = _check(broken_corpus)
    assert not report.ok
    assert any("PG-0099" in p for p in report.cross_reference_problems)


def test_checker_tolerates_a_phrase_wrapped_across_lines(broken_corpus: Path) -> None:
    """Authors wrap prose at 100 characters; the check must not depend on where the line breaks."""
    target = broken_corpus / "policies" / "PG-0003-capitalisation-thresholds.md"
    text = target.read_text(encoding="utf-8")
    mutated = text.replace(
        "general capitalisation threshold of USD 5,000",
        "general capitalisation threshold of\nUSD 5,000",
        1,
    )
    assert mutated != text
    target.write_text(mutated, encoding="utf-8")

    report = _check(broken_corpus)
    assert report.ok, report.render()


def test_report_renders_every_problem_not_just_the_first(broken_corpus: Path) -> None:
    """An author fixing a corpus wants the whole list, not one failure per run."""
    policies = broken_corpus / "policies"
    a = policies / "PG-0007-delegation-of-authority.md"
    a.write_text(
        a.read_text(encoding="utf-8").replace(
            "Department Head may approve commitments up to USD 25,000",
            "Department Head may approve commitments up to USD 30,000",
        ),
        encoding="utf-8",
    )
    b = policies / "PG-0010-corporate-card-and-petty-cash.md"
    b.write_text(
        b.read_text(encoding="utf-8").replace(
            "petty cash claim maximum of USD 500",
            "petty cash claim maximum of USD 750",
        ),
        encoding="utf-8",
    )

    report = _check(broken_corpus)
    assert len(report.disagreements) >= 2
    rendered = report.render()
    assert "30,000" in rendered and "750" in rendered


def test_numbers_with_and_without_separators_compare_equal(broken_corpus: Path) -> None:
    """``USD 5000`` and ``USD 5,000`` are the same threshold; only real drift should fail."""
    target = broken_corpus / "policies" / "PG-0003-capitalisation-thresholds.md"
    text = target.read_text(encoding="utf-8")
    mutated = re.sub(
        r"general capitalisation threshold of USD 5,000",
        "general capitalisation threshold of USD 5000",
        text,
        count=1,
    )
    assert mutated != text
    target.write_text(mutated, encoding="utf-8")

    report = _check(broken_corpus)
    assert report.ok, report.render()
