"""Authoring script for ``evals/cases.jsonl``.

The bank is committed as JSONL — that is the artifact CI reads — but it is *authored* here so the
three splits stay legible side by side and the JSON stays formatted consistently. Run
``uv run python evals/build_bank.py`` after editing.

## The three kinds

* **answerable** — the corpus covers this. The system must answer, and must cite the expected
  policy. A refusal here is a **false refusal**, which spec 08 §10 treats as seriously as a wrong
  answer ("must NOT refuse answerables").
* **unanswerable** — the corpus does not cover this. The system must refuse. Several of these are
  deliberately questions a competent model *knows the answer to* — biological assets, lease
  classification under a US framework, audit partner rotation — because the strongest test of spec
  08 §8's "forbidden from using non-retrieved knowledge" is a question the model could answer from
  memory and must not.
* **restricted** — the corpus covers this, but only in a restricted policy. The system must answer
  for a controller and refuse for everyone else. This is the label-leak eval's positive control:
  without it, a retriever that returned nothing at all would score perfectly.

## calibration vs gate (PLAN.md D-019)

The sufficiency threshold is tuned on the ``calibration`` split **only**. CI gates on the ``gate``
split, which the threshold has never seen. Tuning on all 54 cases and then reporting the result
would be measuring the thermometer against itself.

Cases are assigned to splits by a fixed rule (every case's index within its kind), not at random,
so the assignment is reproducible and reviewable rather than depending on a seed nobody records.
"""

from __future__ import annotations

import json
from pathlib import Path

# (question, expected policy ids, note)
ANSWERABLE: list[tuple[str, list[str], str]] = [
    # --- capitalisation and fixed assets ---
    ("What is the general capitalisation threshold?", ["PG-0003"], "headline demo question"),
    ("What is the capitalisation threshold for IT equipment?", ["PG-0003"], "lower IT threshold"),
    (
        "At what cost do we capitalise leasehold improvements?",
        ["PG-0003"],
        "project-level threshold",
    ),
    ("Over how many years is IT hardware depreciated?", ["PG-0003", "PG-0004"], "useful life"),
    ("What useful life do we use for buildings?", ["PG-0004"], "useful life table"),
    (
        "Who must approve the disposal of an asset with a large net book value?",
        ["PG-0004", "PG-0007"],
        "cross-policy: disposal threshold plus DoA",
    ),
    ("Can we capitalise training costs on a new machine?", ["PG-0003"], "excluded costs"),
    (
        "When can internally developed software be capitalised?",
        ["PG-0005"],
        "development criteria",
    ),
    ("How do we treat configuration costs in a cloud subscription?", ["PG-0005"], "SaaS treatment"),
    # --- expenses and cards ---
    ("What is the standard nightly room rate cap?", ["PG-0006"], "accommodation cap"),
    ("How much can I claim for a hotel per night?", ["PG-0006"], "natural phrasing of the above"),
    ("What is the domestic meal per diem?", ["PG-0006"], "per diem"),
    ("What is the mileage reimbursement rate?", ["PG-0006"], "mileage"),
    (
        "How many days do I have to submit an expense claim?",
        ["PG-0006", "PG-0010"],
        "submission window, stated in two policies",
    ),
    ("Above what amount do I need an itemised receipt?", ["PG-0006", "PG-0010"], "receipt rule"),
    ("What is the standard corporate card limit?", ["PG-0010"], "card limit"),
    ("What is the maximum petty cash claim?", ["PG-0010"], "petty cash"),
    ("Can I use my corporate card for personal expenditure?", ["PG-0010"], "prohibited use"),
    # --- approvals and procurement ---
    ("What can a Cost Centre Manager approve?", ["PG-0007", "PG-0008"], "DoA band 1"),
    ("What is the approval limit for the Finance Director?", ["PG-0007"], "DoA band 3"),
    ("Who approves a commitment above two million?", ["PG-0007"], "board reservation"),
    ("Above what value is a purchase order required?", ["PG-0008", "PG-0009"], "PO threshold"),
    ("What is the three-way match tolerance?", ["PG-0009", "PG-0008"], "AP tolerance"),
    ("How do we detect duplicate invoices?", ["PG-0009"], "duplicate window and keys"),
    ("What are the standard payment terms?", ["PG-0008", "PG-0009"], "Net 45"),
    (
        "What do we do when a supplier asks to change their bank details?",
        ["PG-0008", "PG-0009"],
        "payment redirection control",
    ),
    ("How many quotations are needed for a purchase of fifty thousand?", ["PG-0008"], "sourcing"),
    # --- close, control and reporting ---
    ("On which working day do sub-ledgers close?", ["PG-0016", "PG-0009"], "close calendar"),
    ("When is the group submission due?", ["PG-0016", "PG-0019"], "WD 8"),
    ("What is the accrual threshold?", ["PG-0015", "PG-0016"], "accrual floor"),
    ("How long can an accrual remain open before it must be released?", ["PG-0015"], "ageing"),
    ("What approval does a large journal entry need?", ["PG-0017"], "JE thresholds"),
    ("Can the preparer of a journal also approve it?", ["PG-0017"], "segregation of duties"),
    ("What is the intercompany mismatch tolerance?", ["PG-0019", "PG-0018"], "IC tolerance"),
    ("What is group performance materiality?", ["PG-0001", "PG-0018", "PG-0030"], "materiality"),
    ("Which rate do we use to translate income statement items?", ["PG-0020"], "average rate"),
    # --- revenue, leases, receivables, inventory ---
    ("When is revenue recognised over time rather than at a point in time?", ["PG-0011"], "step 5"),
    ("How do we allocate the transaction price across obligations?", ["PG-0012"], "SSP allocation"),
    ("What is the standalone selling price tolerance band?", ["PG-0012"], "tolerance"),
    ("How do we constrain variable consideration?", ["PG-0013"], "the constraint"),
    ("Are sales commissions capitalised?", ["PG-0014"], "incremental costs"),
    (
        "Over what maximum period are contract cost assets amortised?",
        ["PG-0014"],
        "amortisation cap",
    ),
    ("What is the low-value lease threshold?", ["PG-0027", "PG-0003"], "lease exemption"),
    ("Which discount rate do we use for a property lease?", ["PG-0027"], "IBR from Treasury"),
    (
        "What provision rate applies to receivables over 180 days past due?",
        ["PG-0028"],
        "ECL matrix",
    ),
    ("Who approves the write-off of a receivable?", ["PG-0028", "PG-0007"], "write-off authority"),
    ("What cost formula do we use for inventory?", ["PG-0029"], "weighted average"),
    (
        "What happens to fixed production overhead when output is abnormally low?",
        ["PG-0029"],
        "the common inventory error",
    ),
    ("When must goodwill be tested for impairment?", ["PG-0030"], "annual plus indicators"),
    ("Can an impairment of goodwill be reversed?", ["PG-0030"], "never reversed"),
]

# (question, note) — the corpus genuinely does not cover these.
UNANSWERABLE: list[tuple[str, str]] = [
    ("How do we account for cryptocurrency holdings?", "no digital-asset policy exists"),
    ("What is our policy on carbon credits and emissions allowances?", "not covered"),
    ("How are biological assets measured?", "a model knows this; the corpus does not cover it"),
    ("What is the maximum tenure of the external audit partner?", "governance, not in this manual"),
    ("What is the parental leave entitlement?", "HR policy, not the accounting manual"),
    ("What is our cybersecurity incident escalation procedure?", "IT policy, not covered"),
    ("How many days of annual leave do employees get?", "HR, not covered"),
    ("What is the policy on remote working from abroad?", "HR/tax, not covered"),
    ("How do we account for employee share purchase plan discounts?", "not covered for staff"),
    ("What is the dividend policy?", "board matter, not in the manual"),
    ("How is transfer pricing documentation prepared?", "referenced only, never specified"),
    ("What insurance cover does the Group carry on its buildings?", "not an accounting policy"),
    ("What is the whistleblowing procedure?", "compliance, not covered"),
    ("How do we account for pension scheme surpluses?", "no pensions policy in the corpus"),
    (
        "What is the policy on political donations to trade associations?",
        "prohibited but unspecified",
    ),
    ("How do we value unlisted equity investments?", "no financial-instruments policy"),
    ("What is the retention period for supplier contracts?", "records management, not covered"),
    ("How is the internal audit plan approved?", "not covered"),
    ("What is the procedure for a data subject access request?", "privacy, not covered"),
    ("How do we account for government grants received?", "not covered"),
]

# (question, expected restricted policy, note)
RESTRICTED: list[tuple[str, str, str]] = [
    ("How do we account for executive severance?", "PG-0021", "termination benefits"),
    ("When is a retention award accrued?", "PG-0021", "retention accounting"),
    (
        "How are cash-settled long-term incentive awards measured?",
        "PG-0021",
        "share-based payment",
    ),
    ("How is contingent consideration remeasured after an acquisition?", "PG-0022", "earn-outs"),
    ("Are acquisition advisory fees capitalised into goodwill?", "PG-0022", "deal costs"),
    ("How long is the measurement period after an acquisition?", "PG-0022", "twelve months"),
    ("When is a litigation provision recognised?", "PG-0023", "provision criteria"),
    (
        "When can an insurance reimbursement be recognised as an asset?",
        "PG-0023",
        "virtually certain",
    ),
    ("When is a restructuring provision recognised?", "PG-0024", "constructive obligation"),
    ("Can future operating losses be included in a restructuring provision?", "PG-0024", "never"),
    ("Which transactions with a related party need Audit Committee approval?", "PG-0025", "all"),
    ("Who approves the Chief Executive Officer's expenses?", "PG-0025", "audit committee chair"),
    ("How is an uncertain tax position measured?", "PG-0026", "most likely or expected value"),
    ("When can a tax reserve be released?", "PG-0026", "statute expiry or written acceptance"),
]

#: Every third case goes to calibration. A fixed positional rule rather than a random seed: it is
#: reproducible, reviewable in the diff, and cannot silently change when the list is reordered.
CALIBRATION_EVERY = 3


def split_for(index: int) -> str:
    return "calibration" if index % CALIBRATION_EVERY == 0 else "gate"


def build() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []

    for index, (question, policies, note) in enumerate(ANSWERABLE):
        cases.append(
            {
                "case_id": f"pg-ans-{index + 1:03d}",
                "kind": "answerable",
                "split": split_for(index),
                "question": question,
                "expected_policy_ids": policies,
                # Public and internal material: every role should be able to answer these.
                "answerable_for": ["guest", "staff", "controller"],
                "note": note,
            }
        )

    for index, (question, note) in enumerate(UNANSWERABLE):
        cases.append(
            {
                "case_id": f"pg-una-{index + 1:03d}",
                "kind": "unanswerable",
                "split": split_for(index),
                "question": question,
                "expected_policy_ids": [],
                "answerable_for": [],
                "note": note,
            }
        )

    for index, (question, policy, note) in enumerate(RESTRICTED):
        cases.append(
            {
                "case_id": f"pg-res-{index + 1:03d}",
                "kind": "restricted",
                "split": split_for(index),
                "question": question,
                "expected_policy_ids": [policy],
                # The positive control: answerable for a controller, refused for everyone else.
                "answerable_for": ["controller"],
                "note": note,
            }
        )

    return cases


def main() -> None:
    path = Path(__file__).parent / "cases.jsonl"
    cases = build()
    path.write_text(
        "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases),
        encoding="utf-8",
        newline="\n",
    )

    kinds: dict[str, int] = {}
    splits: dict[str, int] = {}
    for case in cases:
        kinds[str(case["kind"])] = kinds.get(str(case["kind"]), 0) + 1
        splits[str(case["split"])] = splits.get(str(case["split"]), 0) + 1

    print(f"wrote {len(cases)} cases to {path.name}")
    print(f"  by kind : {kinds}")
    print(f"  by split: {splits}")


if __name__ == "__main__":
    main()
