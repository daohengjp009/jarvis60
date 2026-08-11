"""Jarvis_60 underlying backfill — 1-minute stock bars for a past session.
Unlike option ticks, stock history is retrievable at any time.
Usage: python3 backfill_underlying.py NVDA 2026-08-10"""
import sys, os, pandas as pd
from futu import OpenQuoteContext, SysConfig, KLType, AuType

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "underlying_1m")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"

def fetch(ticker: str, date: str) -> str:
    code = ticker if "." in ticker else f"US.{ticker.upper()}"
    SysConfig.enable_proto_encrypt(True)
    SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    try:
        pages, page_key = [], None
        while True:
            ret, data, page_key = ctx.request_history_kline(
                code, start=date, end=date, ktype=KLType.K_1M,
                autype=AuType.QFQ, max_count=1000, page_req_key=page_key)
            if ret != 0:
                print("FAILED:", data); return ""
            pages.append(data)
            if not page_key: break
        df = pd.concat(pages, ignore_index=True)
        path = os.path.join(OUT, f"{code.replace('.','_')}_{date}.csv")
        df.to_csv(path, index=False)
        print(f"saved {len(df)} bars -> {os.path.basename(path)}")
        print(f"session range: {df['time_key'].iloc[0]}  to  {df['time_key'].iloc[-1]}")
        return path
    finally:
        ctx.close()

if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    d = sys.argv[2] if len(sys.argv) > 2 else "2026-08-10"
    fetch(t, d)
