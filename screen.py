"""Jarvis_60 daily screener — fetch + screen in one command.
Usage: python3 screen.py TSLA [AAPL NVDA ...]"""
import sys, os, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from core.futu_fetch import fetch_chain

COLS = ["option_type","option_strike_price","option_open_interest","option_implied_volatility",
        "option_premium","option_delta","option_expiry_date_distance","bid_price","ask_price","volume","code"]

def screen(ticker: str):
    code = ticker if "." in ticker else f"US.{ticker.upper()}"
    print(f"\n########## {code} ##########")
    path = fetch_chain(code)
    if not path:
        print("fetch failed — skipped."); return
    df = pd.read_csv(path)
    missing = [c for c in COLS if c not in df.columns]
    if missing:
        print("missing columns:", missing); return
    rows = df[COLS].fillna(0).to_dict("records")
    ns = {}
    exec(open(os.path.join(os.path.dirname(__file__), "tools", "options_screener.py")).read(), ns)
    res = ns["screen_options"](rows)
    for side in ("calls", "puts"):
        print(f"\n----- TOP {side.upper()} -----")
        if not res[side]:
            print("(none survived the filters)"); continue
        for r in res[side]:
            print(f"{r['code']:26s} K={r['option_strike_price']:<8.1f} dte={r['option_expiry_date_distance']:<3.0f} "
                  f"delta={r['option_delta']:<7.3f} OI={r['option_open_interest']:<7.0f} vol={r['volume']:<7.0f} "
                  f"spread={r['spread_pct']:.1f}% score={r['liquidity_score']:.0f}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 screen.py TSLA [AAPL ...]")
    else:
        for t in sys.argv[1:]:
            screen(t)
