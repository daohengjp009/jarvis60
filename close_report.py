"""End-of-session summary to Telegram, so the daily run reports itself.
Run automatically by ./j close. Read-only."""
import os, glob, datetime, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(BASE, ".env")
if os.path.exists(p):
    for line in open(p):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))

d = str(datetime.date.today())
ticks = glob.glob(os.path.join(BASE, "data", "ticks", f"*_{d}.csv"))
snaps = glob.glob(os.path.join(BASE, "data", "snapshots", f"US_*_{d}.csv"))
intra = glob.glob(os.path.join(BASE, "data", "intraday", f"US_*_{d}.csv"))
alerts = os.path.join(BASE, "data", "alerts", f"alerts_{d}.jsonl")
n_alerts = sum(1 for _ in open(alerts)) if os.path.exists(alerts) else 0

prints = 0
for f in ticks:
    try:
        with open(f) as fh: prints += sum(1 for _ in fh) - 1
    except Exception: pass

ok = len(ticks) >= 20 and len(snaps) == 28
msg = (f"CLOSE {d}\n"
       f"contracts  {len(ticks)}\n"
       f"prints     {prints:,}\n"
       f"snapshots  {len(snaps)}/28\n"
       f"intraday   {len(intra)} symbols\n"
       f"alerts     {n_alerts}\n"
       + ("all good" if ok else "*** CHECK - looks short ***"))

t, c = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
if t and c:
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{t}/sendMessage",
            urllib.parse.urlencode({"chat_id": c, "text": msg}).encode(), timeout=10)
    except Exception as e:
        print("telegram failed:", e)
print(msg)
