# Pattern Library v1 — research design

Status: PAPER ONLY, descriptive research. This layer is isolated from the
production collector, alert detector, whale classifier, cron, and raw data.

## 1. Canonical leg schema

The builder reads alert JSONL and preserves each source line as a raw record.
It canonicalizes available fields into one leg shape: source file, trading
date, source line, deterministic `raw_row_id`, original `sequence_id` when
present, symbol, event timestamp and precision, contract/option code, option
type, expiry, strike, observed side evidence, quantity, price, turnover and
premium fields, bid/ask/quote context, trade conditions, underlying price and
moneyness, vendor `strategy_type` as `vendor_strategy_evidence`, schema
version, and quarantine/source-quality fields. Missing fields remain null;
they are never fabricated. The original JSON payload is retained losslessly.

## 2. Pattern definition format

`patterns/v1.json` is declarative and versioned. A definition specifies the
required leg count, expiry/strike/option-type relationships, quantity and side
constraints, allowed permutations, required evidence, disqualifiers, a
structural classification, conditional directional interpretation, and
ambiguity notes. Only relationships observable in this dataset are included.

## 3. Candidate construction

Each relevant alert event becomes a deterministic single-leg or multi-leg
candidate. Futu/own rows are observed single-leg candidates. An
`inferred_spread` is a production-modeled multi-leg observation whose legs are
parsed but remain explicitly inferred. Candidate ordering is stable by source
date, timestamp, source file, line, and ID.

## 4. Same-execution evidence

Stage A groups only rows with the same symbol and exact event timestamp. A
sequence ID, if present, is recorded as evidence; exact timestamps, contract,
expiry, quantity, quote, and trade-condition agreement/contradiction are also
exposed. The output says `same_execution_hypothesis`, never confirmed parent
order. Two prints remain two prints. Sequence equality or timestamp equality
alone cannot confirm a parent order.

## 5. Execution-family evidence

Stage B creates transparent pair hypotheses within a fixed research window.
It records repeated contract sets, quantity/98-99-lot behavior, side
continuity or reversal, expiry/strike compatibility, elapsed time, and
underlying regime. Each feature and contradiction is emitted; no opaque
confidence score or confirmed parent-order label is used.

## 6. UNKNOWN discovery

Candidates that do not satisfy an explicit definition are `UNKNOWN`, unless
missing or contradictory evidence makes them `AMBIGUOUS`. A stable fingerprint
uses contemporaneous structural features only: leg count, option types,
expiry relation, strike relation, side/quantity relation, sequence
configuration, and vendor evidence. Recurrence is ranked by recurrence,
cleanliness, and cross-date consistency, never profitability.

## 7. Discovery / holdout / prospective separation

Dates are assigned by explicit configuration to discovery, one-time holdout,
or prospective strata. The current data is too short for a defensible
holdout claim; the builder still emits the separation and marks holdout
validation as `NOT_PERFORMED`. Prospective means observations after the
configured historical end date, if supplied on a later run.

## 8. Falsification and leakage controls

No future outcomes, whale lifecycle outcomes, or post-event fields are used
in candidate matching or fingerprints. The builder preserves source facts
separately from normalized fields, derived features, hypotheses, and review
labels. It performs deterministic ID/order checks, source-to-output count
reconciliation, quarantine exclusion checks, and records all unsupported or
malformed rows with reasons. Any future predictive study must be separately
preregistered with holdout, ablation, shuffle, date-shift, contra, sensitivity,
cost, regime, and frozen-specification checks.

## 9. Current-data limitations

The alert tape has only a small number of dates, watchlist-selected symbols,
mixed legacy/v2 schemas, no reliable exchange parent-order ID, no participant
identity, incomplete sequence semantics, and modeled inferred spreads. The
available alert rows do not provide a stock leg, so collars are not defined.
The current dates cannot establish predictive edge, institutional intent,
strategy truth, or a validated holdout. 24-August observations are shown in a
separate diagnostic stratum but cannot enter eligible recurrence/ranking or
validation statistics.
