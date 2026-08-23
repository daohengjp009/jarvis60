"""Inventory every OpenQuoteContext method in futu-api 10.10 and probe the ones
we don't already use. Read-only. Writes api_inventory.md.
Usage: python3 api_inventory.py"""
import inspect, time, datetime, os
import pandas as pd
from futu import OpenQuoteContext, SysConfig
import futu

BASE = os.path.dirname(os.path.abspath(__file__))
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
TODAY = datetime.date.today()
Y_AGO = TODAY - datetime.timedelta(days=365)

ALREADY_USED = {"get_market_snapshot","get_option_chain","get_rt_ticker",
                "request_history_kline","get_history_kl_quota","query_subscription",
                "subscribe","unsubscribe","set_handler","close",
                "get_option_underlying_his_statistic","get_option_underlying_his_volatility"}

def enums():
    out = {}
    for n in dir(futu):
        c = getattr(futu, n)
        if inspect.isclass(c) and hasattr(c, "load_dic"):
            vals = [k for k in vars(c) if not k.startswith("_") and k != "load_dic"]
            if vals: out[n] = vals
    return out

E = enums()
def pick(name, prefer=None):
    v = E.get(name, [])
    if prefer:
        for p in prefer:
            if p in v: return getattr(getattr(futu, name), p)
    for x in v:
        if x not in ("NONE","UNKNOWN","NA"): return getattr(getattr(futu, name), x)
    return None

SysConfig.enable_proto_encrypt(True); SysConfig.set_init_rsa_file(KEY)
ctx = OpenQuoteContext(host="127.0.0.1", port=11112)

OM   = pick("OptionMarket", ["US_SECURITY"])
MKT  = pick("Market", ["US"])
STAT = pick("OptionStatisticDataType", ["OPEN_INTEREST"])

# (method, kwargs) - only methods we do NOT already use
PROBES = [
 ("get_option_market_statistic", dict(option_market=OM, data_type=STAT,
        begin_time=str(Y_AGO), end_time=str(TODAY))),
 ("get_option_event",            dict(option_market=OM, count=20)),
 ("get_option_rank",             dict(option_market=OM)),
 ("get_option_underlying_rank",  dict(option_market=OM)),
 ("get_option_volatility",       dict(code="US.TSLA260918C400000")),
 ("get_option_exercise_probability", dict(code="US.TSLA260918C400000")),
 ("get_earnings_calendar",       dict(market=MKT, begin_date=str(TODAY),
        end_date=str(TODAY + datetime.timedelta(days=6)))),
 ("get_dividend_calendar",       dict(market=MKT, begin_date=str(TODAY),
        end_date=str(TODAY + datetime.timedelta(days=6)))),
 ("get_economic_calendar",       dict(market=MKT, begin_date=str(TODAY),
        end_date=str(TODAY + datetime.timedelta(days=6)))),
 ("get_top_movers_rank",         dict(market=MKT)),
 ("get_hot_list",                dict(market=MKT)),
 ("get_search_quote",            dict(keyword="Tesla")),
 ("get_search_news",             dict(keyword="Tesla", max_count=5)),
 ("get_fed_watch_target_rate",   dict()),
 ("get_fed_watch_dot_plot",      dict()),
 ("get_macro_indicator_list",    dict()),
 ("get_institution_holding_change", dict(code="US.TSLA")),
 ("get_ark_fund_holding",        dict()),
 ("get_stock_screen",            dict(market=MKT)),
 ("get_capital_flow",            dict(stock_code="US.TSLA")),
 ("get_capital_distribution",    dict(stock_code="US.TSLA")),
 ("get_rehab",                   dict(code="US.TSLA")),
 ("get_owner_plate",             dict(code_list=["US.TSLA"])),
]

rows = []
print(f"{'METHOD':38s} {'RESULT':10s} DETAIL")
print("-"*110)
for name, kw in PROBES:
    fn = getattr(ctx, name, None)
    if fn is None:
        print(f"{name:38s} {'ABSENT':10s} not in this SDK"); continue
    try:
        time.sleep(0.6)
        res = fn(**kw)
        r, data = (res[0], res[1]) if isinstance(res, tuple) else (1, res)
        if r != 0:
            print(f"{name:38s} {'ERR':10s} {str(data)[:70]}")
            rows.append((name, "ERR", str(data)[:120], "")); continue
        if isinstance(data, pd.DataFrame):
            cols = ", ".join(list(data.columns)[:9])
            print(f"{name:38s} {'OK':10s} {len(data):>5} rows | {cols[:70]}")
            rows.append((name, "OK", f"{len(data)} rows", ", ".join(data.columns)))
        else:
            print(f"{name:38s} {'OK':10s} {str(data)[:70]}")
            rows.append((name, "OK", str(data)[:120], ""))
    except Exception as e:
        print(f"{name:38s} {'EXC':10s} {type(e).__name__}: {str(e)[:60]}")
        rows.append((name, "EXC", f"{type(e).__name__}: {e}"[:120], ""))
ctx.close()

with open(os.path.join(BASE, "api_inventory.md"), "w") as f:
    f.write(f"# Futu 10.10 API probe — {TODAY}\n\n")
    f.write("| method | result | detail | columns |\n|---|---|---|---|\n")
    for n, s, d, c in rows:
        f.write(f"| `{n}` | {s} | {d} | {c} |\n")
print("\nwritten: api_inventory.md")
