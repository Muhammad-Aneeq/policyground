---
policy_id: PG-0017
title: Journal Entry Standard and Segregation of Duties
label: internal
version: "3.6"
owner: Group Financial Controller
effective_date: 2026-01-01
supersedes: "3.5"
category: close
tags: [journals, segregation-of-duties, approval, evidence, controls]
---

# Journal Entry Standard and Segregation of Duties

The manual journal is the control point where the ledger can be changed without a transaction
behind it. This policy sets the evidence and approval standard for every such entry.

## 1. Scope

Every entry posted to the general ledger other than by an automated interface from a sub-ledger:
accruals, prepayments, reclassifications, corrections, allocations, provisions, consolidation
entries and top-side adjustments.

## 2. Standard for every entry

| Field | Requirement |
|---|---|
| Description | What the entry does, in a sentence a reviewer who did not prepare it can follow |
| Reason | Why it is needed; for a correction, what went wrong |
| Support | The calculation or document, attached — not stored elsewhere and referenced |
| Period | The period the entry relates to |
| Preparer | Named individual |
| Reviewer | A different named individual |
| Reversal | Whether the entry auto-reverses, and if not, why not |

An entry described only as "month end adjustment", "per Controller", or "reclass" fails this
standard and is rejected by the reviewer. Rejection is the reviewer's obligation, not their
discretion.

## 3. Approval levels

| Entry value (larger of debit or credit total) | Approval |
|---|---|
| Up to USD 250,000 | Independent reviewer at Financial Analyst level or above |
| Above USD 250,000 | Entity Financial Controller |
| Above USD 1,000,000 | Entity Financial Controller and Chief Financial Officer |

Stated in full: **journal entries above USD 250,000** require Entity Financial Controller approval,
and the Group additionally requires **countersignature by the Chief Financial Officer for entries
above USD 1,000,000**.

Approval is obtained before posting. Where a system permits posting before approval, the entry is
posted to a held status and released only on approval; entities may not disable that configuration.

## 4. Segregation of duties

The preparer of a journal may not approve it. This holds without exception, including for the
Financial Controller, whose own entries are approved by the Finance Director.

Where an entity is too small to provide an independent reviewer with the necessary knowledge, review
is performed by a controller from another entity in the same region. The arrangement is documented
and approved by the Group Financial Controller annually. "There is nobody else here" is a reason to
arrange cover, not a reason to self-approve.

## 5. Entries requiring additional scrutiny

The following are reviewed by the Financial Controller regardless of value:

- entries posted to revenue, other than automated interfaces from the billing system;
- entries reversing or reducing a provision;
- entries posted with an effective date in a closed period;
- entries posted outside normal working hours or at a weekend;
- entries with a round-number amount above USD 100,000;
- entries posted by a person who does not normally post to that account;
- any entry to an account owned by the preparer.

These criteria are also the standing analytics run by Internal Audit each quarter over the journal
population, and they are published here deliberately: the control works better when everyone knows
what is looked at.

## 6. Prohibited entries

- Entries with no supporting evidence, however small.
- Entries designed to achieve a budget, forecast or covenant outcome rather than to record a fact.
- Entries posted to a suspense account to defer a decision beyond the close in which the item arose.
- Entries recording a transaction between Group entities without the counterparty posting its side
  in the same period, per PG-0019.
- Backdated entries into a period already submitted under PG-0016.

## 7. Retention and audit trail

Journals and their supporting evidence are retained for seven years and are retrievable by entry
number, preparer, account and period. The audit trail records who prepared, who approved, and when
each occurred; it may not be edited, and no user is granted a role that permits editing it.

## 8. Monitoring

The Financial Controller reviews a report each close of: journals by preparer and value, journals
approved by the same person who prepared them (which should be nil, and any occurrence is
investigated within five working days), entries meeting the §5 criteria, and entries posted after
the sub-ledger close under PG-0016.
