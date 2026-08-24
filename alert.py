"""Jarvis_60 live alerts — flags unusual option activity during the session.

Two independent detectors:
  A. OWN  - same-timestamp clusters in the tick stream (HYP-001's definition),
            sized RELATIVE to each contract's own recent typical cluster
  B. FUTU - get_option_event, Futu's own unusual-activity list

Every alert is logged to data/alerts/ with a timestamp, so its predictive value
can be tested LATER against real outcomes. An alert is NOT a prediction.
Writes only to data/alerts/. Does not touch HYP-001 or HYP-002 data.
Usage: python3 alert.py [poll_seconds]"""
import os, sys, time, datetime, json
import pandas as pd, numpy as np
from futu import OpenQuoteContext, SysConfig

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "alerts")
TICKS = os.path.join(BASE, "data", "ticks")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
os.makedirs(OUT, exist_ok=True)

POLL = int(sys.argv[1]) if len(sys.argv) > 1 else 120
SYMS = ("TSLA", "NVDA", "GOOGL")
ABS_FLOOR = 250_000        # absolute minimum notional, as in HYP-001
REL_MULT = 10              # ... AND at least 10x this contract's own median cluster
MIN_HIST = 30              # clusters needed before a relative baseline is trusted

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT = os.environ.get("TELEGRAM_CHAT_ID")
def notify(msg):
    if not (TOKEN and CHAT): return
    try:
        import urllib.request, urllib.parse
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TOKEN,
            urllib.parse.urlencode({"chat_id": CHAT, "text": msg}).encode(), timeout=10)
    except Exception as e:
        print(f"  notify failed: {e}", flush=True)

def load_env():
    p = os.path.join(BASE, ".env")
    if os.path.exists(p):
        for line in open(p):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))
load_env()
TOKEN = os.environ.get("TELEGRAM_TOKEN"); CHAT = os.environ.get("TELEGRAM_CHAT_ID")

seen = set()
def log(rec):
    day = str(datetime.date.today())
    with open(os.path.join(OUT, f"alerts_{day}.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")

def own_clusters(day):
    """Same-timestamp clusters in today's ticks, judged against each contract's
    own recent history so a big name doesn't drown out a quiet one."""
    hits = []
    import glob, re
    for f in glob.glob(os.path.join(TICKS, f"*_{day}.csv")):
        base = os.path.basename(f)[:-15]
        m = re.match(r"US_([A-Z]+)", base)
        if not m or m.group(1) not in SYMS: continue
        try:
            d = pd.read_csv(f, usecols=["time","volume","turnover","ticker_direction"])
        except Exception:
            continue
        d = d[d["ticker_direction"].isin(["BUY","SELL"])]
        if len(d) < 2: continue
        g = d.groupby(["time","ticker_direction"]).agg(
            prints=("volume","size"), lots=("volume","sum"), n=("turnover","sum")).reset_index()
        g = g[g["prints"] >= 2]
        if len(g) < MIN_HIST: continue
        med = g["n"].median()
        for _, r in g.iterrows():
            if r["n"] < ABS_FLOOR: continue
            if med > 0 and r["n"] < REL_MULT * med: continue
            key = f"{base}|{r['time']}|{r['ticker_direction']}"
            if key in seen: continue
            seen.add(key)
            hits.append({"kind":"own","contract":base,"time":r["time"],
                         "dir":r["ticker_direction"],"prints":int(r["prints"]),
                         "lots":float(r["lots"]),"notional":float(r["n"]),
                         "x_typical":round(float(r["n"]/med),1) if med>0 else None})
    return hits

def futu_events(ctx):
    from futu import OptionMarket
    try:
        r, d = ctx.get_option_event(option_market=OptionMarket.US_SECURITY, count=30)
    except Exception as e:
        print(f"  option_event error: {e}", flush=True); return []
    if r != 0: return []
    df = d.get("event_list") if isinstance(d, dict) else d
    if df is None or not len(df): return []
    hits = []
    for _, row in df.iterrows():
        code = str(row.get("option_code",""))
        # only our watchlist - the full US market produces hundreds a day
        sym = str(row.get("symbol", ""))
        if sym not in SYMS: continue
        stamp = str(row.get("update_time", row.get("time","")))
        key = f"futu|{code}|{stamp}"
        if key in seen: continue
        seen.add(key)
        rec = {"kind":"futu","contract":code,"time":stamp}
        for c in df.columns:
            if c in ("option_code","update_time"): continue
            v = row[c]
            if isinstance(v, (str,int,float,np.integer,np.floating)):
                rec[c] = v if not isinstance(v,(np.integer,np.floating)) else float(v)
        hits.append(rec)
    return hits

def spreads(day):
    """Same second, opposite direction, identical lot size, two different strikes
    on the same underlying = one multi-leg order, not two independent trades.
    HYP-001's same-direction rule cannot see these."""
    import glob, re
    rows = []
    for f in glob.glob(os.path.join(TICKS, f"*_{day}.csv")):
        base = os.path.basename(f)[:-15]
        m = re.match(r"US_([A-Z]+)(\d{6})([CP])(\d+)", base)
        if not m or m.group(1) not in SYMS: continue
        try:
            d = pd.read_csv(f, usecols=["time","volume","turnover","ticker_direction"])
        except Exception:
            continue
        d = d[d["ticker_direction"].isin(["BUY","SELL"])]
        if not len(d): continue
        g = d.groupby(["time","ticker_direction"]).agg(
            lots=("volume","sum"), n=("turnover","sum")).reset_index()
        g["sym"], g["strike"] = m.group(1), int(m.group(4))/1000
        g["typ"], g["contract"] = m.group(3), base
        rows.append(g)
    if not rows: return []
    a = pd.concat(rows, ignore_index=True)
    hits = []
    for (t, sym, lots), grp in a.groupby(["time","sym","lots"]):
        if len(grp) < 2: continue
        if grp["ticker_direction"].nunique() < 2: continue     # need both sides
        if grp["contract"].nunique() < 2: continue             # need two legs
        key = f"spread|{sym}|{t}|{lots}"
        if key in seen: continue
        seen.add(key)
        legs = [f"{r.ticker_direction[:1]} {r.typ}{r.strike:g}" for r in grp.itertuples()]
        hits.append({"kind":"spread","symbol":sym,"time":t,"lots":float(lots),
                     "legs":" / ".join(legs), "notional":float(grp["n"].sum()),
                     "n_legs":len(grp)})
    return hits

def main():
    SysConfig.enable_proto_encrypt(True); SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    print(f"alerts running: own clusters >= ${ABS_FLOOR:,} AND >= {REL_MULT}x that "
          f"contract's median, plus Futu option events. poll {POLL}s", flush=True)
    notify(f"Jarvis alerts started ({datetime.datetime.now():%H:%M})")
    try:
        while True:
            day = str(datetime.date.today())
            hits = own_clusters(day) + spreads(day) + futu_events(ctx)
            for h in hits:
                log(h)
                if h["kind"] == "spread":
                    msg = (f"SPREAD  {h['symbol']}\n{h['legs']}\n"
                           f"{h['lots']:,.0f} lots  ${h['notional']:,.0f}\n{h['time']}")
                elif h["kind"] == "own":
                    msg = (f"CLUSTER  {h['contract']}\n{h['dir']} ${h['notional']:,.0f}"
                           f"  {h['prints']} prints  {h['x_typical']}x typical\n{h['time']}")
                else:
                    extra = " ".join(f"{k}={v}" for k,v in h.items()
                                     if k not in ("kind","contract","time"))[:180]
                    msg = f"FUTU EVENT  {h['contract']}\n{extra}"
                print("\n" + msg, flush=True)
                notify(msg)
            if hits: print(f"  [{datetime.datetime.now():%H:%M:%S}] {len(hits)} new", flush=True)
            time.sleep(POLL)
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    finally:
        ctx.close()

if __name__ == "__main__":
    main()
