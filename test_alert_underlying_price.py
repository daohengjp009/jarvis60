#!/usr/bin/env python3
"""Dedicated tests for alert.py event-time underlying-price enrichment."""
import os
import shutil
import tempfile

import pandas as pd

import alert as A


def _spread_candidates(ts="2026-08-25 12:00:00.000"):
    t = pd.Timestamp(ts).timestamp()
    buy = pd.DataFrame([{"_t": pd.Timestamp(ts), "time": ts, "ticker_direction": "BUY",
                         "lots": 100.0, "n": 500000.0, "sym": "NVDA", "expiry": "260828",
                         "typ": "C", "strike": 230.0, "contract": "US_NVDA260828C230000"}])
    sell = pd.DataFrame([{"_t": pd.Timestamp(ts), "time": ts, "ticker_direction": "SELL",
                          "lots": 100.0, "n": 300000.0, "sym": "NVDA", "expiry": "260828",
                          "typ": "C", "strike": 240.0, "contract": "US_NVDA260828C240000"}])
    buy["_t"] = pd.Timestamp(t, unit="s")
    sell["_t"] = pd.Timestamp(t, unit="s")
    return pd.concat([buy, sell], ignore_index=True)


def _with_underlying(rows):
    tmp = tempfile.mkdtemp()
    old = A.UNDER
    A.UNDER = tmp
    A._UNDERLYING_CACHE.clear()
    return tmp, old


def test_event_time_price_when_available():
    tmp, old = _with_underlying(_spread_candidates())
    try:
        pd.DataFrame([{"update_time": "2026-08-25 11:59:55.000", "last_price": 234.5},
                      {"update_time": "2026-08-25 12:00:01.000", "last_price": 235.5}]).to_csv(
                          os.path.join(tmp, "US_NVDA_2026-08-25.csv"), index=False)
        hit = A.decide_spreads(A.AlertState(), "NVDA", _spread_candidates())[0]
        assert hit["underlying_price"] == 234.5
        assert hit["underlying_price_observed_at"] == "2026-08-25T11:59:55.000"
        assert hit["underlying_price_source"] == "US_NVDA_2026-08-25.csv:update_time/last_price"
    finally:
        A.UNDER = old; A._UNDERLYING_CACHE.clear(); shutil.rmtree(tmp, ignore_errors=True)


def test_missing_price_remains_none():
    tmp, old = _with_underlying(_spread_candidates())
    try:
        hit = A.decide_spreads(A.AlertState(), "NVDA", _spread_candidates())[0]
        assert hit["underlying_price"] is None
        assert hit["underlying_price_source"] is None
    finally:
        A.UNDER = old; A._UNDERLYING_CACHE.clear(); shutil.rmtree(tmp, ignore_errors=True)


def test_future_and_stale_prices_are_not_substituted():
    tmp, old = _with_underlying(_spread_candidates())
    try:
        path = os.path.join(tmp, "US_NVDA_2026-08-25.csv")
        pd.DataFrame([{"update_time": "2026-08-25 12:00:01.000", "last_price": 999.0},
                      {"update_time": "2026-08-25 11:00:00.000", "last_price": 888.0}]).to_csv(path, index=False)
        assert A.event_underlying_price("NVDA", "2026-08-25 12:00:00.000")["underlying_price"] is None
        pd.DataFrame([{"update_time": "2026-08-25 11:50:00.000", "last_price": 777.0}]).to_csv(path, index=False)
        A._UNDERLYING_CACHE.clear()
        assert A.event_underlying_price("NVDA", "2026-08-25 12:00:00.000")["underlying_price"] is None
    finally:
        A.UNDER = old; A._UNDERLYING_CACHE.clear(); shutil.rmtree(tmp, ignore_errors=True)


def test_existing_spread_fields_unchanged():
    tmp, old = _with_underlying(_spread_candidates())
    try:
        hit = A.decide_spreads(A.AlertState(), "NVDA", _spread_candidates())[0]
        assert {k: hit[k] for k in ("kind", "symbol", "expiry", "lots", "gross_notional", "net_premium", "n_legs")} == {
            "kind": "inferred_spread", "symbol": "NVDA", "expiry": "260828", "lots": 100.0,
            "gross_notional": 800000.0, "net_premium": 200000.0, "n_legs": 2}
    finally:
        A.UNDER = old; A._UNDERLYING_CACHE.clear(); shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("test_alert_underlying_price.py: PASS (4 tests)")
