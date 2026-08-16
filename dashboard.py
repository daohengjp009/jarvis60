"""Jarvis_60 dashboard — collection status, data quality, sealed-test countdown.
Deliberately shows NO forward returns.
Run: ./j dash    then http://192.168.0.208:8060"""
import os, re, glob, json, subprocess, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
TICKS, SNAPS = os.path.join(BASE, "data", "ticks"), os.path.join(BASE, "data", "snapshots")
CACHE = os.path.join(BASE, "data", "capture_cache.json")
SYMS = ("TSLA", "NVDA", "GOOGL")
ALL13 = "TSLA NVDA AAPL MSFT GOOGL SPY QQQ SPCX INTC MU SKHY COHR BE".split()
MIN_NOTIONAL, THRESHOLD = 250_000, 95.0
EXP_START, TARGET_EVENTS, TARGET_DAYS = "2026-08-12", 150, 20
HARD_STOP, PORT = "2026-09-23", 8060

_cache = {}

def scan(path):
    mt = os.path.getmtime(path)
    hit = _cache.get(path)
    if hit and hit[0] == mt: return hit[1]
    m = re.match(r"US_([A-Z]+)\d{6}[CP]\d+_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(path))
    if not m: return None
    try: d = pd.read_csv(path, usecols=["time","volume","turnover","ticker_direction"])
    except Exception: return None
    ev, hrs = 0, {}
    if len(d) >= 2:
        dd = d[d["ticker_direction"].isin(["BUY","SELL"])]
        if len(dd):
            g = dd.groupby(["time","ticker_direction"]).agg(p=("volume","size"), n=("turnover","sum")).reset_index()
            q = g[(g["p"] >= 2) & (g["n"] >= MIN_NOTIONAL)]
            ev = len(q)
            for t in q["time"]:
                hrs[t[11:13]] = hrs.get(t[11:13], 0) + 1
    st = {"sym": m.group(1), "day": m.group(2), "prints": len(d), "events": ev, "hours": hrs}
    _cache[path] = (mt, st)
    return st

def gather():
    days = {}
    for f in glob.glob(os.path.join(TICKS, "*.csv")):
        s = scan(f)
        if not s or s["sym"] not in SYMS: continue
        d = days.setdefault(s["day"], {y: {"prints":0,"events":0,"contracts":0} for y in SYMS})
        d[s["sym"]]["prints"] += s["prints"]; d[s["sym"]]["events"] += s["events"]
        d[s["sym"]]["contracts"] += 1
    snaps, depth = {}, {}
    for f in glob.glob(os.path.join(SNAPS, "*.csv")):
        mm = re.match(r"US_([A-Z]+)_(\d{4}-\d{2}-\d{2})(_repick)?\.csv$", os.path.basename(f))
        if mm and not mm.group(3):
            snaps.setdefault(mm.group(2), set()).add(mm.group(1))
            depth[mm.group(1)] = depth.get(mm.group(1), 0) + 1
    cap = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    running = subprocess.run(["pgrep","-f","collect.py"], capture_output=True).returncode == 0
    return days, snaps, depth, cap, running

def alerts(days, snaps, cap):
    out, today = [], str(datetime.date.today())
    exp = sorted(d for d in days if d >= EXP_START)
    for d in exp:
        c = cap.get(d)
        if not c:
            if d < today: out.append(("warn", f"{d}: capture not yet checked — run ./j cap"))
        elif c["overall"] < THRESHOLD:
            out.append(("bad", f"{d}: capture {c['overall']}% — below the 95% rule, day excluded"))
        elif c.get("below_threshold"):
            out.append(("warn", f"{d}: {len(c['below_threshold'])} contract(s) below 95% — excluded individually"))
        n = len(snaps.get(d, set()))
        if n < len(ALL13):
            out.append(("bad" if n == 0 else "warn", f"{d}: only {n}/13 chain snapshots saved"))
    if exp:
        s, e = datetime.date.fromisoformat(exp[0]), datetime.date.fromisoformat(exp[-1])
        have, k = set(exp), s
        while k <= e:
            if k.weekday() < 5 and str(k) not in have:
                out.append(("warn", f"{k}: weekday with no collection"))
            k += datetime.timedelta(days=1)
    return out

def render():
    days, snaps, depth, cap, running = gather()
    exp = sorted(d for d in days if d >= EXP_START)
    ok = [d for d in exp if cap.get(d, {}).get("overall", 100) >= THRESHOLD]
    tot_ev = sum(sum(days[d][s]["events"] for s in SYMS) for d in ok)
    n_days, per_day = len(ok), (sum(sum(days[d][s]["events"] for s in SYMS) for d in ok)/len(ok) if ok else 0)
    sym_tot = {s: sum(days[d][s]["events"] for d in ok) for s in SYMS}
    need_days = max(0, TARGET_DAYS - n_days)
    need_ev = max(0, TARGET_EVENTS - tot_ev)
    eta = max(need_days, (need_ev/per_day if per_day else 0))
    finish = datetime.date.today()
    left = eta
    while left > 0:
        finish += datetime.timedelta(days=1)
        if finish.weekday() < 5: left -= 1
    hard = datetime.date.fromisoformat(HARD_STOP)
    finish = min(finish, hard)

    al = alerts(days, snaps, cap)
    albox = "".join(f'<div class="al {k}">{t}</div>' for k, t in al) if al else \
            '<div class="al ok">no data-quality issues</div>'

    rows = ""
    for d in sorted(days, reverse=True):
        pre = d < EXP_START
        c = cap.get(d)
        if c is None: badge = '<span class="b grey">unchecked</span>'
        elif c["overall"] >= THRESHOLD: badge = f'<span class="b green">{c["overall"]}%</span>'
        else: badge = f'<span class="b red">{c["overall"]}%</span>'
        ev = sum(days[d][s]["events"] for s in SYMS)
        pr = sum(days[d][s]["prints"] for s in SYMS)
        ct = sum(days[d][s]["contracts"] for s in SYMS)
        sn = len(snaps.get(d, set()))
        sb = f'<span class="b {"green" if sn==13 else "red" if sn==0 else "amber"}">{sn}/13</span>'
        rows += (f'<tr class="{"pre" if pre else ""}"><td>{d}</td><td>{badge}</td><td>{ct}</td>'
                 f'<td>{pr:,}</td>' + "".join(f"<td>{days[d][s]['events']}</td>" for s in SYMS)
                 + f'<td><b>{ev}</b></td><td>{sb}</td></tr>')

    dep = "".join(f'<span class="chip">{s} <b>{depth.get(s,0)}</b></span>' for s in ALL13)

    return f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<meta http-equiv=refresh content=120><title>Jarvis_60</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;padding:20px;background:#0d1117;color:#c9d1d9;
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
h1{{font-size:20px;margin:0 0 4px}}.sub{{color:#8b949e;font-size:13px;margin-bottom:18px}}
.seal{{background:#1c2128;border:1px solid #30363d;border-left:3px solid #d29922;
border-radius:8px;padding:12px 16px;margin-bottom:18px;font-size:14px}}
.seal b{{color:#e3b341}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:18px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px}}
.lab{{color:#8b949e;font-size:12px;text-transform:uppercase;letter-spacing:.5px}}
.big{{font-size:30px;font-weight:600;margin:6px 0}}
.bar{{height:7px;background:#21262d;border-radius:4px;overflow:hidden;margin-top:10px}}
.fill{{height:100%;border-radius:4px}}
.al{{padding:9px 14px;border-radius:7px;margin-bottom:7px;font-size:13.5px;border:1px solid}}
.al.bad{{background:#2d1214;border-color:#f8514933;color:#ff7b72}}
.al.warn{{background:#2b2314;border-color:#d2992233;color:#e3b341}}
.al.ok{{background:#12261a;border-color:#3fb95033;color:#56d364}}
table{{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;
border-radius:10px;overflow:hidden;margin-top:16px}}
th{{background:#1c2128;padding:9px;text-align:right;font-size:12px;color:#8b949e}}
th:first-child,td:first-child{{text-align:left}}
td{{padding:9px;text-align:right;border-top:1px solid #21262d;font-variant-numeric:tabular-nums}}
tr.pre td{{color:#6e7681}}
.b{{padding:2px 7px;border-radius:11px;font-size:12px;font-weight:600}}
.b.green{{background:#12261a;color:#56d364}}.b.red{{background:#2d1214;color:#ff7b72}}
.b.amber{{background:#2b2314;color:#e3b341}}.b.grey{{background:#21262d;color:#8b949e}}
.chip{{display:inline-block;background:#21262d;border-radius:6px;padding:4px 9px;
margin:3px 4px 0 0;font-size:12.5px;color:#8b949e}}.chip b{{color:#c9d1d9}}
.note{{margin-top:16px;color:#6e7681;font-size:12px}}
</style>
<h1>Jarvis_60 — collection status</h1>
<div class=sub>updated {datetime.datetime.now():%H:%M:%S} &middot; auto-refresh 2 min</div>

<div class=seal>PRIMARY TEST SEALED &mdash; needs <b>{need_days} more trading days</b>
and <b>{need_ev} more events</b>. Projected unseal: <b>{finish}</b> (hard stop {HARD_STOP}).
Forward returns are not shown until then.</div>

{albox}

<div class=grid>
 <div class=card><div class=lab>collector</div>
  <div class=big style="color:{'#3fb950' if running else '#8b949e'}">{'RUNNING' if running else 'stopped'}</div></div>
 <div class=card><div class=lab>qualifying events</div>
  <div class=big>{tot_ev}<span style="font-size:15px;color:#8b949e"> / {TARGET_EVENTS}</span></div>
  <div class=bar><div class=fill style="width:{min(100,tot_ev/TARGET_EVENTS*100):.1f}%;background:#58a6ff"></div></div></div>
 <div class=card><div class=lab>valid trading days</div>
  <div class=big>{n_days}<span style="font-size:15px;color:#8b949e"> / {TARGET_DAYS}</span></div>
  <div class=bar><div class=fill style="width:{min(100,n_days/TARGET_DAYS*100):.1f}%;background:#d29922"></div></div></div>
 <div class=card><div class=lab>events / day</div><div class=big>{per_day:.1f}</div>
  <div class=lab>days counted only if capture &ge; 95%</div></div>
</div>

<div class=grid>
 {"".join(f'<div class=card><div class=lab>{s}</div><div class=big>{sym_tot[s]}</div>'
          f'<div class=lab>{(sym_tot[s]/tot_ev*100 if tot_ev else 0):.0f}% of events</div></div>' for s in SYMS)}
</div>

<div class=card><div class=lab>chain snapshot depth (days banked, all 13 symbols)</div>
<div style="margin-top:8px">{dep}</div></div>

<table><tr><th>date</th><th>capture</th><th>contracts</th><th>prints</th>
{"".join(f"<th>{s}</th>" for s in SYMS)}<th>events</th><th>snapshots</th></tr>{rows}</table>

<div class=note>Grey rows are pre-experiment days. Days below 95% capture are excluded from
the counts above. Forward returns stay sealed until the stopping rule is met.</div>
"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        b = render().encode()
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass

if __name__ == "__main__":
    print(f"dashboard: http://192.168.0.208:{PORT}")
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
