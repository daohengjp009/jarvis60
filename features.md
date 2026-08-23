# HYP-002 Feature Table Specification

Committed BEFORE any analysis. No forward returns computed, no thresholds
searched, no combinations evaluated prior to this commit.

## 1. Unit of analysis
One row = one symbol-day (US trading day, post-close state).
Primary key: `code` + `date`.

## 2. Universe
AMENDED 2026-08-22, before any outcome was computed or inspected.
Original: all 28 symbols treated as research subjects, ETFs merely flagged.
Problem found: SPY/QQQ supply spy_ret_1d and qqq_ret_1d, joined onto every row.
On a QQQ row qqq_ret_1d is identical to that row's own ret_1d (same for SPY) -
a degenerate feature. It also made a SPY symbol-holdout meaningless, since
SPY's returns are embedded in every discovery row.
Revised: SPY, QQQ, IWM are BENCHMARK/CONTEXT assets only - they supply market
features and are excluded from the research universe.
Research universe: 25 symbols -
TSLA NVDA AAPL MSFT GOOGL SPCX INTC MU SKHY COHR BE AMZN META AMD NFLX
AVGO COIN PLTR MSTR ARM SMCI CRWD ORCL LLY XOM
Eligible after the min-history rule (section 5b): 23.
Date range: 2025-08-22 .. 2026-08-21 (~251 trading days, ~7,028 rows).

## 3. Splits — FROZEN, never re-drawn
Time:
  DISCOVERY  date <= 2026-05-21
  HOLDOUT    date >= 2026-05-22
Symbol - REDRAWN 2026-08-22 after benchmarks left the research universe.
Legitimate only because no outcome has been computed or inspected. This draw is
now FROZEN and must never be re-run.
  random.Random(20260822).sample(sorted(eligible_research_symbols), 6)
  SYMBOL_HOLDOUT   ARM AVGO NFLX ORCL PLTR SMCI
  SYMBOL_DISCOVERY AAPL AMD AMZN BE COHR COIN CRWD GOOGL INTC LLY META
                   MSFT MSTR MU NVDA TSLA XOM
Holdout (either kind) must not be used for tuning, threshold search,
feature selection, or any inspection before the rule is frozen and committed.
Holdout is tested ONCE.

## 4. Timestamp convention
`date` is the US trading date (Eastern Time). Every feature on a row must be
knowable after 16:00 ET on that date and before the next session opens.

## 5. Missing / zero / N/A
- `option_open_interest == 0` means NOT YET PUBLISHED, not zero.
  Set `oi_valid = 0`; all OI-derived features become NaN.
- `"N/A"` strings -> NaN.
- Zero denominators -> NaN (never 0, never inf).
- Missing symbol-day -> row excluded. No forward-fill, no interpolation.
- Rolling window with fewer than 15 of 20 valid observations -> NaN.

## 5b. Minimum history requirement (added 2026-08-22, before any analysis)
Discovered at build time: SKHY has 30 days of history and SPCX 48; every other
symbol has 251. With a 20-day trailing window these symbols yield very few rows,
each standardised against a barely-established baseline.
Rule: a symbol-day is excluded from primary analysis unless its symbol has at
least 60 trading days present in the table. Rows are retained and flagged
(`symbol_history_days`, `min_history_ok`), not deleted.
Currently excluded: SKHY (30), SPCX (48).

## 6. Look-ahead prevention
- Rolling means/stds use t-1 .. t-20 only (shift(1) then roll).
- Standardisation uses trailing windows only, never full-sample statistics.
- Outcomes begin strictly after the feature date.

## 7. Features
Direct (source: get_option_underlying_his_statistic / _his_volatility):
  underlying_price, option_volume, call_volume, put_volume,
  pc_volume_ratio, call_oi, put_oi, option_oi, pc_oi_ratio, iv, hv
  NOTE: Futu's exact `iv` definition (tenor, moneyness, weighting) is
  UNVERIFIED. Treated as an opaque vendor series.

Derived (all relative):
  iv_hv_spread, iv_hv_ratio, iv_z20, hv_z20, iv_hv_spread_z20,
  vol_z20, vol_ratio_20, pc_vol_z20, pc_oi_z20,
  oi_change, call_oi_change, put_oi_change, oi_change_pct, oi_change_z20,
  vol_oi_ratio, ret_1d, realized_vol_20, price_z20
  CORRECTED 2026-08-22: realized_vol_20 is the trailing 20-day standard
  deviation of DAILY log returns, NOT annualised. The earlier annualised
  definition, combined with the section 9 outcome formula, would have required
  a ~270% five-day move to register, making abnormal_move_5d identically zero.

Persistence:
  days_iv_z_gt2_last5, days_vol_z_gt2_last5,
  oi_change_sum_3d, oi_change_sum_5d, consec_oi_up

Cross-sectional / market:
  spy_ret_1d, qqq_ret_1d, iv_z20_xs_rank, vol_z20_xs_rank

## 7b. Known deviation: cross-sectional ranks
iv_z20_xs_rank and vol_z20_xs_rank rank each row against all research symbols
present that date, including symbol-holdout members. This shares contemporaneous
FEATURE values across the symbol split, never outcomes, and matches what would
be computable live. Retained deliberately and recorded here.
CORRECTED 2026-08-22: the build originally computed these ranks before dropping
benchmark rows, so the pool was 28 symbols rather than the 25-symbol research
universe. Benchmarks are now removed before any cross-sectional statistic.

## 8. Earnings
Used for GROUPING ONLY, never as a predictive feature. Rationale: only final
(post-revision) earnings dates are obtainable, so any as-of-date feature would
carry mild look-ahead. Primary analysis runs on the unscheduled subset.
STATUS: not yet implemented; get_earnings_calendar historical coverage is
unverified (docs indicate a 7-day span limit per call).

## 9. Outcomes — DEFINED HERE, NOT COMPUTED IN THIS TABLE
  ret_fwd_1d, ret_fwd_3d, ret_fwd_5d
  abnormal_move_5d = 1 if |ret_fwd_5d| >= 2 * realized_vol_20 * sqrt(5)
  abnormal_up_5d, abnormal_down_5d
Computed only in a separate, explicit later step.

## 10. Provenance
Backfillable (Futu serves a ROLLING 252-day window; a frozen copy is kept
under data/symbol_history/frozen/ because the tail expires):
  everything in section 7.
Live-capture only, NOT in this table:
  per-strike OI/IV, skew, term structure, moneyness distribution (snapshot.py)
  intraday IV/greeks/spread (intraday.py)
  tick direction and cluster structure (collect.py, HYP-001)

## 11. Relationship to HYP-001
HYP-001 remains sealed. No forward returns for TSLA/NVDA/GOOGL tick data are
examined until its own stopping rule is met.
