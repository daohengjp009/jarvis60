"""HYP-002 scrambled-label control (pre-registered, features.md section 7 note).
Computes outcomes, then DESTROYS the feature-outcome pairing by permuting the
outcome series within each symbol. Any association surviving this is noise by
construction. Run BEFORE the real analysis so the null is known first.
Writes nothing to symbol_days.csv. Usage: python3 null_demo.py [seed]"""
import sys, os
import numpy as np
import pandas as pd
from scipy import stats

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data", "features", "symbol_days.csv")
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 1

NON_FEATURES = {"date", "symbol", "oi_valid", "symbol_history_days",
                "min_history_ok", "time_split", "symbol_split",
                "usable_for_discovery"}

def main():
    d = pd.read_csv(SRC).sort_values(["symbol", "date"]).reset_index(drop=True)

    # --- outcomes, computed per symbol (never paired with features un-shuffled) ---
    g = d.groupby("symbol")["underlying_price"]
    for h in (1, 3, 5):
        d[f"ret_fwd_{h}d"] = g.shift(-h) / d["underlying_price"] - 1
    d["abnormal_move_5d"] = (d["ret_fwd_5d"].abs() >=
                             2 * d["realized_vol_20"] * np.sqrt(5)).astype(float)
    d.loc[d["ret_fwd_5d"].isna() | d["realized_vol_20"].isna(), "abnormal_move_5d"] = np.nan

    # --- SCRAMBLE: permute outcomes within each symbol, destroying the pairing ---
    rng = np.random.default_rng(SEED)
    outcomes = ["ret_fwd_1d", "ret_fwd_3d", "ret_fwd_5d", "abnormal_move_5d"]
    for sym, idx in d.groupby("symbol").groups.items():
        perm = rng.permutation(len(idx))
        for o in outcomes:
            d.loc[idx, o] = d.loc[idx, o].to_numpy()[perm]

    # --- discovery cell only, exactly as the real analysis would ---
    disc = d[d["usable_for_discovery"] == 1].copy()
    # WITHIN-SYMBOL: centre feature and outcome on each symbol's own mean
    # (features.md section 8b). Pooled levels measure symbol identity, not signal.
    for c in disc.columns:
        if c in NON_FEATURES or disc[c].dtype.kind not in "if": continue
        disc[c] = disc[c] - disc.groupby("symbol")[c].transform("mean")
    feats = sorted(c for c in d.columns
                   if c not in NON_FEATURES and c not in outcomes)
    print(f"scrambled-label control  seed={SEED}")
    print(f"rows {len(disc):,}   features {len(feats)}   outcomes {len(outcomes)}")
    print(f"tests {len(feats)*len(outcomes)}\n")

    rows = []
    for f in feats:
        for o in outcomes:
            x = disc[[f, o]].dropna()
            if len(x) < 200: continue
            r, p = stats.spearmanr(x[f], x[o])
            rows.append({"feature": f, "outcome": o, "n": len(x),
                         "rho": r, "p": p})
    res = pd.DataFrame(rows)
    res["abs_rho"] = res["rho"].abs()
    res = res.sort_values("p")

    print("=== strongest 10 associations FOUND IN PURE NOISE ===")
    print(res.head(10)[["feature", "outcome", "n", "rho", "p"]]
            .to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    n_sig = (res["p"] < 0.05).sum()
    print(f"\ntests run                 : {len(res)}")
    print(f"'significant' at p<0.05   : {n_sig}  ({n_sig/len(res)*100:.1f}%)")
    print(f"expected by chance alone  : {len(res)*0.05:.0f}  (5.0%)")
    print(f"largest |rho| in noise    : {res['abs_rho'].max():.4f}")
    print(f"Bonferroni threshold      : p < {0.05/len(res):.6f}")
    print(f"survives Bonferroni       : {(res['p'] < 0.05/len(res)).sum()}")
    print("\nEvery association above is FALSE BY CONSTRUCTION - the outcome was")
    print("shuffled. This is the bar the real analysis must clear.")

if __name__ == "__main__":
    main()
