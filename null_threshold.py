"""HYP-002 empirical null threshold - per-symbol statistic.

Why not pooled: pooling rows across symbols lets symbol identity leak in, even
after within-symbol centring. Sparse features (days_iv_z_gt2_last5 is 0 on 75%
of rows, abnormal_move_5d on 90%) are the worst case - centring turns the tied
zeros into a per-symbol constant, and those constants correlate across symbols
(rho 0.48), producing |rho| ~ 0.22 on PURE NOISE, every time.

Statistic used instead: Spearman rho computed SEPARATELY within each symbol,
then summarised across symbols by the median. No row from symbol A is ever
compared with a row from symbol B, so symbol identity cannot enter by any route.
Sign agreement is reported alongside - an effect in 15 of 17 symbols means
something an effect in 2 does not.

Usage: python3 null_threshold.py [n_permutations]"""
import sys, os
import numpy as np, pandas as pd
from scipy import stats

BASE = os.path.dirname(os.path.abspath(__file__))
N_PERM = int(sys.argv[1]) if len(sys.argv) > 1 else 200
MIN_ROWS = 60          # per symbol, for a meaningful within-symbol correlation
NON = {"date","symbol","oi_valid","symbol_history_days","min_history_ok",
       "time_split","symbol_split","usable_for_discovery"}
OUTCOMES = ["ret_fwd_1d","ret_fwd_3d","ret_fwd_5d","abnormal_move_5d"]

d = pd.read_csv(os.path.join(BASE,"data","features","symbol_days.csv")) \
      .sort_values(["symbol","date"]).reset_index(drop=True)
g = d.groupby("symbol")["underlying_price"]
for h in (1,3,5):
    d[f"ret_fwd_{h}d"] = g.shift(-h)/d["underlying_price"] - 1
d["abnormal_move_5d"] = (d["ret_fwd_5d"].abs() >=
                         2*d["realized_vol_20"]*np.sqrt(5)).astype(float)
d.loc[d["ret_fwd_5d"].isna()|d["realized_vol_20"].isna(),"abnormal_move_5d"] = np.nan

disc = d[d["usable_for_discovery"]==1].copy()
feats = sorted(c for c in disc.columns if c not in NON and c not in OUTCOMES)
groups = {s: disc.loc[i] for s, i in disc.groupby("symbol").groups.items()}

def stat(frames):
    """Median per-symbol rho, and share of symbols agreeing in sign."""
    best_abs, best_pair, best_agree = 0.0, None, 0
    for f in feats:
        for o in OUTCOMES:
            rs = []
            for x in frames.values():
                y = x[[f,o]].dropna()
                if len(y) < MIN_ROWS: continue
                if y[f].nunique() < 3 or y[o].nunique() < 2: continue
                r = stats.spearmanr(y[f], y[o])[0]
                if np.isfinite(r): rs.append(r)
            if len(rs) < 10: continue
            m = float(np.median(rs))
            if abs(m) > best_abs:
                agree = sum(np.sign(rs) == np.sign(m))
                best_abs, best_pair, best_agree = abs(m), f"{f} ~ {o}", agree
    return best_abs, best_pair, best_agree

rng = np.random.default_rng(20260823)
print(f"per-symbol null: {N_PERM} shuffles x {len(feats)} features x {len(OUTCOMES)} outcomes")
print(f"symbols with >= {MIN_ROWS} rows: {sum(len(x) >= MIN_ROWS for x in groups.values())}\n")

best, pairs = [], []
for k in range(N_PERM):
    perm = {}
    for s, x in groups.items():
        y = x.copy()
        p = rng.permutation(len(y))
        for o in OUTCOMES:
            y[o] = y[o].to_numpy()[p]
        perm[s] = y
    m, pair, _ = stat(perm)
    best.append(m); pairs.append(pair)
    if (k+1) % 20 == 0:
        print(f"  {k+1}/{N_PERM}  running 95th pct = {np.percentile(best,95):.4f}", flush=True)

b = np.array(best)
print(f"\n=== EMPIRICAL NULL (strongest median per-symbol |rho|) ===")
print(f"median {np.median(b):.4f}   90th {np.percentile(b,90):.4f}   "
      f"95th {np.percentile(b,95):.4f}   99th {np.percentile(b,99):.4f}   max {b.max():.4f}")
print(f"\nDECISION THRESHOLD: median per-symbol |rho| must exceed "
      f"{np.percentile(b,95):.4f}")
from collections import Counter
print("\nwhich pair won, across shuffles (spread = healthy null):")
for p, c in Counter(pairs).most_common(5): print(f"  {c:3d}x  {p}")
np.save(os.path.join(BASE,"data","null_max_rho.npy"), b)
