"""Synthetic heartbeat tests; the consumer test reads the frozen 2026-08-28 tape read-only."""
import inspect, json, os, shutil, tempfile, sys, types
from pathlib import Path
# alert.py's heartbeat and log functions do not need Futu. Keep this suite
# genuinely offline and avoid SDK logger initialization during import.
futu_stub=types.ModuleType("futu")
futu_stub.OpenQuoteContext=object
futu_stub.SysConfig=object
futu_stub.OptionMarket=types.SimpleNamespace(US_SECURITY=1)
futu_stub.OptionEventFilter=object
futu_stub.EventIndicatorType=types.SimpleNamespace(OWNER_LIST=1)
sys.modules["futu"]=futu_stub
import alert as A
import alertpipe

def read_rows(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]

def test_30_minute_quiet_loop():
    with tempfile.TemporaryDirectory() as d:
        old=A.OUT; A.OUT=d
        try:
            started=1000.0; next_h=started+A.HEARTBEAT_INTERVAL; emitted=[]
            for now in range(60, 1801, 60):
                if A.heartbeat_due(started+now, next_h):
                    emitted.append(A.heartbeat_record(started, now//60, 0, None,
                                                      now_monotonic=started+now,
                                                      observed_at=f"2026-09-01T14:{now//60:02d}:00", pid=1))
                    while next_h <= started+now: next_h += A.HEARTBEAT_INTERVAL
            A.log(A.collector_started("2026-09-01T14:15:00",1,3))
            for x in emitted: A.log(x)
            rows=read_rows(Path(d)/"alerts_2026-09-01.jsonl")
            assert sum(x["event"]=="collector_started" for x in rows)==1
            assert sum(x["event"]=="heartbeat" for x in rows)==6
            assert [x["uptime_s"] for x in rows if x["event"]=="heartbeat"]==[300,600,900,1200,1500,1800]
            assert all(x["alerts_today"]==0 for x in rows if x["event"]=="heartbeat")
        finally: A.OUT=old

def test_heartbeat_due_arithmetic():
    started=1000.0; next_h=started+300; emitted=[]
    for now in list(range(60, 241, 60))+list(range(361, 601, 60)):
        if A.heartbeat_due(started+now,next_h):
            emitted.append(now)
            while next_h<=started+now: next_h+=300
    assert emitted==[361] and 300 not in emitted

def test_crash_guard_source_shape():
    source = inspect.getsource(A.main)
    assert "stop_reason = None" in source
    assert "if stop_reason is not None:" in source

def test_started_record_identifies_source():
    record = A.collector_started("2026-09-01T14:15:00", 1, 3)
    base_sha = record["git_sha"].removesuffix("-dirty")
    assert len(base_sha) == 7 and all(c in "0123456789abcdef" for c in base_sha)
    assert len(record["source_sha256"]) == 64

def test_notify_failure_is_nonfatal():
    import urllib.request
    old_token, old_chat = A.TOKEN, A.CHAT
    old_urlopen = urllib.request.urlopen
    try:
        A.TOKEN, A.CHAT = "test-token", "test-chat"
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic notify failure")
        urllib.request.urlopen = fail
        A.notify("synthetic")
    finally:
        urllib.request.urlopen = old_urlopen
        A.TOKEN, A.CHAT = old_token, old_chat

def test_stop_is_last_and_flushed():
    with tempfile.TemporaryDirectory() as d:
        old=A.OUT; A.OUT=d
        try:
            A.log(A.collector_started("2026-09-01T14:15:00",1,3))
            A.log(A.collector_stopped(0,2,4,"SIGTERM",now_monotonic=23400,observed_at="2026-09-01T20:45:00",pid=1))
            rows=read_rows(Path(d)/"alerts_2026-09-01.jsonl")
            assert rows[-1]["event"]=="collector_stopped" and rows[-1]["reason"]=="SIGTERM"
            assert rows[-1]["alerts_today"]==4
        finally: A.OUT=old

def test_alert_and_heartbeat_share_tape():
    with tempfile.TemporaryDirectory() as d:
        old=A.OUT; A.OUT=d
        try:
            A.log(A.collector_started("2026-09-01T14:15:00",1,3))
            A.log({"schema_version":2,"kind":"own","event_time":"x","notional":1})
            A.log(A.heartbeat_record(0,5,1,None,now_monotonic=300,observed_at="2026-09-01T14:20:00",pid=1))
            rows=read_rows(Path(d)/"alerts_2026-09-01.jsonl")
            assert len(rows)==3 and sum(x.get("kind")!="_meta" for x in rows)==1
            assert A.alerts_today_count()==1 and rows[-1]["alerts_today"]==1
        finally: A.OUT=old

def test_consumer_ignores_inserted_meta():
    source=Path("data/alerts/alerts_2026-08-28.jsonl")
    with tempfile.TemporaryDirectory() as d:
        original=Path(d)/"orig"/"alerts_2026-08-28.jsonl"; augmented=Path(d)/"aug"/"alerts_2026-08-28.jsonl"
        original.parent.mkdir(); augmented.parent.mkdir()
        shutil.copyfile(source, original)
        original_rows=original.read_text().splitlines()
        metas=[json.dumps({"schema_version":2,"kind":"_meta","event":"heartbeat","observed_at":f"2026-08-28T10:{i:02d}:00"}) for i in range(10)]
        augmented.write_text("\n".join(metas+original_rows)+"\n")
        base=alertpipe.run([str(original)]); with_meta=alertpipe.run([str(augmented)])
        assert base[1:4]==with_meta[1:4]
        for k in base[0]:
            if k not in {"rows_in","meta_alerts","meta_alerts_actionable"}:
                assert base[0][k]==with_meta[0][k]
        assert with_meta[0]["rows_in"]==base[0]["rows_in"]+10
        assert len(with_meta[4])==len(base[4])+10

if __name__=="__main__":
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:t()
    print(f"test_alert_heartbeat.py: PASS ({len(tests)} synthetic/consumer tests)")
