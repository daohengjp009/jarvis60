# Evidence Addendum — Pattern Library v1 Audit + Negative Controls v1

This addendum uses only the already-frozen Pattern Library v1 outputs and the
already-generated audit results. No permutations were rerun, no thresholds
were changed, and no resolver or production work was performed.

## 1. Known-pattern audit

The independent record-level audit covered all 58 records. Results:

| Audit disposition | Count |
|---|---:|
| RULE_CONFIRMED | 58 |
| INSUFFICIENT_EVIDENCE | 0 |
| RULE_CONTRADICTED | 0 |
| TRACEABILITY_FAILURE | 0 |

Yes: all 58 were genuinely `RULE_CONFIRMED` under the independent
re-evaluation. The record-level table is in
`known_pattern_audit.jsonl`; the frozen audit reported `audited=58
failures=0`.

## 2. Candidate semantics

The 736 event rows produced 736 candidates because v1 deliberately applies a
one-raw-row-to-one-candidate mapping. The frozen mapping has cardinality
`{1: 736}` and every candidate has one `raw_row_id`. This is a candidate
observation, not a claim that one source row equals one real-world order.

Multi-leg structures are represented inside one candidate's `legs` array.
The frozen distribution is:

| Parsed leg count | Candidates |
|---:|---:|
| 1 | 625 |
| 2 | 99 |
| 3 | 11 |
| 4 | 1 |

The multi-leg source rows are the 80 `inferred_spread` and 31 `spread` rows;
their legs are parsed from the source leg text and remain explicitly inferred
or modeled. They are not independently observed package executions.

The word “candidate” is potentially misleading if read as “candidate parent
order” or “confirmed trade structure.” In v1 it means a normalized research
observation (including modeled multi-leg observations).

## 3. AMBIGUOUS reachability

The `AMBIGUOUS` path is reachable in the classifier. Synthetic tests exercised
missing side evidence, unequal-or-missing quantity, and non-opposite sides;
the exact frozen test is `test_missing_side_no_orientation_and_linkage_is_not_parent_order`.

Among eligible records, the independent reachability result was:

| Independent class | Count |
|---|---:|
| KNOWN_PATTERN | 58 |
| UNKNOWN | 572 |
| AMBIGUOUS | 0 |

The 106 quarantined candidates are separate: 29 independently have an
ambiguous structural condition and 77 are independently UNKNOWN, while the
frozen candidate status marks all quarantined candidates `AMBIGUOUS` for
quarantine purposes.

UNKNOWN is absorbing within the v1 rule set: once a record fails a structural
definition such as wrong leg count, different expiry, non-distinct strikes,
or heterogeneous option types, v1 does not search a fallback or competing
pattern definition. Partial evidence such as missing side or unequal quantity
can instead enter AMBIGUOUS when the two-leg structure is otherwise in the
ambiguity path.

## 4. Reversal/unwind audit

The frozen audit mechanically covered 514 unique review links and confirmed
that each had `CONTROLLED_SIDE_REVERSAL` and `WITHIN_30_MINUTES`. It did not
record the requested semantic disposition categories. Therefore:

| Requested disposition | Count |
|---|---:|
| REVERSAL_COMPATIBLE | NOT_RECORDED |
| INDEPENDENT_EXECUTION_PLAUSIBLE | NOT_RECORDED |
| INSUFFICIENT_PRIOR_POSITION_EVIDENCE | NOT_RECORDED |
| CONTRADICTED | NOT_RECORDED |
| UNRESOLVED | NOT_RECORDED |

Accordingly, the 514 must not be described as 514 reversals. They are 514
mechanically flagged `POSSIBLE_REVERSAL_OR_UNWIND` review records based on a
controlled side reversal in the family-link evidence.

## 5. Negative controls

The frozen audit ran 250 permutations for each of sequence, timestamp,
quantity, and contract: 1,000 total, seed `20260901`. The stored metric
denominator is `NOT_RECORDED` for each control; the values below are the
stored rates, not newly reconstructed statistics.

The audit plan recorded a right-tailed empirical p-value rule but did not
record a numeric alpha/FDR acceptance threshold. Therefore the threshold
interpretation is `NOT_RECORDED`; the numerical results must not be converted
into a new significance claim here.

| Control | Observed | Null mean | Null median | Null SD | Null 95th pct | Null 99th pct | Obs/null | Empirical p | FDR q | Effect size |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sequence | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | NOT_RECORDED | NOT_RECORDED | 1.000000 | 1.000000 | NOT_RECORDED |
| timestamp | 0.142958 | 0.010899 | 0.010616 | 0.002897 | 0.015570 | NOT_RECORDED | 13.116883 | 0.003984 | 0.005312 | 45.590915 |
| quantity | 0.151451 | 0.020416 | 0.020524 | 0.003538 | 0.026185 | NOT_RECORDED | 7.418192 | 0.003984 | 0.005312 | 37.035662 |
| contract | 0.950460 | 0.383278 | 0.383581 | 0.010183 | 0.399611 | NOT_RECORDED | 2.479818 | 0.003984 | 0.005312 | 55.701372 |

Exact metric denominators: `NOT_RECORDED`.

Interpretation: the stored results show timestamp, quantity, and contract
metrics above their stored null distributions; sequence has no observed or
null sequence agreement because sequence fields are absent. No new threshold
decision is made because the frozen plan did not specify a numeric threshold.

### Date-shift control

The frozen audit recorded only:

| Metric | Value |
|---|---:|
| Observed same-day pair rate | 1.000000 |
| One-day shifted same-day pair rate | 0.000000 |
| Observed pairs | 1,413 |
| Shifted pairs | 0 |
| Null mean, median, SD, 95th/99th percentiles, ratio, p-value, FDR q, effect size | NOT_RECORDED |
| Exact denominator | NOT_RECORDED |

This was explicitly exploratory and cannot be interpreted as a confirmatory
negative control.

## 6. Sequence absence

All 736 event rows had no sequence value in the frozen canonical raw table:

| Partition | Rows | Non-null sequence |
|---|---:|---:|
| alerts_2026-08-24.jsonl | 106 | 0 |
| alerts_2026-08-25.jsonl | 125 | 0 |
| alerts_2026-08-26.jsonl | 97 | 0 |
| alerts_2026-08-27.jsonl | 191 | 0 |
| alerts_2026-08-28.jsonl | 141 | 0 |
| alerts_2026-08-31.jsonl | 76 | 0 |
| schema v1 | 106 | 0 |
| schema v2 | 630 | 0 |

The source-file and date partitions are identical because each event file is
one date. Sequence was absent/null in the source records; it was not
discarded during canonicalization. The audit runner reattached the raw
sequence field through the frozen candidate-to-raw mapping and found zero
non-null values. Sequence-based agreement, sequence uniqueness, and any
sequence-informed parent-order or family claim therefore cannot be tested.

## 7. NVDA versus GOOGL

Stored density results:

| Symbol | Eligible candidates | Dates | Family links | Links / candidate | Links / 1,000 possible pairs | Confidence interval / null percentile |
|---|---:|---:|---:|---:|---:|---|
| NVDA | 423 | 5 | 1,146 | 2.709219 | NOT_RECORDED | NOT_RECORDED |
| GOOGL | 36 | 5 | 6 | 0.166667 | NOT_RECORDED | NOT_RECORDED |

Possible-pair denominators were not stored by the frozen audit:
`NOT_RECORDED`. The values `2.709` versus `0.167` are descriptive density
figures only and are not evidence of intent, institutional activity, or
strategy.

## 8. Duplicate/source audit

The one exact duplicate payload group was:

- Payload SHA-256: `99a0a49d3b1cc3973eb357644da3ab5464c625852b04c8e1e940c233345529ed`
- Source file: `data/alerts/alerts_2026-08-24.jsonl`
- Date: `2026-08-24`
- Symbol: `NVDA`
- Source lines: `46` and `51`
- Raw row IDs: `aadf4b1c5e44966158ac9018` and `1c3c93333d62f32ff31f06f6`
- Source kind: `futu`
- Eligibility: quarantined (`2026-08-24` transition tape)

It did not affect eligible pattern, recurrence, or linkage counts because both
records were quarantined and excluded from eligible recurrence/linkage work.
The source-line overlap audit found maximum multiplicity 1; the duplicate is
payload equality at two distinct source lines, not a source-line collision.

## 9. Vendor/structural queue

The correct queue name is `human_review_queue.jsonl`; the relevant stratum is
`VENDOR_VS_STRUCTURAL_DISAGREEMENT`. It contains 426 review records.

The frozen audit did not record a mutually exclusive comparable classification
for those 426 records. The requested breakdown is therefore:

| Category | Count |
|---|---:|
| Comparable disagreement | NOT_RECORDED |
| Comparable agreement | NOT_RECORDED |
| Vendor-only | NOT_RECORDED |
| Structural-only | NOT_RECORDED |
| Non-comparable | NOT_RECORDED |

What is recorded is that 492 candidates had vendor labels and no structural
match in the audit's vendor summary, while 58 structural matches were counted
as structural-only overall. Those totals are not a disjoint decomposition of
the 426 queue rows and must not be substituted for the requested breakdown.

## 10. Top ten recurring UNKNOWN fingerprints

These are the top ten rows of the frozen `unknown_recurrence.jsonl`, ordered
by recurrence count and fingerprint. Review priority is shown exactly as
stored.

| Fingerprint | Count | Dates | Symbols | Structure summary | Contradictions | Review priority |
|---|---:|---|---|---|---|---|
| `c05f9ff33b541b541476041a` | 4 | 2026-08-26 | TSLA | 2 legs | OPTION_TYPES_NOT_HOMOGENEOUS | recurrence 4; cross-date 1; cleanliness 0 |
| `cb8b80e23944fabb7ef93a69` | 3 | 2026-08-31 | TSLA | 1 leg | LEG_COUNT_NOT_TWO | recurrence 3; cross-date 1; cleanliness 0 |
| `138cdd62905144dee17d2360` | 2 | 2026-08-27 | NVDA | 1 leg | LEG_COUNT_NOT_TWO | recurrence 2; cross-date 1; cleanliness 0 |
| `2bcddf156cb646acb48b97db` | 2 | 2026-08-25, 2026-08-28 | NVDA | 1 leg | LEG_COUNT_NOT_TWO | recurrence 2; cross-date 2; cleanliness 0 |
| `3d5688312ce133924b34ef88` | 2 | 2026-08-27 | NVDA | 1 leg | LEG_COUNT_NOT_TWO | recurrence 2; cross-date 1; cleanliness 0 |
| `5dd5e389672e69de9a0dbc95` | 2 | 2026-08-25 | TSLA | 1 leg | LEG_COUNT_NOT_TWO | recurrence 2; cross-date 1; cleanliness 0 |
| `68fcd7be4f26515e3f3abdee` | 2 | 2026-08-27, 2026-08-28 | TSLA | 1 leg | LEG_COUNT_NOT_TWO | recurrence 2; cross-date 2; cleanliness 0 |
| `6f3f8a9f1387065b33aa5fe6` | 2 | 2026-08-25, 2026-08-27 | NVDA | 1 leg | LEG_COUNT_NOT_TWO | recurrence 2; cross-date 2; cleanliness 0 |
| `72cfd5a0c8f68a3f4aaa5c5a` | 2 | 2026-08-26 | TSLA | 2 legs | OPTION_TYPES_NOT_HOMOGENEOUS | recurrence 2; cross-date 1; cleanliness 0 |
| `8eab0b0293b3a1d2e4c9358c` | 2 | 2026-08-28 | TSLA | 3 legs | LEG_COUNT_NOT_TWO | recurrence 2; cross-date 1; cleanliness 0 |

The separate review stratum contained 35 recurring-UNKNOWN review records;
all 35 were present in `recurring_unknown_review_audit.jsonl`.

## 11. Audit implementation and immutability

Files used to generate the existing results:

- Audit runner: `research/pattern_library/audit_v1/run_audit.py`
- Frozen audit plan: `research/pattern_library/audit_v1/AUDIT_PLAN.md`
- Exact Pattern Library test: `research/pattern_library/test_pattern_library.py`
- Stored results: `audit_report.json`, `audit_manifest.json`,
  `permutation_controls.json`, `baseline_reproduction.json`,
  `known_pattern_audit.jsonl`, `reversal_audit.jsonl`, and
  `recurring_unknown_review_audit.jsonl`.

Exact commands and results:

```sh
python3 research/pattern_library/audit_v1/run_audit.py
# assertions_failed: 0; permutations: 1000; verdict: PASS_WITH_LIMITATIONS

python3 research/pattern_library/test_pattern_library.py
# test_pattern_library.py: PASS (7 tests)
```

The six source-file hashes currently match the hashes recorded in the frozen
v1 manifest. The audit manifest also records frozen v1 artifact hashes. No
frozen Pattern Library v1 file, production file, configuration, cron file,
raw dataset, or trading rule was modified by this addendum; no commit or push
was performed.

## Reassessment

The correct verdict remains `PASS_WITH_LIMITATIONS`, not `PASS`, because the
mechanical audit passed with zero failed assertions and complete required
coverage, but the frozen audit did not record several requested acceptance
metrics: reversal semantic dispositions, exact permutation denominators and
99th percentiles, date-shift null statistics, possible-pair denominators and
confidence intervals for the symbol comparison, and the disjoint vendor
queue classification. These omissions are limitations in the evidence record,
not grounds for `FAIL`, because no baseline mismatch, missing required record
coverage, or audit assertion failure was found. No new evidence was silently
generated.
