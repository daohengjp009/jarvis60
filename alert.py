"""Jarvis_60 live alerts — a durable, auditable options-intelligence tape.

Combines three independent, cheap detectors and writes every hit to
data/alerts/alerts_<date>.jsonl. An alert is NOT a prediction; its predictive
value (if any) can only be tested later against real outcomes.
Writes only to data/alerts/. Does not touch HYP-001 or HYP-002 data/logic.
Usage: python3 alert.py [poll_seconds]

DETECTORS
  own    - same-timestamp option clusters in our own tick stream, sized
           RELATIVE to that contract's own recent typical cluster.
  futu   - get_option_event, Futu's own unusual-activity list.
  inferred_spread - same-second, opposite-direction, same-lots, same-expiry
           legs on the same underlying, inferred to be one multi-leg order.

OWN DETECTOR vs HYP-001 — NOT the same thing, on purpose
  HYP-001 (hypothesis.md) is the pre-registered, frozen trigger used for the
  sealed experiment: notional >= $250k (absolute only), no time-of-day cutoff
  here vs HYP-001's exclusion of events >= 15:00 ET, no DTE filter here vs
  HYP-001's DTE>1, and no completeness/capture-rate check here (that can only
  be known the next morning via ./j cap) vs HYP-001's Layer-0-clean
  requirement. The `own` detector ADDS a relative filter (>= REL_MULT x the
  contract's own recent median cluster) that HYP-001 does not have, to cut
  live noise. NEVER use this file's `own` counts as HYP-001 event counts —
  the stopping rule and GO/KILL thresholds depend on the exact, frozen
  HYP-001 definition, not this one.

JSONL SCHEMA CONTRACT (schema_version=2)
  Mandatory on EVERY line, no exceptions:
    schema_version (int), kind ("own"|"futu"|"inferred_spread"|"_meta"),
    observed_at (ISO8601, America/New_York, when Jarvis wrote the line)
  Mandatory on EVENT lines only (kind != "_meta"):
    dedup_key (string — the exact key used to suppress duplicates, so the
      tape is self-describing and restart-safe without a separate index),
    mkt_time (the market/event time — tick time or Futu's fill_time)
  "_meta" lines carry Tier-0 fields only, plus event/added_columns/
  removed_columns/type_changed. They have no dedup_key/mkt_time — a schema
  drift note is a fact about Jarvis's own pipeline, not a market event.
  "inferred_spread" net_premium/gross_notional are MODELED quantities
  (BUY-leg turnover minus SELL-leg turnover), not a broker-confirmed combo
  ticket — Futu's tick feed carries no order/strategy linkage.

KNOWN, DOCUMENTED LIMITATIONS (not silently papered over)
  - Futu dedup key (option_code, fill_timestamp, volume, price) is a
    best-effort heuristic: the API exposes no true fill/deal ID. Validated
    against real data/alerts/alerts_2026-08-24.jsonl: it correctly recognizes
    a restart-induced re-delivery of the same fill as a duplicate, and does
    not collide across any of the 10 genuine same-second-different-contract
    event groups in that file. It would under-count in the rare case of two
    truly distinct child fills at identical price/size within the same
    second — an accepted, bounded gap (Futu exposes nothing better).
  - v1 -> v2 same-day restart: own/futu dedup keys are exactly reconstructable
    from v1-format lines. inferred_spread is NOT (v1 never captured expiry) —
    a spread already logged pre-upgrade can be re-logged once, only on the
    calendar day of the upgrade. One-time, self-limiting, documented.
  - Genuine out-of-order tick arrival AFTER a timestamp bucket has already
    settled and been emitted cannot be retroactively corrected: the already
    written hit stays as emitted; a later full-file replay of the same
    (now-complete) data can legitimately disagree with what the live process
    wrote. Continuous-run vs restart/replay equivalence holds under the
    (empirically checked) assumption that collect.py appends ticks in
    non-decreasing market-time order; it does not hold universally.
  - The empty-file watermark subtracts COLLECTOR_WRITE_LATENCY_MARGIN as a
    BEST-EFFORT assumption about collect.py's own ~30s write cadence, not a
    guaranteed bound — collect.py could in principle lag further.
"""
import os, sys, time, datetime, json, glob, re, math, hashlib, signal, subprocess
from collections import deque
from zoneinfo import ZoneInfo
import pandas as pd, numpy as np
from futu import OpenQuoteContext, SysConfig

try:
    from futu import OptionMarket, OptionEventFilter, EventIndicatorType
    HAVE_EVENT_FILTER = True
except ImportError:
    from futu import OptionMarket
    HAVE_EVENT_FILTER = False

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "alerts")
TICKS = os.path.join(BASE, "data", "ticks")
UNDER = os.path.join(BASE, "data", "underlying")
KEY = "/Users/leolo/.openclaw/futu/conn_key_1024.pem"
SCHEMA_STATE_PATH = os.path.join(OUT, ".futu_columns.json")
os.makedirs(OUT, exist_ok=True)

POLL = int(sys.argv[1]) if len(sys.argv) > 1 else 120
SYMS = ("TSLA", "NVDA", "GOOGL")
ABS_FLOOR = 250_000        # absolute minimum notional, as in HYP-001
REL_MULT = 10              # ... AND at least 10x this contract's own median cluster
MIN_HIST = 30              # clusters needed before a relative baseline is trusted
CLUSTER_HIST_MAXLEN = 500  # cap per-contract history buffer size
SPREAD_MIN_NOTIONAL = 100_000   # a real combo order, not two retail lots colliding
SPREAD_MIN_LOTS = 50            # 1-lot coincidences at the open are not footprints

IDLE_FLUSH_POLLS = 2        # consecutive empty reads before a non-empty pending tail settles
EMPTY_FILE_IDLE_POLLS = 1   # consecutive empty reads before an EMPTY file's watermark advances
COLLECTOR_POLL_SECONDS = 30 # mirrors collect.py's own POLL_SECONDS
# Best-effort assumption about collect.py's own write cadence, NOT a guaranteed
# bound (collect.py could lag further under load). 3x its own poll interval
# for headroom against unmeasured Futu-side reporting lag on top of it.
COLLECTOR_WRITE_LATENCY_MARGIN = 3 * COLLECTOR_POLL_SECONDS

SCHEMA_VERSION = 2
NY = ZoneInfo("America/New_York")
SPREAD_RE = re.compile(r"US_([A-Z]+)(\d{6})([CP])(\d+)")
UNDERLYING_MAX_AGE_SECONDS = 300
_UNDERLYING_CACHE = {}

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT = os.environ.get("TELEGRAM_CHAT_ID")
def notify(msg):
    if not (TOKEN and CHAT): return
    try:
        import urllib.request, urllib.parse
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TOKEN,
            urllib.parse.urlencode({"chat_id": CHAT, "text": msg}).encode(), timeout=10)
    except Exception as e:
        print(f"  notify failed: {e}", flush=True)

def load_env():
    p = os.path.join(BASE, ".env")
    if os.path.exists(p):
        for line in open(p):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))
load_env()
TOKEN = os.environ.get("TELEGRAM_TOKEN"); CHAT = os.environ.get("TELEGRAM_CHAT_ID")


def now_ny():
    """Tz-naive datetime in America/New_York wall-clock — the SAME comparable
    representation as parsed tick times (which carry no offset in the CSV)."""
    return datetime.datetime.now(NY).replace(tzinfo=None)


class AlertState:
    """All mutable cross-poll state, bundled so tests can run isolated
    scenarios without fighting shared module globals."""
    def __init__(self):
        self.offset = {}          # (path, consumer) -> rows already parsed
        self.pending = {}         # (path, consumer) -> DataFrame still-open tail, or None
        self.idle_count = {}      # (path, consumer) -> consecutive empty reads
        self.file_watermark = {}  # (path, consumer) -> pd.Timestamp, highest confirmed-settled time
        self.cluster_hist = {}    # contract base -> deque[float] notional, own detector accumulator
        self.spread_buffer = {}   # symbol -> DataFrame of settled, not-yet-decided leg candidates
        self.seen = set()         # dedup_key set
        self.futu_schema = {}     # column -> {"dtype":..., "types":[...]}
        self.last_api_ok = None


# ---------------------------------------------------------------------------
# Incremental file reading + watermark/settlement primitives
# ---------------------------------------------------------------------------

def read_new(state, path, cols, consumer):
    """Read only rows appended since the last poll for this (path, consumer).
    Re-reading every tick file each cycle does not scale once files reach
    tens of thousands of rows. Returns None on read failure (e.g. a race with
    collect.py creating the file), or a DataFrame (possibly empty) with an
    extra parsed "_t" column used for all watermark/grouping comparisons —
    tick "time" strings are not guaranteed to be one consistent format
    (collect.py itself parses them with format="mixed"), so raw string
    comparison/grouping is unreliable; parsed datetimes are not."""
    key = (path, consumer)
    try:
        start = state.offset.get(key, 0)
        d = pd.read_csv(path, usecols=cols, skiprows=range(1, start + 1)) if start \
            else pd.read_csv(path, usecols=cols)
        state.offset[key] = start + len(d)
    except Exception:
        return None
    d = d.reset_index(drop=True)
    if len(d):
        d["_t"] = pd.to_datetime(d["time"], format="mixed")
    return d


def _advance_watermark(state, key, t):
    cur = state.file_watermark.get(key)
    if cur is None or t > cur:
        state.file_watermark[key] = t


def settle_file(state, key, new_rows):
    """Watermark/settlement for one (path, consumer) stream.

    Defers only the rows at the current max observed timestamp (they might
    still gain siblings next poll) and settles everything strictly older.
    A confirmed-empty file (no pending tail) advances its own watermark to
    now-minus-margin after EMPTY_FILE_IDLE_POLLS empty reads, so one silent
    contract can never permanently block cross-file spread decidability for
    its symbol. A non-empty pending tail idle-flushes after IDLE_FLUSH_POLLS
    consecutive empty reads, so the last cluster of a quiet contract's day
    isn't held hostage by other, busier contracts.
    """
    wm_before = state.file_watermark.get(key)
    if new_rows is not None and len(new_rows) and wm_before is not None:
        if new_rows["_t"].min() < wm_before:
            print(f"  [warn] {key}: late/out-of-order tick(s) before already-settled "
                  f"watermark {wm_before} — may undercount an already-emitted cluster",
                  flush=True)

    if new_rows is None or not len(new_rows):
        state.idle_count[key] = state.idle_count.get(key, 0) + 1
        pending = state.pending.get(key)
        if pending is not None and len(pending):
            if state.idle_count[key] >= IDLE_FLUSH_POLLS:
                settled = pending
                state.pending[key] = None
                _advance_watermark(state, key, settled["_t"].max())
                return settled
            return None
        else:
            if state.idle_count[key] >= EMPTY_FILE_IDLE_POLLS:
                wm = now_ny() - datetime.timedelta(seconds=COLLECTOR_WRITE_LATENCY_MARGIN)
                _advance_watermark(state, key, wm)
            return None

    state.idle_count[key] = 0
    carry = state.pending.get(key)
    d = pd.concat([carry, new_rows], ignore_index=True) if carry is not None and len(carry) else new_rows
    max_t = d["_t"].max()
    settled = d[d["_t"] < max_t]
    state.pending[key] = d[d["_t"] == max_t].reset_index(drop=True)
    if len(settled):
        _advance_watermark(state, key, settled["_t"].max())
    return settled if len(settled) else None


def flush_file(state, key):
    """Force-settle whatever is pending, e.g. at shutdown."""
    pending = state.pending.get(key)
    if pending is None or not len(pending):
        return None
    state.pending[key] = None
    _advance_watermark(state, key, pending["_t"].max())
    return pending


def worst_case_flush_latency_seconds():
    return (1 + IDLE_FLUSH_POLLS) * POLL


# ---------------------------------------------------------------------------
# Shared record envelope
# ---------------------------------------------------------------------------

def make_record(kind, dedup_key, mkt_time, payload):
    rec = {"schema_version": SCHEMA_VERSION, "kind": kind,
           "observed_at": now_ny().isoformat(timespec="seconds"),
           "dedup_key": dedup_key, "mkt_time": mkt_time}
    rec.update(payload)
    return rec


def log(rec):
    global _alerts_today_count
    day = str(datetime.date.today())
    with open(os.path.join(OUT, f"alerts_{day}.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    if rec.get("kind") != "_meta":
        _alerts_today_count += 1


HEARTBEAT_INTERVAL = 300

def heartbeat_due(now_monotonic, next_heartbeat):
    return now_monotonic >= next_heartbeat

def _git_sha():
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                      cwd=BASE, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "alert.py"],
                               cwd=BASE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL).returncode != 0
        return f"{sha}-dirty" if dirty else sha
    except Exception:
        return None

def _source_sha256():
    try:
        with open(os.path.join(BASE, "alert.py"), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None

def _alerts_today(day):
    path = os.path.join(OUT, f"alerts_{day}.jsonl")
    if not os.path.exists(path):
        return 0
    n = 0
    try:
        with open(path) as f:
            for line in f:
                try:
                    if json.loads(line).get("kind") != "_meta":
                        n += 1
                except Exception:
                    continue
    except Exception:
        return n
    return n

_alerts_today_count = 0

def reset_alerts_today(day):
    global _alerts_today_count
    _alerts_today_count = _alerts_today(day)

def alerts_today_count():
    return _alerts_today_count

def collector_started(started_at, pid, symbols):
    return {"schema_version": SCHEMA_VERSION, "kind": "_meta", "event": "collector_started",
            "observed_at": started_at, "pid": pid, "git_sha": _git_sha(),
            "source_sha256": _source_sha256(), "symbols": symbols}

def heartbeat_record(started_monotonic, loops, alerts_today, last_api_ok,
                     now_monotonic=None, observed_at=None, pid=None):
    now = time.monotonic() if now_monotonic is None else now_monotonic
    return {"schema_version": SCHEMA_VERSION, "kind": "_meta", "event": "heartbeat",
            "observed_at": observed_at or now_ny().isoformat(timespec="seconds"),
            "pid": os.getpid() if pid is None else pid,
            "uptime_s": int(now - started_monotonic), "alerts_today": alerts_today,
            "loops": loops, "last_api_ok": last_api_ok}

def collector_stopped(started_monotonic, loops, alerts_today, reason,
                      now_monotonic=None, observed_at=None, pid=None):
    now = time.monotonic() if now_monotonic is None else now_monotonic
    return {"schema_version": SCHEMA_VERSION, "kind": "_meta", "event": "collector_stopped",
            "observed_at": observed_at or now_ny().isoformat(timespec="seconds"),
            "pid": os.getpid() if pid is None else pid,
            "uptime_s": int(now - started_monotonic), "alerts_today": alerts_today,
            "reason": reason}

class CollectorStop(Exception):
    def __init__(self, reason): self.reason = reason


# ---------------------------------------------------------------------------
# v1 -> v2 restart-safe dedup replay
# ---------------------------------------------------------------------------

def replay_key(rec):
    """Reconstruct the dedup key a live process would have used, for seeding
    `seen` from an already-written JSONL. own/futu are exactly reconstructable
    from v1-format lines (they already carried the needed fields, even though
    v1 didn't use them correctly). inferred_spread/v1 "spread" is NOT exactly
    reconstructable (v1 never captured expiry) — documented, one-time gap at
    the v1->v2 upgrade boundary day only."""
    kind = rec.get("kind")
    if kind == "_meta":
        return None
    if rec.get("schema_version") == SCHEMA_VERSION and "dedup_key" in rec:
        return rec["dedup_key"]
    if kind == "own":
        return f"own|{rec.get('contract')}|{rec.get('time')}|{rec.get('dir')}"
    if kind == "futu":
        return f"futu|{rec.get('contract')}|{rec.get('fill_timestamp')}|{rec.get('volume')}|{rec.get('price')}"
    if kind == "spread":
        return f"spread|{rec.get('symbol')}|{rec.get('time')}|{rec.get('lots')}"
    return None


def seed_seen_from_today(state, day):
    path = os.path.join(OUT, f"alerts_{day}.jsonl")
    if not os.path.exists(path):
        return
    n = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            k = replay_key(rec)
            if k:
                state.seen.add(k)
                n += 1
    if n:
        print(f"  seeded dedup from {os.path.basename(path)}: {n} prior alerts", flush=True)


# ---------------------------------------------------------------------------
# OWN detector — same-timestamp clusters, judged against own recent history
# ---------------------------------------------------------------------------

def cluster_table(settled):
    """Pure: group settled ticks into (timestamp, direction) cluster rows.
    No threshold/history logic — used both by evaluate_own and directly by
    tests checking settlement/grouping equivalence independent of alerting
    thresholds."""
    if settled is None or not len(settled):
        return None
    d = settled[settled["ticker_direction"].isin(["BUY", "SELL"])]
    if not len(d):
        return None
    g = (d.groupby(["_t", "ticker_direction"])
           .agg(prints=("volume", "size"), lots=("volume", "sum"), n=("turnover", "sum"),
                time=("time", "first"))
           .reset_index().sort_values("_t"))
    g = g[g["prints"] >= 2]
    return g if len(g) else None


def evaluate_own(state, base, settled):
    """Update this contract's rolling cluster-notional history and return any
    hits. History accumulates across polls/restarts (via read_new's natural
    cold-start full read), NOT recomputed per poll-slice, so the relative
    baseline is stable regardless of poll cadence."""
    hits = []
    g = cluster_table(settled)
    if g is None:
        return hits
    hist = state.cluster_hist.setdefault(base, deque(maxlen=CLUSTER_HIST_MAXLEN))
    for _, r in g.iterrows():
        med = float(np.median(hist)) if len(hist) >= MIN_HIST else None
        hist.append(float(r["n"]))          # after computing med — a cluster never inflates its own baseline
        if med is None:
            continue
        if r["n"] < ABS_FLOOR or r["n"] < REL_MULT * med:
            continue
        mkt_time = r["time"]
        dedup_key = f"own|{base}|{mkt_time}|{r['ticker_direction']}"
        if dedup_key in state.seen:
            continue
        state.seen.add(dedup_key)
        hits.append(make_record("own", dedup_key, mkt_time, {
            "contract": base, "dir": r["ticker_direction"], "prints": int(r["prints"]),
            "lots": float(r["lots"]), "notional": float(r["n"]),
            "x_typical": round(float(r["n"] / med), 1)}))
    return hits


def own_clusters(state, day):
    hits = []
    for f in sorted(glob.glob(os.path.join(TICKS, f"*_{day}.csv"))):
        base = os.path.basename(f)[:-15]
        m = re.match(r"US_([A-Z]+)", base)
        if not m or m.group(1) not in SYMS:
            continue
        key = (f, "own")
        new = read_new(state, f, ["time", "volume", "turnover", "ticker_direction"], "own")
        settled = settle_file(state, key, new)
        hits.extend(evaluate_own(state, base, settled))
    return hits


# ---------------------------------------------------------------------------
# inferred_spread — cross-file, watermark-gated decidability
# ---------------------------------------------------------------------------

def files_by_symbol(day):
    out = {}
    for f in sorted(glob.glob(os.path.join(TICKS, f"*_{day}.csv"))):
        base = os.path.basename(f)[:-15]
        m = SPREAD_RE.match(base)
        if not m or m.group(1) not in SYMS:
            continue
        out.setdefault(m.group(1), []).append((f, base, m))
    return out


def aggregate_leg_candidates(base, m, settled):
    """Collapse settled raw ticks for one contract into one row per
    (timestamp, direction) — a leg candidate for the cross-file join."""
    if settled is None or not len(settled):
        return None
    d = settled[settled["ticker_direction"].isin(["BUY", "SELL"])]
    if not len(d):
        return None
    g = (d.groupby(["_t", "ticker_direction"])
           .agg(lots=("volume", "sum"), n=("turnover", "sum"), time=("time", "first"))
           .reset_index())
    g["sym"] = m.group(1)
    g["expiry"] = m.group(2)
    g["typ"] = m.group(3)
    g["strike"] = int(m.group(4)) / 1000
    g["contract"] = base
    return g


def _underlying_rows(sym, day):
    """Load one session's historical underlying tape, never a live quote."""
    path = os.path.join(UNDER, f"US_{sym}_{day}.csv")
    if path in _UNDERLYING_CACHE:
        return _UNDERLYING_CACHE[path]
    try:
        d = pd.read_csv(path, usecols=["update_time", "last_price"])
        d["_observed"] = pd.to_datetime(d["update_time"], format="mixed", errors="coerce")
        d["_price"] = pd.to_numeric(d["last_price"], errors="coerce")
        d = d[d["_observed"].notna() & d["_price"].notna() &
              np.isfinite(d["_price"]) & (d["_price"] > 0)].copy()
        _UNDERLYING_CACHE[path] = d
        return d
    except Exception:
        _UNDERLYING_CACHE[path] = None
        return None


def event_underlying_price(sym, mkt_time):
    """Return the latest valid historical price at or before an event time."""
    empty = {"underlying_price": None, "underlying_price_source": None,
             "underlying_price_observed_at": None, "underlying_price_age_seconds": None}
    try:
        event_time = pd.Timestamp(mkt_time)
        if event_time.tzinfo is not None:
            event_time = event_time.tz_localize(None)
        day = event_time.strftime("%Y-%m-%d")
    except Exception:
        return empty
    d = _underlying_rows(str(sym).upper(), day)
    if d is None or not len(d):
        return empty
    eligible = d[d["_observed"] <= event_time]
    if not len(eligible):
        return empty
    row = eligible.iloc[-1] if eligible["_observed"].is_monotonic_increasing else \
        eligible.loc[eligible["_observed"].idxmax()]
    age = (event_time - row["_observed"]).total_seconds()
    if age < 0 or age > UNDERLYING_MAX_AGE_SECONDS:
        return empty
    observed_at = pd.Timestamp(row["_observed"]).isoformat(timespec="milliseconds")
    return {"underlying_price": float(row["_price"]),
            "underlying_price_source": f"US_{str(sym).upper()}_{day}.csv:update_time/last_price",
            "underlying_price_observed_at": observed_at,
            "underlying_price_age_seconds": float(age)}


def decide_spreads(state, sym, candidates):
    """Pure: evaluate a symbol's DECIDABLE leg-candidate rows (every relevant
    file's watermark has already passed their timestamp) for spread
    membership. Called both from the normal per-poll decidable subset and
    from the shutdown flush over whatever remains buffered."""
    hits = []
    if candidates is None or not len(candidates):
        return hits
    for (t, expiry, lots), grp in candidates.groupby(["_t", "expiry", "lots"]):
        if len(grp) < 2:
            continue
        if grp["ticker_direction"].nunique() < 2:
            continue
        if grp["contract"].nunique() < 2:
            continue
        if lots < SPREAD_MIN_LOTS:
            continue
        gross = float(grp["n"].sum())
        if gross < SPREAD_MIN_NOTIONAL:
            continue
        net = float(grp.loc[grp["ticker_direction"] == "BUY", "n"].sum()
                     - grp.loc[grp["ticker_direction"] == "SELL", "n"].sum())
        mkt_time = grp["time"].iloc[0]
        underlying = event_underlying_price(sym, mkt_time)
        dedup_key = f"inferred_spread|{sym}|{expiry}|{mkt_time}|{lots}"
        if dedup_key in state.seen:
            continue
        state.seen.add(dedup_key)
        legs = [f"{r.ticker_direction[:1]} {r.typ}{r.strike:g}" for r in grp.itertuples()]
        hits.append(make_record("inferred_spread", dedup_key, mkt_time, {
            "symbol": sym, "expiry": expiry, "legs": " / ".join(legs),
            "lots": float(lots), "gross_notional": gross, "net_premium": net,
            "n_legs": len(grp), **underlying}))
    return hits


def _append_buf(state, sym, g):
    if g is None or not len(g):
        return
    buf = state.spread_buffer.get(sym)
    state.spread_buffer[sym] = pd.concat([buf, g], ignore_index=True) if buf is not None and len(buf) else g


def spread_poll_step(state, sym, file_keys, new_rows_by_key, base_and_match_by_key):
    """One poll's worth of settlement + buffering + cross-file decidability
    for one symbol. Factored out of spreads() so tests can drive the exact
    same logic with synthetic per-poll data instead of real files — the
    production path and the test path share this one implementation, so a
    test can't silently pass against logic the real code doesn't run.

    file_keys: [(path,"spread"), ...] belonging to this symbol this poll.
    new_rows_by_key: key -> DataFrame|None, this poll's read_new() output.
    base_and_match_by_key: key -> (contract_base, regex_match).
    """
    for key in file_keys:
        settled = settle_file(state, key, new_rows_by_key.get(key))
        base, m = base_and_match_by_key[key]
        _append_buf(state, sym, aggregate_leg_candidates(base, m, settled))
    buf = state.spread_buffer.get(sym)
    if buf is None or not len(buf):
        return []
    wms = [state.file_watermark.get(k) for k in file_keys]
    if not wms or any(w is None for w in wms):
        return []   # at least one file not yet observed even once — nothing decidable
    min_wm = min(wms)
    decidable = buf[buf["_t"] < min_wm]
    state.spread_buffer[sym] = buf[buf["_t"] >= min_wm]
    return decide_spreads(state, sym, decidable)


def spreads(state, day):
    """Same second, opposite direction, identical lot size, same expiry, two
    different strikes on the same underlying = one multi-leg order, not two
    independent trades. HYP-001's same-direction rule cannot see these.
    A group is only ever decided once — once EVERY file belonging to that
    symbol has a watermark strictly past the group's timestamp — so a leg
    settling in one poll and its partner settling several polls later in a
    different file are still correctly joined."""
    hits = []
    for sym, files in files_by_symbol(day).items():
        file_keys = [(f, "spread") for f, _, _ in files]
        new_rows_by_key = {(f, "spread"): read_new(state, f, ["time", "volume", "turnover", "ticker_direction"], "spread")
                            for f, _, _ in files}
        base_and_match = {(f, "spread"): (base, m) for f, base, m in files}
        hits.extend(spread_poll_step(state, sym, file_keys, new_rows_by_key, base_and_match))
    return hits


def flush_all(state, day):
    """Force-settle every remaining pending bucket (own + spread) and force-
    decide every remaining buffered spread candidate, bypassing the watermark
    gate — safe only because nothing more will ever arrive once we're
    shutting down."""
    hits = []
    for key in list(state.pending.keys()):
        pending = flush_file(state, key)
        if pending is None or not len(pending):
            continue
        path, consumer = key
        base = os.path.basename(path)[:-15]
        if consumer == "own":
            hits.extend(evaluate_own(state, base, pending))
        elif consumer == "spread":
            m = SPREAD_RE.match(base)
            if m:
                _append_buf(state, m.group(1), aggregate_leg_candidates(base, m, pending))
    for sym, buf in list(state.spread_buffer.items()):
        if buf is None or not len(buf):
            continue
        hits.extend(decide_spreads(state, sym, buf))
        state.spread_buffer[sym] = None
    return hits


# ---------------------------------------------------------------------------
# Futu unusual-activity events
# ---------------------------------------------------------------------------

def is_missing(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def json_safe(v):
    if isinstance(v, (list, tuple, np.ndarray)):
        return [json_safe(x) for x in v]
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        v = float(v)
        return None if math.isnan(v) else v
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return str(v)   # unexpected type at an external API boundary — keep, don't silently drop


def type_signature(series):
    """Order-independent: the set of distinct non-missing Python types
    observed across the WHOLE column this poll, not one sample value.
    Confirmed necessary against real data: get_option_event's
    earnings_pub_type mixes int (2) and str ("N/A") in the SAME poll — a
    first-non-null sample would flip type between polls purely from row
    order, with zero actual schema change."""
    names = set()
    for v in series:
        if is_missing(v):
            continue
        tn = type(v).__name__
        if tn == "ndarray":
            tn = "list"   # pandas' list-materialization is not a Futu schema fact
        names.add(tn)
    return sorted(names)


def check_schema_drift(state, df):
    cur = {c: {"dtype": str(df[c].dtype), "types": type_signature(df[c])} for c in df.columns}
    prev = state.futu_schema
    if not prev:
        state.futu_schema = cur
        return []   # cold start / first observation — nothing to compare against
    added = sorted(set(cur) - set(prev))
    removed = sorted(set(prev) - set(cur))
    type_changed = {}
    for c in set(cur) & set(prev):
        if cur[c]["types"] and prev[c]["types"] and cur[c]["types"] != prev[c]["types"]:
            type_changed[c] = {"from": prev[c]["types"], "to": cur[c]["types"]}
    state.futu_schema = cur
    if not added and not removed and not type_changed:
        return []
    rec = {"schema_version": SCHEMA_VERSION, "kind": "_meta",
           "observed_at": now_ny().isoformat(timespec="seconds"),
           "event": "futu_schema_changed", "added_columns": added,
           "removed_columns": removed, "type_changed": type_changed}
    return [rec]


def load_schema_state():
    try:
        with open(SCHEMA_STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_schema_state(schema):
    try:
        with open(SCHEMA_STATE_PATH, "w") as f:
            json.dump(schema, f)
    except Exception as e:
        print(f"  [warn] could not persist schema state: {e}", flush=True)


def futu_events(state, ctx):
    kwargs = dict(option_market=OptionMarket.US_SECURITY, count=300)
    if HAVE_EVENT_FILTER:
        kwargs["filter_list"] = [OptionEventFilter(EventIndicatorType.OWNER_LIST,
                                                     security_list=[f"US.{s}" for s in SYMS])]
    try:
        r, d = ctx.get_option_event(**kwargs)
    except TypeError:
        print("  [warn] get_option_event: filter_list unsupported by this SDK/OpenD — "
              "falling back unfiltered (client-side symbol filter still applies)", flush=True)
        try:
            r, d = ctx.get_option_event(option_market=OptionMarket.US_SECURITY, count=300)
        except Exception as e:
            print(f"  option_event error: {e}", flush=True); return []
    except Exception as e:
        print(f"  option_event error: {e}", flush=True); return []
    if r != 0:
        return []
    state.last_api_ok = now_ny().isoformat(timespec="seconds")

    df = d.get("event_list") if isinstance(d, dict) else d
    all_count = d.get("all_count") if isinstance(d, dict) else None
    hits = []
    if df is None or not len(df):
        return hits
    hits.extend(check_schema_drift(state, df))
    if all_count is not None and all_count > len(df):
        print(f"  [warn] get_option_event: all_count={all_count} > fetched={len(df)} "
              f"— possible truncation this poll", flush=True)

    today_ny = now_ny().date()
    for _, row in df.iterrows():
        sym = str(row.get("symbol", ""))
        if sym not in SYMS:
            continue
        fill_ts = row.get("fill_timestamp")
        if is_missing(fill_ts):
            continue
        ev_date = datetime.datetime.fromtimestamp(float(fill_ts), tz=NY).date()
        if ev_date != today_ny:
            continue   # exclude prior-session events
        code = str(row.get("option_code", ""))
        volume, price = row.get("volume"), row.get("price")
        dedup_key = f"futu|{code}|{fill_ts}|{volume}|{price}"
        if dedup_key in state.seen:
            continue
        state.seen.add(dedup_key)
        payload = {c: json_safe(row[c]) for c in df.columns}
        mkt_time = payload.get("fill_time", "")
        hits.append(make_record("futu", dedup_key, mkt_time, payload))
    return hits


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    SysConfig.enable_proto_encrypt(True); SysConfig.set_init_rsa_file(KEY)
    ctx = OpenQuoteContext(host="127.0.0.1", port=11112)
    state = AlertState()
    day = str(datetime.date.today())
    started_monotonic = time.monotonic()
    started_at = now_ny().isoformat(timespec="seconds")
    loops = 0
    reset_alerts_today(day)
    stop_reason = None
    def request_stop(signum, _frame):
        raise CollectorStop("SIGTERM" if signum == signal.SIGTERM else "SIGINT")
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    log(collector_started(started_at, os.getpid(), len(SYMS)))
    seed_seen_from_today(state, day)
    state.futu_schema = load_schema_state()
    print(f"alerts running: own clusters >= ${ABS_FLOOR:,} AND >= {REL_MULT}x that "
          f"contract's median (own detector — NOT the HYP-001 registered trigger, "
          f"see module docstring), plus Futu option events + inferred spreads. "
          f"poll {POLL}s. worst-case idle-flush latency ~{worst_case_flush_latency_seconds()}s",
          flush=True)
    notify(f"Jarvis alerts started ({datetime.datetime.now():%H:%M})")
    next_heartbeat = started_monotonic + HEARTBEAT_INTERVAL
    try:
        while True:
            loops += 1
            day = str(datetime.date.today())
            try:
                hits = own_clusters(state, day) + spreads(state, day) + futu_events(state, ctx)
            except Exception as e:
                print(f"  [{datetime.datetime.now():%H:%M:%S}] poll error: "
                      f"{type(e).__name__}: {e}", flush=True)
                hits = []
            for h in hits:
                log(h)
                if h["kind"] == "_meta":
                    print("\n[meta] " + json.dumps(h)[:300], flush=True)
                    continue
                if h["kind"] == "inferred_spread":
                    msg = (f"POSSIBLE SPREAD (inferred)  {h['symbol']}\n{h['legs']}\n"
                           f"{h['lots']:,.0f} lots  gross ${h['gross_notional']:,.0f}  "
                           f"net {h['net_premium']:+,.0f}\n{h['mkt_time']}")
                elif h["kind"] == "own":
                    msg = (f"CLUSTER  {h['contract']}\n{h['dir']} ${h['notional']:,.0f}"
                           f"  {h['prints']} prints  {h['x_typical']}x typical\n{h['mkt_time']}")
                else:
                    extra = " ".join(f"{k}={v}" for k, v in h.items()
                                     if k not in ("kind", "option_code", "mkt_time", "schema_version",
                                                  "dedup_key", "observed_at"))[:180]
                    msg = f"FUTU EVENT  {h.get('option_code', '?')}\n{extra}"
                print("\n" + msg, flush=True)
                notify(msg)
            save_schema_state(state.futu_schema)
            print(f"  [{datetime.datetime.now():%H:%M:%S}] poll done, {len(hits)} new", flush=True)
            now_monotonic = time.monotonic()
            if heartbeat_due(now_monotonic, next_heartbeat):
                while next_heartbeat <= now_monotonic:
                    next_heartbeat += HEARTBEAT_INTERVAL
                log(heartbeat_record(started_monotonic, loops, alerts_today_count(),
                                     state.last_api_ok, now_monotonic=now_monotonic))
            time.sleep(POLL)
    except (KeyboardInterrupt, CollectorStop) as e:
        stop_reason = e.reason if isinstance(e, CollectorStop) else "SIGINT"
        print("\nstopped", flush=True)
    finally:
        for h in flush_all(state, day):
            log(h)
        if stop_reason is not None:
            log(collector_stopped(started_monotonic, loops, alerts_today_count(), stop_reason))
        ctx.close()


if __name__ == "__main__":
    main()
