# HYP-002 Feature Table Specification

Committed BEFORE any analysis. No forward returns computed, no thresholds
searched, no combinations evaluated prior to this commit.

## 1. Unit of analysis
One row = one symbol-day (US trading day, post-close state).
Primary key: `symbol` + `date`. (The vendor `code` column is dropped at build
time; `symbol` is the identifier throughout.)

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
Date range: 2025-08-22 .. 2026-08-21 (251 trading days).
Row count: 5,845 (23 symbols x 251, plus SKHY 27 and SPCX 45). The figure of
~7,028 in the pre-amendment draft was the 28-symbol count, before benchmarks
left the research universe.

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
The stored `symbol_split` column is THREE-valued: "holdout", "discovery", and
"excluded". SKHY and SPCX are "excluded" - they belong to neither registered
list (section 5b). Added 2026-08-22: previously they defaulted to "discovery",
so the stored label contradicted the registered membership.
Holdout (either kind) must not be used for tuning, threshold search,
feature selection, or any inspection before the rule is frozen and committed.
Holdout is tested ONCE.

## 4. Timestamp convention
`date` is the US trading date (Eastern Time). Every feature on a row must be
knowable after 16:00 ET on that date and before the next session opens.

## 5. Missing / zero / N/A
- OPEN INTEREST IS PUBLISHED ONE DAY LATE (added 2026-08-22, before any
  analysis). Futu documents call_open_interest and put_open_interest as T-1
  delayed, and the newest row of every series carries 0 / "N/A" - confirmed on
  TSLA. The raw value on row t is therefore day t's OI, which is not knowable
  until t+1. All OI columns (option_oi, call_oi, put_oi, pc_oi_ratio) are
  SHIFTED BY ONE DAY at build time, so row t holds the OI known at t's close.
  Every OI-derived feature inherits this shift. Without it, nine features
  (oi_change, oi_change_pct, oi_change_z20, pc_oi_ratio, pc_oi_z20,
  vol_oi_ratio, oi_change_sum_3d, oi_change_sum_5d, consec_oi_up) would carry a
  one-day look-ahead.
- After the shift, `option_oi == 0` or NaN means NOT YET PUBLISHED, not zero.
  Set `oi_valid = 0`; all OI-derived features become NaN.
- FIELD TIMING (verified 2026-08-22). On the newest row of every series,
  option_volume, call_volume, put_volume, iv, hv and underlying_price all carry
  real values while the OI columns carry 0 / "N/A". Those fields are therefore
  same-day and need no shift; OI alone is T-1 delayed. This was checked
  empirically, not documented by the vendor for every field.
- `"N/A"` strings -> NaN.
- Zero denominators -> NaN (never 0, never inf).
- Missing symbol-day -> row excluded from the output. No forward-fill, no
  interpolation. MECHANISM (added 2026-08-22): each symbol's series is first
  reindexed onto the pooled trading-day calendar over its own first..last date
  range, so shift(1), diff() and rolling windows step by TRADING DAY rather
  than by "previous available row". A data gap therefore becomes a real NaN
  step instead of being invisible. The padded rows carry no values and are
  dropped before output; nothing is filled or interpolated.
- Rolling window with fewer than 15 of 20 valid observations -> NaN.

## 5b. Minimum history requirement (added 2026-08-22, before any analysis)
Discovered at build time: SKHY has 27 joined days and SPCX 45; every other
symbol has 251. (The raw statistic files hold 30 and 48 rows respectively; the
joined counts are lower because the volatility file is the limiting side.) With a 20-day trailing window these symbols yield very few rows,
each standardised against a barely-established baseline.
Rule: a symbol-day is excluded from primary analysis unless its symbol has at
least 60 trading days present in the table. Rows are retained and flagged
(`symbol_history_days`, `min_history_ok`), not deleted.
Currently excluded: SKHY (27), SPCX (45).

## 5c. Build-time guards (added 2026-08-22)
The build asserts rather than assumes:
- the registered symbol holdout still reproduces from seed 20260822;
- holdout + discovery + short-history partition the research universe;
- no duplicate dates in either source file per symbol;
- every registered research symbol and every benchmark is present;
- `symbol` + `date` is unique in the output;
- no output row falls outside 2025-08-22 .. 2026-08-21.
A violation fails the build loudly instead of silently producing a table over a
different universe or period.

## 5d. Output columns beyond section 7
`oi_valid`, `symbol_history_days`, `min_history_ok`, `time_split`,
`symbol_split`, and `usable_for_discovery` are bookkeeping columns, not
features. `usable_for_discovery` = time_split discovery AND symbol_split
discovery AND min_history_ok. Primary analysis filters on this compound flag,
never on `symbol_split` alone.

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
  NaN SEMANTICS (added 2026-08-22). These use their own 3- and 5-day windows,
  not the W=20/MINP=15 rule above. A window containing any NaN yields NaN, and
  consec_oi_up returns NaN for a missing input rather than 0. Previously
  (NaN > 2) evaluated False and a missing value silently read as "not extreme"
  or "zero consecutive days" - an unknown presenting as a confident number.

Cross-sectional / market:
  spy_ret_1d, qqq_ret_1d, iwm_ret_1d, iv_z20_xs_rank, vol_z20_xs_rank

Capital flow (stock side, by trade size) - ADDED 2026-08-23, before any genuine
feature-outcome pairing was inspected:
  flow_net_z20, flow_big_z20, flow_small_z20, flow_big_minus_small_z20,
  flow_big_sum_5d, consec_flow_big_up
Source: get_capital_flow(period_type="DAY"), ~250 trading days per symbol, no
quota cost, rolling window (must be re-pulled or the tail is lost).
big = super_in_flow + big_in_flow; small = mid_in_flow + sml_in_flow.
Rationale: HYP-002 asks whether large money accumulates before a move. Until now
only OPTION flow was visible; this adds the equity side, split by trade size.
An earlier note called underlying trade-level flow perishable and uncollected -
that was wrong; it is backfillable.
TIMING UNVERIFIED: the newest row carries real values (unlike OI, which shows 0),
suggesting same-day availability, but this was checked on a non-trading day. A
conservative one-day shift is applied until a live-session test settles it.
Direct flow columns retained and declared as features (consistent with the
option-side raw levels in this section): in_flow, super_in_flow, big_in_flow,
mid_in_flow, sml_in_flow. They are safe under the per-symbol statistic (section
8b), which never compares rows across symbols.
Feature count 39 -> 50 (5 direct + 6 derived); test family 234 -> 300.
  ADDED 2026-08-22: iwm_ret_1d. IWM was declared a benchmark and loaded but
  contributed no feature column, so its exclusion from the research universe
  bought nothing. It now supplies small-cap market context alongside SPY and
  QQQ. Feature count 38 -> 39.

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

## 8b. Analysis method — WITHIN-SYMBOL ONLY (added 2026-08-23, before any
##      real outcome was computed or inspected)

Established by the scrambled-label control (null_demo.py), run before any real
analysis. With outcomes permuted within each symbol - so no true association can
exist - a pooled Spearman scan returned 18-22% of tests significant at p<0.05
against an expected 5%, and 3-9 associations survived Bonferroni correction.
The winners were overwhelmingly RAW LEVEL features (underlying_price,
option_volume, call_oi, option_oi, pc_oi_ratio, vol_oi_ratio).

Cause: a within-symbol permutation destroys the day-to-day pairing but leaves
every BETWEEN-symbol difference intact. Symbols differ enormously in price
level and option volume, and also differ in mean forward return over the
sample. A pooled correlation therefore measures symbol identity, not signal.
This is the same confound that invalidated the HYP-001 pilot.

Confirmed directly: on identical shuffled data, pooled levels gave 18
significant results; subtracting each symbol's own mean from both feature and
outcome gave 3, against an expected 2.

RULE: every association in HYP-002 is estimated WITHIN SYMBOL. Feature and
outcome are both centred on the symbol's own mean before testing, or the test
is run on a per-date cross-sectional rank. Pooled raw-level correlations are
never reported, in discovery or in validation.
Symbol means are computed on the DISCOVERY period only and applied as fixed
offsets, so no holdout data enters the centring.

CORRECTED 2026-08-23, still before any real outcome was inspected. Within-symbol
CENTRING was not sufficient. Sparse features defeat it: days_iv_z_gt2_last5 is 0
on 75% of discovery rows and abnormal_move_5d on 90%, with 68.8% tied at zero on
both. Centring turns that tied mass into a per-symbol constant, and those
constants correlate across symbols (rho 0.48), so one pair produced |rho| ~ 0.22
on shuffled data in 29 of 30 permutations. A within-symbol shuffle cannot break
it, because the values are constant within symbol.

FINAL RULE: the test statistic is Spearman rho computed SEPARATELY WITHIN EACH
SYMBOL (minimum 60 rows), summarised across symbols by the MEDIAN. No row from
one symbol is ever compared with a row from another, so symbol identity cannot
enter by any route. Sign agreement across symbols is reported alongside the
median: an effect present in 15 of 17 symbols means something that an effect
in 2 does not.

EMPIRICAL DECISION THRESHOLD (100 permutations, null_threshold.py, established
2026-08-23 before any real result): median per-symbol |rho| must exceed 0.0816
(95th percentile of the strongest association found under shuffled outcomes;
median 0.0626, 99th 0.0888, max 0.0898). Under this statistic the winning pair
is spread across permutations - no pair exceeded 3 of 100 - confirming the null
behaves. Theoretical p-values are NOT used: features are strongly autocorrelated,
so nominal degrees of freedom are wrong. The permutation distribution is the
reference.

RULE: the scrambled-label control is re-run alongside every real scan, on the
same features, splits and test statistic. A real result is only reportable if
it clearly exceeds what the same procedure produces on shuffled outcomes.

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
