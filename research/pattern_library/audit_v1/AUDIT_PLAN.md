# Pattern Library v1 Audit + Negative Controls v1

Status: FROZEN AUDIT PLAN. This document is immutable for this audit run.

## Scope

Audit the frozen Pattern Library v1 artifacts in `../output/v1/` without
changing them. Audit outputs, scripts, hashes, and reports live only under
`research/pattern_library/audit_v1/`. No production code, configuration,
cron, raw dataset, trading rule, or Execution Family Resolver work is in
scope.

## Questions and acceptance criteria

1. Reproduce every baseline count independently from the frozen JSONL and
   source files; report any mismatch.
2. Investigate candidate semantics: source-kind parsing, one-row/one-candidate
   mapping, leg quantities, timestamps, sequence fields, quarantine behavior,
   and modeled inferred spreads.
3. Independently re-evaluate all 58 `KNOWN_PATTERN` records and emit a
   record-level audit table.
4. Explain the reachability of `AMBIGUOUS = 0` among eligible candidates and
   distinguish it from the 106 quarantined candidates marked ambiguous.
5. Mechanically audit every one of the 514 reversal/unwind review records.
6. Explain the 426 vendor/structural review records and separate vendor-only,
   disagreement, and structural agreement cases.
7. Audit source overlap, duplicate raw rows, duplicate candidates, and
   candidate-to-raw mapping cardinality.
8. Run at least 1,000 deterministic null permutations, covering sequence,
   timestamp, quantity, and contract fields. For each control report observed
   and null values, ratios, null percentiles, empirical p-values, effect sizes,
   and Benjamini-Hochberg FDR-adjusted p-values.
9. Run an exploratory date-shift control and label it non-confirmatory.
10. Compare NVDA and GOOGL after density normalization, including uncertainty
    and explicit denominator definitions.
11. Audit all 35 recurring-UNKNOWN review records/fingerprints.
12. Run the exact Pattern Library v1 tests and audit assertions; preserve
    commands and results.

## Fixed methods

The audit is descriptive and deterministic. JSON objects are parsed without
executing the frozen builder. Record identity is based on existing IDs and
source line numbers. Null controls use a fixed seed and 250 permutations per
feature (1,000 total), shuffling labels within date and symbol strata when the
stratum has enough records. The observed metric is computed before shuffling.
Empirical p-values use `(1 + count(null >= observed)) / (1 + N)` for
right-tailed metrics. Effect size is `(observed - null_mean) / null_sd`.
FDR adjustment is Benjamini-Hochberg over the four primary permutation tests.

The control metrics are deliberately limited to observable fields: sequence
agreement, exact timestamp agreement, equal quantity, and contract/expiry/
option-type compatibility. They do not estimate parent-order truth or trading
profitability. Date shift compares same-day family-link rates with a fixed
one-day shift of timestamps within symbol and is exploratory only.

## Verdict rules

`PASS` requires exact baseline reproduction, zero audit assertion failures,
complete record coverage for required audits, and no material unexplained
artifact discrepancy. `PASS_WITH_LIMITATIONS` is used when the audit passes
mechanically but the data cannot support causal, predictive, parent-order, or
institutional-intent claims. `FAIL` is used for baseline mismatch, missing
required coverage, or an audit assertion failure.

## Reproducibility

Run from the repository root:

```sh
python3 research/pattern_library/audit_v1/run_audit.py
python3 research/pattern_library/test_pattern_library.py
```

The plan hash is recorded in `audit_manifest.json`; changing this plan after
the run invalidates the audit.
