import json
import inspect
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
import pattern_library as P

def row(day="2026-08-25", kind="inferred_spread", **extra):
    base={"schema_version":2,"kind":kind,"mkt_time":"2026-08-25 10:00:00.123","symbol":"TSLA","expiry":"260904","legs":"B C350 / S C360","lots":99,"gross_notional":100000,"strategy_type":"MULTI_LEG"}
    base.update(extra); return base

def test_identical_input_ids_and_ordering(tmp_path):
    p=tmp_path/"alerts_2026-08-25.jsonl"; p.write_text(json.dumps(row())+"\n"+json.dumps(row(mkt_time="2026-08-25 10:01:00.123"))+"\n")
    a=P.build([p],tmp_path/"a"); b=P.build([p],tmp_path/"b")
    assert a==b
    assert (tmp_path/"a/candidates.jsonl").read_bytes()==(tmp_path/"b/candidates.jsonl").read_bytes()

def test_canonicalization_traceability_and_reconciliation(tmp_path):
    p=tmp_path/"alerts_2026-08-25.jsonl"; p.write_text(json.dumps(row())+"\n{"+"\"kind\":\"_meta\",\"event\":\"drift\"}"+"\n")
    s=P.build([p],tmp_path/"out")
    raws=[json.loads(x) for x in (tmp_path/"out/raw_rows.jsonl").read_text().splitlines()]
    assert len(raws)==2 and s["raw_rows"]==2 and s["candidate_count"]==1
    c=json.loads((tmp_path/"out/candidates.jsonl").read_text())
    m=json.loads((tmp_path/"out/candidate_raw_map.jsonl").read_text())
    assert c["raw_row_ids"]==[m["raw_row_id"]] and raws[0]["raw_row_id"]==m["raw_row_id"]

def test_permutation_known_and_near_match_unknown():
    legs=[{"side":"BUY","option_type":"CALL","strike":350.0,"expiry":"260904","quantity":99},{"side":"SELL","option_type":"CALL","strike":360.0,"expiry":"260904","quantity":99}]
    assert P.classify(legs)[0]=="KNOWN_PATTERN"
    assert P.classify(list(reversed(legs)))[0]=="KNOWN_PATTERN"
    bad=[dict(x) for x in legs]; bad[1]["expiry"]="260911"
    assert P.classify(bad)[0]=="UNKNOWN"

def test_missing_side_no_orientation_and_linkage_is_not_parent_order():
    legs=[{"side":None,"option_type":"CALL","strike":350.0,"expiry":"260904","quantity":99},{"side":"SELL","option_type":"CALL","strike":360.0,"expiry":"260904","quantity":99}]
    assert P.classify(legs)[0]=="AMBIGUOUS"
    a=P.candidate(P.canonical(Path("alerts_2026-08-25.jsonl"),1,row(legs="B C350 / S C360")))
    b=P.candidate(P.canonical(Path("alerts_2026-08-25.jsonl"),2,row(legs="B C370 / S C380")))
    links=P.same_execution([a,b])
    assert links and links[0]["parent_order_confirmed"] is False
    assert links[0]["timestamp_is_proof"] is False

def test_98_99_and_timestamp_do_not_confirm_family_or_parent():
    a=P.candidate(P.canonical(Path("alerts_2026-08-25.jsonl"),1,row(kind="own",contract="US.TSLA260904C350000",time="2026-08-25 10:00:00",dir="BUY",lots=99)))
    b=P.candidate(P.canonical(Path("alerts_2026-08-25.jsonl"),2,row(kind="own",contract="US.TSLA260904C360000",time="2026-08-25 10:01:00",dir="SELL",lots=99)))
    fs=P.families([a,b]); assert fs and fs[0]["parent_order_confirmed"] is False
    assert "98_99_LOT_EVIDENCE" in fs[0]["evidence"]

def test_vendor_disagreement_is_visible_and_quarantine_excluded(tmp_path):
    p=tmp_path/"alerts_2026-08-24.jsonl"; p.write_text(json.dumps(row(strategy_type="SINGLE_LEG"))+"\n")
    s=P.build([p],tmp_path/"out")
    assert s["quarantined_candidate_count"]==1 and s["eligible_candidate_count"]==0
    assert s["quarantine_excluded_from_recurrence"] is True
    # A non-quarantined vendor-labelled inferred vertical is disagreement if the label is wrong.
    c=P.candidate(P.canonical(Path("alerts_2026-08-25.jsonl"),1,row(strategy_type="SINGLE_LEG")))
    assert P.vendor_summary([c])["DISAGREEMENT"]==1

def test_all_candidate_mappings_and_no_silent_drop(tmp_path):
    p=tmp_path/"alerts_2026-08-25.jsonl"; p.write_text("\n".join(json.dumps(x) for x in [row(),row(kind="own",contract="BAD",time="2026-08-25 10:02:00",dir="BUY",lots=1)])+"\n")
    s=P.build([p],tmp_path/"out")
    assert s["no_raw_rows_dropped"] is True
    maps=(tmp_path/"out/candidate_raw_map.jsonl").read_text().splitlines()
    assert len(maps)==s["candidate_count"]==1

if __name__ == "__main__":
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        if "tmp_path" in inspect.signature(test).parameters:
            with tempfile.TemporaryDirectory() as d: test(Path(d))
        else:
            test()
    print(f"test_pattern_library.py: PASS ({len(tests)} tests)")
