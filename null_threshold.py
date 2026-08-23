"""HYP-002 empirical null - corrected 2026-08-23 after independent audit.

Four corrections to the first version:
1. BLOCK permutation (block = 5 days = max outcome horizon). Overlapping forward
   returns make adjacent rows dependent; an unrestricted shuffle destroys that
   and yields a null that is too narrow.
2. ONE GLOBAL date permutation applied to every symbol, not an independent
   shuffle per symbol. Symbols move together with market regimes; independent
   shuffles destroy that covariance before the cross-symbol median is taken.
3. ALL SIX registered outcomes (features.md section 9), not four. The earlier
   four-outcome scan silently reduced the multiplicity family.
4. EMBARGO: the last 5 trading days of discovery are dropped, because their
   outcomes resolve inside the temporal holdout.

Statistic: |median across symbols of within-symbol Spearman rho|. Directional,
not magnitude-only: opposite-signed symbols cancel rather than reinforce.

Usage: python3 null_threshold.py [n_permutations]"""
import sys, os
from collections import Counter
import numpy as np, pandas as pd
from scipy import stats

BASE = os.path.dirname(os.path.abspath(__file__))
B = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
BLOCK, MIN_ROWS, MIN_SYMBOLS = 5, 60, 15
NON = {"date","symbol","oi_valid","symbol_history_days","min_history_ok",
       "time_split","symbol_split","usable_for_discovery"}
OUT = ["ret_fwd_1d","ret_fwd_3d","ret_fwd_5d",
       "abnormal_move_5d","abnormal_up_5d","abnormal_down_5d"]

d = pd.read_csv(os.path.join(BASE,"data","features","symbol_days.csv")) \
      .sort_values(["symbol","date"]).reset_index(drop=True)
g = d.groupby("symbol")["underlying_price"]
for h in (1,3,5):
    d[f"ret_fwd_{h}d"] = g.shift(-h)/d["underlying_price"] - 1
thr = 2*d["realized_vol_20"]*np.sqrt(5)
d["abnormal_move_5d"] = (d["ret_fwd_5d"].abs() >= thr).astype(float)
d["abnormal_up_5d"]   = (d["ret_fwd_5d"] >=  thr).astype(float)
d["abnormal_down_5d"] = (d["ret_fwd_5d"] <= -thr).astype(float)
bad = d["ret_fwd_5d"].isna() | d["realized_vol_20"].isna()
d.loc[bad, ["abnormal_move_5d","abnormal_up_5d","abnormal_down_5d"]] = np.nan

disc = d[d["usable_for_discovery"]==1].copy()
cal = sorted(disc["date"].unique())
embargo = set(cal[-BLOCK:])                      # outcomes resolve in holdout
disc = disc[~disc["date"].isin(embargo)].copy()
cal = sorted(disc["date"].unique())
feats = sorted(c for c in disc.columns if c not in NON and c not in OUT)
print(f"discovery rows after embargo: {len(disc):,}  (dropped {len(embargo)} dates)")
print(f"features {len(feats)}   outcomes {len(OUT)}   tests {len(feats)*len(OUT)}")
print(f"block length {BLOCK}   permutations {B}\n")

wide = {o: disc.pivot(index="date", columns="symbol", values=o).reindex(cal) for o in OUT}
groups = {s: disc.loc[i].set_index("date") for s, i in disc.groupby("symbol").groups.items()}
syms = sorted(groups)

def best_stat(outmaps):
    top, pair, nsym = 0.0, None, 0
    for f in feats:
        fv = {s: groups[s][f] for s in syms}
        for o in OUT:
            rs = []
            for s in syms:
                y = pd.concat([fv[s], outmaps[o][s]], axis=1).dropna()
                if len(y) < MIN_ROWS: continue
                if y.iloc[:,0].nunique() < 3 or y.iloc[:,1].nunique() < 2: continue
                r = stats.spearmanr(y.iloc[:,0], y.iloc[:,1])[0]
                if np.isfinite(r): rs.append(r)
            if len(rs) < MIN_SYMBOLS: continue      # same symbol count required
            m = abs(float(np.median(rs)))
            if m > top: top, pair, nsym = m, f"{f} ~ {o}", len(rs)
    return top, pair, nsym

def block_perm(rng):
    blocks = [cal[i:i+BLOCK] for i in range(0, len(cal), BLOCK)]
    order = rng.permutation(len(blocks))
    newcal = [dt for b in order for dt in blocks[b]]
    mapping = dict(zip(cal, newcal))              # ONE mapping, all symbols
    out = {}
    for o in OUT:
        w = wide[o]
        src = w.reindex([mapping[c] for c in cal])
        src.index = cal
        out[o] = {s: src[s] for s in syms}
    return out

rng = np.random.default_rng(20260823)
best, pairs = [], []
for k in range(B):
    m, p, _ = best_stat(block_perm(rng))
    best.append(m); pairs.append(p)
    if (k+1) % 50 == 0:
        print(f"  {k+1}/{B}  running 95th pct = {np.percentile(best,95):.4f}", flush=True)

b = np.array(best)
print(f"\n=== EMPIRICAL NULL  |median per-symbol rho|,  B={B} ===")
print(f"median {np.median(b):.4f}   90th {np.percentile(b,90):.4f}   "
      f"95th {np.percentile(b,95):.4f}   99th {np.percentile(b,99):.4f}   max {b.max():.4f}")
lo, hi = np.percentile(b,[93,97])
print(f"\nDECISION THRESHOLD: {np.percentile(b,95):.4f}")
print(f"Monte-Carlo sensitivity (93rd-97th pct): {lo:.4f} - {hi:.4f}")
print("\nwinning pair spread (concentration = residual artefact):")
for p,c in Counter(pairs).most_common(5): print(f"  {c:4d}x  {p}")
np.save(os.path.join(BASE,"data","null_max_rho.npy"), b)
