"""Jarvis_60 Telegram notifier — outbound only, no commands accepted."""
import os, json, urllib.request, urllib.parse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")

def send(text: str) -> bool:
    """Push a message to Leo. Never raises — notification must not break collection."""
    if not TOKEN or not CHAT:
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": CHAT, "text": text}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data)
        return json.load(urllib.request.urlopen(req, timeout=10)).get("ok", False)
    except Exception:
        return False

if __name__ == "__main__":
    ok = send("Jarvis_60 online. Notifier test successful.")
    print("sent OK" if ok else "FAILED — check TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env")
