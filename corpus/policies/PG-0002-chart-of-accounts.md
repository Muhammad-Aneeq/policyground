---
policy_id: PG-0002
title: Chart of Accounts, Account Ownership and Coding Discipline
label: public
version: "2.6"
owner: Group Financial Controller
effective_date: 2026-01-01
supersedes: "2.5"
category: governance
tags: [chart-of-accounts, coding, cost-centres, ownership]
---

# Chart of Accounts, Account Ownership and Coding Discipline

A shared chart of accounts is what makes consolidation possible without manual mapping. This
policy defines the structure of the Group chart, who owns each account, and the coding rules that
keep the ledger interpretable.

## 1. Structure of the coding block

Every posting carries a five-segment coding block:

| Segment | Length | Meaning | Example |
|---|---|---|---|
| Entity | 3 | Legal entity in the consolidation | `210` |
| Account | 6 | Natural account from the Group chart | `620400` |
| Cost centre | 6 | Owning cost centre | `CC-4125` |
| Project | 8 | Capital or client project; `00000000` if none | `PJ-004182` |
| Intercompany | 3 | Counterparty entity, or `000` for third party | `140` |

No segment is optional. A posting with a placeholder cost centre is a coding failure, not a
convenience, and reconciliation owners reject batches that use one.

## 2. Account ranges

| Range | Class | Notes |
|---|---|---|
| 1xxxxx | Assets | 11–13 current, 15–17 non-current |
| 2xxxxx | Liabilities | 21–23 current, 25–27 non-current |
| 3xxxxx | Equity | Movements require Group Technical Accounting approval |
| 4xxxxx | Revenue | Analysed by performance obligation type |
| 5xxxxx | Cost of sales | |
| 6xxxxx | Operating expenses | 62 employment, 63 property, 64 professional, 65 travel |
| 7xxxxx | Other income and expense | |
| 8xxxxx | Finance and tax | |
| 9xxxxx | Statistical and memo | Never consolidated |

## 3. Account ownership

Every account has a named owner recorded in the account master. The owner is accountable for the
account's balance being explainable at any time, for its monthly reconciliation, and for approving
any change to its description or mapping. Ownership sits with a person, not a team mailbox.

Accounts with no owner are locked to posting at the next quarterly review.

## 4. Opening, changing and closing accounts

Requests are raised through the account master workflow and require:

- a business reason that is not "the existing account is inconvenient";
- confirmation from Group Technical Accounting that no existing account fits;
- a mapping to the Group consolidation hierarchy and to the statutory chart of each affected
  entity.

Accounts are closed only when their balance is nil and no posting has been made for two
consecutive close cycles.

## 5. Coding discipline

- Code to the account that describes the **nature** of the cost, never to the account with budget
  remaining. Budget pressure is a planning problem and is resolved by reforecast, not by coding.
- Do not net income against expense. Rebates, credits and recoveries are recorded gross unless a
  policy in this manual states otherwise.
- Suspense accounts are cleared within the same close cycle in which they are used. A suspense
  balance carried across a period end is reported to the Financial Controller with an explanation.
- Reclassification entries carry a reference to the original posting.

## 6. Cost centre hierarchy

Cost centres roll into departments, departments into functions, and functions into reportable
segments. The hierarchy is maintained centrally; local changes to a rollup are not permitted
because they silently change segment reporting.
