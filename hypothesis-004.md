# HYP-004 — Opening-window option flow and same-day direction

Written 2026-08-24, BEFORE any opening-window data has been analysed. No forward
returns for any opening window have been computed or inspected. Collection of the
test sample begins 2026-08-25.

## 1. The question
Does aggregate signed option flow in the first 30 minutes of the session predict
the underlying's direction over the remainder of that day?

## 2. Why this is being asked
On 2026-08-24 two alerts looked suggestive (TSLA C365 SELL $913k at 09:30:36,
TSLA P360 BUY $620k at 09:34:01, both bearish-implied, and TSLA fell). That is
ONE day and TWO trades, chosen after the fact. It is a reason to ask a question,
not evidence. The same session also contained a same-second SELL of TSLA C380
($3.2m) and SELL of TSLA P330 ($1.33m) - a short strangle, which is a bet on NO
large move and does not fit a directional reading at all.

## 3. Signed flow - definition
For each symbol-day, using tick data from 09:30:00 to 09:59:59 ET inclusive:
  bullish_notional = turnover of (CALL and ticker_direction BUY)
                   + turnover of (PUT  and ticker_direction SELL)
  bearish_notional = turnover of (PUT  and ticker_direction BUY)
                   + turnover of (CALL and ticker_direction SELL)
  open_flow_ratio  = (bullish - bearish) / (bullish + bearish)
Range -1 to +1. Positive = bullish-implied.

LIMITATION STATED IN ADVANCE: ticker_direction identifies the aggressor side
only. A CALL SELL may be a directional view, a covered call, or a market maker
hedging. There is no order ID, no participant type, no position data. This
hypothesis tests whether the AGGREGATE has predictive value despite that
ambiguity; it does not claim to identify intent.

## 4. Inclusion rules
- Symbols: TSLA, NVDA, GOOGL (the tick-collection universe)
- A symbol-day is INCLUDED only if that day passes the 95% capture rule
  (capture_check.py) - identical standard to HYP-001
- A symbol-day is INCLUDED only if total 09:30-09:59 notional >= $500,000,
  so the ratio is not driven by a handful of small prints
- DTE > 1 contracts only, matching HYP-001, so 0-1DTE microstructure does not
  dominate. 0-1DTE is a separate question and is NOT tested here.

## 5. Outcome
  ret_rest_of_day = (close price 15:59) / (price at 10:00) - 1
Measured from the END of the observation window, so the window and the outcome
never overlap. Underlying 1-minute bars, backfilled via backfill_underlying.py.

## 6. Primary test - FROZEN
Statistic: Spearman rho between open_flow_ratio and ret_rest_of_day, computed
SEPARATELY WITHIN EACH SYMBOL, then summarised as |median across the 3 symbols|.
Rationale: pooling symbols measures symbol identity, not signal - established
empirically on 2026-08-23 (features.md section 8b).
Sign agreement across the 3 symbols is reported alongside and must be unanimous
for a GO, as in HYP-001.

Null: the outcome series is block-permuted within each symbol (block = 1 day,
since the outcome does not overlap across days), one global date mapping applied
to all symbols, B = 1000. Threshold = 95th percentile of the permuted maximum.
The threshold is computed ONCE, when the stopping rule is met, before the real
statistic is looked at.

## 7. Stopping rule
Stop when BOTH:
  - at least 40 valid symbol-days per symbol (~120 symbol-days total), AND
  - at least 20 distinct trading days collected
Hard cap: 2026-12-31. Whichever comes first after both minima are met.
No inspection of the primary statistic before then.

## 8. Verdict rules - FROZEN
GO      median |rho| exceeds the permutation threshold AND all 3 symbols agree
        in sign
KILL    median |rho| below the threshold, or signs disagree
Either way the result is recorded. A GO means "worth a larger test", never
"tradable" - 3 symbols cannot rule out symbol-specific effects.

## 9. What this hypothesis does NOT do
- It does not use machine learning. With ~120 symbol-days, any model with more
  than a couple of parameters will fit noise. A single pre-specified statistic
  is the only honest test at this sample size.
- It does not add features later. The definition in section 3 is the whole
  input. If it fails, that is an answer, not an invitation to search.
- It does not touch HYP-001, HYP-002 or HYP-003 data or seals.

## 10. Relationship to the other lines
HYP-001  sealed, tick clusters -> +60m, unseals ~mid-September
HYP-002  discovery phase, symbol-day features -> multi-day outcomes
HYP-003  live alerts, logged prospectively, no rule frozen yet
HYP-004  this one, opening window -> rest of day
Each has its own data, its own rule, and its own clock. A result in one is not
evidence for another.
