"""HYP-002 feature table — one row per symbol-day.
Implements features.md exactly. Computes NO forward returns and NO outcomes.
Usage: python3 features.py
Output: data/features/symbol_days.csv"""
import os, glob, random
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data", "symbol_history", "frozen")
FLOW = os.path.join(BASE, "data", "capital_flow")
OUT = os.path.join(BASE, "data", "features")
os.makedirs(OUT, exist_ok=True)

SYMBOLS = "TSLA NVDA AAPL MSFT GOOGL SPY QQQ SPCX INTC MU SKHY COHR BE AMZN META AMD NFLX AVGO COIN PLTR MSTR ARM IWM SMCI CRWD ORCL LLY XOM".split()
BENCHMARKS = {"SPY", "QQQ", "IWM"}          # context only, not research subjects
RESEARCH = [s for s in SYMBOLS if s not in BENCHMARKS]
SHORT_HISTORY = {"SKHY", "SPCX"}            # frozen 2026-08-22 (<60 trading days)
SEED = 20260822
# REGISTERED membership - frozen in features.md section 3. Treated as data, not
# regenerated. The seed is kept only to prove the draw is reproducible; if the
# universe ever changes, the assertion fails loudly instead of silently
# reassigning the holdout.
SYMBOL_HOLDOUT = {"ARM", "AVGO", "NFLX", "ORCL", "PLTR", "SMCI"}
SYMBOL_DISCOVERY = {"AAPL", "AMD", "AMZN", "BE", "COHR", "COIN", "CRWD", "GOOGL",
                    "INTC", "LLY", "META", "MSFT", "MSTR", "MU", "NVDA", "TSLA", "XOM"}
assert SYMBOL_HOLDOUT == set(random.Random(SEED).sample(
    sorted(s for s in RESEARCH if s not in SHORT_HISTORY), 6)), \
    "registered symbol holdout no longer reproduces from the frozen seed"
assert SYMBOL_HOLDOUT | SYMBOL_DISCOVERY | SHORT_HISTORY == set(RESEARCH), \
    "registered splits do not partition the research universe"

DATE_START, DATE_END = "2025-08-22", "2026-08-21"   # registered sample period
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
    """Consecutive days with s > 0. NaN input -> NaN output: a missing value is
    'unknown', not 'zero consecutive days'. The run resets after a gap."""
    out, run = [], 0
    for v in s:
        if pd.isna(v):
            out.append(np.nan); run = 0
        else:
            run = run + 1 if v > 0 else 0
            out.append(run)
    return pd.Series(out, index=s.index, dtype="float64")

def load(sym):
    fs = os.path.join(SRC, f"US_{sym}_stat.csv")
    fv = os.path.join(SRC, f"US_{sym}_vol.csv")
    if not (os.path.exists(fs) and os.path.exists(fv)):
        return None
    st = pd.read_csv(fs)
    vo = pd.read_csv(fv)[["time", "iv", "hv"]]
    for nm, x in (("stat", st), ("vol", vo)):
        dup = x["time"].duplicated().sum()
        assert dup == 0, f"{sym} {nm}: {dup} duplicate dates in source"
    d = st.merge(vo, on="time", how="inner").sort_values("time").reset_index(drop=True)
    d = d[d["time"].between(DATE_START, DATE_END)].reset_index(drop=True)   # registered period
    d = d.rename(columns={
        "time": "date",
        "option_open_interest": "option_oi",
        "call_open_interest": "call_oi",
        "put_open_interest": "put_oi",
        "put_call_volume_ratio": "pc_volume_ratio",
        "put_call_open_interest_ratio": "pc_oi_ratio"})
    d["symbol"] = sym

    # --- stock-side capital flow by trade size (added 2026-08-23) ---
    fp = os.path.join(FLOW, f"US_{sym}_flow.csv")
    if os.path.exists(fp):
        fl = pd.read_csv(fp).rename(columns={"time": "date"})
        keep = ["date","in_flow","super_in_flow","big_in_flow","mid_in_flow","sml_in_flow"]
        fl = fl[[c for c in keep if c in fl.columns]]
        for c in fl.columns:
            if c != "date": fl[c] = pd.to_numeric(fl[c], errors="coerce")
        # CONSERVATIVE ONE-DAY SHIFT. Publication timing is UNVERIFIED: unlike OI,
        # the newest row carries real values, which suggests same-day availability -
        # but that was checked on a non-trading day and could not be distinguished
        # from overnight publication. Shifted until a live-session test settles it.
        # If same-day is confirmed, removing the shift is a pre-pairing amendment.
        fl[[c for c in fl.columns if c != "date"]] = \
            fl[[c for c in fl.columns if c != "date"]].shift(1)
        d = d.merge(fl, on="date", how="left")
    else:
        for c in ("in_flow","super_in_flow","big_in_flow","mid_in_flow","sml_in_flow"):
            d[c] = np.nan
    for c in ("pc_volume_ratio", "pc_oi_ratio", "iv", "hv", "underlying_price",
              "option_volume", "call_volume", "put_volume",
              "option_oi", "call_oi", "put_oi"):
        d[c] = pd.to_numeric(d[c], errors="coerce")     # "N/A" -> NaN
    return d

def build(d, calendar):
    """calendar: the full sorted list of trading dates in the table. The symbol's
    series is reindexed onto the calendar dates within its own first..last range,
    so .shift(1) / .diff() / rolling windows step by TRADING DAY, not by
    'previous available row'. Rows with no source data are dropped at the end."""
    sym = d["symbol"].iloc[0]
    span = [c for c in calendar if d["date"].min() <= c <= d["date"].max()]
    d["has_source"] = True
    d = d.set_index("date").reindex(span).rename_axis("date").reset_index()
    d["symbol"] = sym
    d["has_source"] = d["has_source"].fillna(False)
    return _build_features(d)

def _build_features(d):
    # --- OI is published ONE DAY LATE ---
    # Futu documents call/put_open_interest as T-1 delayed, and the newest row
    # carries 0 / "N/A". So the raw value on row t is day t's OI, which nobody
    # could see until t+1. Shift by one so row t holds the OI KNOWN at t's close.
    for _c in ("option_oi", "call_oi", "put_oi", "pc_oi_ratio"):
        d[_c] = d[_c].shift(1)

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
    d["vol_oi_ratio"] = d["option_volume"] / d["option_oi"].replace(0, np.nan)

    # --- price (backward-looking only) ---
    prev_px = d["underlying_price"].shift(1).replace(0, np.nan)
    d["ret_1d"] = np.log(d["underlying_price"] / prev_px)
    d["realized_vol_20"] = d["ret_1d"].shift(1).rolling(W, min_periods=MINP).std()   # DAILY, not annualised
    d["price_z20"] = zscore(d["underlying_price"])

    # --- capital flow (stock side, by trade size) ---
    big   = d["super_in_flow"] + d["big_in_flow"]      # institutional-size prints
    small = d["mid_in_flow"] + d["sml_in_flow"]        # retail-size prints
    d["flow_net_z20"]   = zscore(d["in_flow"])
    d["flow_big_z20"]   = zscore(big)
    d["flow_small_z20"] = zscore(small)
    d["flow_big_sum_5d"] = big.rolling(5, min_periods=5).sum()
    d["consec_flow_big_up"] = consec_positive(big)

    # --- persistence ---
    # NaN must stay NaN: (NaN > 2) is False in pandas, which would silently
    # report "not extreme" during each symbol's warmup instead of "unknown".
    d["days_iv_z_gt2_last5"] = (d["iv_z20"] > 2).where(d["iv_z20"].notna()) \
                                 .rolling(5, min_periods=5).sum()
    d["days_vol_z_gt2_last5"] = (d["vol_z20"] > 2).where(d["vol_z20"].notna()) \
                                 .rolling(5, min_periods=5).sum()
    d["oi_change_sum_3d"] = d["oi_change"].rolling(3, min_periods=3).sum()
    d["oi_change_sum_5d"] = d["oi_change"].rolling(5, min_periods=5).sum()
    d["consec_oi_up"] = consec_positive(d["oi_change"])
    return d

def main():
    loaded = {}
    for s in SYMBOLS:
        d = load(s)
        if d is not None and len(d):
            loaded[s] = d
        else:
            print(f"  {s}: MISSING source files")
    required = set(RESEARCH) | BENCHMARKS              # benchmarks supply market context
    missing = required - set(loaded)
    assert not missing, f"registered symbols absent from build: {sorted(missing)}"

    calendar = sorted({t for d in loaded.values() for t in d["date"]})
    df = pd.concat([build(d, calendar) for d in loaded.values()], ignore_index=True)

    # --- market context ---
    mkt = df[df["symbol"].isin(BENCHMARKS)].pivot(index="date", columns="symbol", values="ret_1d")
    mkt = mkt.rename(columns={"SPY": "spy_ret_1d", "QQQ": "qqq_ret_1d",
                              "IWM": "iwm_ret_1d"}).reset_index()
    df = df.merge(mkt, on="date", how="left")

    # --- benchmarks are context only: drop BEFORE any cross-sectional statistic,
    #     but AFTER the market-context merge which needs their rows ---
    df = df[~df["symbol"].isin(BENCHMARKS)].copy()

    # --- cross-sectional ranks within each date (research universe only) ---
    df["iv_z20_xs_rank"] = df.groupby("date")["iv_z20"].rank(pct=True)
    df["vol_z20_xs_rank"] = df.groupby("date")["vol_z20"].rank(pct=True)

    # --- flags and splits ---
    df["time_split"] = np.where(df["date"] <= TIME_CUTOFF, "discovery", "holdout")
    df["symbol_split"] = np.select(
        [df["symbol"].isin(SYMBOL_HOLDOUT), df["symbol"].isin(SYMBOL_DISCOVERY)],
        ["holdout", "discovery"], default="excluded")   # SKHY/SPCX: neither, per spec
    hist = df.groupby("symbol")["date"].transform("count")
    df["symbol_history_days"] = hist
    df["min_history_ok"] = (hist >= 60).astype(int)
    df["usable_for_discovery"] = ((df["time_split"] == "discovery") &
                                  (df["symbol_split"] == "discovery") &
                                  (df["min_history_ok"] == 1)).astype(int)

    df = df[df["has_source"]].drop(columns=["has_source"])      # remove calendar padding
    df = df.drop(columns=[c for c in ("code", "name", "timestamp") if c in df.columns])
    df = df.sort_values(["date", "symbol"]).reset_index(drop=True)
    assert not df.duplicated(["symbol", "date"]).any(), "symbol+date is not unique"
    assert df["date"].between(DATE_START, DATE_END).all(), "rows outside the registered period"
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
             ("date", "symbol", "time_split", "symbol_split",
              "usable_for_discovery", "oi_valid")]
    miss = (df[feats].isna().mean() * 100).round(1).sort_values(ascending=False)
    print(miss[miss > 0].to_string() or "  none")
    print(f"\noi_valid = 0 on {int((df['oi_valid']==0).sum())} rows "
          f"({(df['oi_valid']==0).mean()*100:.1f}%)")
    assert not any("fwd" in c or "outcome" in c for c in df.columns), "outcome leaked in"
    print("\nno outcome columns present - confirmed")

if __name__ == "__main__":
    main()
