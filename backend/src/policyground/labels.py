"""Sensitivity labels and session roles — the governance vocabulary of the whole system.

This module is deliberately tiny and dependency-free, because everything else imports it and
because the mapping in ``ROLE_ALLOWED_LABELS`` is the single place where "who may see what" is
decided. Spec 08 §4 F6 requires that "restricted docs never enter context for unprivileged
roles"; that guarantee is only as good as this table plus the retriever's obligation to apply it
(PLAN.md **D-003**).

Two design points worth stating:

1. ``allowed_labels`` returns a *frozenset*, not a list, so a caller cannot append to it and
   quietly widen its own access.
2. There is no "admin" or "superuser" role that bypasses filtering. A role either has ``restricted``
   in its label set or it does not. A bypass flag would be the first thing an injection attempt
   went looking for.
"""

from __future__ import annotations

from enum import StrEnum


class Label(StrEnum):
    """Sensitivity label carried by every document and every chunk derived from it.

    Ordered least to most sensitive. The values match the front-matter written in
    ``corpus/policies/*.md`` exactly, so a typo in a policy header fails validation rather than
    silently downgrading a document to a more permissive label.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class Role(StrEnum):
    """The session role, which in v1 is simulated rather than taken from a real identity provider.

    Spec 08 §11: "Role from authenticated session (simulated in v1)." The simulation is honest —
    the role arrives as a request field — but everything downstream treats it as authoritative, so
    swapping in a real claim from an authenticated token later is a change at the API boundary
    only.
    """

    GUEST = "guest"
    STAFF = "staff"
    CONTROLLER = "controller"


#: The access matrix. Three roles rather than two so the roles demo (spec 08 §9 screen 4) shows
#: two distinct steps of content disappearing, not one.
ROLE_ALLOWED_LABELS: dict[Role, frozenset[Label]] = {
    Role.GUEST: frozenset({Label.PUBLIC}),
    Role.STAFF: frozenset({Label.PUBLIC, Label.INTERNAL}),
    Role.CONTROLLER: frozenset({Label.PUBLIC, Label.INTERNAL, Label.RESTRICTED}),
}


def allowed_labels(role: Role) -> frozenset[Label]:
    """Labels this role may retrieve.

    Raises on an unknown role rather than defaulting. A permissive default here would be a silent
    security failure; a loud one is a bug report.
    """
    try:
        return ROLE_ALLOWED_LABELS[role]
    except KeyError as exc:  # pragma: no cover - defensive; Role is a closed enum
        raise ValueError(f"unknown role: {role!r}") from exc


def can_access(role: Role, label: Label) -> bool:
    """Whether ``role`` may see content carrying ``label``."""
    return label in allowed_labels(role)


def hidden_labels(role: Role) -> frozenset[Label]:
    """The complement of :func:`allowed_labels` — used by the UI to report what is being withheld.

    Telling a user "3 policies are hidden at your role" is deliberate: silently returning fewer
    results teaches people the corpus is thin, whereas naming the gap teaches them the control
    exists. It reveals the *count*, never the content.
    """
    return frozenset(Label) - allowed_labels(role)
