"""Jarvis_60 Telegram bot — fixed command menu, whitelisted sender, no shell exec.
Run: nohup python3 bot.py > logs/bot.log 2>&1 &"""
import os, sys, json, time, subprocess, urllib.request, urllib.parse
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
def cmd_snap(arg):   return _sh([sys.executable, "snapshot.py"], timeout=1800)

def cmd_dash(arg):
    if subprocess.run(["pgrep", "-f", "dashboard.py"], capture_output=True).returncode == 0:
        return "dashboard already running: http://192.168.0.208:8060"
    log = os.path.join(BASE, "logs", "dashboard.log")
    subprocess.Popen([sys.executable, "dashboard.py"], cwd=BASE,
                     stdout=open(log, "a"), stderr=subprocess.STDOUT)
    return "dashboard started: http://192.168.0.208:8060"

def cmd_nodash(arg): return _sh(["pkill", "-f", "dashboard.py"]) or "dashboard stopped"
def cmd_cap(arg):    return _sh([sys.executable, "capture_check.py"], timeout=900)
def cmd_help(arg):
    return ("/start [TICKERS] - begin collecting\n/stop - stop collector\n"
            "/status - is it alive\n/screen TICKER - option screener\n"
            "/check - toolbelt health\n/snap - daily chain snapshot (all 28)\n/dash - start dashboard\n/nodash - stop dashboard\n/cap - capture check (run next morning)\n/help - this menu")

COMMANDS = {"/start": cmd_start, "/stop": cmd_stop, "/status": cmd_status,
            "/screen": cmd_screen, "/check": cmd_check, "/snap": cmd_snap, "/dash": cmd_dash, "/nodash": cmd_nodash, "/cap": cmd_cap, "/help": cmd_help}

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
