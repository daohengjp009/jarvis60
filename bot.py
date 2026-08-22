"""Jarvis_60 Telegram bot — fixed command menu, whitelisted sender, no shell exec.
Run: nohup python3 bot.py > logs/bot.log 2>&1 &"""
import os, sys, re, json, time, subprocess, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))
TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER = str(os.getenv("TELEGRAM_CHAT_ID"))
API = f"https://api.telegram.org/bot{TOKEN}"

def send(text: str):
    try:
        data = urllib.parse.urlencode({"chat_id": OWNER, "text": text[:4000]}).encode()
        urllib.request.urlopen(urllib.request.Request(f"{API}/sendMessage", data=data), timeout=10)
    except Exception as e:
        print("send failed:", e)

def _sh(args: list, timeout: int = 240) -> str:
    """Run a fixed argument list (never a shell string) inside the project dir."""
    try:
        r = subprocess.run(args, cwd=BASE, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "timed out"

# ---- the ONLY actions the bot can perform ----
def cmd_start(arg):
    if subprocess.run(["pgrep", "-f", "collect.py"], capture_output=True).returncode == 0:
        return "collector already running"
    tickers = [t.upper() for t in arg.split()][:5] or ["TSLA", "NVDA", "GOOGL"]
    if not all(t.isalpha() for t in tickers):
        return "invalid ticker"
    log = os.path.join(BASE, "logs", f"collect_{time.strftime('%F')}.log")
    subprocess.Popen([sys.executable, "collect.py"] + tickers,
                     cwd=BASE, stdout=open(log, "a"), stderr=subprocess.STDOUT)
    return f"starting collector: {' '.join(tickers)}"

def cmd_stop(arg):  return _sh(["pkill", "-f", "collect.py"]) or "collector stopped"
def cmd_status(arg):
    running = subprocess.run(["pgrep", "-f", "collect.py"], capture_output=True).returncode == 0
    ticks = _sh(["bash", "-c", "cat data/ticks/*.csv 2>/dev/null | wc -l"])
    return f"collector: {'RUNNING' if running else 'stopped'}\nticks on disk: {ticks.strip()}"
def cmd_screen(arg):
    t = (arg.split() or ["TSLA"])[0].upper()
    if not t.isalpha(): return "invalid ticker"
    return _sh([sys.executable, "screen.py", t])
def cmd_check(arg):  return _sh([sys.executable, "core/recheck.py"])
def cmd_snap(arg):
    if subprocess.run(["pgrep", "-f", "snapshot.py"], capture_output=True).returncode == 0:
        return "snapshot already running"
    log = os.path.join(BASE, "logs", "snapshot.log")
    subprocess.Popen([sys.executable, "-u", "snapshot.py"], cwd=BASE,
                     stdout=open(log, "a"), stderr=subprocess.STDOUT)
    return "snapshot started in background (~6 min) — you'll get a message when it finishes"

def cmd_dash(arg):
    if subprocess.run(["pgrep", "-f", "dashboard.py"], capture_output=True).returncode == 0:
        return "dashboard already running: http://192.168.0.208:8060"
    log = os.path.join(BASE, "logs", "dashboard.log")
    subprocess.Popen([sys.executable, "dashboard.py"], cwd=BASE,
                     stdout=open(log, "a"), stderr=subprocess.STDOUT)
    return "dashboard started: http://192.168.0.208:8060"

def cmd_nodash(arg): return _sh(["pkill", "-f", "dashboard.py"]) or "dashboard stopped"
def cmd_cap(arg):    return _sh([sys.executable, "capture_check.py"], timeout=900)

def cmd_stream(arg):
    if subprocess.run(["pgrep", "-f", "stream_test.py"], capture_output=True).returncode == 0:
        return "stream already running"
    secs = 23400
    if arg.strip().isdigit(): secs = min(30000, int(arg.strip()))
    log = os.path.join(BASE, "logs", f"stream_{time.strftime('%F')}.log")
    subprocess.Popen([sys.executable, "-u", "stream_test.py", str(secs)], cwd=BASE,
                     stdout=open(log, "a"), stderr=subprocess.STDOUT)
    return f"stream test started ({secs//3600}h) — writes only to data/ticks_stream/"

def cmd_nostream(arg): return _sh(["pkill", "-f", "stream_test.py"]) or "stream stopped"

def cmd_intra(arg):
    if subprocess.run(["pgrep", "-f", "intraday.py"], capture_output=True).returncode == 0:
        return "intraday capture already running"
    mins = arg.strip() if arg.strip().isdigit() else "30"
    log = os.path.join(BASE, "logs", f"intraday_{time.strftime('%F')}.log")
    subprocess.Popen([sys.executable, "-u", "intraday.py", mins], cwd=BASE,
                     stdout=open(log, "a"), stderr=subprocess.STDOUT)
    return f"intraday chain capture started (every {mins} min) - writes to data/intraday/"

def cmd_nointra(arg): return _sh(["pkill", "-f", "intraday.py"]) or "intraday capture stopped"

def cmd_open(arg):
    """14:15 - everything the trading day needs."""
    return ("OPEN\n"
            f"1. collector: {cmd_start(arg)}\n"
            f"2. stream:    {cmd_stream('')}\n"
            f"3. intraday:  {cmd_intra('')}")

def cmd_close(arg):
    """21:00 - stop collecting, save the chain snapshot."""
    cmd_nointra("")
    return ("CLOSE\n"
            f"1. collector: {cmd_stop('') or 'stopped'}\n"
            f"2. snapshot:  {cmd_snap('')}\n"
            "3. intraday:  stopped")

def cmd_morning(arg):
    """Next morning - verify yesterday."""
    return (f"CAPTURE CHECK\n{cmd_cap('')}\n\n"
            f"BACKFILL\n{cmd_fill('')}\n\n"
            f"{cmd_day(arg)}")

def cmd_fill(arg):
    """Backfill 1-minute underlying bars for any collection day missing them."""
    import glob
    ticks = os.path.join(BASE, "data", "ticks")
    bars = os.path.join(BASE, "data", "underlying_1m")
    days = sorted({re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", f).group(1)
                   for f in glob.glob(os.path.join(ticks, "*.csv"))})
    out = []
    for d in days:
        for t in ("TSLA", "NVDA", "GOOGL"):
            if os.path.exists(os.path.join(bars, f"US_{t}_{d}.csv")): continue
            _sh([sys.executable, "backfill_underlying.py", t, d], timeout=180)
            p = os.path.join(bars, f"US_{t}_{d}.csv")
            if os.path.exists(p):
                with open(p) as fh: n = sum(1 for _ in fh) - 1
                out.append(f"{t} {d}: {n} bars")
            else:
                out.append(f"{t} {d}: FAILED")
    return "\n".join(out) if out else "nothing missing - all days have 1-minute bars"

def cmd_day(arg):
    a = arg.strip()
    args = [sys.executable, "daycheck.py"] + ([a] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a) else [])
    return _sh(args, timeout=300)

def cmd_day(arg):
    a = arg.strip()
    args = [sys.executable, "daycheck.py"] + ([a] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a) else [])
    return _sh(args, timeout=300)
def cmd_help(arg):
    return ("DAILY (just these three)\n/open - 14:15 start everything\n/close - 21:00 stop + snapshot\n/morning - next day: check + backfill + summary\n\nINDIVIDUAL\n/start [TICKERS] - begin collecting\n/stop - stop collector\n"
            "/status - is it alive\n/screen TICKER - option screener\n"
            "/check - toolbelt health\n/snap - daily chain snapshot (all 28)\n/dash - start dashboard\n/nodash - stop dashboard\n/day [DATE] - session summary (today by default)\n/cap - capture check (run next morning)\n/fill - backfill missing 1-min underlying bars\n/intra - start intraday chain capture\n/nointra - stop it\n/stream - start streaming test (6.5h)\n/nostream - stop it\n/help - this menu")

COMMANDS = {"/start": cmd_start, "/stop": cmd_stop, "/status": cmd_status,
            "/screen": cmd_screen, "/check": cmd_check, "/snap": cmd_snap, "/dash": cmd_dash, "/nodash": cmd_nodash, "/cap": cmd_cap, "/day": cmd_day, "/day": cmd_day, "/fill": cmd_fill, "/open": cmd_open, "/close": cmd_close, "/morning": cmd_morning, "/intra": cmd_intra, "/nointra": cmd_nointra, "/stream": cmd_stream, "/nostream": cmd_nostream, "/help": cmd_help}

def main():
    offset = None
    send("Jarvis_60 bot online. /help for commands.")
    while True:
        try:
            url = f"{API}/getUpdates?timeout=30" + (f"&offset={offset}" if offset else "")
            r = json.load(urllib.request.urlopen(url, timeout=40))
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != OWNER:
                    continue                      # whitelist: ignore everyone else
                text = (msg.get("text") or "").strip()
                word, _, arg = text.partition(" ")
                fn = COMMANDS.get(word.lower())
                send(fn(arg.strip()) if fn else "unknown command. /help")
        except Exception as e:
            print("loop error:", e); time.sleep(5)

if __name__ == "__main__":
    main()
