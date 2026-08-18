"""Jarvis_60 capture check — measures tick completeness against K-line truth.
Results cached permanently in data/capture_cache.json (K-line volume never changes).
Repeat pulls of the same contract code are free within Futu's 30-day quota window.
Usage: python3 capture_check.py"""
import os, re, glob, json, time, datetime, pandas as pd
from futu import OpenQuoteContext, SysConfig, KLType, AuType

BASE = os.path.dirname(os.path.abspath(__file__))
TICKS = os.path.join(BASE, "data", "ticks")
CACHE = os.path.join(BASE, "data", "capture_cache.json")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
SYMS = ("TSLA", "NVDA", "GOOGL")
MIN_QUOTA = 100          # abort rather than exhaust the history quota
PER_SYMBOL = 3           # contracts sampled per symbol per day (quota is 1000/30d)
PAUSE = 0.7              # seconds between K-line calls (avoid rate limiting)
THRESHOLD = 95.0

def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE) as f: return json.load(f)
    return {}

def save_cache(c):
    with open(CACHE, "w") as f: json.dump(c, f, indent=1)

def main():
    cache = load_cache()
    today = str(datetime.date.today())
    byday = {}
    for f in glob.glob(os.path.join(TICKS, "*.csv")):
        m = re.match(r"US_([A-Z]+)\d{6}[CP]\d+_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))
        if m and m.group(1) in SYMS:
            byday.setdefault(m.group(2), []).append(f)

    def fingerprint(fs):
        return f"{len(fs)}:{max(os.path.getmtime(f) for f in fs):.0f}"
    todo = []
    for d in sorted(byday):
        if d >= today: continue
        fp = fingerprint(byday[d])
        if d not in cache:
            todo.append(d)
        elif cache[d].get("fingerprint") != fp:
            print(f"{d}: tick files changed since last check — re-checking")
            todo.append(d)
    if not todo:
        print("nothing to check — all past days already cached")
        return

    SysConfig.enable_proto_encrypt(True); SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    try:
        r, q = ctx.get_history_kl_quota(get_detail=False)
        remain = q[1] if r == 0 else 0
        print(f"quota remaining: {remain}")
        for day in todo:
            files = byday[day]
            if remain < MIN_QUOTA:
                print(f"stopping — quota below {MIN_QUOTA}"); break
            sample, fails = [], 0
            for sym in SYMS:                       # busiest 3 contracts per symbol
                cand = [f for f in files if os.path.basename(f).startswith(f"US_{sym}")]
                sized = []
                for f in cand:
                    try: sized.append((len(pd.read_csv(f, usecols=["volume"])), f))
                    except Exception: pass
                sample += [f for _, f in sorted(sized, reverse=True)[:PER_SYMBOL]]
            res, ours_t, truth_t = {}, 0.0, 0.0
            for f in sample:
                code = os.path.basename(f)[:-15].replace("US_", "US.")
                try:
                    d = pd.read_csv(f, usecols=["volume"])
                except Exception:
                    continue
                time.sleep(PAUSE)
                rr, k, _ = ctx.request_history_kline(code, start=day, end=day,
                                                     ktype=KLType.K_DAY, autype=AuType.NONE)
                if rr != 0:
                    fails += 1
                    print(f"  {day} {code}: K-line FAILED: {k}")
                    continue
                truth = float(k["volume"].iloc[0]) if len(k) else 0.0
                ours = float(d["volume"].sum())
                if truth > 0:
                    res[code] = round(ours / truth * 100, 1)
                    ours_t += ours; truth_t += truth
            if not res:
                print(f"{day}: no data returned ({fails} failed calls) — NOT cached")
                continue
            bad = [c for c, v in res.items() if v < THRESHOLD]
            cache[day] = {"overall": round(ours_t / truth_t * 100, 1) if truth_t else 0,
                          "contracts": res, "below_threshold": bad,
                          "sampled": len(res), "failed_calls": fails,
                          "fingerprint": fingerprint(files),
                          "checked_at": datetime.datetime.now().isoformat(timespec="seconds")}
            save_cache(cache)
            print(f"{day}: {cache[day]['overall']:5.1f}%  contracts {len(res)}  below 95%: {len(bad)}")
        r, q = ctx.get_history_kl_quota(get_detail=False)
        if r == 0: print(f"quota remaining after: {q[1]}")
    finally:
        ctx.close()

if __name__ == "__main__":
    main()
