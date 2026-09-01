# Pattern Library v1 summary

Status: PAPER ONLY; descriptive structure research, not a trading signal.

## Counts

- Source lines preserved: **762** (event lines 736, metadata lines 26)
- Candidates: **{len(candidates)}**; eligible **{summary['eligible_candidate_count']}**; quarantined **{summary['quarantined_candidate_count']}**
- Match status: known **{known}**, ambiguous **{amb}**, UNKNOWN **{unk}**
- Same-execution hypotheses: **{len(stage_a)}**; execution-family hypotheses: **{len(stage_b)}**

## Vendor versus structural evidence

{"STRUCTURAL_ONLY_CLASSIFICATION": 58, "UNRESOLVED_UNKNOWN_OR_AMBIGUOUS": 678, "VENDOR_ONLY_CLASSIFICATION": 492}

Vendor `strategy_type` is retained as evidence, never treated as truth. Sequence and timestamp are evidence, not confirmed parent-order identity.

## Recurring UNKNOWN fingerprints

- `c05f9ff33b541b541476041a`: 4 occurrences; dates=2026-08-26; symbols=TSLA; vendors={"NONE": 4}
- `cb8b80e23944fabb7ef93a69`: 3 occurrences; dates=2026-08-31; symbols=TSLA; vendors={"SINGLE_LEG": 3}
- `138cdd62905144dee17d2360`: 2 occurrences; dates=2026-08-27; symbols=NVDA; vendors={"MULTI_LEG": 2}
- `2bcddf156cb646acb48b97db`: 2 occurrences; dates=2026-08-25,2026-08-28; symbols=NVDA; vendors={"SINGLE_LEG": 2}
- `3d5688312ce133924b34ef88`: 2 occurrences; dates=2026-08-27; symbols=NVDA; vendors={"SINGLE_LEG": 2}
- `5dd5e389672e69de9a0dbc95`: 2 occurrences; dates=2026-08-25; symbols=TSLA; vendors={"SINGLE_LEG": 2}
- `68fcd7be4f26515e3f3abdee`: 2 occurrences; dates=2026-08-27,2026-08-28; symbols=TSLA; vendors={"SINGLE_LEG": 2}
- `6f3f8a9f1387065b33aa5fe6`: 2 occurrences; dates=2026-08-25,2026-08-27; symbols=NVDA; vendors={"MULTI_LEG": 2}
- `72cfd5a0c8f68a3f4aaa5c5a`: 2 occurrences; dates=2026-08-26; symbols=TSLA; vendors={"NONE": 2}
- `8eab0b0293b3a1d2e4c9358c`: 2 occurrences; dates=2026-08-28; symbols=TSLA; vendors={"NONE": 2}

## Review and validation

Review queue rows: **1111**; strata: {"COMMON_SEQUENCE_OR_TIMESTAMP_CANDIDATE": 182, "DENSE_NVDA_ACTIVITY": 423, "DIFFERENT_EXPIRY_COMBINATION": 0, "LOWER_DENSITY_GOOGL_ACTIVITY": 36, "POSSIBLE_REVERSAL_OR_UNWIND": 514, "RECURRING_UNKNOWN": 35, "REPEATED_98_99_LOT_STRUCTURE": 25, "VENDOR_VS_STRUCTURAL_DISAGREEMENT": 426}

24-August observations are retained for diagnostics but excluded from eligible recurrence/ranking statistics. Holdout validation was **not performed** because the current date span is too short; no predictive performance is reported.

## Limitations

The tape lacks reliable package-order IDs, participant identity, complete sequence semantics, stock legs, and comprehensive market coverage. Inferred spreads are modeled observations. This library cannot prove parent orders, institutional intent, strategy truth, or predictive edge.
