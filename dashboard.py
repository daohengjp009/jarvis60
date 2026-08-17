"""Jarvis_60 dashboard — collection status, quality, events, charts.
Deliberately shows NO forward returns.
Run: ./j dash    then http://192.168.0.208:8060"""
import os, re, glob, json, subprocess, datetime, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
TICKS, SNAPS = os.path.join(BASE, "data", "ticks"), os.path.join(BASE, "data", "snapshots")
CACHE = os.path.join(BASE, "data", "capture_cache.json")
SYMS = ("TSLA", "NVDA", "GOOGL")
ALL13 = "TSLA NVDA AAPL MSFT GOOGL SPY QQQ SPCX INTC MU SKHY COHR BE AMZN META AMD NFLX AVGO COIN PLTR MSTR ARM IWM SMCI CRWD ORCL LLY XOM".split()
MIN_NOTIONAL, THRESHOLD = 250_000, 95.0
EXP_START, TARGET_EVENTS, TARGET_DAYS = "2026-08-12", 150, 20
CUTOFF_HOUR = 15   # events at/after 15:00 ET excluded (horizon would pass the close)
HARD_STOP, PORT = "2026-09-23", 8060
COL = {"TSLA": "#58a6ff", "NVDA": "#3fb950", "GOOGL": "#d29922"}

_cache = {}

def scan(path):
    mt = os.path.getmtime(path)
    hit = _cache.get(path)
    if hit and hit[0] == mt: return hit[1]
    m = re.match(r"US_([A-Z]+)(\d{6})([CP])(\d+)_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(path))
    if not m: return None
    try:
        d = pd.read_csv(path, usecols=["time", "volume", "turnover", "ticker_direction"])
    except Exception:
        return None
    evs = []
    if len(d) >= 2:
        dd = d[d["ticker_direction"].isin(["BUY", "SELL"])]
        if len(dd):
            g = dd.groupby(["time", "ticker_direction"]).agg(
                p=("volume", "size"), v=("volume", "sum"), n=("turnover", "sum")).reset_index()
            q = g[(g["p"] >= 2) & (g["n"] >= MIN_NOTIONAL)]
            label = f'{m.group(1)} {m.group(3)}{int(m.group(4))/1000:g} {m.group(2)}'
            for _, r in q.iterrows():
                evs.append({"t": r["time"], "dir": r["ticker_direction"], "p": int(r["p"]),
                            "v": float(r["v"]), "n": float(r["n"]), "sym": m.group(1),
                            "label": label, "code": os.path.basename(path)[:-15].replace("US_", "US.")})
    st = {"sym": m.group(1), "day": m.group(5), "prints": len(d), "events": evs}
    _cache[path] = (mt, st)
    return st

def gather():
    days, evbyday = {}, {}
    for f in glob.glob(os.path.join(TICKS, "*.csv")):
        s = scan(f)
        if not s or s["sym"] not in SYMS: continue
        d = days.setdefault(s["day"], {y: {"prints": 0, "events": 0, "contracts": 0} for y in SYMS})
        d[s["sym"]]["prints"] += s["prints"]
        d[s["sym"]]["events"] += len(s["events"])
        d[s["sym"]]["contracts"] += 1
        evbyday.setdefault(s["day"], []).extend(s["events"])
    snaps, depth = {}, {}
    for f in glob.glob(os.path.join(SNAPS, "*.csv")):
        mm = re.match(r"US_([A-Z]+)_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))
        if mm:
            snaps.setdefault(mm.group(2), set()).add(mm.group(1))
            depth[mm.group(1)] = depth.get(mm.group(1), 0) + 1
    cap = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    running = subprocess.run(["pgrep", "-f", "collect.py"], capture_output=True).returncode == 0
    return days, evbyday, snaps, depth, cap, running

def qualifies(e, day, cap):
    if int(e["t"][11:13]) >= CUTOFF_HOUR: return False
    c = cap.get(day)
    if c is None or c["overall"] < THRESHOLD: return False
    return e["code"] not in set(c.get("below_threshold", []))

def alerts(days, snaps, cap):
    out, today = [], str(datetime.date.today())
    exp = sorted(d for d in days if d >= EXP_START)
    for d in exp:
        c = cap.get(d)
        if not c:
            if d < today: out.append(("warn", f"{d}: capture not yet checked — run /cap"))
        elif c["overall"] < THRESHOLD:
            out.append(("bad", f"{d}: capture {c['overall']}% — below 95%, day excluded"))
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

def svg_bars(pairs, colours=None, height=140, label_every=1, fmt=lambda v: f"{v:g}"):
    """pairs: [(label, value)] -> simple SVG column chart."""
    if not pairs: return "<div class=lab>no data</div>"
    w, pad = 44, 26
    mx = max(v for _, v in pairs) or 1
    width = max(260, len(pairs) * w + pad)
    bars = ""
    for i, (lab, v) in enumerate(pairs):
        h = (v / mx) * (height - 34)
        x = pad + i * w
        c = (colours or {}).get(lab, "#58a6ff")
        bars += (f'<rect x="{x}" y="{height-20-h:.1f}" width="{w-12}" height="{h:.1f}" rx="3" fill="{c}"/>'
                 f'<text x="{x+(w-12)/2}" y="{height-24-h:.1f}" class="v">{fmt(v)}</text>')
        if i % label_every == 0:
            bars += f'<text x="{x+(w-12)/2}" y="{height-6}" class="x">{lab}</text>'
    return (f'<svg viewBox="0 0 {width} {height}" style="width:100%;max-width:{width*1.6}px">'
            f'<style>.v{{fill:#8b949e;font:11px sans-serif;text-anchor:middle}}'
            f'.x{{fill:#6e7681;font:11px sans-serif;text-anchor:middle}}</style>{bars}</svg>')

def page(body):
    return f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Jarvis_60</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;padding:20px;background:#0d1117;color:#c9d1d9;
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
a{{color:#58a6ff;text-decoration:none}}a:hover{{text-decoration:underline}}
h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:15px;margin:22px 0 10px;color:#8b949e;
text-transform:uppercase;letter-spacing:.5px;font-weight:600}}
.sub{{color:#8b949e;font-size:13px;margin-bottom:18px}}
.seal{{background:#1c2128;border:1px solid #30363d;border-left:3px solid #d29922;
border-radius:8px;padding:12px 16px;margin-bottom:18px;font-size:14px}}.seal b{{color:#e3b341}}
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
border-radius:10px;overflow:hidden}}
th{{background:#1c2128;padding:9px;text-align:right;font-size:12px;color:#8b949e}}
th:first-child,td:first-child{{text-align:left}}
td{{padding:9px;text-align:right;border-top:1px solid #21262d;font-variant-numeric:tabular-nums}}
tr.pre td{{color:#6e7681}}
.b{{padding:2px 7px;border-radius:11px;font-size:12px;font-weight:600}}
.b.green{{background:#12261a;color:#56d364}}.b.red{{background:#2d1214;color:#ff7b72}}
.b.amber{{background:#2b2314;color:#e3b341}}.b.grey{{background:#21262d;color:#8b949e}}
.mut{{color:#6e7681;font-weight:400}}.buy{{color:#56d364}}.sell{{color:#ff7b72}}
.chip{{display:inline-block;background:#21262d;border-radius:6px;padding:4px 9px;
margin:3px 4px 0 0;font-size:12.5px;color:#8b949e}}.chip b{{color:#c9d1d9}}
.note{{margin-top:16px;color:#6e7681;font-size:12px}}
</style>{body}"""

def render_home():
    days, evbyday, snaps, depth, cap, running = gather()
    exp = sorted(d for d in days if d >= EXP_START)
    ok = [d for d in exp if cap.get(d, {}).get("overall", 0) >= THRESHOLD]
    qual = {d: [e for e in evbyday.get(d, []) if qualifies(e, d, cap)] for d in ok}
    tot_ev = sum(len(v) for v in qual.values())
    n_days = len(ok)
    per_day = tot_ev / n_days if n_days else 0
    sym_tot = {s: sum(1 for d in ok for e in qual[d] if e["sym"] == s) for s in SYMS}
    pending = [d for d in exp if d not in ok]
    need_days, need_ev = max(0, TARGET_DAYS - n_days), max(0, TARGET_EVENTS - tot_ev)
    eta = max(need_days, need_ev / per_day if per_day else 0)
    finish, left = datetime.date.today(), eta
    while left > 0:
        finish += datetime.timedelta(days=1)
        if finish.weekday() < 5: left -= 1
    finish = min(finish, datetime.date.fromisoformat(HARD_STOP))

    al = alerts(days, snaps, cap)
    if pending:
        al.insert(0, ("warn", f"not yet counted (capture unchecked): {', '.join(pending)}"))
    albox = "".join(f'<div class="al {k}">{t}</div>' for k, t in al) or \
            '<div class="al ok">no data-quality issues</div>'

    rows = ""
    for d in sorted(days, reverse=True):
        c = cap.get(d)
        badge = ('<span class="b grey">unchecked</span>' if c is None else
                 f'<span class="b {"green" if c["overall"]>=THRESHOLD else "red"}">{c["overall"]}%</span>')
        dq = [e for e in evbyday.get(d, []) if qualifies(e, d, cap)]
        ev, raw = len(dq), len(evbyday.get(d, []))
        pr = sum(days[d][s]["prints"] for s in SYMS)
        ct = sum(days[d][s]["contracts"] for s in SYMS)
        sn = len(snaps.get(d, set()))
        sb = f'<span class="b {"green" if sn==len(ALL13) else "red" if sn==0 else "amber"}">{sn}/{len(ALL13)}</span>'
        rows += (f'<tr class="{"pre" if d < EXP_START else ""}"><td><a href="/day?d={d}">{d}</a></td>'
                 f'<td>{badge}</td><td>{ct}</td><td>{pr:,}</td>'
                 + "".join(f"<td>{sum(1 for e in dq if e['sym']==s)}</td>" for s in SYMS)
                 + f'<td><b>{ev}</b> <span class=mut>/ {raw}</span></td><td>{sb}</td></tr>')

    # charts (experiment days only)
    trend = [(d[5:], len(qual[d])) for d in ok]
    hours = {}
    buckets = [("250k-500k", 0), ("500k-1M", 0), ("1M-2M", 0), ("2M-5M", 0), ("5M+", 0)]
    bcount = dict(buckets)
    for d in ok:
        for e in evbyday.get(d, []):                 # RAW: everything collected
            hours[e["t"][11:13]] = hours.get(e["t"][11:13], 0) + 1
        for e in qual[d]:                            # COUNTED
            n = e["n"]
            k = ("250k-500k" if n < 5e5 else "500k-1M" if n < 1e6 else
                 "1M-2M" if n < 2e6 else "2M-5M" if n < 5e6 else "5M+")
            bcount[k] += 1
    hpairs = [(h, hours.get(h, 0)) for h in sorted(hours)] if hours else []
    hcol = {h: ("#6e7681" if int(h) >= CUTOFF_HOUR else "#58a6ff") for h, _ in hpairs}
    bpairs = [(k, bcount[k]) for k, _ in buckets]
    spairs = [(s, sym_tot[s]) for s in SYMS]

    dep = "".join(f'<span class="chip">{s} <b>{depth.get(s,0)}</b></span>' for s in ALL13)

    return page(f"""
<h1>Jarvis_60 — collection status</h1>
<div class=sub>updated {datetime.datetime.now():%H:%M:%S} &middot; <a href="/">refresh</a></div>

<div class=seal>PRIMARY TEST SEALED &mdash; needs <b>{need_days} more trading days</b> and
<b>{need_ev} more events</b>. Projected unseal: <b>{finish}</b> (hard stop {HARD_STOP}).</div>

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
  <div class=lab>excludes unchecked days, sub-95% contracts, and events after {CUTOFF_HOUR}:00</div></div>
</div>

<h2>events by day</h2><div class=card>{svg_bars(trend)}</div>
<h2>events by hour (US Eastern) &mdash; raw collected</h2><div class=card>{svg_bars(hpairs, hcol)}
<div class=note>Grey bars are collected but NOT counted: events at/after {CUTOFF_HOUR}:00 are
excluded because a +60m horizon would run past the 16:00 close. Blue bars are counted.</div></div>
<h2>notional size distribution</h2><div class=card>{svg_bars(bpairs)}</div>
<h2>events by symbol</h2><div class=card>{svg_bars(spairs, COL)}</div>

<h2>chain snapshot depth (days banked)</h2><div class=card>{dep}</div>

<h2>daily detail</h2>
<table><tr><th>date</th><th>capture</th><th>contracts</th><th>prints</th>
{"".join(f"<th>{s}</th>" for s in SYMS)}<th>events counted / raw</th><th>snapshots</th></tr>{rows}</table>
<div class=note>Click a date for its event list. Grey rows are pre-experiment days.
Forward returns stay sealed until the stopping rule is met.</div>""")

def render_day(day):
    _, evbyday, _, _, cap, _ = gather()
    evs = sorted(evbyday.get(day, []), key=lambda e: -e["n"])
    c0 = cap.get(day)
    for e in evs:
        e["ok"] = qualifies(e, day, cap)
        if e["ok"]: e["why"] = "counted"
        elif int(e["t"][11:13]) >= CUTOFF_HOUR: e["why"] = f"after {CUTOFF_HOUR}:00"
        elif c0 is None: e["why"] = "day unchecked"
        elif c0["overall"] < THRESHOLD: e["why"] = "day &lt;95%"
        else: e["why"] = "contract &lt;95%"
    c = cap.get(day)
    badge = ("not yet checked" if c is None else
             f'{c["overall"]}% capture' + ("" if c["overall"] >= THRESHOLD else " — DAY EXCLUDED"))
    rows = "".join(
        f'<tr style="opacity:{1 if e["ok"] else .4}"><td>{e["t"][11:]}</td><td>{e["label"]}</td>'
        f'<td class="{"buy" if e["dir"]=="BUY" else "sell"}">{e["dir"]}</td>'
        f'<td>{e["p"]}</td><td>{e["v"]:,.0f}</td><td><b>${e["n"]:,.0f}</b></td>'
        f'<td><span class="b {"green" if e["ok"] else "grey"}">{e["why"]}</span></td></tr>' for e in evs)
    tot = sum(e["n"] for e in evs)
    return page(f"""
<h1>{day} — qualifying events</h1>
<div class=sub><a href="/">&larr; back</a> &middot; {sum(e["ok"] for e in evs)} counted of {len(evs)} &middot;
${tot:,.0f} total notional &middot; {badge}</div>
<table><tr><th>time</th><th>contract</th><th>dir</th><th>prints</th><th>lots</th><th>notional</th><th>status</th></tr>
{rows or '<tr><td colspan=7>no events collected</td></tr>'}</table>
<div class=note>Sorted by notional. An event = 2+ prints sharing an identical timestamp and
direction, totalling at least ${MIN_NOTIONAL:,}. No forward returns shown.</div>""")

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/day":
            q = urllib.parse.parse_qs(u.query).get("d", [""])[0]
            body = render_day(q) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", q) else page("<h1>bad date</h1>")
        else:
            body = render_home()
        b = body.encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass

if __name__ == "__main__":
    print(f"dashboard: http://192.168.0.208:{PORT}")
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
