"""Cross-policy consistency: the check that makes "internally consistent" a testable property.

A 30-document manual is only credible if a threshold quoted in PG-0003 is the same threshold
quoted in PG-0007. This module enforces the three invariants documented at the top of
``corpus/constants.yaml`` (PLAN.md **D-011**):

* **AGREEMENT** — every occurrence of a shared fact's pattern captures the declared value.
  This is the one that matters. Drift between two policies becomes a failing test.
* **COVERAGE** — every policy registered as referencing a fact actually contains it, so a
  reference deleted during an edit is caught rather than quietly reducing the corpus.
* **NO-ORPHAN** — every policy that quotes a shared fact is registered against it, so a new
  reference joins the agreement check instead of escaping it.

Plus the canary invariants from ``corpus/canaries.yaml`` (PLAN.md **D-018**), which the label-leak
eval depends on being true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from policyground.corpus.models import PolicyDoc
from policyground.labels import Label


@dataclass(frozen=True, slots=True)
class SharedFact:
    """One entry from ``constants.yaml``."""

    name: str
    value: float
    unit: str
    pattern: re.Pattern[str]
    referenced_by: frozenset[str]
    description: str = ""


@dataclass(slots=True)
class ConsistencyReport:
    """Every problem found, grouped by invariant. Empty lists mean the corpus is consistent."""

    disagreements: list[str] = field(default_factory=list)
    missing_references: list[str] = field(default_factory=list)
    orphan_references: list[str] = field(default_factory=list)
    canary_problems: list[str] = field(default_factory=list)
    cross_reference_problems: list[str] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        return [
            *self.disagreements,
            *self.missing_references,
            *self.orphan_references,
            *self.canary_problems,
            *self.cross_reference_problems,
        ]

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        if self.ok:
            return "corpus consistent: no problems found"
        lines = [f"corpus consistency: {len(self.problems)} problem(s)"]
        for group, items in (
            ("value disagreement", self.disagreements),
            ("missing reference", self.missing_references),
            ("unregistered reference", self.orphan_references),
            ("canary", self.canary_problems),
            ("cross-reference", self.cross_reference_problems),
        ):
            for item in items:
                lines.append(f"  [{group}] {item}")
        return "\n".join(lines)


_NUMBER_CLEAN_RE = re.compile(r"[,\s]")
_POLICY_REF_RE = re.compile(r"\bPG-\d{4}\b")
#: Runs of whitespace in the source markdown are normalised before matching, so a declared phrase
#: may wrap across lines in a policy without defeating the check.
_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text)


def _to_number(raw: str) -> float:
    return float(_NUMBER_CLEAN_RE.sub("", raw))


def load_shared_facts(constants_path: Path) -> list[SharedFact]:
    """Parse ``constants.yaml`` into typed facts, validating the regex contract."""
    data: dict[str, Any] = yaml.safe_load(constants_path.read_text(encoding="utf-8"))
    raw_constants = data.get("constants") or {}

    facts: list[SharedFact] = []
    for name, entry in raw_constants.items():
        pattern = re.compile(entry["pattern"], re.IGNORECASE)
        if pattern.groups != 1:
            raise ValueError(
                f"constants.yaml: {name}: pattern must have exactly one capture group "
                f"(wrapping the number), found {pattern.groups}"
            )
        facts.append(
            SharedFact(
                name=name,
                value=float(entry["value"]),
                unit=str(entry.get("unit", "")),
                pattern=pattern,
                referenced_by=frozenset(entry.get("referenced_by", [])),
                description=str(entry.get("description", "")),
            )
        )
    return facts


def load_canaries(canaries_path: Path) -> dict[str, str]:
    data: dict[str, Any] = yaml.safe_load(canaries_path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in (data.get("canaries") or {}).items()}


def check_corpus(
    docs: list[PolicyDoc],
    *,
    constants_path: Path,
    canaries_path: Path,
) -> ConsistencyReport:
    """Run every invariant over the loaded corpus and return a report.

    Returns rather than raises: the CLI wants to print all problems at once, and an author fixing
    a corpus benefits far more from the complete list than from the first failure.
    """
    report = ConsistencyReport()
    facts = load_shared_facts(constants_path)
    canaries = load_canaries(canaries_path)

    by_id = {doc.policy_id: doc for doc in docs}
    normalised = {doc.policy_id: _normalise(doc.body) for doc in docs}

    _check_shared_facts(facts, by_id, normalised, report)
    _check_canaries(canaries, by_id, docs, report)
    _check_cross_references(docs, by_id, report)

    return report


def _check_shared_facts(
    facts: list[SharedFact],
    by_id: dict[str, PolicyDoc],
    normalised: dict[str, str],
    report: ConsistencyReport,
) -> None:
    for fact in facts:
        unknown = fact.referenced_by - by_id.keys()
        for policy_id in sorted(unknown):
            report.missing_references.append(
                f"{fact.name}: referenced_by names {policy_id}, which is not in the corpus"
            )

        found_in: set[str] = set()

        for policy_id, text in normalised.items():
            matches = list(fact.pattern.finditer(text))
            if not matches:
                continue
            found_in.add(policy_id)

            for match in matches:
                captured = _to_number(match.group(1))
                if captured != fact.value:
                    report.disagreements.append(
                        f"{policy_id} states {fact.name} as {match.group(1)!r} "
                        f"but constants.yaml declares {fact.value:g} "
                        f"(context: ...{_context(text, match)}...)"
                    )

        for policy_id in sorted(fact.referenced_by & by_id.keys()):
            if policy_id not in found_in:
                report.missing_references.append(
                    f"{policy_id} is registered as referencing {fact.name} "
                    f"but no text matches /{fact.pattern.pattern}/"
                )

        for policy_id in sorted(found_in - fact.referenced_by):
            report.orphan_references.append(
                f"{policy_id} quotes {fact.name} but is not listed in its referenced_by "
                f"(add it, so the agreement check covers this policy)"
            )


def _context(text: str, match: re.Match[str], width: int = 45) -> str:
    start = max(0, match.start() - width)
    end = min(len(text), match.end() + width)
    return text[start:end].strip()


def _check_canaries(
    canaries: dict[str, str],
    by_id: dict[str, PolicyDoc],
    docs: list[PolicyDoc],
    report: ConsistencyReport,
) -> None:
    restricted = {doc.policy_id for doc in docs if doc.label is Label.RESTRICTED}

    for policy_id in sorted(restricted - canaries.keys()):
        report.canary_problems.append(
            f"{policy_id} is label: restricted but has no canary in canaries.yaml "
            f"(the label-leak eval would not cover it)"
        )

    for policy_id in sorted(canaries.keys() - restricted):
        report.canary_problems.append(
            f"canaries.yaml declares a canary for {policy_id}, which is not label: restricted"
        )

    for policy_id, canary in sorted(canaries.items()):
        owner = by_id.get(policy_id)
        if owner is None:
            report.canary_problems.append(f"canary declared for unknown policy {policy_id}")
            continue

        occurrences = _normalise(owner.body).count(canary)
        if occurrences != 1:
            report.canary_problems.append(
                f"{policy_id}: canary {canary!r} appears {occurrences} time(s) in its own "
                f"policy; it must appear exactly once"
            )

        for other in docs:
            if other.policy_id == policy_id:
                continue
            if canary in _normalise(other.body):
                report.canary_problems.append(
                    f"canary {canary!r} (owned by {policy_id}) also appears in "
                    f"{other.policy_id} — a canary must be unique to one policy"
                )


def _check_cross_references(
    docs: list[PolicyDoc],
    by_id: dict[str, PolicyDoc],
    report: ConsistencyReport,
) -> None:
    """Every ``PG-00xx`` mentioned in prose must resolve to a policy that exists.

    A manual whose internal references dangle reads as unmaintained, and a citation-driven product
    that follows a dead reference looks broken in the demo.
    """
    for doc in docs:
        for referenced in sorted(set(_POLICY_REF_RE.findall(doc.body))):
            if referenced == doc.policy_id:
                continue
            if referenced not in by_id:
                report.cross_reference_problems.append(
                    f"{doc.policy_id} refers to {referenced}, which does not exist"
                )
