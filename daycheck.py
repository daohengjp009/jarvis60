"""Jarvis_60 day check — one-screen summary of a collection day.
Usage: python3 daycheck.py [YYYY-MM-DD]"""
import sys, os, re, glob, json, datetime
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
TICKS, SNAPS = os.path.join(BASE, "data", "ticks"), os.path.join(BASE, "data", "snapshots")
STREAM = os.path.join(BASE, "data", "ticks_stream")
CACHE = os.path.join(BASE, "data", "capture_cache.json")
SYMS = ("TSLA", "NVDA", "GOOGL")
MIN_NOTIONAL, CUTOFF_HOUR = 250_000, 15

def main(day):
    files = glob.glob(os.path.join(TICKS, f"*_{day}.csv"))
    if not files:
        print(f"{day}: NO TICK DATA"); return
    per, first, last, raw, counted = {}, [], [], 0, 0
    for f in files:
        m = re.match(r"US_([A-Z]+)", os.path.basename(f))
        if not m or m.group(1) not in SYMS: continue
        d = pd.read_csv(f)
        t = pd.to_datetime(d["time"], format="mixed")
        first.append(t.min()); last.append(t.max())
        p = per.setdefault(m.group(1), {"c": 0, "p": 0, "e": 0})
        p["c"] += 1; p["p"] += len(d)
        dd = d[d["ticker_direction"].isin(["BUY", "SELL"])]
        if len(dd) >= 2:
            g = dd.groupby(["time", "ticker_direction"]).agg(
                n=("turnover", "sum"), k=("volume", "size")).reset_index()
            q = g[(g["k"] >= 2) & (g["n"] >= MIN_NOTIONAL)]
            raw += len(q)
            ok = q[pd.to_datetime(q["time"], format="mixed").dt.hour < CUTOFF_HOUR]
            counted += len(ok); p["e"] += len(ok)

    cap = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    c = cap.get(day)
    snaps = len(glob.glob(os.path.join(SNAPS, f"US_*_{day}.csv")))
    stream = glob.glob(os.path.join(STREAM, f"*_{day}.csv"))

    print(f"=== {day} ===")
    print(f"span     {min(first):%H:%M:%S} - {max(last):%H:%M:%S}")
    print(f"capture  {str(c['overall'])+'%' if c else 'not checked yet'}"
          + (f"  ({len(c['below_threshold'])} contracts <95%)" if c and c.get("below_threshold") else ""))
    print(f"events   {counted} counted / {raw} raw")
    print(f"snaps    {snaps} symbols")
    if stream:
        sp = sum(len(pd.read_csv(f)) for f in stream)
        print(f"stream   {len(stream)} contracts, {sp:,} prints")
    print()
    for s in SYMS:
        v = per.get(s, {"c": 0, "p": 0, "e": 0})
        print(f"  {s:6s} {v['c']:>3d} contracts  {v['p']:>8,} prints  {v['e']:>3d} events")
    print(f"  {'TOTAL':6s} {sum(v['c'] for v in per.values()):>3d} contracts  "
          f"{sum(v['p'] for v in per.values()):>8,} prints  {counted:>3d} events")

if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", sys.argv[1]) \
        else str(datetime.date.today())
    main(d)
