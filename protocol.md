# HYP-002 Analysis Protocol
Frozen 2026-08-23, before any genuine feature-outcome pairing was computed,
ranked, or inspected, and before any holdout cell was opened.

## 0. Honest framing
This is NOT an unchanged preregistration. The discovery statistic was chosen
adaptively, using negative controls, while the genuine pairing stayed blinded.
The defensible claim is: adaptive calibration under pairing blindness, followed
by a frozen confirmatory procedure. Section 1 records exactly what was exposed.

## 1. Amendment log - what was visible before each change
2026-08-22 built feature table. Exposed: feature marginals, missing rates,
  row/split counts. NOT exposed: any outcome.
2026-08-23a computed outcomes, permuted within symbol. Exposed: outcome
  marginals; associations under SHUFFLED pairing only.
  -> found pooled tests gave 18-22% significance vs 5% expected; winners were
     raw-level features. Amendment: within-symbol centring.
2026-08-23b Exposed: null maxima, identity of null-winning pairs, tie
  frequencies (days_iv_z_gt2_last5 zero on 75%, abnormal_move_5d on 90%,
  68.8% jointly), cross-symbol rate correlation 0.48.
  -> centring insufficient; tied mass encodes symbol identity. Amendment:
     per-symbol statistic, no pooling.
2026-08-23c Exposed: null distribution under naive shuffle (95th 0.0816).
  External audit identified overlapping-outcome dependence, per-symbol
  permutation destroying cross-symbol covariance, four-of-six outcome family,
  and discovery/holdout label overlap.
  -> Amendments: block permutation, single global date mapping, all six
     outcomes, 5-day embargo, B=1000.
AT NO POINT was a genuine (unshuffled) feature-outcome association computed,
ranked, signed, or inspected. No holdout cell has been opened.

2026-08-23d Probed all unused Futu 10.10 methods (read-only, no pairing seen).
  Found get_capital_flow(period_type="DAY") returns ~250 trading days of
  stock-side flow split by trade size, for all 28 symbols, at zero quota cost.
  An earlier note had called underlying trade-level flow perishable and
  uncollected; that was wrong. Added 11 features (5 direct + 6 derived).
  Verified orthogonal to existing option features (|rho| < 0.03 against
  vol_z20, oi_change_z20, pc_vol_z20), so these are new information rather
  than restatements. Publication timing UNVERIFIED - a conservative one-day
  shift is applied pending a live-session test.
  Family grows 39 features / 234 tests -> 50 / 300. The null threshold must be
  recomputed on the final table; the earlier 0.166 figure is superseded.
  Exposed: feature marginals and feature-feature correlations only. NO genuine
  feature-outcome pairing inspected. No holdout opened.

## 2. Discovery procedure - FROZEN
Cell: usable_for_discovery == 1, minus the last 5 dates (embargo: their
outcomes resolve inside the temporal holdout).
Statistic: Spearman rho within each symbol (>= 60 paired rows, feature >= 3
distinct values, outcome >= 2), aggregated as |median across symbols|.
Directional: opposite-signed symbols cancel, they do not reinforce.
Family: 50 features x 6 outcomes = 300 tests (was 39/234 before the capital
flow family was added on 2026-08-23, pre-pairing).
Null: block permutation of dates, block = 5 (= max outcome horizon), ONE date
mapping applied identically to every symbol and every outcome, preserving
cross-symbol and cross-outcome dependence. B = 1000.
Threshold: 95th percentile of the per-permutation maximum, reported with
93rd-97th sensitivity. Theoretical p-values are NOT used.
Minimum symbols per pair: 15 of 17.

## 3. Block-length sensitivity - REQUIRED before any result is believed
Block 5 is motivated by outcome overlap, not proved sufficient; volatility
regimes may persist longer, and fixed blocks cut dependence at boundaries.
The null will be recomputed at block = 5, 10, 21 and all three thresholds
reported. The PRIMARY threshold is the block-21 value if the thresholds differ
by more than 0.02, otherwise block-5. This rule is fixed now so the choice
cannot be made to suit a result.

## 4. Confirmatory procedure - FROZEN, per cell
CORRECTION: the discovery rule requires 15 symbols; the symbol-holdout cells
contain only 6. The discovery rule therefore cannot transfer unchanged. Each
cell gets its own null computed on its own structure:

  CELL A  time holdout, discovery symbols   17 symbols x  63 dates
          min symbols 15, own block-permutation null on this cell
  CELL B  symbol holdout, discovery period   6 symbols x 188 dates
          min symbols  6 (all), own null
  CELL C  both holdouts                      6 symbols x  63 dates
          min symbols  6 (all), own null

Only pairs that cross the discovery threshold are carried forward - the
confirmatory family is those pairs, not 234.
All three cells are opened ONCE, on the same day, and reported together.
No sequential peeking; no cell informs the analysis of another.
A result is confirmed only if it exceeds that cell's own threshold AND keeps
the same sign as in discovery.

## 5. Power simulation protocol - FROZEN BEFORE RUNNING
Purpose: DIAGNOSTIC ONLY. Its results may not change the statistic, block
length, threshold, or any part of sections 2-4. If it ever does, that is a
further pre-pairing amendment and must be logged in section 1.
Method: keep the observed feature matrix unchanged. Start from a block-permuted
(null) return path, add a monotone feature-linked perturbation to the DAILY
return series, then recompute ret_fwd_1d/3d/5d and the three abnormal outcomes
from the perturbed path, so structural relationships are preserved.
Grid, declared now: effect strength in {weak, moderate, strong} x prevalence in
{6, 9, 12, 17} of 17 symbols. Report the REALISED distribution of symbol-level
rho each setting produces; do not assume a requested rho is delivered.
Recovery = the DELIBERATELY INJECTED pair exceeds the registered threshold.
Any other pair crossing counts as a familywise false positive, not recovery.

## 6. One-shot rule
Discovery scan: run once, on the frozen procedure, after section 3 completes.
Holdout: opened once, ever. If any cell is inspected, HYP-002 is concluded -
there is no second attempt on this dataset.
