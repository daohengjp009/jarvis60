"""Descriptive structure in the symbol-day data. NO forward returns, NO outcomes,
NO feature-outcome pairing - HYP-002's seal is untouched. These are questions
about the features themselves.

Test 1 is a CALIBRATION CHECK: the variance risk premium (IV above realised HV)
is one of the most replicated findings in options research. If it is absent
here, the dataset or the vendor's iv field is not measuring what we think.

Usage: python3 explore_structure.py"""
import os
import numpy as np, pandas as pd
from scipy import stats

BASE = os.path.dirname(os.path.abspath(__file__))
d = pd.read_csv(os.path.join(BASE, "data", "features", "symbol_days.csv"))
d["date"] = pd.to_datetime(d["date"])
d["dow"] = d["date"].dt.day_name().str[:3]
print(f"{len(d):,} symbol-days, {d.symbol.nunique()} symbols, "
      f"{d.date.min():%Y-%m-%d} to {d.date.max():%Y-%m-%d}\n")

# ---------- 1. CALIBRATION: variance risk premium ----------
print("=" * 62)
print("1. VARIANCE RISK PREMIUM  (does IV sit above HV, as literature says?)")
print("=" * 62)
per = d.dropna(subset=["iv", "hv"]).groupby("symbol").apply(
    lambda x: pd.Series({"n": len(x), "iv": x.iv.mean(), "hv": x.hv.mean(),
                         "spread": (x.iv - x.hv).mean(),
                         "pct_iv_gt_hv": (x.iv > x.hv).mean() * 100}),
    include_groups=False).sort_values("spread", ascending=False)
print(per.to_string(float_format=lambda v: f"{v:8.2f}"))
pos = (per.spread > 0).sum()
print(f"\nsymbols with mean IV > mean HV : {pos} of {len(per)}")
print(f"median premium across symbols  : {per.spread.median():.2f} vol points")
t, p = stats.wilcoxon(per.spread)
print(f"Wilcoxon on the {len(per)} symbol means : p = {p:.4f}")
print("VERDICT:", "premium present - instrument behaves as expected"
      if pos >= len(per) * 0.7 else
      "PREMIUM ABSENT - investigate the vendor iv field before trusting it")

# ---------- 2. weekday structure in put/call ----------
print("\n" + "=" * 62)
print("2. WEEKDAY STRUCTURE  (do option flows follow a calendar rhythm?)")
print("=" * 62)
for col, label in (("pc_volume_ratio", "put/call volume"),
                   ("option_volume", "option volume"),
                   ("iv", "implied vol")):
    x = d.dropna(subset=[col])
    # within-symbol: each symbol relative to its own mean, per section 8b logic
    x = x.assign(rel=x[col] / x.groupby("symbol")[col].transform("mean"))
    tab = x.groupby("dow")["rel"].mean().reindex(["Mon","Tue","Wed","Thu","Fri"])
    groups = [g["rel"].values for _, g in x.groupby("dow")]
    h, pv = stats.kruskal(*groups)
    print(f"\n{label:18s} (1.00 = that symbol's own average)")
    print("  " + "  ".join(f"{k} {v:.3f}" for k, v in tab.items()))
    print(f"  Kruskal-Wallis p = {pv:.4g}"
          + ("   <- real weekday structure" if pv < 0.001 else ""))

# ---------- 3. cross-symbol co-movement ----------
print("\n" + "=" * 62)
print("3. CO-MOVEMENT  (do the 25 names move together, or independently?)")
print("=" * 62)
for col, label in (("vol_z20", "option volume surprise"),
                   ("iv_z20", "IV surprise"),
                   ("ret_1d", "underlying return")):
    w = d.pivot(index="date", columns="symbol", values=col).dropna(axis=1, thresh=200)
    c = w.corr().values
    off = c[np.triu_indices_from(c, 1)]
    off = off[np.isfinite(off)]
    print(f"{label:24s} median pairwise rho {np.median(off):+.3f}   "
          f"range {np.nanmin(off):+.2f} to {np.nanmax(off):+.2f}   ({w.shape[1]} symbols)")
print("\nHigh co-movement means symbol-days are NOT independent observations -")
print("which is exactly why the null had to be built by permutation.")

# ---------- 4. monthly expiry footprint ----------
print("\n" + "=" * 62)
print("4. MONTHLY EXPIRY  (is the mechanical roll visible in open interest?)")
print("=" * 62)
d["is_opex"] = (d.date.dt.dayofweek == 4) & d.date.dt.day.between(15, 21)
opex = sorted(d.loc[d.is_opex, "date"].unique())
print(f"third-Friday expiries in sample: {len(opex)}")
x = d.dropna(subset=["oi_change_pct"]).copy()
x["days_to_opex"] = x["date"].apply(
    lambda t: min([(pd.Timestamp(o) - t).days for o in opex if pd.Timestamp(o) >= t] or [np.nan]))
tab = x[x.days_to_opex <= 7].groupby("days_to_opex")["oi_change_pct"].agg(["mean", "count"])
print("\nmean daily OI change (%) by days until monthly expiry:")
print((tab.assign(mean=tab["mean"] * 100)).to_string(float_format=lambda v: f"{v:8.2f}"))
print("\nA sharp negative value at 0-1 days is the roll: positions closing at expiry.")
