"""Descriptive profile of one symbol. NO forward returns, NO outcomes.
Usage: python3 profile_symbol.py MU"""
import sys, os
import numpy as np, pandas as pd
from scipy import stats

BASE = os.path.dirname(os.path.abspath(__file__))
SYM = sys.argv[1].upper() if len(sys.argv) > 1 else "MU"
d = pd.read_csv(os.path.join(BASE,"data","features","symbol_days.csv"))
d["date"] = pd.to_datetime(d["date"])
x = d[d.symbol == SYM].sort_values("date").reset_index(drop=True)
if not len(x): print(f"{SYM}: no rows"); sys.exit()
peers = d[(d.symbol != SYM) & (d.min_history_ok == 1)]

print(f"===== {SYM} =====")
print(f"{len(x)} days   {x.date.min():%Y-%m-%d} .. {x.date.max():%Y-%m-%d}   "
      f"split={x.symbol_split.iloc[0]}  usable={int(x.usable_for_discovery.sum())}")
if len(x) < 60:
    print("!! under 60 days - excluded from primary analysis; treat all of the below\n"
          "   as description only, not evidence")

print("\n--- levels vs the other symbols (percentile among peers) ---")
for c in ["iv","hv","iv_hv_spread","option_volume","pc_volume_ratio",
          "pc_oi_ratio","vol_oi_ratio"]:
    if c not in x or x[c].isna().all(): continue
    me = x[c].mean(); pm = peers.groupby("symbol")[c].mean()
    pct = (pm < me).mean()*100
    print(f"  {c:18s} {me:>12.3f}   peer median {pm.median():>10.3f}   pctile {pct:5.1f}")

print("\n--- weekday footprint (1.00 = this symbol's own average) ---")
x["dow"] = x.date.dt.day_name().str[:3]
for c in ["option_volume","pc_volume_ratio","iv","in_flow"]:
    if c not in x or x[c].isna().all(): continue
    rel = x[c] / x[c].mean() if x[c].mean() != 0 else x[c]
    t = rel.groupby(x.dow).mean().reindex(["Mon","Tue","Wed","Thu","Fri"])
    g = [v.dropna().values for _, v in rel.groupby(x.dow)]
    g = [v for v in g if len(v) > 2]
    p = stats.kruskal(*g)[1] if len(g) >= 3 else np.nan
    print(f"  {c:18s} " + " ".join(f"{k} {v:6.3f}" for k,v in t.items()) + f"   p={p:.4g}")

print("\n--- capital flow: who is buying (mean $, and share of days positive) ---")
for c in ["super_in_flow","big_in_flow","mid_in_flow","sml_in_flow"]:
    if c not in x or x[c].isna().all(): continue
    v = x[c].dropna()
    print(f"  {c:18s} mean {v.mean():>14,.0f}   positive on {(v>0).mean()*100:5.1f}% of days")
if "super_in_flow" in x:
    big = (x.super_in_flow + x.big_in_flow).dropna()
    sml = (x.mid_in_flow + x.sml_in_flow).dropna()
    n = min(len(big), len(sml))
    if n > 20:
        r = stats.spearmanr(big[:n], sml[:n])[0]
        print(f"  big vs small same-day rho: {r:+.3f}   "
              f"({'they trade together' if r > 0.3 else 'they diverge - opposite sides' if r < -0.3 else 'largely independent'})")

print("\n--- persistence: does activity cluster in runs? ---")
for c in ["vol_z20","iv_z20","flow_big_z20"]:
    if c not in x or x[c].isna().all(): continue
    v = x[c].dropna()
    if len(v) < 30: continue
    ac = v.autocorr(1)
    print(f"  {c:18s} lag-1 autocorr {ac:+.3f}   days above +2sd: {(v>2).sum()}")

print("\n--- biggest single days by option volume ---")
top = x.nlargest(5, "option_volume")[["date","option_volume","pc_volume_ratio","iv","in_flow"]]
top["date"] = top.date.dt.strftime("%Y-%m-%d")
print(top.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
