---
policy_id: PG-0015
title: Accruals, Prepayments and Period Cut-Off
label: internal
version: "3.3"
owner: Group Financial Controller
effective_date: 2026-01-01
supersedes: "3.2"
category: close
tags: [accruals, prepayments, cut-off, provisions, matching]
---

# Accruals, Prepayments and Period Cut-Off

Cut-off is the discipline of putting a cost in the period in which it was incurred, regardless of
when the invoice arrives or the payment is made. This policy sets out how the Group does that
consistently across entities.

## 1. Principle

A cost belongs to the period in which the goods were received or the service was performed. An
accrual is raised where that has happened and no invoice has been posted. A prepayment is recognised
where cash has been paid for a benefit not yet received.

Neither is a mechanism for smoothing results. An accrual raised without an underlying obligation, or
released without the obligation being settled or lapsing, is an accounting misstatement and is
reported under PG-0017.

## 2. Threshold

The Group applies an **accrual threshold of USD 2,500** per item. Items below the threshold are not
accrued; the cost falls into the period the invoice is posted. The threshold is applied per item,
not per supplier and not per cost centre, and items are never grouped to bring them above it or
split to bring them below it.

The threshold does not apply to payroll, tax, interest, or any item that recurs monthly, all of
which are accrued in full regardless of amount.

Items above the **general capitalisation threshold of USD 5,000** are additionally assessed under
PG-0003 before being accrued as an expense, since an accrual for a capital item is an asset addition
with a corresponding liability, not a charge to profit.

## 3. Evidence standard

Every accrual carries, in the supporting file:

| Field | Requirement |
|---|---|
| Basis | The purchase order, contract, rate card, or written estimate the amount comes from |
| Amount | The calculation, not just the result |
| Period | The period the cost relates to |
| Owner | The named individual who will confirm or release it |
| Expected settlement | When the invoice is expected |

An accrual whose basis is "prior month, repeated" is not evidenced. Recurring accruals are still
recalculated each period against the current rate or usage.

## 4. Categories

- **Goods received not invoiced.** Taken from the receipting system under PG-0009 §7, not
  re-estimated by the finance team.
- **Services performed not invoiced.** Confirmed with the budget holder against the contract
  milestone or the timesheet, and supported by their written confirmation.
- **Payroll-related.** Bonus, commission, untaken leave, overtime and employer taxes, calculated by
  Payroll and provided to each entity on Working Day 2.
- **Utilities and periodic charges.** Estimated from meter readings or the most recent bill, adjusted
  for known price changes.
- **Professional fees.** Confirmed with the engagement partner or relationship contact where the
  amount exceeds USD 25,000; an internal estimate alone is not sufficient at that level.

## 5. Release and ageing

Accruals are released when the invoice is posted or when the obligation lapses. Every accrual is
reviewed at each close by its owner and either confirmed with a current basis or released.

| Age of accrual | Action |
|---|---|
| Up to 2 close cycles | Normal; reviewed by owner |
| 3 to 5 close cycles | Explanation required in the close file; reported to the Financial Controller |
| Over 5 close cycles | Released unless the Financial Controller approves retention in writing |

A stale accrual released in a later period distorts both periods. Ageing is therefore reported as a
control metric, not a housekeeping task.

## 6. Prepayments

Prepayments are recognised where cash is paid for a benefit spanning more than one period, above the
same threshold as §2. They are released on a straight-line basis over the benefit period unless
consumption is demonstrably uneven.

Annual insurance, software subscriptions, maintenance contracts, rates and licence fees are the
common cases. A prepayment schedule is maintained per entity showing opening balance, additions,
release and closing balance, and it is reconciled to the general ledger every close under PG-0018.

Deposits paid are not prepayments; they are receivables, and they are reviewed for recoverability.

## 7. Cut-off testing

Each close, every entity tests cut-off by examining:

- the last five goods receipts before the period end and the first five after;
- every invoice above USD 25,000 posted in the first five working days of the new period, to confirm
  the service date falls in the new period;
- every credit note above USD 25,000 issued in the first five working days after the period end.

Exceptions found are corrected before submission, not disclosed as known errors.

## 8. Provisions distinguished

An accrual is a liability of certain timing and amount, or nearly so. A provision involves genuine
uncertainty in timing or amount and is governed separately; restructuring provisions and litigation
provisions are outside the scope of this policy and are approved centrally.
