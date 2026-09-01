# Pattern Library v1 Audit + Negative Controls v1

Verdict: **PASS_WITH_LIMITATIONS**

Plan SHA-256: `37aa9f247fc0bc88e0f47e66bc807e57bf6dfc59e9c4551b2fc6a66dc7d9b5a8`

## Baseline reproduction

```json
{
  "ambiguous_count": 0,
  "candidate_count": 736,
  "eligible_candidate_count": 630,
  "event_rows": 736,
  "execution_family_hypothesis_count": 1277,
  "known_pattern_count": 58,
  "quarantined_candidate_count": 106,
  "raw_rows": 762,
  "recurring_unknown_fingerprint_rows": 553,
  "review_queue_rows": 1111,
  "same_execution_hypothesis_count": 136,
  "unknown_count": 572
}
```

All baseline assertions, record coverage checks, duplicate checks, and exact test checks are recorded in `audit_report.json`. The frozen `output/v1/report.md` is stale because it contains literal count placeholders; JSON artifacts are internally consistent.

## Required audit results

- Known patterns audited: **58 / 58**.
- Eligible AMBIGUOUS reachability: **0**; quarantined ambiguous records explained: **29**.
- Reversal/unwind records mechanically audited: **514 / 514**.
- Vendor/structural review records: **426**.
- Negative controls: **1000 deterministic permutations** across four fields.
- Recurring UNKNOWN fingerprints audited: **553 / 35 review records** (the recurrence table itself contains 553 fingerprints).

## Limitations

Controls test observable association patterns, not parent-order identity, participant identity, institutional intent, strategy truth, or predictive edge. The date shift is exploratory, and NVDA/GOOGL comparisons are density-normalized descriptive comparisons.

See `audit_report.json` for ratios, percentiles, empirical p-values, effect sizes, FDR q-values, record-level audits, and exact test output.
