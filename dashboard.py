"""Jarvis_60 dashboard — collection status only. No forward returns.
Run: python3 dashboard.py     then open http://192.168.0.208:8060 from any device."""
import os, re, glob, json, subprocess, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
TICKS = os.path.join(BASE, "data", "ticks")
SNAPS = os.path.join(BASE, "data", "snapshots")
SYMS = ("TSLA", "NVDA", "GOOGL")
MIN_NOTIONAL = 250_000
EXP_START = "2026-08-12"
TARGET_EVENTS, TARGET_DAYS = 150, 20
PORT = 8060

_cache = {}   # path -> (mtime, stats)

def scan_file(path):
    mt = os.path.getmtime(path)
    hit = _cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    m = re.match(r"US_([A-Z]+)\d{6}[CP]\d+_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(path))
    if not m:
        return None
    sym, day = m.group(1), m.group(2)
    try:
        d = pd.read_csv(path, usecols=["time", "volume", "turnover", "ticker_direction"])
    except Exception:
        return None
    ev = 0
    if len(d) >= 2:
        dd = d[d["ticker_direction"].isin(["BUY", "SELL"])]
        if len(dd):
            g = dd.groupby(["time", "ticker_direction"]).agg(
                p=("volume", "size"), n=("turnover", "sum")).reset_index()
            ev = int(((g["p"] >= 2) & (g["n"] >= MIN_NOTIONAL)).sum())
    st = {"sym": sym, "day": day, "prints": len(d), "vol": float(d["volume"].sum()), "events": ev}
    _cache[path] = (mt, st)
    return st

def gather():
    days = {}
    for f in glob.glob(os.path.join(TICKS, "*.csv")):
        s = scan_file(f)
        if not s or s["sym"] not in SYMS:
            continue
        d = days.setdefault(s["day"], {y: {"prints": 0, "events": 0, "contracts": 0} for y in SYMS})
        d[s["sym"]]["prints"] += s["prints"]
        d[s["sym"]]["events"] += s["events"]
        d[s["sym"]]["contracts"] += 1
    snaps = {}
    for f in glob.glob(os.path.join(SNAPS, "*.csv")):
        mm = re.match(r"US_([A-Z]+)_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))
        if mm:
            snaps.setdefault(mm.group(2), set()).add(mm.group(1))
    running = subprocess.run(["pgrep", "-f", "collect.py"], capture_output=True).returncode == 0
    return days, snaps, running

def bar(pct, colour):
    pct = min(100, pct)
    return (f'<div class="bar"><div class="fill" style="width:{pct:.1f}%;background:{colour}"></div></div>')

def render():
    days, snaps, running = gather()
    exp_days = sorted([d for d in days if d >= EXP_START])
    all_days = sorted(days, reverse=True)
    tot_ev = sum(sum(days[d][s]["events"] for s in SYMS) for d in exp_days)
    n_days = len(exp_days)
    sym_tot = {s: sum(days[d][s]["events"] for d in exp_days) for s in SYMS}

    rows = ""
    for d in all_days:
        tag = "exp" if d >= EXP_START else "pre"
        ev = sum(days[d][s]["events"] for s in SYMS)
        pr = sum(days[d][s]["prints"] for s in SYMS)
        ct = sum(days[d][s]["contracts"] for s in SYMS)
        sn = len(snaps.get(d, set()))
        rows += (f'<tr class="{tag}"><td>{d}</td><td>{ct}</td><td>{pr:,}</td>'
                 + "".join(f"<td>{days[d][s]['events']}</td>" for s in SYMS)
                 + f'<td><b>{ev}</b></td><td>{sn or "-"}</td></tr>')

    per_day = tot_ev / n_days if n_days else 0
    eta_days = max(0, TARGET_DAYS - n_days)
    status = ("RUNNING" if running else "stopped")
    scol = "#3fb950" if running else "#8b949e"

    return f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<meta http-equiv=refresh content=120>
<title>Jarvis_60</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:20px;background:#0d1117;color:#c9d1d9;
 font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#8b949e;font-size:13px;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin-bottom:22px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px}}
.lab{{color:#8b949e;font-size:12px;text-transform:uppercase;letter-spacing:.5px}}
.big{{font-size:30px;font-weight:600;margin:6px 0}}
.bar{{height:7px;background:#21262d;border-radius:4px;overflow:hidden;margin-top:10px}}
.fill{{height:100%;border-radius:4px}}
table{{width:100%;border-collapse:collapse;background:#161b22;
 border:1px solid #30363d;border-radius:10px;overflow:hidden}}
th{{background:#1c2128;padding:9px;text-align:right;font-size:12px;color:#8b949e}}
th:first-child,td:first-child{{text-align:left}}
td{{padding:9px;text-align:right;border-top:1px solid #21262d;font-variant-numeric:tabular-nums}}
tr.pre td{{color:#6e7681}}
.note{{margin-top:18px;color:#6e7681;font-size:12px}}
</style>
<h1>Jarvis_60 — collection status</h1>
<div class=sub>updated {datetime.datetime.now():%H:%M:%S} &middot; auto-refresh 2 min</div>

<div class=grid>
 <div class=card><div class=lab>collector</div>
  <div class=big style="color:{scol}">{status}</div></div>
 <div class=card><div class=lab>qualifying events</div>
  <div class=big>{tot_ev}<span style="font-size:15px;color:#8b949e"> / {TARGET_EVENTS}</span></div>
  {bar(tot_ev/TARGET_EVENTS*100, "#58a6ff")}</div>
 <div class=card><div class=lab>trading days</div>
  <div class=big>{n_days}<span style="font-size:15px;color:#8b949e"> / {TARGET_DAYS}</span></div>
  {bar(n_days/TARGET_DAYS*100, "#d29922")}</div>
 <div class=card><div class=lab>events / day</div>
  <div class=big>{per_day:.1f}</div>
  <div class=lab>{eta_days} more days needed</div></div>
</div>

<div class=grid>
 {"".join(f'<div class=card><div class=lab>{s}</div><div class=big>{sym_tot[s]}</div>'
          f'<div class=lab>{(sym_tot[s]/tot_ev*100 if tot_ev else 0):.0f}% of events</div></div>' for s in SYMS)}
</div>

<table><tr><th>date</th><th>contracts</th><th>prints</th>
{"".join(f"<th>{s}</th>" for s in SYMS)}<th>events</th><th>snapshots</th></tr>{rows}</table>

<div class=note>Grey rows are pre-experiment days and are not counted.
Forward returns are deliberately not shown &mdash; the primary test stays sealed until the stopping rule is met.</div>
"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

if __name__ == "__main__":
    print(f"dashboard: http://192.168.0.208:{PORT}  (Ctrl-C to stop)")
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
