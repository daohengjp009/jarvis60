"""HYP-002 feature table — one row per symbol-day.
Implements features.md exactly. Computes NO forward returns and NO outcomes.
Usage: python3 features.py
Output: data/features/symbol_days.csv"""
import os, glob, random
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data", "symbol_history", "frozen")
OUT = os.path.join(BASE, "data", "features")
os.makedirs(OUT, exist_ok=True)

SYMBOLS = "TSLA NVDA AAPL MSFT GOOGL SPY QQQ SPCX INTC MU SKHY COHR BE AMZN META AMD NFLX AVGO COIN PLTR MSTR ARM IWM SMCI CRWD ORCL LLY XOM".split()
ETFS = {"SPY", "QQQ", "IWM"}
SEED = 20260822
SYMBOL_HOLDOUT = set(random.Random(SEED).sample(sorted(SYMBOLS), 7))
TIME_CUTOFF = "2026-05-21"          # discovery <= this, holdout after
W, MINP = 20, 15                    # rolling window, minimum valid observations

def zscore(s):
    """Trailing z-score: mean/std from t-1..t-20, never including t."""
    base = s.shift(1)
    mu = base.rolling(W, min_periods=MINP).mean()
    sd = base.rolling(W, min_periods=MINP).std()
    return (s - mu) / sd.replace(0, np.nan)

def ratio_to_median(s):
    med = s.shift(1).rolling(W, min_periods=MINP).median()
    return s / med.replace(0, np.nan)

def consec_positive(s):
    """Consecutive days with s > 0, reset on <=0 or NaN."""
    out, run = [], 0
    for v in s:
        run = run + 1 if (pd.notna(v) and v > 0) else 0
        out.append(run)
    return pd.Series(out, index=s.index)

def load(sym):
    fs = os.path.join(SRC, f"US_{sym}_stat.csv")
    fv = os.path.join(SRC, f"US_{sym}_vol.csv")
    if not (os.path.exists(fs) and os.path.exists(fv)):
        return None
    st = pd.read_csv(fs)
    vo = pd.read_csv(fv)[["time", "iv", "hv"]]
    d = st.merge(vo, on="time", how="inner").sort_values("time").reset_index(drop=True)
    d = d.rename(columns={
        "time": "date",
        "option_open_interest": "option_oi",
        "call_open_interest": "call_oi",
        "put_open_interest": "put_oi",
        "put_call_volume_ratio": "pc_volume_ratio",
        "put_call_open_interest_ratio": "pc_oi_ratio"})
    d["symbol"] = sym
    for c in ("pc_volume_ratio", "pc_oi_ratio", "iv", "hv", "underlying_price",
              "option_volume", "call_volume", "put_volume",
              "option_oi", "call_oi", "put_oi"):
        d[c] = pd.to_numeric(d[c], errors="coerce")     # "N/A" -> NaN
    return d

def build(d):
    # --- OI validity: 0 means "not yet published", not zero ---
    d["oi_valid"] = (d["option_oi"] > 0).astype(int)
    for c in ("option_oi", "call_oi", "put_oi", "pc_oi_ratio"):
        d[c] = d[c].where(d["oi_valid"] == 1)

    # --- volatility ---
    d["iv_hv_spread"] = d["iv"] - d["hv"]
    d["iv_hv_ratio"] = d["iv"] / d["hv"].replace(0, np.nan)
    d["iv_z20"] = zscore(d["iv"])
    d["hv_z20"] = zscore(d["hv"])
    d["iv_hv_spread_z20"] = zscore(d["iv_hv_spread"])

    # --- volume ---
    d["vol_z20"] = zscore(d["option_volume"])
    d["vol_ratio_20"] = ratio_to_median(d["option_volume"])
    d["pc_vol_z20"] = zscore(d["pc_volume_ratio"])

    # --- open interest ---
    d["pc_oi_z20"] = zscore(d["pc_oi_ratio"])
    d["oi_change"] = d["option_oi"].diff()          # NaN if either day invalid
    d["call_oi_change"] = d["call_oi"].diff()
    d["put_oi_change"] = d["put_oi"].diff()
    d["oi_change_pct"] = d["oi_change"] / d["option_oi"].shift(1).replace(0, np.nan)
    d["oi_change_z20"] = zscore(d["oi_change"])
    d["vol_oi_ratio"] = d["option_volume"] / d["option_oi"].shift(1).replace(0, np.nan)

    # --- price (backward-looking only) ---
    d["ret_1d"] = np.log(d["underlying_price"] / d["underlying_price"].shift(1))
    d["realized_vol_20"] = d["ret_1d"].shift(1).rolling(W, min_periods=MINP).std() * np.sqrt(252)
    d["price_z20"] = zscore(d["underlying_price"])

    # --- persistence ---
    d["days_iv_z_gt2_last5"] = (d["iv_z20"] > 2).rolling(5, min_periods=1).sum()
    d["days_vol_z_gt2_last5"] = (d["vol_z20"] > 2).rolling(5, min_periods=1).sum()
    d["oi_change_sum_3d"] = d["oi_change"].rolling(3, min_periods=3).sum()
    d["oi_change_sum_5d"] = d["oi_change"].rolling(5, min_periods=5).sum()
    d["consec_oi_up"] = consec_positive(d["oi_change"])
    return d

def main():
    frames = []
    for s in SYMBOLS:
        d = load(s)
        if d is None:
            print(f"  {s}: MISSING source files"); continue
        frames.append(build(d))
    df = pd.concat(frames, ignore_index=True)

    # --- market context ---
    mkt = df[df["symbol"].isin(["SPY", "QQQ"])].pivot(index="date", columns="symbol", values="ret_1d")
    mkt = mkt.rename(columns={"SPY": "spy_ret_1d", "QQQ": "qqq_ret_1d"}).reset_index()
    df = df.merge(mkt, on="date", how="left")

    # --- cross-sectional ranks within each date ---
    df["iv_z20_xs_rank"] = df.groupby("date")["iv_z20"].rank(pct=True)
    df["vol_z20_xs_rank"] = df.groupby("date")["vol_z20"].rank(pct=True)

    # --- flags and splits ---
    df["is_etf"] = df["symbol"].isin(ETFS).astype(int)
    df["time_split"] = np.where(df["date"] <= TIME_CUTOFF, "discovery", "holdout")
    df["symbol_split"] = np.where(df["symbol"].isin(SYMBOL_HOLDOUT), "holdout", "discovery")
    hist = df.groupby("symbol")["date"].transform("count")
    df["symbol_history_days"] = hist
    df["min_history_ok"] = (hist >= 60).astype(int)
    df["usable_for_discovery"] = ((df["time_split"] == "discovery") &
                                  (df["symbol_split"] == "discovery") &
                                  (df["min_history_ok"] == 1)).astype(int)

    df = df.drop(columns=[c for c in ("code", "name", "timestamp") if c in df.columns])
    df = df.sort_values(["date", "symbol"]).reset_index(drop=True)
    path = os.path.join(OUT, "symbol_days.csv")
    df.to_csv(path, index=False)

    print(f"\nwrote {path}")
    print(f"rows {len(df):,}   symbols {df['symbol'].nunique()}   "
          f"dates {df['date'].min()} .. {df['date'].max()}")
    print(f"\nsymbol holdout (seed {SEED}): {' '.join(sorted(SYMBOL_HOLDOUT))}")
    print("\nsplit counts:")
    print(df.groupby(["time_split", "symbol_split"]).size().to_string())
    print(f"\nusable for discovery: {int(df['usable_for_discovery'].sum()):,} rows")
    print("\nmissing rate by feature (%):")
    feats = [c for c in df.columns if c not in
             ("date", "symbol", "is_etf", "time_split", "symbol_split",
              "usable_for_discovery", "oi_valid")]
    miss = (df[feats].isna().mean() * 100).round(1).sort_values(ascending=False)
    print(miss[miss > 0].to_string() or "  none")
    print(f"\noi_valid = 0 on {int((df['oi_valid']==0).sum())} rows "
          f"({(df['oi_valid']==0).mean()*100:.1f}%)")
    assert not any("fwd" in c or "outcome" in c for c in df.columns), "outcome leaked in"
    print("\nno outcome columns present - confirmed")

if __name__ == "__main__":
    main()
