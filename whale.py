#!/usr/bin/env python3
"""Whale Strategy Engine v0.3 — offline evidence layer for Jarvis_60.

Research / PAPER ONLY. This module never places orders and never sends Telegram
messages. It consumes the durable alert tape produced by alert.py and turns it
into conservative, auditable strategy candidates plus a T0 lifecycle hint.

WHY THIS EXISTS
---------------
alert.py is the live detector. whale.py is a separate research layer. Keeping
those concerns separate lets the existing alert pipeline stay stable while the
strategy logic evolves and is falsified.

CURRENT INPUT
-------------
    data/alerts/alerts_<YYYY-MM-DD>.jsonl

CURRENT OUTPUT
--------------
    data/whale/whale_<YYYY-MM-DD>.jsonl

WHAT v0.1 CAN DO
----------------
* Normalize alert.py's `own`, `futu`, and `inferred_spread` evidence.
* Parse standard Futu/OSI-like US option symbols when present.
* Classify SAME-EXPIRY inferred structures conservatively:
    - bull/bear call spread
    - bull/bear put spread
    - straddle / strangle
    - synthetic long / synthetic short
    - bullish / bearish risk reversal
    - otherwise unclassified
* Express an economic-exposure HINT (direction / vol / theta), while keeping
  intent explicitly UNKNOWN.
* Compare today's candidate with the previous stored whale day and emit only a
  T0 lifecycle hint:
    NEW_T0 / REPEATED_SUPPORT_T0 / POSSIBLE_UNWIND_OR_REVERSE_T0 /
    CHANGED_STRUCTURE_T0.
* Emit a daily per-symbol EVIDENCE summary. It is not a trading signal.

WHAT v0.1 CANNOT DO — BY DESIGN
-------------------------------
* It cannot identify a specific institution or prove that two prints belong to
  the same account.
* It cannot confirm opening vs closing from alert.py alone. That requires T+1
  open-interest snapshots.
* It cannot determine whether event volatility is cheap/expensive without an IV
  surface + realised event history.
* It cannot reliably distinguish speculation from hedge/dealer inventory
  without richer market data.
* `inferred_spread` remains an inferred candidate. Futu provides no package ID,
  exchange code, or OPRA condition code in this pipeline.

CLI
---
    python3 whale.py
    python3 whale.py 2026-08-26
    python3 whale.py 2026-08-26 --base /Users/leolo/jarvis60
    python3 whale.py --alerts-file /path/to/alerts_2026-08-26.jsonl --no-write
    python3 whale.py --self-test

Exit codes:
    0 success
    2 input missing / malformed enough to prevent analysis
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
WHALE_SCHEMA_VERSION = 5
ENGINE_VERSION = "0.3.3"

# v0.3.3's execution clustering policy.  These values are part of the output
# contract: changing one requires an algorithm-version change and fresh replay.
CLUSTER_ALGORITHM_VERSION = "execution_cluster_v1"
CLUSTER_MAX_ADJACENT_GAP_SECONDS = 300.0
CLUSTER_MAX_TOTAL_SPAN_SECONDS = 900.0
CLUSTER_MAX_ROLLING_MEDIAN_PREMIUM_DIFF = 0.05
CLUSTER_MAX_PREMIUM_RANGE = 0.10

# Moneyness is descriptive only.  ATM uses a small, explicit tolerance because
# exact equality between an equity price and strike is not observable reliably.
ATM_MONEYNESS_TOLERANCE_PCT = 0.005

# Known transition tape: it mixes legacy schema and prior-session vendor data.
# It remains readable/auditable, but can never provide lifecycle history.
QUARANTINED_HISTORY_DATES = {"2026-08-24": "EXPLICITLY_QUARANTINED_TRANSITION_TAPE"}

# One timestamp per RUN, not per record: replaying the same input with
# --freeze-time must produce a byte-identical file (design requirement:
# idempotent, diffable replay).
_RUN_AT: Optional[str] = None

# Futu filenames / symbols in alert.py use forms such as:
#   US_NVDA261016C00220000  (canonical OSI-ish)
# but older/local files can omit OSI zero-padding. Strike is encoded in 1/1000.
# Two contract formats coexist in one alert tape, confirmed against real data:
#   own   (from collect.py filenames) US_NVDA260828C210000   underscore
#   futu  (from get_option_event)     US.NVDA261016C255000   DOT
# v0.2's underscore-only pattern silently returned None for EVERY vendor event,
# so side was recovered but exposure stayed UNKNOWN. Accept both, and prefer
# the explicit strike_price / strike_time / option_type fields when present.
OPTION_RE = re.compile(r"^(?:US[._])?([A-Z]+)(\d{6})([CP])(\d+)$")
LEG_RE = re.compile(r"\b([BS])\s+([CP])([0-9]+(?:\.[0-9]+)?)\b", re.I)
DATE_FROM_ALERT_FILE_RE = re.compile(r"alerts_(\d{4}-\d{2}-\d{2})\.jsonl$")
DATE_FROM_WHALE_FILE_RE = re.compile(r"whale_(\d{4}-\d{2}-\d{2})\.jsonl$")

# T0 structure inversion is intentionally called "possible unwind OR reverse".
# Without T+1 OI we cannot tell whether the old position was closed, a new
# opposite position opened, or two unrelated participants traded the same legs.
INVERSE_STRUCTURE = {
    "bull_call_spread": "bear_call_spread",
    "bear_call_spread": "bull_call_spread",
    "bull_put_spread": "bear_put_spread",
    "bear_put_spread": "bull_put_spread",
    "synthetic_long": "synthetic_short",
    "synthetic_short": "synthetic_long",
    "bullish_risk_reversal": "bearish_risk_reversal",
    "bearish_risk_reversal": "bullish_risk_reversal",
    "long_straddle": "short_straddle",
    "short_straddle": "long_straddle",
    "long_strangle": "short_strangle",
    "short_strangle": "long_strangle",
}

MONITORABLE_DIRECTIONAL_STRUCTURES = {
    "bull_call_spread", "bear_call_spread", "bull_put_spread", "bear_put_spread",
    "synthetic_long", "synthetic_short", "bullish_risk_reversal", "bearish_risk_reversal",
}
MONITORABLE_ORIENTATION_BANDS = {"MODERATE", "WEAK_TO_MODERATE"}


@dataclass(frozen=True)
class Leg:
    side: str   # BUY / SELL
    right: str  # C / P
    strike: float
    expiry: Optional[str] = None  # YYMMDD for alert.py inferred spread

    @property
    def sign(self) -> int:
        return 1 if self.side == "BUY" else -1

    def compact(self) -> str:
        k = int(self.strike) if self.strike.is_integer() else self.strike
        return f"{self.side[0]} {self.right}{k}"


@dataclass(frozen=True)
class ParsedOption:
    symbol: str
    expiry: str
    right: str
    strike: float


# ---------------------------------------------------------------------------
# Utility / serialization
# ---------------------------------------------------------------------------


def now_ny_iso() -> str:
    global _RUN_AT
    if _RUN_AT is None:
        _RUN_AT = dt.datetime.now(NY).isoformat(timespec="seconds")
    return _RUN_AT


def set_run_time(value: Optional[str]) -> None:
    """Freeze the run timestamp so a replay is byte-identical."""
    global _RUN_AT
    _RUN_AT = value


def sha256_file(path: str) -> Optional[str]:
    try:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def finite_float(value: Any) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def json_dump_line(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deterministic_id(prefix: str, *parts: Any) -> str:
    payload = json_dump_line({"parts": list(parts)})
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def parse_market_time(value: Any) -> Optional[dt.datetime]:
    text = safe_text(value)
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(NY).replace(tzinfo=None)
    return parsed


def median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    middle = n // 2
    return ordered[middle] if n % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0


def event_underlying_price(source: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    """Return only a price carried by the source event; never query live data."""
    for key in ("underlying_price", "underlying_price_at_event"):
        value = finite_float(source.get(key))
        if value is not None and value > 0:
            return value, (safe_text(source.get("underlying_price_source")) or key)
    return None, None


def event_underlying_metadata(source: Dict[str, Any]) -> Dict[str, Any]:
    """Return event-time provenance carried by alert.py, without replay lookup."""
    price, source_key = event_underlying_price(source)
    return {
        "underlying_price_at_event": price,
        "underlying_price_source": source_key or "UNKNOWN",
        "underlying_price_observed_at": (source.get("underlying_price_observed_at")
                                           if price is not None else None),
        "underlying_price_age_seconds": (finite_float(source.get("underlying_price_age_seconds"))
                                         if price is not None else None),
    }


def leg_price_metrics(legs: Sequence[Leg], underlying_price: Optional[float]) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    for leg in legs:
        distance = (underlying_price - leg.strike) if underlying_price is not None else None
        distance_pct = (distance / leg.strike) if distance is not None and leg.strike else None
        moneyness = "UNKNOWN"
        if distance_pct is not None:
            if abs(distance_pct) <= ATM_MONEYNESS_TOLERANCE_PCT:
                moneyness = "ATM"
            elif (leg.right == "C" and distance > 0) or (leg.right == "P" and distance < 0):
                moneyness = "ITM"
            else:
                moneyness = "OTM"
        metrics.append({
            "expiry": leg.expiry, "right": leg.right, "strike": leg.strike, "side": leg.side,
            "strike_distance_dollars": distance,
            "strike_distance_percent": distance_pct,
            "moneyness": moneyness,
        })
    return metrics


def aggregate_event_price(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    values = [float(r["underlying_price_at_event"]) for r in records
              if finite_float(r.get("underlying_price_at_event")) is not None]
    sources = sorted({str(r.get("underlying_price_source")) for r in records
                      if r.get("underlying_price_source")})
    if not values:
        return {"underlying_price_at_event": None, "underlying_price_source": "UNKNOWN",
                "underlying_price_observed_at": None, "underlying_price_age_seconds": None,
                "underlying_price_observation_count": 0}
    representatives = [r for r in records if finite_float(r.get("underlying_price_at_event")) is not None]
    observed_at = [safe_text(r.get("underlying_price_observed_at")) for r in representatives]
    ages = [finite_float(r.get("underlying_price_age_seconds")) for r in representatives]
    observed_at_value = observed_at[0] if len(set(observed_at)) == 1 else None
    age_value = ages[0] if len(set(ages)) == 1 else None
    return {
        "underlying_price_at_event": values[0] if len(set(values)) == 1 else median(values),
        "underlying_price_source": sources[0] if len(sources) == 1 else "MULTIPLE_EVENT_SOURCES",
        "underlying_price_observed_at": observed_at_value,
        "underlying_price_age_seconds": age_value,
        "underlying_price_observation_count": len(values),
        "underlying_price_at_event_min": min(values),
        "underlying_price_at_event_max": max(values),
    }


def safe_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s and s.lower() not in {"nan", "none", "n/a"} else None


def parse_day(value: Optional[str]) -> str:
    if value is None:
        return dt.datetime.now(NY).date().isoformat()
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"[warn] {os.path.basename(path)}:{line_no}: invalid JSON: {exc}", file=sys.stderr)
                continue
            if not isinstance(rec, dict):
                print(f"[warn] {os.path.basename(path)}:{line_no}: non-object JSON skipped", file=sys.stderr)
                continue
            rows.append(rec)
    return rows


# ---------------------------------------------------------------------------
# Parsing / canonicalization
# ---------------------------------------------------------------------------


def parse_option_code(code: Any) -> Optional[ParsedOption]:
    text = safe_text(code)
    if not text:
        return None
    m = OPTION_RE.match(text)
    if not m:
        return None
    strike = int(m.group(4)) / 1000.0
    return ParsedOption(symbol=m.group(1), expiry=m.group(2), right=m.group(3), strike=strike)


def parse_inferred_legs(legs_text: Any, expiry: Optional[str]) -> List[Leg]:
    text = safe_text(legs_text) or ""
    legs: List[Leg] = []
    for m in LEG_RE.finditer(text):
        side = "BUY" if m.group(1).upper() == "B" else "SELL"
        legs.append(Leg(side=side, right=m.group(2).upper(), strike=float(m.group(3)), expiry=expiry))
    return legs


def canonical_signature(legs: Sequence[Leg]) -> str:
    # Full signature includes side; stable order makes deterministic replay easy.
    ordered = sorted(legs, key=lambda x: (x.expiry or "", x.right, x.strike, x.side))
    return "|".join(f"{x.expiry or '?'}:{x.right}:{x.strike:g}:{x.side[0]}" for x in ordered)


def position_key(symbol: str, legs: Sequence[Leg]) -> str:
    # Position key deliberately ignores side. Same contracts with opposite sides
    # on a later day can therefore be surfaced as a possible unwind/reversal.
    ordered = sorted(legs, key=lambda x: (x.expiry or "", x.right, x.strike))
    body = "|".join(f"{x.expiry or '?'}:{x.right}:{x.strike:g}" for x in ordered)
    return f"{symbol}|{body}"


def parse_option_fields(rec: Dict[str, Any]) -> Optional[ParsedOption]:
    """Build the contract from explicit vendor fields, falling back to the code.

    get_option_event carries option_type / strike_price / strike_time directly,
    which is unambiguous; parsing the symbol string is the fallback.
    """
    right = None
    otype = safe_text(rec.get("option_type"))
    if otype:
        u = otype.upper().rsplit(".", 1)[-1]
        if u.startswith("CALL") or u == "C":
            right = "C"
        elif u.startswith("PUT") or u == "P":
            right = "P"
    strike = finite_float(rec.get("strike_price"))
    expiry = None
    st = safe_text(rec.get("strike_time"))
    if st:
        try:
            expiry = dt.date.fromisoformat(st[:10]).strftime("%y%m%d")
        except ValueError:
            expiry = None
    symbol = None
    for key in ("symbol", "owner_code"):
        v = safe_text(rec.get(key))
        if v:
            symbol = v.replace("US.", "").replace("US_", "").upper()
            break

    if right and strike and expiry and symbol:
        return ParsedOption(symbol=symbol, expiry=expiry, right=right, strike=strike)

    for key in ("option_code", "contract", "code"):
        po = parse_option_code(rec.get(key))
        if po:
            return po
    return None


def canonical_contract(rec: Dict[str, Any]) -> Optional[str]:
    """One contract identity across both source formats, so `own` clusters and
    `futu` events on the same contract can actually be joined."""
    po = parse_option_fields(rec)
    if not po:
        return None
    return f"{po.symbol}{po.expiry}{po.right}{int(round(po.strike * 1000)):08d}"


def parse_symbol_from_record(rec: Dict[str, Any]) -> Optional[str]:
    for key in ("symbol", "underlying"):
        s = safe_text(rec.get(key))
        if s:
            return s.replace("US.", "").replace("US_", "").upper()
    for key in ("contract", "option_code", "code"):
        po = parse_option_code(rec.get(key))
        if po:
            return po.symbol
    return None


# ---------------------------------------------------------------------------
# Structure classification
# ---------------------------------------------------------------------------


def classify_structure(legs: Sequence[Leg]) -> Tuple[str, Dict[str, Any]]:
    """Classify only canonical structures supported by the evidence.

    Returns (label, details). It never guesses a structure when the leg pattern
    does not uniquely match one of the supported families.
    """
    seen = Counter((x.expiry, x.right, x.strike) for x in legs)
    dupes = [k for k, c in seen.items() if c > 1]
    if dupes:
        # Confirmed in real data: "B C220 / S C220 / S P200" - the SAME contract
        # appearing as both a buy leg and a sell leg in one timestamp bucket.
        # That is matched/cross-trade noise, not a strategy.
        return "same_contract_both_sides", {
            "reason": "one or more contracts appear on both sides of the same "
                      "timestamp bucket; this is crossed/matched flow, not a structure",
            "duplicate_contracts": [f"{r}{k:g}" for _, r, k in dupes],
        }

    if len(legs) != 2:
        return "multi_leg_unclassified", {"reason": f"{len(legs)} legs; v0.3 classifies two-leg families only"}

    a, b = legs[0], legs[1]
    if a.expiry != b.expiry:
        # alert.py's inferred_spread is same-expiry, but keep this guard for
        # forward compatibility and hand-crafted test input.
        return "cross_expiry_unclassified", {"reason": "cross-expiry linkage needs a separate calendar/diagonal model"}

    # Same right -> vertical spread if strikes differ.
    if a.right == b.right and a.strike != b.strike:
        lo, hi = sorted((a, b), key=lambda x: x.strike)
        if a.right == "C":
            if lo.side == "BUY" and hi.side == "SELL":
                return "bull_call_spread", {"expected_premium_form": "DEBIT"}
            if lo.side == "SELL" and hi.side == "BUY":
                return "bear_call_spread", {"expected_premium_form": "CREDIT"}
        else:  # Put vertical, K1 < K2
            if lo.side == "BUY" and hi.side == "SELL":
                return "bull_put_spread", {"expected_premium_form": "CREDIT"}
            if lo.side == "SELL" and hi.side == "BUY":
                return "bear_put_spread", {"expected_premium_form": "DEBIT"}
        return "vertical_unclassified", {"reason": "same-right legs did not form a long/short vertical"}

    # Call + put structures.
    rights = {a.right, b.right}
    if rights == {"C", "P"}:
        call = a if a.right == "C" else b
        put = a if a.right == "P" else b

        if call.strike == put.strike:
            if call.side == put.side == "BUY":
                return "long_straddle", {"expected_premium_form": "DEBIT"}
            if call.side == put.side == "SELL":
                return "short_straddle", {"expected_premium_form": "CREDIT"}
            if call.side == "BUY" and put.side == "SELL":
                return "synthetic_long", {}
            if call.side == "SELL" and put.side == "BUY":
                return "synthetic_short", {}

        # Conventional strangle ordering: lower put strike, higher call strike.
        if put.strike < call.strike and call.side == put.side:
            if call.side == "BUY":
                return "long_strangle", {"expected_premium_form": "DEBIT"}
            return "short_strangle", {"expected_premium_form": "CREDIT"}

        # Risk reversal: opposite sides, usually lower-strike put and higher call.
        if call.side != put.side:
            if call.side == "BUY" and put.side == "SELL":
                return "bullish_risk_reversal", {}
            if call.side == "SELL" and put.side == "BUY":
                return "bearish_risk_reversal", {}

    return "two_leg_unclassified", {"reason": "leg pattern not uniquely recognized by v0.1"}


EXPOSURE_HINTS: Dict[str, Dict[str, str]] = {
    "bull_call_spread": {"direction": "BULLISH", "volatility": "LONG_VEGA_HINT", "theta": "NEGATIVE_THETA_HINT"},
    "bear_call_spread": {"direction": "BEARISH", "volatility": "SHORT_VEGA_HINT", "theta": "POSITIVE_THETA_HINT"},
    "bull_put_spread": {"direction": "BULLISH", "volatility": "SHORT_VEGA_HINT", "theta": "POSITIVE_THETA_HINT"},
    "bear_put_spread": {"direction": "BEARISH", "volatility": "LONG_VEGA_HINT", "theta": "NEGATIVE_THETA_HINT"},
    "long_straddle": {"direction": "NEUTRAL", "volatility": "LONG_VOL", "theta": "NEGATIVE_THETA"},
    "short_straddle": {"direction": "NEUTRAL", "volatility": "SHORT_VOL", "theta": "POSITIVE_THETA"},
    "long_strangle": {"direction": "NEUTRAL", "volatility": "LONG_VOL", "theta": "NEGATIVE_THETA"},
    "short_strangle": {"direction": "NEUTRAL", "volatility": "SHORT_VOL", "theta": "POSITIVE_THETA"},
    "synthetic_long": {"direction": "BULLISH", "volatility": "APPROX_VEGA_NEUTRAL", "theta": "APPROX_THETA_NEUTRAL"},
    "synthetic_short": {"direction": "BEARISH", "volatility": "APPROX_VEGA_NEUTRAL", "theta": "APPROX_THETA_NEUTRAL"},
    "bullish_risk_reversal": {"direction": "BULLISH", "volatility": "SKEW_DEPENDENT", "theta": "MIXED"},
    "bearish_risk_reversal": {"direction": "BEARISH", "volatility": "SKEW_DEPENDENT", "theta": "MIXED"},
}


def link_confidence(structure: str, legs: Sequence[Leg], premium_consistency: Optional[bool]) -> Tuple[str, List[str], Optional[str]]:
    """Band the link/classification confidence from evidence actually present.

    v0.1 hard-coded MODERATE for every inferred spread, including structures
    whose own net premium contradicted the classification. The net debit/credit
    is the one independent check available, so it must be able to move the band.
    Returns (band, reasons, alternative_structure).
    """
    reasons: List[str] = []
    alternative: Optional[str] = None
    if not legs:
        return "NONE", ["no legs parsed"], None
    if premium_consistency is False:
        alternative = INVERSE_STRUCTURE.get(structure)
        reasons.append(
            "net premium contradicts the classified structure - aggressor-side "
            "labelling is probably inverted, so the inverse structure is at "
            "least as likely")
        return "WEAK", reasons, alternative
    if structure == "same_contract_both_sides":
        reasons.append("same contract on both sides - crossed/matched flow, not a structure")
        return "NONE", reasons, None
    if structure.endswith("_unclassified"):
        reasons.append("leg pattern not uniquely recognised")
        return "WEAK", reasons, None
    if premium_consistency is True:
        reasons.append("net premium form matches the classified structure")
        return "MODERATE", reasons, None
    reasons.append("net premium unavailable - no independent corroboration")
    return "WEAK_TO_MODERATE", reasons, None


def t0_opening_floor(trade_size: Optional[float], prior_open_interest: Optional[float]) -> Optional[float]:
    """Rigorous LOWER bound on the opening fraction of one print, at T0.

    Every closing action needs an existing position to close, and a contract's
    open positions total 2 x open interest in side-actions (one long, one short
    per contract of OI). So all closing side-actions today satisfy
    C <= 2 * OI_prior, and a print of size S has opening quantity

        q0 >= S - C >= S - 2 * OI_prior

    This needs only PRIOR open interest, which arrives with the event - unlike
    the point estimate, which needs next-day OI. It is a floor, never a
    confirmation: a floor of 0 means "no information", not "closing".
    """
    if trade_size is None or prior_open_interest is None:
        return None
    if trade_size <= 0 or prior_open_interest < 0:
        return None
    return round(max(0.0, (trade_size - 2.0 * prior_open_interest) / trade_size), 4)


def single_leg_exposure(po: ParsedOption, side: Optional[str]) -> Dict[str, str]:
    side = (side or "").upper()
    if side not in {"BUY", "SELL"}:
        return {"direction": "UNKNOWN", "volatility": "UNKNOWN", "theta": "UNKNOWN"}
    if po.right == "C" and side == "BUY":
        return {"direction": "POSITIVE_DELTA_HINT", "volatility": "LONG_VEGA_HINT", "theta": "NEGATIVE_THETA_HINT"}
    if po.right == "C" and side == "SELL":
        return {"direction": "NEGATIVE_DELTA_HINT", "volatility": "SHORT_VEGA_HINT", "theta": "POSITIVE_THETA_HINT"}
    if po.right == "P" and side == "BUY":
        return {"direction": "NEGATIVE_DELTA_HINT", "volatility": "LONG_VEGA_HINT", "theta": "NEGATIVE_THETA_HINT"}
    return {"direction": "POSITIVE_DELTA_HINT", "volatility": "SHORT_VEGA_HINT", "theta": "POSITIVE_THETA_HINT"}


# ---------------------------------------------------------------------------
# Alert normalisation
# ---------------------------------------------------------------------------


def base_envelope(day: str, source: Dict[str, Any], kind: str, symbol: Optional[str]) -> Dict[str, Any]:
    return {
        "whale_schema_version": WHALE_SCHEMA_VERSION,
        "kind": kind,
        "analysis_date": day,
        "analysis_created_at": now_ny_iso(),
        "symbol": symbol,
        "source_alert_kind": source.get("kind"),
        "source_alert_schema_version": source.get("schema_version"),
        "source_dedup_key": source.get("dedup_key"),
        # v1 tapes put the market time in `time`; v2 uses `mkt_time`; vendor
        # events also carry `fill_time`. Take the first that is actually filled in.
        "mkt_time": (safe_text(source.get("mkt_time")) or safe_text(source.get("fill_time"))
                     or safe_text(source.get("time"))),
        "source_observed_at": source.get("observed_at"),
        "paper_only": True,
    }


def normalize_inferred_spread(day: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    symbol = parse_symbol_from_record(rec)
    expiry = safe_text(rec.get("expiry"))
    legs = parse_inferred_legs(rec.get("legs"), expiry)
    structure, details = classify_structure(legs)
    out = base_envelope(day, rec, "strategy_candidate", symbol)

    net_premium = finite_float(rec.get("net_premium"))
    premium_form = "UNKNOWN"
    if net_premium is not None:
        premium_form = "DEBIT" if net_premium > 0 else "CREDIT" if net_premium < 0 else "FLAT"

    expected = details.get("expected_premium_form")
    premium_consistency = None
    if expected and premium_form != "UNKNOWN":
        premium_consistency = premium_form == expected

    band, band_reasons, alternative = link_confidence(structure, legs, premium_consistency)
    stock_leg_ambiguous = structure in {
        "bullish_risk_reversal", "bearish_risk_reversal",
        "synthetic_long", "synthetic_short"}

    lots = finite_float(rec.get("lots"))
    underlying = event_underlying_metadata(rec)
    underlying_price = underlying["underlying_price_at_event"]
    premium_per_spread = (
        net_premium / (lots * 100.0)
        if net_premium is not None and lots is not None and lots > 0 else None)
    print_id = deterministic_id(
        "print", day, rec.get("dedup_key"), out.get("mkt_time"),
        canonical_signature(legs) if legs else None, lots, net_premium)
    out.update({
        "observation_level": "PRINT",
        "print_id": print_id,
        "execution_cluster_id": None,
        "orientation_thesis_id": None,
        "contract_set_activity_id": None,
        "independence_claim": "NONE",
        **underlying,
        "underlying_price_raw_source_value": rec.get("underlying_price_source"),
        "strike_distance": leg_price_metrics(legs, underlying_price),
        "moneyness": [x["moneyness"] for x in leg_price_metrics(legs, underlying_price)],
        "monitoring_state": "NOT_APPLICABLE",
        "high_frequency_monitoring_active": False,
        "structure": structure,
        "canonical_signature": canonical_signature(legs) if legs else None,
        "position_key": position_key(symbol or "?", legs) if legs else None,
        "legs": [asdict(x) for x in legs],
        "lots": lots,
        "gross_notional": finite_float(rec.get("gross_notional")),
        "net_premium": net_premium,
        "premium_per_spread": premium_per_spread,
        "signed_net_premium": net_premium,
        "premium_turnover": abs(net_premium) if net_premium is not None else None,
        "gross_leg_turnover": finite_float(rec.get("gross_notional")),
        "economic_measure_note": (
            "Modeled observed net-premium activity/turnover; not exposure, "
            "capital, position value, or maximum loss."),
        "premium_form": premium_form,
        "expected_premium_form": expected,
        "premium_consistency": premium_consistency,
        "link_confidence_band": band,
        "link_confidence_reasons": band_reasons,
        "alternative_structure": alternative,
        "link_evidence": [
            "same market timestamp bucket",
            "same expiry",
            "same lot count",
            "opposite aggressor directions present",
            "same underlying",
        ],
        "link_evidence_note": (
            "These five items are alert.py's own filter conditions, so they are "
            "true by construction and are NOT independent corroboration. The "
            "only independent check available is premium_consistency."),
        "link_limitations": [
            "no package/complex-order ID",
            "no execution exchange",
            "no OPRA trade-condition codes",
            "same-account ownership cannot be observed",
        ],
        "exposure_hint": EXPOSURE_HINTS.get(structure, {"direction": "UNKNOWN", "volatility": "UNKNOWN", "theta": "UNKNOWN"}),
        "intent": "UNKNOWN",
        "opening_closing": "UNKNOWN_T0",
        "requires_t1_oi_confirmation": True,
        "stock_leg_unobservable": stock_leg_ambiguous,
        "stock_leg_note": (
            "With an unobservable stock leg this is indistinguishable from a "
            "collar / covered position / stock replacement."
            if stock_leg_ambiguous else None),
        "thesis_language": "Observed flow is consistent with the classified exposure; participant identity and intent are not established.",
        "classification_notes": details.get("reason"),
    })
    return out


def normalize_own(day: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    po = parse_option_fields(rec)
    symbol = po.symbol if po else parse_symbol_from_record(rec)
    side = safe_text(rec.get("dir"))
    underlying_price, underlying_price_source = event_underlying_price(rec)
    out = base_envelope(day, rec, "flow_evidence", symbol)
    out.update({
        "evidence_type": "relative_cluster",
        "contract": rec.get("contract"),
        "contract_canonical": canonical_contract(rec),
        "option": asdict(po) if po else None,
        "side": side,
        "prints": rec.get("prints"),
        "lots": finite_float(rec.get("lots")),
        "notional": finite_float(rec.get("notional")),
        "x_typical": finite_float(rec.get("x_typical")),
        "underlying_price_at_event": underlying_price,
        "underlying_price_source": underlying_price_source or "UNKNOWN",
        "underlying_price_raw_source_value": rec.get(underlying_price_source) if underlying_price_source else None,
        "strike_distance": leg_price_metrics([Leg(side=side or "UNKNOWN", right=po.right, strike=po.strike, expiry=po.expiry)] if po else [], underlying_price),
        "moneyness": (leg_price_metrics([Leg(side=side, right=po.right, strike=po.strike, expiry=po.expiry)], underlying_price)[0]["moneyness"]
                      if po and side else "UNKNOWN"),
        "monitoring_state": "NOT_APPLICABLE",
        "high_frequency_monitoring_active": False,
        "exposure_hint": single_leg_exposure(po, side) if po else {"direction": "UNKNOWN", "volatility": "UNKNOWN", "theta": "UNKNOWN"},
        "intent": "UNKNOWN",
        "opening_closing": "UNKNOWN_T0",
        "requires_t1_oi_confirmation": True,
        "note": "Single-leg cluster is evidence, not a strategy thesis; it may be speculation, hedge, close, roll, or dealer inventory.",
    })
    return out


# get_option_event's trade-direction field is `ticker_type`
# (BUY=1 / SELL=2 / NEUTRAL=3). v0.1 did not look at it, so every vendor event
# fell through to side=None and UNKNOWN exposure. Depending on SDK version the
# value arrives as "BUY", "TickerType.BUY", 1, or 1.0 - normalise all of them.
_SIDE_FIELDS = ("ticker_type", "direction", "ticker_direction", "trade_direction", "side")


def normalize_side(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            if float(value).is_integer():
                return {1: "BUY", 2: "SELL"}.get(int(value))
        except (ValueError, OverflowError):
            return None
        return None
    text = safe_text(value)
    if not text:
        return None
    s = text.upper()
    if "." in s and not s.replace(".", "", 1).isdigit():
        s = s.rsplit(".", 1)[-1]          # "TICKERTYPE.BUY" -> "BUY"
    if s in {"BUY", "SELL"}:
        return s
    if s in {"1", "1.0"}:
        return "BUY"
    if s in {"2", "2.0"}:
        return "SELL"
    return None                            # NEUTRAL / unknown stays unknown


def _first_side_field(rec: Dict[str, Any]) -> Optional[str]:
    for key in _SIDE_FIELDS:
        if key in rec:
            side = normalize_side(rec.get(key))
            if side:
                return side
    return None


def normalize_futu(day: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    po = parse_option_fields(rec)
    symbol = po.symbol if po else parse_symbol_from_record(rec)
    side = _first_side_field(rec)
    out = base_envelope(day, rec, "vendor_event_evidence", symbol)
    volume = finite_float(rec.get("volume"))
    prior_oi = finite_float(rec.get("total_open_interest"))
    floor = t0_opening_floor(volume, prior_oi)
    underlying_price, underlying_price_source = event_underlying_price(rec)
    out.update({
        "evidence_type": "futu_option_event",
        "contract": rec.get("option_code"),
        "contract_canonical": canonical_contract(rec),
        "option": asdict(po) if po else None,
        "side": side,
        "side_source": next((k for k in _SIDE_FIELDS if k in rec and normalize_side(rec.get(k))), None),
        "volume": volume,
        "price": finite_float(rec.get("price")),
        "prior_open_interest": prior_oi,
        "vo_ratio": finite_float(rec.get("vo_ratio")),
        "iv": finite_float(rec.get("iv")),
        "dte": finite_float(rec.get("dte")),
        "underlying_price": finite_float(rec.get("underlying_price")),
        "underlying_price_at_event": underlying_price,
        "underlying_price_source": underlying_price_source or "UNKNOWN",
        "underlying_price_raw_source_value": rec.get(underlying_price_source) if underlying_price_source else None,
        "strike_distance": leg_price_metrics([Leg(side=side or "UNKNOWN", right=po.right, strike=po.strike, expiry=po.expiry)] if po and side else [], underlying_price),
        "moneyness": ([leg_price_metrics([Leg(side=side, right=po.right, strike=po.strike, expiry=po.expiry)], underlying_price)[0]["moneyness"]]
                      if po and side else ["UNKNOWN"]),
        "monitoring_state": "NOT_APPLICABLE",
        "high_frequency_monitoring_active": False,
        "bid_at_event": finite_float(rec.get("bid_price")),
        "ask_at_event": finite_float(rec.get("ask_price")),
        "vendor_labels": {
            "order_type_list": rec.get("order_type_list"),
            "strategy_type": safe_text(rec.get("strategy_type")),
            "sentiment": safe_text(rec.get("sentiment")),
        },
        "vendor_label_note": (
            "order_type_list / strategy_type / sentiment are Futu's own "
            "classifications with undocumented methodology. Treat as features "
            "to be tested, never as ground truth about intent."),
        "opening_floor_fraction": floor,
        "opening_floor_basis": (
            "q0 >= volume - 2 * prior_open_interest; requires "
            "total_open_interest to be PRIOR-session OI (verify)"
            if floor is not None else None),
        "exposure_hint": single_leg_exposure(po, side) if po and side else {"direction": "UNKNOWN", "volatility": "UNKNOWN", "theta": "UNKNOWN"},
        "intent": "UNKNOWN",
        "opening_closing": ("OPENING_FLOOR_T0" if (floor or 0) > 0 else "UNKNOWN_T0"),
        "requires_t1_oi_confirmation": True,
        "raw_vendor_fields": {k: v for k, v in rec.items() if k not in {"schema_version", "kind", "dedup_key", "mkt_time", "observed_at"}},
        "note": "Vendor unusual-activity event retained as evidence; whale.py does not treat vendor labeling as institutional intent.",
    })
    return out


def normalize_alert(day: str, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    kind = rec.get("kind")
    if kind == "_meta":
        return None
    if kind in {"inferred_spread", "spread"}:
        return normalize_inferred_spread(day, rec)
    if kind == "own":
        return normalize_own(day, rec)
    if kind == "futu":
        return normalize_futu(day, rec)

    symbol = parse_symbol_from_record(rec)
    out = base_envelope(day, rec, "unclassified_evidence", symbol)
    out.update({"raw": rec, "note": "Unknown alert kind preserved, not interpreted."})
    return out


# ---------------------------------------------------------------------------
# v0.3.3 hierarchy: PRINT -> cluster -> orientation -> contract-set activity
# ---------------------------------------------------------------------------


def _cluster_eligible(rec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if rec.get("kind") != "strategy_candidate": reasons.append("NOT_STRATEGY_PRINT")
    band_eligible = rec.get("link_confidence_band") in {"MODERATE", "WEAK_TO_MODERATE"}
    # A session-level opposing orientation is handled at CONTRACT_SET_ACTIVITY,
    # not by deleting otherwise premium-consistent orientation evidence.
    conflict_only_eligible = (rec.get("link_confidence_band") == "WEAK"
                              and rec.get("intraday_direction_conflict")
                              and rec.get("premium_consistency") is True
                              and not rec.get("fixed_clip_degeneracy"))
    if not (band_eligible or conflict_only_eligible): reasons.append("LINK_NOT_ELIGIBLE")
    if rec.get("tape_date_mismatch"): reasons.append("WRONG_DAY")
    if rec.get("tape_undated"): reasons.append("UNDATED")
    if rec.get("history_quarantined"): reasons.append("QUARANTINED")
    if not rec.get("position_key") or not rec.get("canonical_signature"): reasons.append("INVALID_IDENTITY")
    if parse_market_time(rec.get("mkt_time")) is None: reasons.append("INVALID_TIMESTAMP")
    lots = finite_float(rec.get("lots"))
    if lots is None or lots <= 0: reasons.append("INVALID_LOTS")
    if finite_float(rec.get("net_premium")) is None: reasons.append("INVALID_NET_PREMIUM")
    if finite_float(rec.get("premium_per_spread")) is None: reasons.append("INVALID_PREMIUM_PER_SPREAD")
    if not rec.get("structure") or str(rec.get("structure")).endswith("_unclassified"): reasons.append("INVALID_STRUCTURE")
    if rec.get("premium_form") not in {"DEBIT", "CREDIT"}: reasons.append("INVALID_PREMIUM_FORM")
    return not reasons, reasons


def _cluster_record(day: str, group: Sequence[Dict[str, Any]], split_before: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(group, key=lambda r: (parse_market_time(r["mkt_time"]), str(r["print_id"])))
    times = [parse_market_time(r["mkt_time"]) for r in ordered]
    premiums = [float(r["premium_per_spread"]) for r in ordered]
    lots = [float(r["lots"]) for r in ordered]
    print_ids = [str(r["print_id"]) for r in ordered]
    cluster_id = deterministic_id("cluster", day, ordered[0]["position_key"],
                                  ordered[0]["canonical_signature"], print_ids)
    signed = sum(float(r["net_premium"]) for r in ordered)
    turnover = sum(abs(float(r["net_premium"])) for r in ordered)
    gross = sum(float(r.get("gross_notional") or 0.0) for r in ordered)
    price_fields = aggregate_event_price(ordered)
    legs = ordered[0].get("legs") or []
    cluster_price = price_fields.get("underlying_price_at_event")
    for rec in ordered:
        rec["execution_cluster_id"] = cluster_id
        rec["cluster_eligibility"] = {"eligible": True, "reasons": []}
    return {
        "whale_schema_version": WHALE_SCHEMA_VERSION,
        "kind": "execution_cluster", "observation_level": "EXECUTION_CLUSTER",
        "analysis_date": day, "analysis_created_at": now_ny_iso(), "symbol": ordered[0].get("symbol"),
        "execution_cluster_id": cluster_id, "position_key": ordered[0]["position_key"],
        "canonical_signature": ordered[0]["canonical_signature"], "structure": ordered[0]["structure"],
        "premium_form": ordered[0]["premium_form"], "link_confidence_band": ordered[0]["link_confidence_band"],
        "print_ids": print_ids, "print_count": len(ordered),
        "lots_sum": sum(lots), "lots_min": min(lots), "lots_max": max(lots),
        "first_mkt_time": ordered[0]["mkt_time"], "last_mkt_time": ordered[-1]["mkt_time"],
        "duration_seconds": round((times[-1] - times[0]).total_seconds(), 6),
        "premium_per_spread_min": min(premiums), "premium_per_spread_median": median(premiums),
        "premium_per_spread_max": max(premiums),
        "legs": legs,
        **price_fields,
        "strike_distance": leg_price_metrics([Leg(**x) for x in legs], cluster_price) if legs else [],
        "moneyness": [x["moneyness"] for x in leg_price_metrics([Leg(**x) for x in legs], cluster_price)] if legs else [],
        "signed_net_premium_sum": signed, "premium_turnover_sum": turnover,
        "gross_leg_turnover_sum": gross,
        "activity_description": "MODELED_NET_DEBIT_ACTIVITY" if signed > 0 else "MODELED_NET_CREDIT_ACTIVITY" if signed < 0 else "MODELED_NET_FLAT_ACTIVITY",
        "economic_measure_note": "Modeled observed net-premium activity/turnover; not exposure or capital. Gross leg turnover is diagnostic only.",
        "cluster_algorithm": {
            "version": CLUSTER_ALGORITHM_VERSION,
            "max_adjacent_gap_seconds": CLUSTER_MAX_ADJACENT_GAP_SECONDS,
            "max_total_span_seconds": CLUSTER_MAX_TOTAL_SPAN_SECONDS,
            "max_rolling_median_premium_diff": CLUSTER_MAX_ROLLING_MEDIAN_PREMIUM_DIFF,
            "max_total_premium_range": CLUSTER_MAX_PREMIUM_RANGE,
        },
        "split_before": split_before, "independence_claim": "NONE",
        "participant_identity": "UNKNOWN", "parent_order": "UNKNOWN", "opening_closing": "UNKNOWN_T0",
        "paper_only": True,
        "monitoring_state": "NOT_APPLICABLE",
        "high_frequency_monitoring_active": False,
    }


def build_execution_clusters(day: str, records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    partitions: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = defaultdict(list)
    for rec in records:
        if rec.get("kind") != "strategy_candidate":
            continue
        eligible, reasons = _cluster_eligible(rec)
        rec["cluster_eligibility"] = {"eligible": eligible, "reasons": reasons}
        if not eligible:
            continue
        key = (rec.get("position_key"), rec.get("canonical_signature"), rec.get("structure"), rec.get("premium_form"))
        partitions[key].append(rec)

    output: List[Dict[str, Any]] = []
    eps = 1e-12
    for _, items in sorted(partitions.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        ordered = sorted(items, key=lambda r: (parse_market_time(r["mkt_time"]), str(r["print_id"])))
        current: List[Dict[str, Any]] = []
        split_before: Optional[Dict[str, Any]] = None
        for rec in ordered:
            if not current:
                current = [rec]
                continue
            candidate_time = parse_market_time(rec["mkt_time"])
            prior_time = parse_market_time(current[-1]["mkt_time"])
            first_time = parse_market_time(current[0]["mkt_time"])
            p = float(rec["premium_per_spread"])
            existing = [float(x["premium_per_spread"]) for x in current]
            checks = {
                "ADJACENT_GAP": (candidate_time - prior_time).total_seconds() <= CLUSTER_MAX_ADJACENT_GAP_SECONDS + eps,
                "TOTAL_SPAN": (candidate_time - first_time).total_seconds() <= CLUSTER_MAX_TOTAL_SPAN_SECONDS + eps,
                "ROLLING_MEDIAN_PREMIUM": abs(p - median(existing)) <= CLUSTER_MAX_ROLLING_MEDIAN_PREMIUM_DIFF + eps,
                "TOTAL_PREMIUM_RANGE": max(existing + [p]) - min(existing + [p]) <= CLUSTER_MAX_PREMIUM_RANGE + eps,
            }
            if all(checks.values()):
                current.append(rec)
                continue
            failed = [name for name, passed in checks.items() if not passed]
            output.append(_cluster_record(day, current, split_before))
            split_before = {"print_id": rec["print_id"], "primary_reason": failed[0], "failed_checks": failed}
            current = [rec]
        if current:
            output.append(_cluster_record(day, current, split_before))
    return output


def build_orientation_theses(day: str, clusters: Sequence[Dict[str, Any]],
                             print_index: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for cluster in clusters:
        groups[(str(cluster["position_key"]), str(cluster["canonical_signature"]))].append(cluster)
    output: List[Dict[str, Any]] = []
    for (pk, signature), items in sorted(groups.items()):
        items = sorted(items, key=lambda x: (x["first_mkt_time"], x["execution_cluster_id"]))
        cluster_ids = [x["execution_cluster_id"] for x in items]
        print_ids = [pid for x in items for pid in x["print_ids"]]
        oid = deterministic_id("orientation", day, pk, signature, cluster_ids)
        signed = sum(float(x["signed_net_premium_sum"]) for x in items)
        price_fields = aggregate_event_price(items)
        legs = items[0].get("legs") or []
        orientation_price = price_fields.get("underlying_price_at_event")
        orientation_monitorable = (items[0].get("structure") in MONITORABLE_DIRECTIONAL_STRUCTURES
                                   and any(x.get("link_confidence_band") in MONITORABLE_ORIENTATION_BANDS
                                           for x in items))
        rec = {
            "whale_schema_version": WHALE_SCHEMA_VERSION, "kind": "orientation_thesis",
            "observation_level": "ORIENTATION_THESIS", "analysis_date": day,
            "analysis_created_at": now_ny_iso(), "symbol": items[0].get("symbol"),
            "orientation_thesis_id": oid, "position_key": pk, "canonical_signature": signature,
            "structure": items[0]["structure"], "premium_form": items[0]["premium_form"],
            "directional_monitoring_eligible": orientation_monitorable,
            "legs": legs, **price_fields,
            "strike_distance": leg_price_metrics([Leg(**x) for x in legs], orientation_price) if legs else [],
            "moneyness": [x["moneyness"] for x in leg_price_metrics([Leg(**x) for x in legs], orientation_price)] if legs else [],
            "execution_cluster_ids": cluster_ids, "print_ids": print_ids,
            "execution_cluster_count": len(items), "raw_print_count": len(print_ids),
            "lots_sum": sum(float(x["lots_sum"]) for x in items),
            "signed_net_premium_sum": signed,
            "premium_turnover_sum": sum(float(x["premium_turnover_sum"]) for x in items),
            "gross_leg_turnover_sum": sum(float(x["gross_leg_turnover_sum"]) for x in items),
            "independence_claim": "NONE", "participant_identity": "UNKNOWN", "paper_only": True,
            "monitoring_state": "NOT_APPLICABLE", "high_frequency_monitoring_active": False,
        }
        output.append(rec)
        for pid in print_ids:
            print_index[pid]["orientation_thesis_id"] = oid
    return output


def _monitoring_seed(activity: Dict[str, Any], day: str, eligible: bool) -> Dict[str, Any]:
    """Seed the separate abnormal-structure monitoring lifecycle."""
    abnormal = activity.get("direction_status") == "DIRECTION_CONFLICT"
    if not abnormal and not eligible:
        return {
            "monitoring_state": "NOT_APPLICABLE", "monitoring_started_at": None,
            "outcome_label": None, "outcome_captured_at": None,
            "monitoring_reason": None, "monitoring_history": [],
            "high_frequency_monitoring_active": False,
            "low_frequency_lifecycle_active": False,
            "low_frequency_monitoring_scope": [],
        }
    started = activity.get("analysis_created_at") or now_ny_iso()
    reason = "DIRECTION_CONFLICT" if abnormal else "eligible consistent directional structure"
    history = [
        {"state": "DETECTED", "at": started, "reason": reason},
        {"state": "ACTIVE_MONITOR", "at": started, "reason": "begin high-frequency monitoring"},
    ]
    return {
        "monitoring_state": "ACTIVE_MONITOR", "monitoring_started_at": started,
        "outcome_label": None, "outcome_captured_at": None,
        "monitoring_reason": reason, "monitoring_history": history,
        "high_frequency_monitoring_active": True,
        "low_frequency_lifecycle_active": False,
        "low_frequency_monitoring_scope": ["repeated_flow", "opposite_flow", "t_plus_1_open_interest", "expiry"],
    }


def advance_monitoring_state(activity: Dict[str, Any], event: str,
                             outcome_label: Optional[str] = None,
                             at: Optional[str] = None) -> Dict[str, Any]:
    """Deterministic state machine; outcome thresholds are intentionally absent."""
    current = str(activity.get("monitoring_state") or "NOT_APPLICABLE")
    stamp = at or activity.get("analysis_created_at") or now_ny_iso()
    allowed = {
        "start": {"DETECTED": "ACTIVE_MONITOR"},
        "outcome_captured": {"ACTIVE_MONITOR": "OUTCOME_CAPTURED"},
        "low_frequency": {"OUTCOME_CAPTURED": "LOW_FREQUENCY_LIFECYCLE"},
        "expiry": {"DETECTED": "CLOSED_OR_EXPIRED", "ACTIVE_MONITOR": "CLOSED_OR_EXPIRED",
                   "OUTCOME_CAPTURED": "CLOSED_OR_EXPIRED", "LOW_FREQUENCY_LIFECYCLE": "CLOSED_OR_EXPIRED"},
    }
    target = allowed.get(event, {}).get(current)
    if target is None:
        return activity
    history = list(activity.get("monitoring_history") or [])
    history.append({"state": target, "at": stamp, "event": event})
    activity["monitoring_state"] = target
    activity["monitoring_history"] = history
    activity["high_frequency_monitoring_active"] = target in {"DETECTED", "ACTIVE_MONITOR"}
    activity["low_frequency_lifecycle_active"] = target in {"OUTCOME_CAPTURED", "LOW_FREQUENCY_LIFECYCLE"}
    if target == "OUTCOME_CAPTURED":
        directional_labels = {"BULLISH_FOLLOW_THROUGH", "BEARISH_FOLLOW_THROUGH",
                              "BULLISH_SUCCESS", "BEARISH_SUCCESS"}
        if (activity.get("direction_status") == "DIRECTION_CONFLICT" and
                outcome_label in directional_labels):
            activity["outcome_label"] = "NO_DIRECTIONAL_FOLLOW_THROUGH_LABEL"
        else:
            activity["outcome_label"] = outcome_label or "UNLABELED_OUTCOME_CAPTURED"
        activity["outcome_captured_at"] = stamp
        activity["monitoring_reason"] = "explicit outcome captured; no success threshold inferred"
    elif target == "LOW_FREQUENCY_LIFECYCLE":
        activity["monitoring_reason"] = "outcome captured; continue low-frequency checks"
    elif target == "CLOSED_OR_EXPIRED":
        activity["high_frequency_monitoring_active"] = False
        activity["monitoring_reason"] = "contract set expired or monitoring closed"
    return activity


def monitoring_expired(activity: Dict[str, Any], day: str) -> bool:
    for leg in activity.get("legs") or []:
        expiry = safe_text(leg.get("expiry"))
        if expiry:
            try:
                expiry_day = dt.datetime.strptime(expiry, "%y%m%d").date()
                return dt.date.fromisoformat(day) >= expiry_day
            except ValueError:
                continue
    return False


def build_contract_set_activities(day: str, orientations: Sequence[Dict[str, Any]],
                                  print_index: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for orientation in orientations:
        groups[str(orientation["position_key"])].append(orientation)
    output: List[Dict[str, Any]] = []
    for pk, items in sorted(groups.items()):
        items = sorted(items, key=lambda x: x["canonical_signature"])
        orientation_ids = [x["orientation_thesis_id"] for x in items]
        cid = deterministic_id("contractset", day, pk, orientation_ids)
        signatures = [x["canonical_signature"] for x in items]
        conflict = len(set(signatures)) > 1
        print_ids = [pid for x in items for pid in x["print_ids"]]
        price_fields = aggregate_event_price(items)
        legs = items[0].get("legs") or []
        activity_price = price_fields.get("underlying_price_at_event")
        activity = {
            "whale_schema_version": WHALE_SCHEMA_VERSION, "kind": "contract_set_activity",
            "observation_level": "CONTRACT_SET_ACTIVITY", "analysis_date": day,
            "analysis_created_at": now_ny_iso(), "symbol": items[0].get("symbol"),
            "contract_set_activity_id": cid, "position_key": pk,
            "orientation_thesis_ids": orientation_ids, "canonical_signatures": signatures,
            "structures": dict(Counter(str(x["structure"]) for x in items)),
            "print_ids": print_ids,
            "legs": legs, **price_fields,
            "strike_distance": leg_price_metrics([Leg(**x) for x in legs], activity_price) if legs else [],
            "moneyness": [x["moneyness"] for x in leg_price_metrics([Leg(**x) for x in legs], activity_price)] if legs else [],
            "execution_cluster_count": sum(int(x["execution_cluster_count"]) for x in items),
            "orientation_thesis_count": len(items), "raw_print_count": len(print_ids),
            "lots_sum": sum(float(x["lots_sum"]) for x in items),
            "signed_net_premium_sum": sum(float(x["signed_net_premium_sum"]) for x in items),
            "premium_turnover_sum": sum(float(x["premium_turnover_sum"]) for x in items),
            "gross_leg_turnover_sum": sum(float(x["gross_leg_turnover_sum"]) for x in items),
            "direction_status": "DIRECTION_CONFLICT" if conflict else "CONSISTENT",
            "directional_bias_eligible": not conflict,
            "independence_claim": "NONE", "participant_identity": "UNKNOWN",
            "parent_execution_programme": "UNKNOWN", "opening_closing": "UNKNOWN_T0",
            "paper_only": True,
        }
        monitorable_orientations = [x for x in items if x.get("directional_monitoring_eligible")]
        monitoring_eligible = bool(monitorable_orientations)
        activity["monitoring_eligibility"] = {
            "eligible": (conflict or (not conflict and monitoring_eligible)),
            "reasons": (["DIRECTION_CONFLICT_ACTIVITY_ONLY"] if conflict else
                        (["CONSISTENT_DIRECTIONAL_STRUCTURE"] if monitoring_eligible else
                         ["NO_ELIGIBLE_DIRECTIONAL_ORIENTATION"]))
        }
        activity.update(_monitoring_seed(activity, day, conflict or monitoring_eligible))
        if monitoring_expired(activity, day):
            advance_monitoring_state(activity, "expiry")
        output.append(activity)
        for pid in print_ids:
            print_index[pid]["contract_set_activity_id"] = cid
    return output


# ---------------------------------------------------------------------------
# T0 lifecycle comparison at CONTRACT_SET_ACTIVITY level
# ---------------------------------------------------------------------------


def find_previous_whale_file(out_dir: str, day: str) -> Optional[str]:
    target = dt.date.fromisoformat(day)
    candidates: List[Tuple[dt.date, str]] = []
    for path in glob.glob(os.path.join(out_dir, "whale_*.jsonl")):
        m = DATE_FROM_WHALE_FILE_RE.search(os.path.basename(path))
        if not m:
            continue
        try:
            d = dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if d < target:
            candidates.append((d, path))
    return max(candidates, default=(None, None), key=lambda x: x[0] or dt.date.min)[1]


def find_previous_whale_files(out_dir: str, day: str, lookback_days: int) -> List[str]:
    """All prior whale files within the lookback window, newest first.

    v0.1 looked at only the single most recent file, so a structure seen three
    sessions ago - or one day after a quiet/empty session - was reported as
    NEW_T0. Position lifecycles do not respect file adjacency.
    """
    target = dt.date.fromisoformat(day)
    earliest = target - dt.timedelta(days=max(1, lookback_days))
    found: List[Tuple[dt.date, str]] = []
    for path in glob.glob(os.path.join(out_dir, "whale_*.jsonl")):
        m = DATE_FROM_WHALE_FILE_RE.search(os.path.basename(path))
        if not m:
            continue
        try:
            d = dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if earliest <= d < target:
            found.append((d, path))
    return [p for _, p in sorted(found, reverse=True)]


def prior_activity_index(paths: Sequence[str]) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """Load only schema-v4, integrity-valid, non-quarantined contract activity."""
    idx: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    audit: List[Dict[str, Any]] = []
    for one in paths:
        name = os.path.basename(one)
        match = DATE_FROM_WHALE_FILE_RE.search(name)
        file_day = match.group(1) if match else None
        reasons: List[str] = []
        if file_day in QUARANTINED_HISTORY_DATES:
            reasons.append(QUARANTINED_HISTORY_DATES[file_day])
        rows = read_jsonl(one) if os.path.exists(one) else []
        activities = [r for r in rows if r.get("kind") == "contract_set_activity"]
        if not activities:
            reasons.append("NO_CONTRACT_SET_ACTIVITY")
        if any(r.get("whale_schema_version") != WHALE_SCHEMA_VERSION for r in activities):
            reasons.append("UNRECOGNIZED_OR_LEGACY_SCHEMA")
        if any(r.get("analysis_date") != file_day for r in activities):
            reasons.append("ANALYSIS_DATE_MISMATCH")
        if any(not r.get("source_file_sha256") for r in activities):
            reasons.append("MISSING_SOURCE_PROVENANCE")
        summaries = [r for r in rows if r.get("kind") == "symbol_summary"]
        if any((r.get("tape_integrity") or {}).get(k) for r in summaries for k in ("stale_dated", "undated")):
            reasons.append("INVALID_TAPE_INTEGRITY")
        reasons = list(dict.fromkeys(reasons))
        eligible = not reasons
        audit.append({"file": name, "eligible": eligible, "reasons": reasons,
                      "source_file_sha256": sha256_file(one)})
        if eligible:
            for rec in activities:
                copied = dict(rec)
                copied["_prior_file"] = name
                idx[str(rec["position_key"])].append(copied)
    return idx, audit


def apply_activity_lifecycle(records: List[Dict[str, Any]], prior_idx: Dict[str, List[Dict[str, Any]]],
                             history_audit: Sequence[Dict[str, Any]]) -> None:
    accepted = [x["file"] for x in history_audit if x["eligible"]]
    rejected = [{"file": x["file"], "reasons": x["reasons"]} for x in history_audit if not x["eligible"]]
    for rec in records:
        if rec.get("kind") != "contract_set_activity":
            continue
        pk = rec.get("position_key")
        prior = prior_idx.get(str(pk), []) if pk else []
        current_signatures = set(rec.get("canonical_signatures") or [])
        current_structures = set((rec.get("structures") or {}).keys())
        status = "NEW_T0_RELATIVE_TO_ELIGIBLE_HISTORY"
        rationale = "No eligible prior contract-set activity uses the same contract set."
        if prior:
            prior_signatures = {s for x in prior for s in (x.get("canonical_signatures") or [])}
            prior_structures = {s for x in prior for s in (x.get("structures") or {}).keys()}
            if current_signatures & prior_signatures:
                status = "REPEATED_SUPPORT_T0"
                rationale = "The same contract set and side-defined orientation appeared in eligible prior history; participant continuity and opening/adding are not established."
            elif any(INVERSE_STRUCTURE.get(str(s)) in prior_structures for s in current_structures):
                status = "POSSIBLE_UNWIND_OR_REVERSE_T0"
                rationale = "Opposite-side structure appeared on the same contract set; T+1 OI is required to distinguish unwind from new reversal or unrelated flow."
            else:
                status = "CHANGED_STRUCTURE_T0"
                rationale = "Same contract set reappeared with a different structure classification."
        rec["lifecycle"] = {
            "state": status,
            "rationale": rationale,
            "eligible_prior_files": accepted,
            "rejected_prior_files": rejected,
            "matched_prior_files": sorted({str(x.get("_prior_file")) for x in prior}) or None,
            "t1_oi_confirmation": "REQUIRED",
            "participant_continuity": "UNKNOWN",
        }


def check_tape_integrity(day: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Refuse to silently aggregate records that do not belong to this day.

    Confirmed in real data (alerts_2026-08-24.jsonl): the pre-v2 tape carried
    no schema_version / dedup_key / observed_at, used `contract` instead of
    `option_code`, and - critically - had no same-session guard, so a file
    dated 2026-08-24 contains vendor events whose fill_time is 2026-08-21.
    Aggregating those into "2026-08-24" makes every daily figure wrong.

    Marks each affected record and returns counts. Marked records are excluded
    from the weighted reading; raw structure counts are left untouched so the
    tape stays self-describing.
    """
    issues: Dict[str, Any] = {
        "legacy_schema": 0, "stale_dated": 0, "undated": 0,
        "stale_date_counts": {},
    }
    stale: Counter = Counter()
    for rec in records:
        if rec.get("kind") == "symbol_summary":
            continue
        if rec.get("source_alert_schema_version") is None:
            issues["legacy_schema"] += 1
            rec["tape_legacy_schema"] = True
        mkt = safe_text(rec.get("mkt_time"))
        seen_day = mkt[:10] if mkt and len(mkt) >= 10 else None
        if seen_day is None:
            issues["undated"] += 1
            rec["tape_undated"] = True
        elif seen_day != day:
            issues["stale_dated"] += 1
            stale[seen_day] += 1
            rec["tape_date_mismatch"] = seen_day
    issues["stale_date_counts"] = dict(sorted(stale.items()))
    return issues


def flag_session_artifacts(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Two session-level tells that a day's inferred spreads are not what they look like.

    (1) INTRADAY DIRECTION CONFLICT. The same contract set appearing with both
        side assignments in one session. Observed in real data: TSLA C345/P350
        was emitted as B C345 / S P350 six times and as S C345 / B P350 twice
        inside twenty minutes. Either two different participants are being
        spuriously paired, or the aggressor labels on combo legs are unreliable.
        Either way the structure label cannot be trusted, so every candidate on
        that contract set is downgraded.

    (2) FIXED-CLIP DEGENERACY. alert.py links legs partly on "same lot count".
        If most of a symbol's candidates share one clip size, that criterion
        carries no information that day. Observed in real data: 16 of 16 TSLA
        candidates were 98-99 lots.

    Returns per-symbol diagnostics; mutates the affected candidates in place.
    """
    cands = [r for r in records if r.get("kind") == "strategy_candidate"]

    sides_by_key: Dict[str, Dict[Tuple[Any, ...], set]] = defaultdict(lambda: defaultdict(set))
    for r in cands:
        pk = str(r.get("position_key"))
        for leg in r.get("legs") or []:
            sides_by_key[pk][(leg.get("expiry"), leg.get("right"), leg.get("strike"))].add(leg.get("side"))
    conflicted = {
        pk for pk, contracts in sides_by_key.items()
        if any(len(v) > 1 for v in contracts.values())
    }

    by_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in cands:
        if r.get("symbol"):
            by_symbol[str(r["symbol"])].append(r)

    diagnostics: Dict[str, Dict[str, Any]] = {}
    for sym, items in by_symbol.items():
        lots = [x.get("lots") for x in items if x.get("lots")]
        clip = None
        clip_share = 0.0
        if lots:
            counts = Counter(round(float(x)) for x in lots)
            clip, top = counts.most_common(1)[0]
            near = sum(c for k, c in counts.items() if abs(k - clip) <= 1)
            clip_share = near / len(lots)
        degenerate = bool(lots) and len(lots) >= 5 and clip_share >= 0.5
        diagnostics[sym] = {
            "modal_lot_clip": clip,
            "modal_clip_share": round(clip_share, 3),
            "fixed_clip_degeneracy": degenerate,
            "conflicted_position_keys": sorted(
                pk for pk in conflicted if any(str(x.get("position_key")) == pk for x in items)),
        }

    for r in cands:
        pk = str(r.get("position_key"))
        sym = str(r.get("symbol"))
        conflict = pk in conflicted
        degen = diagnostics.get(sym, {}).get("fixed_clip_degeneracy", False)
        r["intraday_direction_conflict"] = conflict
        r["fixed_clip_degeneracy"] = degen
        if conflict or degen:
            reasons = list(r.get("link_confidence_reasons") or [])
            if conflict:
                reasons.append("same contract set appears with both side assignments this session")
            if degen:
                reasons.append(
                    f"symbol's candidates cluster on one lot clip "
                    f"({diagnostics[sym]['modal_lot_clip']}, "
                    f"{diagnostics[sym]['modal_clip_share']:.0%}) - "
                    f"the 'same lot count' link criterion is uninformative today")
            r["link_confidence_reasons"] = reasons
            # Preserve the raw PRINT confidence warning. Opposing signatures
            # may still cluster independently; _cluster_eligible handles that
            # narrow exception before CONTRACT_SET_ACTIVITY suppresses bias.
            if r.get("link_confidence_band") not in {"NONE"}:
                r["link_confidence_band"] = "WEAK"
    return diagnostics


# ---------------------------------------------------------------------------
# Daily summaries — evidence, not signal
# ---------------------------------------------------------------------------


def build_symbol_summaries(day: str, records: Sequence[Dict[str, Any]],
                           diagnostics: Optional[Dict[str, Dict[str, Any]]] = None,
                           tape: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    by_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in records:
        sym = rec.get("symbol")
        if sym:
            by_symbol[str(sym)].append(rec)

    summaries: List[Dict[str, Any]] = []
    for sym, items in sorted(by_symbol.items()):
        kinds = Counter(str(x.get("kind")) for x in items)
        raw_structures = Counter(
            str(x.get("structure")) for x in items
            if x.get("kind") == "strategy_candidate" and x.get("structure")
        )
        prints = [x for x in items if x.get("kind") == "strategy_candidate"]
        cluster_eligible_prints = [x for x in prints if (x.get("cluster_eligibility") or {}).get("eligible")]
        clusters = [x for x in items if x.get("kind") == "execution_cluster"]
        orientations = [x for x in items if x.get("kind") == "orientation_thesis"]
        activities = [x for x in items if x.get("kind") == "contract_set_activity"]
        eligible_activities = [x for x in activities if x.get("directional_bias_eligible")]
        eligible_orientation_ids = {
            oid for x in eligible_activities for oid in (x.get("orientation_thesis_ids") or [])}
        eligible_orientations = [x for x in orientations if x.get("orientation_thesis_id") in eligible_orientation_ids]
        directionally_eligible_print_ids = {
            pid for x in eligible_activities for pid in (x.get("print_ids") or [])}
        directionally_eligible_prints = [x for x in prints if x.get("print_id") in directionally_eligible_print_ids]
        lifecycle = Counter(
            str((x.get("lifecycle") or {}).get("state"))
            for x in activities if (x.get("lifecycle") or {}).get("state")
        )

        BULL = ("bull_call_spread", "bull_put_spread", "synthetic_long", "bullish_risk_reversal")
        BEAR = ("bear_call_spread", "bear_put_spread", "synthetic_short", "bearish_risk_reversal")
        VOL = ("long_straddle", "short_straddle", "long_strangle", "short_strangle")

        def bucket(structure: str) -> Optional[str]:
            if structure in BULL: return "bullish"
            if structure in BEAR: return "bearish"
            if structure in VOL: return "volatility"
            return None

        thesis_counts = Counter(bucket(str(x.get("structure"))) for x in eligible_orientations)
        thesis_counts.pop(None, None)
        activity_view: Dict[str, Dict[str, float]] = {
            name: {"signed_net_premium_sum": 0.0, "premium_turnover_sum": 0.0}
            for name in ("bullish", "bearish", "volatility")}
        for orientation in eligible_orientations:
            name = bucket(str(orientation.get("structure")))
            if name:
                activity_view[name]["signed_net_premium_sum"] += float(orientation.get("signed_net_premium_sum") or 0.0)
                activity_view[name]["premium_turnover_sum"] += float(orientation.get("premium_turnover_sum") or 0.0)

        present = [name for name, count in thesis_counts.items() if count]
        if "bullish" in present and "bearish" in present:
            bias = "MIXED_DIRECTIONAL_THESIS_EVIDENCE"
        elif "bullish" in present:
            bias = "BULLISH_DIRECTIONAL_THESIS_EVIDENCE"
        elif "bearish" in present:
            bias = "BEARISH_DIRECTIONAL_THESIS_EVIDENCE"
        elif "volatility" in present:
            bias = "VOLATILITY_THESIS_EVIDENCE"
        else:
            bias = "NO_CLASSIFIED_STRUCTURE_BIAS"

        summaries.append({
            "whale_schema_version": WHALE_SCHEMA_VERSION,
            "kind": "symbol_summary",
            "analysis_date": day,
            "analysis_created_at": now_ny_iso(),
            "symbol": sym,
            "classification": "EVIDENCE_ONLY",
            "unweighted_directional_thesis_view": bias,
            "unweighted_directional_thesis_count": dict(thesis_counts),
            "modeled_net_premium_activity_by_direction": activity_view,
            "parallel_views_note": "Thesis count and modeled net-premium activity are parallel descriptive views; neither is automatically more trustworthy.",
            "direction_conflict_contract_sets_excluded": sum(1 for x in activities if x.get("direction_status") == "DIRECTION_CONFLICT"),
            "observation_counts": {
                "raw_prints": len(prints),
                "cluster_eligible_prints": len(cluster_eligible_prints),
                "directionally_eligible_prints": len(directionally_eligible_prints),
                "execution_clusters": len(clusters), "orientation_theses": len(orientations),
                "contract_set_activities": len(activities),
                "directionally_eligible_contract_sets": len(eligible_activities),
            },
            "conservative_observation_count": len(activities),
            "conservative_observation_unit": "CONTRACT_SET_ACTIVITY",
            "independence_claim": "NONE",
            "session_artifacts": (diagnostics or {}).get(sym),
            "tape_integrity": tape,
            "records_excluded_wrong_day": sum(
                1 for x in items if x.get("tape_date_mismatch") or x.get("tape_undated")),
            "record_counts": dict(kinds),
            "raw_print_structure_counts": dict(raw_structures),
            "lifecycle_counts": dict(lifecycle),
            "hard_limits": [
                "no T+1 OI confirmation in alert dataset",
                "no IV surface / event-jump valuation in alert dataset",
                "no contemporaneous NBBO stored in alert dataset",
                "institution/account identity unobservable",
            ],
            "action": "NO_TRADE_FROM_WHALE_V0_3_3",
            "paper_only": True,
        })
    return summaries


# ---------------------------------------------------------------------------
# Analysis entry point
# ---------------------------------------------------------------------------


def analyze(day: str, alerts_path: str, out_dir: str, lookback_days: int = 5) -> List[Dict[str, Any]]:
    alerts = read_jsonl(alerts_path)
    records: List[Dict[str, Any]] = []
    for rec in alerts:
        norm = normalize_alert(day, rec)
        if norm is not None:
            records.append(norm)

    tape = check_tape_integrity(day, records)
    if day in QUARANTINED_HISTORY_DATES:
        tape["quarantined"] = True
        tape["quarantine_reason"] = QUARANTINED_HISTORY_DATES[day]
        for rec in records:
            rec["history_quarantined"] = True
    diagnostics = flag_session_artifacts(records)
    clusters = build_execution_clusters(day, records)
    print_index = {str(x["print_id"]): x for x in records if x.get("kind") == "strategy_candidate"}
    orientations = build_orientation_theses(day, clusters, print_index)
    activities = build_contract_set_activities(day, orientations, print_index)
    prior_files = find_previous_whale_files(out_dir, day, lookback_days)
    pidx, history_audit = prior_activity_index(prior_files)
    apply_activity_lifecycle(activities, pidx, history_audit)
    records.extend(clusters)
    records.extend(orientations)
    records.extend(activities)
    records.extend(build_symbol_summaries(day, records, diagnostics, tape))
    return records


def write_records(path: str, records: Iterable[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json_dump_line(rec) + "\n")
    os.replace(tmp, path)


def _money(x: float) -> str:
    return f"${x:,.0f}"


def print_human_summary(day: str, alerts_path: str, records: Sequence[Dict[str, Any]], output: Optional[str]) -> None:
    """Terminal view.

    v0.3 computed the link bands, the notional-weighted bias and the session
    artifacts, then printed none of them - so a downgraded day looked identical
    to an undowngraded one and the count-based bias (the weaker metric) was the
    only thing on screen. Everything that can withdraw a claim is now visible.
    """
    candidates = [x for x in records if x.get("kind") == "strategy_candidate"]
    summaries = [x for x in records if x.get("kind") == "symbol_summary"]
    evidence = [x for x in records if x.get("kind") not in {"strategy_candidate", "symbol_summary"}]

    print(f"Whale v{ENGINE_VERSION}  {day}")
    print(f"input:  {alerts_path}")
    print(f"strategy candidates: {len(candidates)} | other evidence: {len(evidence)}")

    tape = next((s.get("tape_integrity") for s in summaries if s.get("tape_integrity")), None) or {}
    if tape.get("legacy_schema") or tape.get("stale_dated") or tape.get("undated"):
        print("\nTAPE INTEGRITY")
        if tape.get("legacy_schema"):
            print(f"    {tape['legacy_schema']} record(s) from a legacy tape "
                  f"(no schema_version) - written by different code")
        if tape.get("stale_dated"):
            detail = ", ".join(f"{d}: {n}" for d, n in tape["stale_date_counts"].items())
            print(f"    {tape['stale_dated']} record(s) dated other than {day}  ({detail})")
        if tape.get("undated"):
            print(f"    {tape['undated']} record(s) with no usable market time")
        print("    -> excluded from every weighted reading below; raw counts left as-is")
    if tape.get("quarantined"):
        print(f"\nHISTORY QUARANTINE\n    {day}: {tape.get('quarantine_reason')} — excluded from clustering and lifecycle history")

    bands = Counter(str(x.get("link_confidence_band")) for x in candidates)
    if bands:
        order = ["MODERATE", "WEAK_TO_MODERATE", "WEAK", "NONE"]
        shown = [f"{b} {bands[b]}" for b in order if bands.get(b)]
        shown += [f"{b} {c}" for b, c in bands.items() if b not in order]
        print("link bands: " + "  ".join(shown))

    for s in summaries:
        counts = s.get("observation_counts") or {}
        thesis = s.get("unweighted_directional_thesis_count") or {}
        activity = s.get("modeled_net_premium_activity_by_direction") or {}
        art = s.get("session_artifacts") or {}

        print(f"\n  {s['symbol']}")
        print(f"    hierarchy    raw prints {counts.get('raw_prints', 0)} · cluster-eligible {counts.get('cluster_eligible_prints', 0)} · "
              f"directionally eligible {counts.get('directionally_eligible_prints', 0)} · "
              f"clusters {counts.get('execution_clusters', 0)} · orientations {counts.get('orientation_theses', 0)} · "
              f"contract sets {counts.get('contract_set_activities', 0)}")
        print(f"    thesis count {dict(thesis)}   {s.get('unweighted_directional_thesis_view')}")
        pieces = []
        for name in ("bullish", "bearish", "volatility"):
            values = activity.get(name) or {}
            if values.get("premium_turnover_sum"):
                pieces.append(f"{name} signed {_money(values.get('signed_net_premium_sum', 0))} / turnover {_money(values.get('premium_turnover_sum', 0))}")
        print("    premium      " + (" · ".join(pieces) if pieces else "no directionally eligible modeled activity"))
        conflicts = s.get("direction_conflict_contract_sets_excluded") or 0
        if conflicts:
            print(f"    excluded     {conflicts} DIRECTION_CONFLICT contract set(s) from both directional views")

        flags = []
        if art.get("fixed_clip_degeneracy"):
            flags.append(f"FIXED-CLIP {art.get('modal_lot_clip')} "
                         f"({art.get('modal_clip_share', 0):.0%} of candidates) - "
                         f"'same lot count' linkage is uninformative today")
        n_conf = len(art.get("conflicted_position_keys") or [])
        if n_conf:
            flags.append(f"{n_conf} contract set(s) seen with BOTH side assignments today")
        if flags:
            for fl in flags:
                print(f"    ARTIFACT     {fl}")

        if s.get("raw_print_structure_counts"):
            print(f"    raw prints   {s['raw_print_structure_counts']}")
        if s.get("lifecycle_counts"):
            print(f"    lifecycle    {s['lifecycle_counts']}")

    if output:
        print(f"\noutput: {output}")
    print("status: PAPER ONLY · EVIDENCE ONLY — NO_TRADE_FROM_WHALE_V0_3_3")


# ---------------------------------------------------------------------------
# Self-tests with synthetic alert.py-shaped records
# ---------------------------------------------------------------------------


def _fake_spread(legs: str, net: float = 100000.0, expiry: str = "261016", sym: str = "NVDA") -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "kind": "inferred_spread",
        "observed_at": "2026-08-26T10:00:01",
        "dedup_key": f"test|{legs}",
        "mkt_time": "2026-08-26 10:00:00",
        "symbol": sym,
        "expiry": expiry,
        "legs": legs,
        "lots": 100.0,
        "gross_notional": 500000.0,
        "net_premium": net,
        "n_legs": 2,
    }


def self_test() -> None:
    cases = [
        ("B C220 / S C245", "bull_call_spread"),
        ("S C220 / B C245", "bear_call_spread"),
        ("B P200 / S P220", "bull_put_spread"),
        ("S P200 / B P220", "bear_put_spread"),
        ("B C220 / B P220", "long_straddle"),
        ("S C220 / S P220", "short_straddle"),
        ("B P200 / B C240", "long_strangle"),
        ("S P200 / S C240", "short_strangle"),
        ("B C220 / S P220", "synthetic_long"),
        ("S C220 / B P220", "synthetic_short"),
        ("S P200 / B C240", "bullish_risk_reversal"),
        ("B P200 / S C240", "bearish_risk_reversal"),
    ]
    for legs, expected in cases:
        rec = normalize_inferred_spread("2026-08-26", _fake_spread(legs))
        assert rec["structure"] == expected, (legs, rec["structure"], expected)

    # Contract-set lifecycle behavior: matching orientation is repeated support.
    prior = {"kind": "contract_set_activity", "position_key": "NVDA|x",
             "canonical_signatures": ["x:B"], "structures": {"bull_call_spread": 1},
             "_prior_file": "whale_2026-08-25.jsonl"}
    same = {"kind": "contract_set_activity", "position_key": "NVDA|x",
            "canonical_signatures": ["x:B"], "structures": {"bull_call_spread": 1}}
    apply_activity_lifecycle([same], {"NVDA|x": [prior]}, [])
    assert same["lifecycle"]["state"] == "REPEATED_SUPPORT_T0"

    # Option-code parser.
    p = parse_option_code("US_NVDA261016C00220000")
    assert p and p.symbol == "NVDA" and p.right == "C" and abs(p.strike - 220.0) < 1e-12
    print("whale.py self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Offline Whale Strategy evidence layer for alert.py JSONL")
    p.add_argument("date", nargs="?", help="analysis date YYYY-MM-DD; default New York today")
    p.add_argument("--base", help="Jarvis_60 repo root; default directory containing whale.py")
    p.add_argument("--alerts-file", help="explicit alert JSONL path; overrides --base/date")
    p.add_argument("--output", help="explicit whale JSONL output path")
    p.add_argument("--no-write", action="store_true", help="analyze/print only; do not create output")
    p.add_argument("--dump-json", action="store_true", help="print all derived JSONL records to stdout")
    p.add_argument("--lookback-days", type=int, default=5, help="prior whale files to scan for lifecycle matching (default 5)")
    p.add_argument("--freeze-time", help="fix analysis_created_at to this value for byte-identical replay")
    p.add_argument("--self-test", action="store_true", help="run built-in synthetic tests and exit")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0

    if args.freeze_time:
        set_run_time(args.freeze_time)

    base = os.path.abspath(args.base or os.path.dirname(os.path.abspath(__file__)))
    if args.alerts_file:
        alerts_path = os.path.abspath(args.alerts_file)
        m = DATE_FROM_ALERT_FILE_RE.search(os.path.basename(alerts_path))
        file_day = m.group(1) if m else None
        if args.date is None and file_day:
            day = file_day                      # trust the filename over "today"
        else:
            day = parse_day(args.date)
            if file_day and file_day != day:
                print(f"error: --alerts-file is dated {file_day} but analysis date is {day}; "
                      f"mislabelling every record. Pass the matching date or omit it.",
                      file=sys.stderr)
                return 2
    else:
        day = parse_day(args.date)
        alerts_path = os.path.join(base, "data", "alerts", f"alerts_{day}.jsonl")
    out_dir = os.path.join(base, "data", "whale")
    output = os.path.abspath(args.output) if args.output else os.path.join(out_dir, f"whale_{day}.jsonl")

    if not os.path.exists(alerts_path):
        print(f"error: alert input not found: {alerts_path}", file=sys.stderr)
        return 2

    try:
        records = analyze(day, alerts_path, out_dir, lookback_days=args.lookback_days)
        digest = sha256_file(alerts_path)
        for rec in records:
            rec["source_file"] = os.path.basename(alerts_path)
            rec["source_file_sha256"] = digest
    except Exception as exc:
        print(f"error: analysis failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not args.no_write:
        write_records(output, records)
    print_human_summary(day, alerts_path, records, None if args.no_write else output)

    if args.dump_json:
        for rec in records:
            print(json_dump_line(rec))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # piping into head/less closes stdout early; that is not an error
        try:
            sys.stdout.close()
        except Exception:
            pass
        os._exit(0)
