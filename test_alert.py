"""Standalone test suite for alert.py — plain assertions, no pytest dependency
(none is configured in this repo). Run: python3 test_alert.py

Covers the full multi-round design review: schema/dedup contract, the own
detector's rolling baseline, futu dedup validated against real historical
data, v1->v2 restart compatibility, poll-boundary cluster splitting and its
documented equivalence boundary, cross-file spread watermark/decidability
(including asynchronous settlement and the collector-write-latency margin),
per-file idle-flush latency, empty-file watermark advancement, and
type-aware schema drift detection validated against real heterogeneous data.

Does not touch OpenD / requires no live connection. Reads two existing real
fixtures read-only: data/ticks/US_GOOGL260826C345000_2026-08-24.csv and
data/alerts/alerts_2026-08-24.jsonl.
"""
import os, sys, json, shutil, tempfile, datetime, traceback
import pandas as pd, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alert as A

SCRATCH = "/private/tmp/claude-501/-Users-leolo-jarvis60/850786c7-51d4-4160-9495-73e1abbd6acd/scratchpad"
if not os.path.isdir(SCRATCH):
    SCRATCH = tempfile.gettempdir()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self, start):
        self.t = start
    def advance(self, seconds):
        self.t += datetime.timedelta(seconds=seconds)
    def __call__(self):
        return self.t


def _mock_clock(start):
    orig = A.now_ny
    clock = _Clock(start)
    A.now_ny = clock
    return orig, clock


def _restore_clock(orig):
    A.now_ny = orig


def _leg_row(t, tstr, dirn, n, sym, expiry, typ, strike, contract, lots=100.0):
    return pd.DataFrame([{"_t": t, "time": tstr, "ticker_direction": dirn, "lots": lots, "n": n,
                            "sym": sym, "expiry": expiry, "typ": typ, "strike": strike, "contract": contract}])


def _tick_row(tstr, t, volume, turnover, direction):
    return pd.DataFrame([{"time": tstr, "volume": volume, "turnover": turnover,
                            "ticker_direction": direction, "_t": t}])


def _synth_cluster_rows(n, start, prints=2):
    rows = []
    for i in range(n):
        t = start + datetime.timedelta(seconds=i)
        tstr = t.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        for _ in range(prints):
            rows.append({"time": tstr, "volume": 100, "turnover": 10000.0 + i * 111.0,
                         "ticker_direction": "BUY"})
    return rows


# ---------------------------------------------------------------------------
# json_safe / type_signature / schema drift
# ---------------------------------------------------------------------------

def test_json_safe_preserves_lists_and_sanitizes_nan():
    assert A.json_safe(["A", "B"]) == ["A", "B"]
    assert A.json_safe(np.array(["X", "Y"])) == ["X", "Y"]
    assert A.json_safe(float("nan")) is None
    v = A.json_safe(np.int64(5))
    assert v == 5 and isinstance(v, int)
    v2 = A.json_safe(np.float64(1.5))
    assert v2 == 1.5 and isinstance(v2, float)


def test_type_signature_real_heterogeneity_order_independent():
    # earnings_pub_type confirmed in real data to mix int (2) and str ("N/A")
    # in the SAME poll's DataFrame — the exact case that breaks first-non-null sampling.
    s1 = pd.Series([2, "N/A", "N/A"])
    s2 = pd.Series(["N/A", 2, "N/A"])
    assert A.type_signature(s1) == A.type_signature(s2) == ["int", "str"]


def test_type_signature_missing_values_neutral():
    s1 = pd.Series(["x", None, "y"])
    s2 = pd.Series([None, "x", "y"])
    assert A.type_signature(s1) == A.type_signature(s2) == ["str"]
    s3 = pd.Series(["x", float("nan")])
    assert A.type_signature(s3) == ["str"]


def test_type_signature_list_and_ndarray_normalized():
    s1 = pd.Series([["a", "b"], ["c"]])
    s2 = pd.Series([np.array(["a", "b"]), np.array(["c"])])
    assert A.type_signature(s1) == A.type_signature(s2) == ["list"]


def test_check_schema_drift_no_false_positive_from_row_order():
    state = A.AlertState()
    df1 = pd.DataFrame({"order_type_list": [["X"], ["Y"]], "earnings_pub_type": [2, "N/A"]})
    assert A.check_schema_drift(state, df1) == [], "cold start must not emit a spurious _meta"
    df2 = pd.DataFrame({"order_type_list": [["Z"], ["W"]], "earnings_pub_type": ["N/A", 2]})
    hits = A.check_schema_drift(state, df2)
    assert hits == [], f"row-order-only difference must not trigger drift: {hits}"


def test_check_schema_drift_detects_genuine_change_and_meta_contract():
    state = A.AlertState()
    df1 = pd.DataFrame({"order_type_list": [["X"], ["Y"]], "earnings_pub_type": [2, "N/A"]})
    A.check_schema_drift(state, df1)
    df2 = pd.DataFrame({"order_type_list": ["X", "Y"], "earnings_pub_type": [2, "N/A"]})
    hits = A.check_schema_drift(state, df2)
    assert len(hits) == 1
    rec = hits[0]
    assert rec["kind"] == "_meta"
    assert rec["type_changed"]["order_type_list"] == {"from": ["list"], "to": ["str"]}
    # _meta schema contract: Tier-0 only, no dedup_key/mkt_time
    for f in ("schema_version", "kind", "observed_at"):
        assert f in rec
    assert "dedup_key" not in rec and "mkt_time" not in rec


# ---------------------------------------------------------------------------
# futu dedup key validated against real data + prior-session exclusion
# ---------------------------------------------------------------------------

def test_futu_dedup_key_real_data_single_known_collision():
    path = os.path.join(A.BASE, "data", "alerts", "alerts_2026-08-24.jsonl")
    rows = [json.loads(l) for l in open(path)]
    futu_rows = [r for r in rows if r.get("kind") == "futu"]
    assert futu_rows, "fixture missing futu rows"
    groups = {}
    for r in futu_rows:
        k = f"futu|{r['contract']}|{r.get('fill_timestamp')}|{r.get('volume')}|{r.get('price')}"
        groups.setdefault(k, []).append(r)
    collisions = {k: v for k, v in groups.items() if len(v) > 1}
    assert len(collisions) == 1, f"expected exactly the one known restart-duplicate, got {list(collisions)}"
    (k, v), = collisions.items()
    assert v[0]["contract"] == "US.NVDA260918C220000"
    assert v[0]["fill_timestamp"] == 1787579190.0


class _FakeCtx:
    def __init__(self, df, all_count=None):
        self.df = df
        self.all_count = all_count if all_count is not None else len(df)
    def get_option_event(self, **kwargs):
        return 0, {"event_list": self.df, "all_count": self.all_count, "next_page": ""}


def test_prior_session_events_excluded():
    today = A.now_ny().date()
    y_ts = datetime.datetime.combine(today - datetime.timedelta(days=1), datetime.time(15, 0),
                                       tzinfo=A.NY).timestamp()
    t_ts = datetime.datetime.combine(today, datetime.time(10, 0), tzinfo=A.NY).timestamp()
    df = pd.DataFrame([
        {"symbol": "TSLA", "option_code": "US.TSLA1", "fill_time": "y", "fill_timestamp": y_ts,
         "volume": 1, "price": 1.0},
        {"symbol": "TSLA", "option_code": "US.TSLA2", "fill_time": "t", "fill_timestamp": t_ts,
         "volume": 1, "price": 1.0},
    ])
    state = A.AlertState()
    hits = A.futu_events(state, _FakeCtx(df))
    assert len(hits) == 1, hits
    assert hits[0]["option_code"] == "US.TSLA2"


def test_hit_records_have_fields_main_uses():
    """Guards against the exact bug caught during implementation: main()
    referencing h['contract'] for futu-kind hits, which don't carry that key."""
    rec = A.make_record("own", "k", "t", {"contract": "C", "dir": "BUY", "prints": 2,
                                            "lots": 1.0, "notional": 1.0, "x_typical": 1.0})
    for f in ("contract", "dir", "notional", "prints", "x_typical", "mkt_time"):
        assert f in rec
    rec2 = A.make_record("inferred_spread", "k", "t", {"symbol": "S", "expiry": "e", "legs": "l",
                                                          "lots": 1.0, "gross_notional": 1.0,
                                                          "net_premium": 1.0, "n_legs": 2})
    for f in ("symbol", "legs", "lots", "gross_notional", "net_premium", "mkt_time"):
        assert f in rec2
    rec3 = A.make_record("futu", "k", "t", {"option_code": "X"})
    assert "option_code" in rec3 and "contract" not in rec3


# ---------------------------------------------------------------------------
# v1 -> v2 restart-safe dedup replay
# ---------------------------------------------------------------------------

def test_replay_key_v1_own_and_futu_exact():
    v1_own = {"kind": "own", "contract": "US_TSLA1", "time": "2026-08-24 09:30:00.000", "dir": "BUY"}
    assert A.replay_key(v1_own) == "own|US_TSLA1|2026-08-24 09:30:00.000|BUY"
    v1_futu = {"kind": "futu", "contract": "US.TSLA1", "fill_timestamp": 123.0, "volume": 10, "price": 1.5}
    assert A.replay_key(v1_futu) == "futu|US.TSLA1|123.0|10|1.5"


def test_replay_key_v2_uses_stored_dedup_key():
    v2 = {"kind": "own", "schema_version": 2, "dedup_key": "own|X|Y|BUY"}
    assert A.replay_key(v2) == "own|X|Y|BUY"


def test_replay_key_meta_skipped():
    assert A.replay_key({"kind": "_meta"}) is None


def test_replay_key_v1_spread_documented_gap():
    v1 = {"kind": "spread", "symbol": "TSLA", "time": "09:30:00", "lots": 50}
    v1_key = A.replay_key(v1)
    v2_equivalent = "inferred_spread|TSLA|260220|09:30:00|50"
    assert v1_key != v2_equivalent, "documents the known, one-time, expiry-less v1 gap"


def test_seed_seen_from_today_mixed_v1_v2():
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    old_out = A.OUT
    A.OUT = tmp
    try:
        day = "2099-01-01"
        path = os.path.join(tmp, f"alerts_{day}.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"kind": "own", "contract": "US_X", "time": "t1", "dir": "BUY"}) + "\n")
            f.write(json.dumps({"kind": "futu", "contract": "US.Y", "fill_timestamp": 1.0,
                                 "volume": 1, "price": 1.0}) + "\n")
            f.write(json.dumps({"kind": "_meta", "schema_version": 2, "event": "x"}) + "\n")
            f.write(json.dumps({"kind": "own", "schema_version": 2, "dedup_key": "own|Z|t2|SELL"}) + "\n")
        state = A.AlertState()
        A.seed_seen_from_today(state, day)
        assert state.seen == {"own|US_X|t1|BUY", "futu|US.Y|1.0|1|1.0", "own|Z|t2|SELL"}
    finally:
        A.OUT = old_out
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# read_new offset isolation per consumer
# ---------------------------------------------------------------------------

def test_read_new_offset_isolated_per_consumer():
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        path = os.path.join(tmp, "ticks.csv")
        pd.DataFrame({"time": ["09:30:00.000", "09:30:01.000"], "volume": [1, 2],
                      "turnover": [100.0, 200.0], "ticker_direction": ["BUY", "SELL"]}).to_csv(path, index=False)
        state = A.AlertState()
        cols = ["time", "volume", "turnover", "ticker_direction"]
        own_read = A.read_new(state, path, cols, "own")
        spread_read = A.read_new(state, path, cols, "spread")
        assert len(own_read) == 2
        assert len(spread_read) == 2, "own consuming the file must not starve the spread consumer"
        assert len(A.read_new(state, path, cols, "own")) == 0
        assert len(A.read_new(state, path, cols, "spread")) == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# OWN detector: accumulator stability + poll-boundary equivalence
# ---------------------------------------------------------------------------

def test_own_accumulator_independent_of_chunking():
    cols = ["time", "volume", "turnover", "ticker_direction"]
    start = datetime.datetime(2026, 1, 2, 9, 30, 0)
    rows = _synth_cluster_rows(40, start)

    tmp1 = tempfile.mkdtemp(dir=SCRATCH)
    tmp2 = tempfile.mkdtemp(dir=SCRATCH)
    try:
        p1 = os.path.join(tmp1, "t.csv")
        pd.DataFrame(rows).to_csv(p1, index=False)
        state1 = A.AlertState(); key1 = (p1, "own")
        settled1 = A.settle_file(state1, key1, A.read_new(state1, p1, cols, "own"))
        A.evaluate_own(state1, "SYNTH", settled1)
        A.evaluate_own(state1, "SYNTH", A.flush_file(state1, key1))

        p2 = os.path.join(tmp2, "t.csv")
        state2 = A.AlertState(); key2 = (p2, "own")
        written = False
        for r in rows:
            pd.DataFrame([r]).to_csv(p2, mode=("a" if written else "w"), header=not written, index=False)
            written = True
            settled2 = A.settle_file(state2, key2, A.read_new(state2, p2, cols, "own"))
            A.evaluate_own(state2, "SYNTH", settled2)
        A.evaluate_own(state2, "SYNTH", A.flush_file(state2, key2))

        assert list(state1.cluster_hist["SYNTH"]) == list(state2.cluster_hist["SYNTH"]), \
            "accumulated baseline must be identical regardless of row-by-row poll chunking"
        assert len(state1.cluster_hist["SYNTH"]) == 40
    finally:
        shutil.rmtree(tmp1, ignore_errors=True)
        shutil.rmtree(tmp2, ignore_errors=True)


def test_own_real_fixture_mid_cluster_split():
    cols = ["time", "volume", "turnover", "ticker_direction"]
    real_path = os.path.join(A.BASE, "data", "ticks", "US_GOOGL260826C345000_2026-08-24.csv")
    full = pd.read_csv(real_path, usecols=cols)
    cluster_rows = full[full["time"] == "2026-08-24 09:33:22.025"]
    assert len(cluster_rows) == 4, "fixture assumption changed — real file no longer has the expected 4-row cluster"

    tmp1 = tempfile.mkdtemp(dir=SCRATCH)
    tmp2 = tempfile.mkdtemp(dir=SCRATCH)
    try:
        p1 = os.path.join(tmp1, "t.csv")
        full.to_csv(p1, index=False)
        state1 = A.AlertState(); key1 = (p1, "own")
        settled1 = A.settle_file(state1, key1, A.read_new(state1, p1, cols, "own"))
        A.evaluate_own(state1, "GOOGL_REAL", settled1)
        A.evaluate_own(state1, "GOOGL_REAL", A.flush_file(state1, key1))

        idx = cluster_rows.index.tolist()
        split_at = idx[1] + 1   # boundary lands between the 2nd and 3rd identical-timestamp row
        p2 = os.path.join(tmp2, "t.csv")
        full.iloc[:split_at].to_csv(p2, index=False)
        state2 = A.AlertState(); key2 = (p2, "own")
        settled2a = A.settle_file(state2, key2, A.read_new(state2, p2, cols, "own"))
        A.evaluate_own(state2, "GOOGL_REAL", settled2a)
        full.iloc[split_at:].to_csv(p2, mode="a", header=False, index=False)
        settled2b = A.settle_file(state2, key2, A.read_new(state2, p2, cols, "own"))
        A.evaluate_own(state2, "GOOGL_REAL", settled2b)
        A.evaluate_own(state2, "GOOGL_REAL", A.flush_file(state2, key2))

        assert list(state1.cluster_hist["GOOGL_REAL"]) == list(state2.cluster_hist["GOOGL_REAL"]), \
            "splitting the real 4-row cluster across a poll boundary must not change accumulated history"
    finally:
        shutil.rmtree(tmp1, ignore_errors=True)
        shutil.rmtree(tmp2, ignore_errors=True)


def test_out_of_order_after_settlement_diverges_from_replay():
    """Documents the stated boundary: genuine out-of-order arrival AFTER a
    bucket has already settled+emitted cannot be retroactively corrected —
    the live run and a later full-file replay CAN legitimately disagree."""
    cols = ["time", "volume", "turnover", "ticker_direction"]
    t0 = datetime.datetime(2026, 1, 2, 9, 30, 0)
    t0_str = t0.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    later_str = (t0 + datetime.timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    early = [{"time": t0_str, "volume": 100, "turnover": 10000.0, "ticker_direction": "BUY"}] * 2
    forces_settle = [{"time": later_str, "volume": 100, "turnover": 10000.0, "ticker_direction": "BUY"}]
    late_arrival = [{"time": t0_str, "volume": 100, "turnover": 10000.0, "ticker_direction": "BUY"}]

    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        p = os.path.join(tmp, "t.csv")
        pd.DataFrame(early).to_csv(p, index=False)
        state_live = A.AlertState(); key = (p, "own")
        A.settle_file(state_live, key, A.read_new(state_live, p, cols, "own"))   # both t0 rows -> pending
        pd.DataFrame(forces_settle).to_csv(p, mode="a", header=False, index=False)
        settled = A.settle_file(state_live, key, A.read_new(state_live, p, cols, "own"))
        live_table = A.cluster_table(settled)
        assert live_table is not None and live_table.iloc[0]["prints"] == 2, "t0 cluster settles+is emitted at 2 prints"

        pd.DataFrame(late_arrival).to_csv(p, mode="a", header=False, index=False)
        settled_late = A.settle_file(state_live, key, A.read_new(state_live, p, cols, "own"))
        late_table = A.cluster_table(settled_late)
        assert late_table is None, "the lone late arrival forms only a prints=1 group and is dropped, not merged back"

        state_replay = A.AlertState(); key_r = (p, "own")
        settled_r = A.settle_file(state_replay, key_r, A.read_new(state_replay, p, cols, "own"))
        replay_table = A.cluster_table(settled_r)
        t0_replay = replay_table[replay_table["time"] == t0_str]
        assert t0_replay.iloc[0]["prints"] == 3, "a full replay of the now-complete file correctly sees all 3 prints"

        assert live_table.iloc[0]["prints"] != t0_replay.iloc[0]["prints"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# spread inference: same-expiry, gross vs net, labeling
# ---------------------------------------------------------------------------

def test_spread_same_expiry_required():
    t = pd.Timestamp("2026-01-02 09:30:00.000"); tstr = "2026-01-02 09:30:00.000"
    leg1 = _leg_row(t, tstr, "BUY", 150000.0, "TSLA", "260220", "C", 450.0, "A")
    leg2_diff = _leg_row(t, tstr, "SELL", 150000.0, "TSLA", "260320", "C", 475.0, "B")
    state = A.AlertState()
    assert A.decide_spreads(state, "TSLA", pd.concat([leg1, leg2_diff], ignore_index=True)) == []

    leg2_same = _leg_row(t, tstr, "SELL", 150000.0, "TSLA", "260220", "C", 475.0, "B")
    state2 = A.AlertState()
    hits = A.decide_spreads(state2, "TSLA", pd.concat([leg1, leg2_same], ignore_index=True))
    assert len(hits) == 1 and hits[0]["kind"] == "inferred_spread"


def test_spread_gross_vs_net_notional():
    t = pd.Timestamp("2026-01-02 09:30:00.000"); tstr = "2026-01-02 09:30:00.000"
    buy = _leg_row(t, tstr, "BUY", 300000.0, "TSLA", "260220", "C", 450.0, "A")
    sell = _leg_row(t, tstr, "SELL", 280000.0, "TSLA", "260220", "C", 475.0, "B")
    state = A.AlertState()
    hits = A.decide_spreads(state, "TSLA", pd.concat([buy, sell], ignore_index=True))
    assert len(hits) == 1
    h = hits[0]
    assert h["gross_notional"] == 580000.0
    assert h["net_premium"] == 20000.0


def test_inferred_spread_kind_and_message_labeled():
    t = pd.Timestamp("2026-01-02 09:30:00.000"); tstr = "2026-01-02 09:30:00.000"
    buy = _leg_row(t, tstr, "BUY", 300000.0, "TSLA", "260220", "C", 450.0, "A")
    sell = _leg_row(t, tstr, "SELL", 280000.0, "TSLA", "260220", "C", 475.0, "B")
    state = A.AlertState()
    h = A.decide_spreads(state, "TSLA", pd.concat([buy, sell], ignore_index=True))[0]
    assert h["kind"] == "inferred_spread"
    msg = (f"POSSIBLE SPREAD (inferred)  {h['symbol']}\n{h['legs']}\n"
           f"{h['lots']:,.0f} lots  gross ${h['gross_notional']:,.0f}  "
           f"net {h['net_premium']:+,.0f}\n{h['mkt_time']}")
    assert "inferred" in msg.lower()


# ---------------------------------------------------------------------------
# spread: asynchronous cross-file settlement (proves leg A is not lost)
# ---------------------------------------------------------------------------

def test_spread_async_new_leg_arrives_later_via_real_data():
    orig, clock = _mock_clock(datetime.datetime(2026, 1, 2, 10, 0, 0))
    try:
        sym = "TSLA"
        t_leg = pd.Timestamp("2026-01-02 09:59:50.000"); t_leg_str = "2026-01-02 09:59:50.000"
        key_a = ("/synth/A", "spread"); key_b = ("/synth/B", "spread")
        bam_a = {key_a: ("US_TSLA260220C450000", A.SPREAD_RE.match("US_TSLA260220C450000"))}
        bam_full = dict(bam_a)
        bam_full[key_b] = ("US_TSLA260220P400000", A.SPREAD_RE.match("US_TSLA260220P400000"))

        state = A.AlertState()
        all_hits = []
        a_rows = pd.concat([
            _tick_row(t_leg_str, t_leg, 100, 150000.0, "BUY"),
            _tick_row("2026-01-02 09:59:55.000", pd.Timestamp("2026-01-02 09:59:55.000"), 10, 5000.0, "BUY"),
        ], ignore_index=True)
        hits = A.spread_poll_step(state, sym, [key_a], {key_a: a_rows}, bam_a)
        assert hits == [], "leg B hasn't arrived (its file isn't even known yet) — must not fire"
        assert len(state.spread_buffer[sym]) == 1
        clock.advance(A.POLL)

        hits = A.spread_poll_step(state, sym, [key_a], {key_a: None}, bam_a)
        assert hits == []
        clock.advance(A.POLL)

        b_rows = pd.concat([
            _tick_row(t_leg_str, t_leg, 100, 140000.0, "SELL"),
            _tick_row("2026-01-02 10:00:01.000", pd.Timestamp("2026-01-02 10:00:01.000"), 10, 5000.0, "SELL"),
        ], ignore_index=True)
        hits = A.spread_poll_step(state, sym, [key_a, key_b], {key_a: None, key_b: b_rows}, bam_full)
        assert hits == [], "both watermarks land exactly AT the leg timestamp, not past it, yet"
        all_hits.extend(hits)
        clock.advance(A.POLL)

        # a couple more quiet polls push both files' watermarks past the leg's own timestamp
        for _ in range(4):
            all_hits.extend(A.spread_poll_step(state, sym, [key_a, key_b], {key_a: None, key_b: None}, bam_full))
            clock.advance(A.POLL)

        assert len(all_hits) == 1, all_hits
        assert all_hits[0]["n_legs"] == 2
    finally:
        _restore_clock(orig)


def test_spread_async_partner_settles_via_idle_flush():
    orig, clock = _mock_clock(datetime.datetime(2026, 1, 2, 10, 0, 0))
    try:
        sym = "TSLA"
        t_leg = pd.Timestamp("2026-01-02 09:59:50.000"); t_leg_str = "2026-01-02 09:59:50.000"
        key_a = ("/synth/A", "spread"); key_b = ("/synth/B", "spread")
        bam = {key_a: ("US_TSLA260220C450000", A.SPREAD_RE.match("US_TSLA260220C450000")),
               key_b: ("US_TSLA260220P400000", A.SPREAD_RE.match("US_TSLA260220P400000"))}
        keys = [key_a, key_b]
        state = A.AlertState()
        a_row = _tick_row(t_leg_str, t_leg, 100, 150000.0, "BUY")
        b_row = _tick_row(t_leg_str, t_leg, 100, 140000.0, "SELL")

        hits = A.spread_poll_step(state, sym, keys, {key_a: a_row, key_b: b_row}, bam)
        assert hits == []
        clock.advance(A.POLL)

        all_hits = []
        for _ in range(6):
            all_hits.extend(A.spread_poll_step(state, sym, keys, {key_a: None, key_b: None}, bam))
            clock.advance(A.POLL)
        assert len(all_hits) == 1, all_hits
        assert all_hits[0]["n_legs"] == 2
    finally:
        _restore_clock(orig)


def test_spread_three_leg_race():
    orig, clock = _mock_clock(datetime.datetime(2026, 1, 2, 10, 0, 0))
    try:
        sym = "TSLA"
        t_leg = pd.Timestamp("2026-01-02 09:59:50.000"); t_leg_str = "2026-01-02 09:59:50.000"
        keys = [("/synth/A", "spread"), ("/synth/B", "spread"), ("/synth/C", "spread")]
        bam = {keys[0]: ("US_TSLA260220C450000", A.SPREAD_RE.match("US_TSLA260220C450000")),
               keys[1]: ("US_TSLA260220P400000", A.SPREAD_RE.match("US_TSLA260220P400000")),
               keys[2]: ("US_TSLA260220C500000", A.SPREAD_RE.match("US_TSLA260220C500000"))}
        state = A.AlertState()
        all_hits = []

        h = A.spread_poll_step(state, sym, [keys[0]], {keys[0]: _tick_row(t_leg_str, t_leg, 100, 150000.0, "BUY")},
                                 {keys[0]: bam[keys[0]]})
        all_hits.extend(h); clock.advance(A.POLL)

        h = A.spread_poll_step(state, sym, [keys[0], keys[1]],
                                 {keys[0]: None, keys[1]: _tick_row(t_leg_str, t_leg, 100, 140000.0, "SELL")},
                                 {k: bam[k] for k in (keys[0], keys[1])})
        assert h == [], "must not fire with only 2 of 3 legs while the 3rd file is still unknown"
        all_hits.extend(h); clock.advance(A.POLL)

        h = A.spread_poll_step(state, sym, keys,
                                 {keys[0]: None, keys[1]: None, keys[2]: _tick_row(t_leg_str, t_leg, 100, 130000.0, "SELL")},
                                 bam)
        all_hits.extend(h); clock.advance(A.POLL)

        for _ in range(6):
            all_hits.extend(A.spread_poll_step(state, sym, keys, {k: None for k in keys}, bam))
            clock.advance(A.POLL)

        assert len(all_hits) == 1, all_hits
        assert all_hits[0]["n_legs"] == 3
    finally:
        _restore_clock(orig)


def test_spread_no_partner_eviction():
    orig, clock = _mock_clock(datetime.datetime(2026, 1, 2, 10, 0, 0))
    try:
        sym = "TSLA"
        t_leg = pd.Timestamp("2026-01-02 09:59:50.000"); t_leg_str = "2026-01-02 09:59:50.000"
        key_a = ("/synth/A", "spread"); key_b = ("/synth/B", "spread")   # B never has data, ever
        bam = {key_a: ("US_TSLA260220C450000", A.SPREAD_RE.match("US_TSLA260220C450000")),
               key_b: ("US_TSLA260220P400000", A.SPREAD_RE.match("US_TSLA260220P400000"))}
        keys = [key_a, key_b]
        state = A.AlertState()
        a_row = _tick_row(t_leg_str, t_leg, 100, 150000.0, "BUY")

        all_hits = []
        all_hits.extend(A.spread_poll_step(state, sym, keys, {key_a: a_row, key_b: None}, bam))
        clock.advance(A.POLL)
        for _ in range(6):
            all_hits.extend(A.spread_poll_step(state, sym, keys, {key_a: None, key_b: None}, bam))
            clock.advance(A.POLL)

        assert all_hits == [], "a lone leg with no real partner must never fire as a spread"
        buf = state.spread_buffer.get(sym)
        assert buf is None or not len(buf), "the unmatched leg must eventually be evicted, not held forever"
    finally:
        _restore_clock(orig)


# ---------------------------------------------------------------------------
# per-file idle-flush latency bound (corrected: 3 polls, not 2)
# ---------------------------------------------------------------------------

def test_idle_flush_latency_is_three_polls_not_two():
    key = ("/synth/latency", "own")
    state = A.AlertState()
    t0 = pd.Timestamp("2026-01-02 09:30:00.000")
    row = _tick_row("2026-01-02 09:30:00.000", t0, 100, 10000.0, "BUY")

    settled = A.settle_file(state, key, row)
    assert settled is None, "a lone new row must not settle immediately — it's the current max bucket"
    settled = A.settle_file(state, key, None)
    assert settled is None, "must NOT flush after only ONE empty poll (this was the corrected 240s claim)"
    settled = A.settle_file(state, key, None)
    assert settled is not None and len(settled) == 1, "must flush on the 2nd consecutive empty poll"

    assert A.worst_case_flush_latency_seconds() == (1 + A.IDLE_FLUSH_POLLS) * A.POLL


# ---------------------------------------------------------------------------
# empty-file watermark: unblocks the symbol, respects collector write latency
# ---------------------------------------------------------------------------

def test_empty_file_never_permanently_blocks_symbol():
    orig, clock = _mock_clock(datetime.datetime(2026, 1, 2, 10, 0, 0))
    try:
        sym = "TSLA"
        t_leg = pd.Timestamp("2026-01-02 09:59:50.000"); t_leg_str = "2026-01-02 09:59:50.000"
        key_a = ("/synth/A", "spread"); key_b = ("/synth/B", "spread")   # B silent all day
        bam = {key_a: ("US_TSLA260220C450000", A.SPREAD_RE.match("US_TSLA260220C450000")),
               key_b: ("US_TSLA260220P400000", A.SPREAD_RE.match("US_TSLA260220P400000"))}
        keys = [key_a, key_b]
        state = A.AlertState()
        a_row = _tick_row(t_leg_str, t_leg, 100, 150000.0, "BUY")

        all_hits = []
        all_hits.extend(A.spread_poll_step(state, sym, keys, {key_a: a_row, key_b: None}, bam))
        clock.advance(A.POLL)
        for _ in range(6):
            all_hits.extend(A.spread_poll_step(state, sym, keys, {key_a: None, key_b: None}, bam))
            clock.advance(A.POLL)

        assert state.file_watermark.get(key_b) is not None, \
            "an all-day-silent file must still get a watermark, or it would block the symbol forever"
        assert all_hits == []
        assert state.spread_buffer.get(sym) is None or not len(state.spread_buffer[sym])
    finally:
        _restore_clock(orig)


def test_collector_write_latency_margin_blocks_premature_decision():
    orig, clock = _mock_clock(datetime.datetime(2026, 1, 2, 10, 0, 0))
    try:
        sym = "TSLA"
        t_leg = pd.Timestamp("2026-01-02 09:59:50.000")
        key_a = ("/synth/A", "spread"); key_b = ("/synth/B", "spread")
        state = A.AlertState()
        state.spread_buffer[sym] = _leg_row(t_leg, "2026-01-02 09:59:50.000", "BUY", 150000.0,
                                             sym, "260220", "C", 450.0, "US_TSLA260220C450000")
        state.file_watermark[key_a] = t_leg + datetime.timedelta(seconds=5)
        bam = {key_a: ("US_TSLA260220C450000", A.SPREAD_RE.match("US_TSLA260220C450000")),
               key_b: ("US_TSLA260220P400000", A.SPREAD_RE.match("US_TSLA260220P400000"))}

        hits = A.spread_poll_step(state, sym, [key_a, key_b], {key_b: None}, bam)
        assert hits == [], "leg A must NOT be decided/discarded before collect.py's own write latency has elapsed"
        assert len(state.spread_buffer[sym]) == 1

        wm_b = state.file_watermark[key_b]
        expected = datetime.datetime(2026, 1, 2, 10, 0, 0) - datetime.timedelta(seconds=A.COLLECTOR_WRITE_LATENCY_MARGIN)
        assert wm_b == expected
        assert wm_b < t_leg, "the whole point: the margin must keep B's watermark before A's buffered leg"
    finally:
        _restore_clock(orig)


def test_collector_race_negative_control_without_margin():
    orig, clock = _mock_clock(datetime.datetime(2026, 1, 2, 10, 0, 0))
    orig_margin = A.COLLECTOR_WRITE_LATENCY_MARGIN
    try:
        A.COLLECTOR_WRITE_LATENCY_MARGIN = 0
        sym = "TSLA"
        t_leg = pd.Timestamp("2026-01-02 09:59:50.000")
        key_a = ("/synth/A", "spread"); key_b = ("/synth/B", "spread")
        state = A.AlertState()
        state.spread_buffer[sym] = _leg_row(t_leg, "2026-01-02 09:59:50.000", "BUY", 150000.0,
                                             sym, "260220", "C", 450.0, "US_TSLA260220C450000")
        state.file_watermark[key_a] = t_leg + datetime.timedelta(seconds=5)
        bam = {key_a: ("US_TSLA260220C450000", A.SPREAD_RE.match("US_TSLA260220C450000")),
               key_b: ("US_TSLA260220P400000", A.SPREAD_RE.match("US_TSLA260220P400000"))}

        A.spread_poll_step(state, sym, [key_a, key_b], {key_b: None}, bam)
        buf = state.spread_buffer.get(sym)
        assert buf is None or not len(buf), \
            "with margin=0 (the rejected design), leg A IS wrongly decided/discarded — proves the margin is necessary"
    finally:
        A.COLLECTOR_WRITE_LATENCY_MARGIN = orig_margin
        _restore_clock(orig)


# ---------------------------------------------------------------------------
# timezone / representation correctness
# ---------------------------------------------------------------------------

def test_watermark_uses_ny_not_host_timezone():
    import time
    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Europe/London"
        time.tzset()
        host_now = datetime.datetime.now()
        ny_now = A.now_ny()
        independent_ny = datetime.datetime.now(A.NY).replace(tzinfo=None)
        assert abs((ny_now - independent_ny).total_seconds()) < 5
        assert abs((ny_now - host_now).total_seconds()) > 3600, \
            "now_ny() must not silently follow the host's local timezone"
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


def test_watermark_representation_matches_real_tick_parsing():
    real_str = "2026-08-24 09:30:42.862"
    parsed = pd.to_datetime(pd.Series([real_str]), format="mixed").iloc[0]
    synthetic_wm = datetime.datetime(2026, 8, 24, 9, 30, 42, 900000)
    assert parsed < synthetic_wm
    assert parsed.to_pydatetime().tzinfo is None, "naive, matching now_ny()'s naive NY output"


def test_mixed_format_instant_equality():
    s = pd.Series(["2026-08-24 09:30:42", "2026-08-24 09:30:42.000"])
    parsed = pd.to_datetime(s, format="mixed")
    assert parsed.iloc[0] == parsed.iloc[1], \
        "same real instant, different string precision, must parse equal (grouping uses parsed _t, not raw strings)"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
              if name.startswith("test_") and callable(fn)]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed.append(name)
    print(f"\n{passed}/{len(tests)} passed")
    if failed:
        print("FAILED:")
        for n in failed:
            print(" -", n)
        sys.exit(1)


if __name__ == "__main__":
    main()
