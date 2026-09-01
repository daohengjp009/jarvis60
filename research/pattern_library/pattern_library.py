#!/usr/bin/env python3
"""Pattern Library v1: isolated, deterministic, PAPER-ONLY research builder."""
import argparse, csv, datetime as dt, hashlib, json, re, statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUARANTINED_DATES = {"2026-08-24": "EXPLICITLY_QUARANTINED_TRANSITION_TAPE"}
CONTRACT = re.compile(r"^US[._]?(?P<symbol>[A-Z]+)(?P<expiry>\d{6})(?P<right>[CP])(?P<strike>\d+)$")
LEG = re.compile(r"(?P<side>[BS])\s+(?P<right>[CP])\s*(?P<strike>\d+(?:\.\d+)?)")

def stable(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()[:24]

def num(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError): return None

def event_time(r): return r.get("mkt_time") or r.get("fill_time") or r.get("time") or None
def date_of(path, r):
    m = re.search(r"alerts_(\d{4}-\d{2}-\d{2})", str(path))
    return (m.group(1) if m else None) or (event_time(r) or "")[:10] or None
def precision(t):
    if not t: return "MISSING"
    if "." in t: return "MILLISECOND_OR_FINER"
    return "SECOND"

def contract_fields(code):
    m = CONTRACT.match(str(code or ""))
    if not m: return {}
    return {"symbol": m["symbol"], "expiry": m["expiry"], "option_type": "CALL" if m["right"] == "C" else "PUT", "strike": float(m["strike"]) / 1000}

def parse_legs(r):
    if r.get("kind") in ("inferred_spread", "spread"):
        out=[]
        for x in LEG.finditer(str(r.get("legs") or "")):
            out.append({"side": "BUY" if x["side"] == "B" else "SELL", "option_type": "CALL" if x["right"] == "C" else "PUT", "strike": float(x["strike"]), "expiry": r.get("expiry")})
        return out
    f = contract_fields(r.get("option_code") or r.get("contract"))
    if not f: return []
    side = r.get("dir") or r.get("ticker_type")
    return [{**f, "side": side if side in ("BUY", "SELL") else None}]

def canonical(path, line_no, r):
    day=date_of(path,r); code=r.get("option_code") or r.get("contract")
    cf=contract_fields(code); legs=parse_legs(r)
    payload=json.loads(json.dumps(r, sort_keys=True))
    raw_id=stable({"source_file":str(path),"source_line":line_no,"payload":payload})
    underlying=num(r.get("underlying_price"))
    return {"source_file":str(path),"trading_date":day,"source_line":line_no,"raw_row_id":raw_id,
      "sequence_id":r.get("sequence_id") or r.get("sequence"),"symbol":r.get("symbol") or cf.get("symbol"),
      "event_time":event_time(r),"event_time_precision":precision(event_time(r)),"option_code":code,
      "option_type":r.get("option_type") or cf.get("option_type"),"expiry":r.get("expiry") or cf.get("expiry"),
      "strike":num(r.get("strike_price")) if r.get("strike_price") is not None else cf.get("strike"),
      "observed_side":r.get("dir") or r.get("ticker_type"),"raw_quantity":num(r.get("lots") if r.get("lots") is not None else r.get("volume")),
      "price":num(r.get("price")),"turnover":num(r.get("turnover") or r.get("notional")),"net_premium":num(r.get("net_premium")),
      "bid_price":num(r.get("bid_price")),"ask_price":num(r.get("ask_price")),"quote_context":{k:r.get(k) for k in ("bid_price","ask_price","iv","delta","otm") if k in r},
      "trade_conditions":r.get("trade_conditions"),"underlying_price":underlying,"underlying_price_source":r.get("underlying_price_source"),
      "moneyness":None,"vendor_strategy_evidence":r.get("strategy_type"),"source_schema_version":r.get("schema_version",1),"source_kind":r.get("kind"),"raw_payload":payload,
      "parsed_legs":legs,"quarantined":day in QUARANTINED_DATES,"quarantine_reason":QUARANTINED_DATES.get(day),
      "source_quality":"QUARANTINED" if day in QUARANTINED_DATES else ("META" if r.get("kind")=="_meta" else "OBSERVED")}

def rel(values):
    if not values: return "UNKNOWN"
    return "SAME" if len(set(values))==1 else "MIXED"

def classify(legs):
    reasons=[]; evidence=[]; contradictions=[]
    if len(legs)!=2: return "UNKNOWN",None,evidence,["LEG_COUNT_NOT_TWO"]
    types=[x.get("option_type") for x in legs]; exps=[x.get("expiry") for x in legs]; strikes=[x.get("strike") for x in legs]; sides=[x.get("side") for x in legs]; qty=[x.get("quantity") for x in legs]
    if None in exps or None in strikes: return "AMBIGUOUS",None,evidence,["MISSING_EXPIRY_OR_STRIKE"]
    if len(set(exps))!=1: return "UNKNOWN",None,evidence,["DIFFERENT_EXPIRIES"]
    if len(set(strikes))!=2: return "UNKNOWN",None,evidence,["STRIKES_NOT_DISTINCT"]
    if any(x is None for x in sides): return "AMBIGUOUS",None,evidence,["MISSING_SIDE_EVIDENCE"]
    if None in qty or qty[0] != qty[1]: return "AMBIGUOUS",None,evidence,["QUANTITY_NOT_EQUAL_OR_MISSING"]
    if set(sides)!={"BUY","SELL"}: return "AMBIGUOUS",None,evidence,["SIDES_NOT_OPPOSITE"]
    if types[0]!=types[1] or types[0] not in ("CALL","PUT"): return "UNKNOWN",None,evidence,["OPTION_TYPES_NOT_HOMOGENEOUS"]
    lo,hi=sorted(legs,key=lambda x:x["strike"]); buylo=lo["side"]=="BUY"
    pat="CALL_VERTICAL" if types[0]=="CALL" else "PUT_VERTICAL"
    if types[0]=="CALL": direction="BULLISH" if buylo else "BEARISH"
    else: direction="BULLISH" if hi["side"]=="SELL" else "BEARISH"
    evidence=["TWO_LEGS","SAME_EXPIRY","DISTINCT_STRIKES", "HOMOGENEOUS_OPTION_TYPE","OPPOSITE_SIDES","EQUAL_QUANTITY"]
    return "KNOWN_PATTERN", {"pattern_id":pat,"pattern_version":"1","directional_interpretation":direction}, evidence, contradictions

def fingerprint(legs):
    if not legs: return stable({"legs":0})
    sig=[]
    for x in sorted(legs,key=lambda y:(y.get("option_type") or "",y.get("strike") or 0,y.get("expiry") or "")):
        sig.append({"right":x.get("option_type"),"expiry":x.get("expiry"),"strike":x.get("strike"),"side":x.get("side"),"quantity":x.get("quantity")})
    return stable({"leg_count":len(legs),"legs":sig})

def candidate(raw):
    legs=[]
    for x in raw["parsed_legs"]:
        y=dict(x); y["quantity"]=raw["raw_quantity"] if raw["source_kind"]!="inferred_spread" else raw["raw_quantity"]; legs.append(y)
    status, match, evidence, contradictions=classify(legs)
    if raw["source_kind"]=="inferred_spread" and status=="KNOWN_PATTERN": evidence.append("PRODUCTION_INFERRED_SPREAD_SOURCE")
    cid=stable({"raw_row_ids":[raw["raw_row_id"]],"legs":legs})
    return {"candidate_id":cid,"raw_row_ids":[raw["raw_row_id"]],"source_file":raw["source_file"],"source_line":raw["source_line"],"trading_date":raw["trading_date"],"symbol":raw["symbol"],"event_time":raw["event_time"],"legs":legs,"leg_count":len(legs),"vendor_strategy_evidence":raw["vendor_strategy_evidence"],"match_status":"AMBIGUOUS" if raw["quarantined"] else status,"matched_pattern":match,"match_evidence":evidence,"contradictions":contradictions,"structural_fingerprint":fingerprint(legs),"quarantined":raw["quarantined"],"quarantine_reason":raw["quarantine_reason"],"review_status":"UNREVIEWED","review_reasons":contradictions}

def parse_dt(s):
    try:return dt.datetime.fromisoformat(str(s).replace("Z","+00:00")).replace(tzinfo=None)
    except (TypeError,ValueError):return None

def same_execution(candidates):
    groups=defaultdict(list)
    for c in candidates:
        if c["quarantined"] or not c["event_time"] or not c["symbol"]: continue
        groups[(c["symbol"],c["event_time"])].append(c)
    out=[]
    for key, rows in sorted(groups.items()):
        if len(rows)<2: continue
        for i,a in enumerate(rows):
            for b in rows[i+1:]:
                ev=["SAME_SYMBOL","EXACT_TIMESTAMP"]; contra=[]
                if a.get("vendor_strategy_evidence") and b.get("vendor_strategy_evidence"): ev.append("VENDOR_EVIDENCE_PRESENT")
                out.append({"link_id":stable({"stage":"A","a":a["candidate_id"],"b":b["candidate_id"]}),"stage":"A_SAME_EXECUTION","candidate_ids":[a["candidate_id"],b["candidate_id"]],"status":"HYPOTHESIS_ONLY","same_execution_hypothesis":True,"evidence":ev,"contradictions":contra,"parent_order_confirmed":False,"sequence_is_proof":False,"timestamp_is_proof":False})
    return out

def compatible(a,b):
    la=a["legs"]; lb=b["legs"]
    if len(la)!=1 or len(lb)!=1 or a["symbol"]!=b["symbol"]: return False
    return la[0].get("option_type")==lb[0].get("option_type") and la[0].get("expiry")==lb[0].get("expiry")

def families(candidates):
    eligible=[c for c in candidates if not c["quarantined"] and parse_dt(c["event_time"])]
    out=[]
    for i,a in enumerate(eligible):
        for b in eligible[i+1:]:
            ta,tb=parse_dt(a["event_time"]),parse_dt(b["event_time"])
            if ta.date()!=tb.date() or abs((tb-ta).total_seconds())>1800 or not compatible(a,b): continue
            ev=["SAME_SYMBOL","SAME_EXPIRY","SAME_OPTION_TYPE","WITHIN_30_MINUTES"]; con=[]
            qa=a["legs"][0].get("quantity"); qb=b["legs"][0].get("quantity")
            if qa is not None and qb is not None and qa==qb: ev.append("REPEATED_QUANTITY")
            if qa in (98,99) or qb in (98,99): ev.append("98_99_LOT_EVIDENCE")
            sa,sb=a["legs"][0].get("side"),b["legs"][0].get("side")
            if sa and sb and sa!=sb: ev.append("CONTROLLED_SIDE_REVERSAL")
            elif sa and sb: ev.append("SIDE_CONTINUITY")
            out.append({"link_id":stable({"stage":"B","a":a["candidate_id"],"b":b["candidate_id"]}),"stage":"B_EXECUTION_FAMILY","candidate_ids":[a["candidate_id"],b["candidate_id"]],"status":"HYPOTHESIS_ONLY","execution_family_hypothesis":True,"evidence":ev,"contradictions":con,"parent_order_confirmed":False})
    return out

def vendor_summary(candidates):
    x=Counter();
    for c in candidates:
        v=c.get("vendor_strategy_evidence"); s=c.get("matched_pattern",{}).get("pattern_id") if c.get("matched_pattern") else None
        if not v: continue
        if s and ((v=="MULTI_LEG" and s in ("CALL_VERTICAL","PUT_VERTICAL"))): k="AGREEMENT"
        elif s: k="DISAGREEMENT"
        else: k="VENDOR_ONLY_CLASSIFICATION"
        x[k]+=1
    x["STRUCTURAL_ONLY_CLASSIFICATION"]=sum(1 for c in candidates if c.get("matched_pattern") and not c.get("vendor_strategy_evidence"))
    x["UNRESOLVED_UNKNOWN_OR_AMBIGUOUS"]=sum(1 for c in candidates if c["match_status"] in ("UNKNOWN","AMBIGUOUS"))
    return dict(x)

def write_jsonl(path, rows):
    with path.open("w",encoding="utf-8") as f:
        for x in rows:f.write(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=True)+"\n")

def build(inputs, out):
    out.mkdir(parents=True,exist_ok=True); raw=[]; source_counts=Counter()
    for p in sorted(inputs):
        for line_no,line in enumerate(Path(p).read_text(encoding="utf-8").splitlines(),1):
            if not line.strip(): continue
            try:r=json.loads(line)
            except Exception as e:
                raw.append({"source_file":str(p),"source_line":line_no,"raw_row_id":stable({"source_file":str(p),"source_line":line_no,"line":line}),"source_quality":"QUARANTINED","quarantine_reason":"INVALID_JSON","raw_payload":line}); continue
            q=canonical(Path(p),line_no,r); source_counts[q["source_kind"]]+=1; raw.append(q)
    events=[x for x in raw if x.get("source_kind")!="_meta" and x.get("parsed_legs")]
    candidates=[candidate(x) for x in events]
    # Candidate mapping is intentionally one raw row to one candidate in v1.
    mapping=[{"candidate_id":c["candidate_id"],"raw_row_id":rid,"mapping_role":"SOURCE_ROW"} for c in candidates for rid in c["raw_row_ids"]]
    stage_a=same_execution(candidates); stage_b=families(candidates)
    unknown=defaultdict(list)
    for c in candidates:
        if c["match_status"]=="UNKNOWN" and not c["quarantined"]: unknown[c["structural_fingerprint"]].append(c)
    recurrence=[]
    for fp,rows in sorted(unknown.items(),key=lambda z:(-len(z[1]),z[0])):
        recurrence.append({"structural_fingerprint":fp,"recurrence_count":len(rows),"dates":sorted({r["trading_date"] for r in rows}),"symbols":sorted({r["symbol"] for r in rows}),"leg_count_distribution":dict(Counter(r["leg_count"] for r in rows)),"vendor_label_distribution":dict(Counter(r.get("vendor_strategy_evidence") or "NONE" for r in rows)),"structural_consistency":"DESCRIPTIVE_ONLY","contradictions":sorted({x for r in rows for x in r["contradictions"]}),"review_priority":{"recurrence":len(rows),"cross_date":len({r["trading_date"] for r in rows}),"cleanliness":len(rows)-sum(bool(r["contradictions"]) for r in rows)}})
    strata=[]
    for c in candidates:
        reasons=[]
        if c["quarantined"]: continue
        if any("SAME_SYMBOL" in x.get("evidence",[]) and "EXACT_TIMESTAMP" in x.get("evidence",[]) for x in stage_a if c["candidate_id"] in x["candidate_ids"]): reasons.append("COMMON_SEQUENCE_OR_TIMESTAMP_CANDIDATE")
        if c["symbol"]=="NVDA": reasons.append("DENSE_NVDA_ACTIVITY")
        if c["symbol"]=="GOOGL": reasons.append("LOWER_DENSITY_GOOGL_ACTIVITY")
        if c["vendor_strategy_evidence"] and not c["matched_pattern"]: reasons.append("VENDOR_VS_STRUCTURAL_DISAGREEMENT")
        if c["match_status"]=="UNKNOWN" and any(x["recurrence_count"]>1 for x in recurrence if x["structural_fingerprint"]==c["structural_fingerprint"]): reasons.append("RECURRING_UNKNOWN")
        if any(x.get("quantity") in (98,99) for x in c["legs"]): reasons.append("REPEATED_98_99_LOT_STRUCTURE")
        if len({x.get("expiry") for x in c["legs"]})>1: reasons.append("DIFFERENT_EXPIRY_COMBINATION")
        if reasons: strata.append({"candidate_id":c["candidate_id"],"strata":sorted(set(reasons)),"review_status":"UNREVIEWED"})
    for link in stage_b:
        reasons=[]
        if "CONTROLLED_SIDE_REVERSAL" in link["evidence"]: reasons.append("POSSIBLE_REVERSAL_OR_UNWIND")
        if "98_99_LOT_EVIDENCE" in link["evidence"]: reasons.append("REPEATED_98_99_LOT_STRUCTURE")
        if reasons: strata.append({"link_id":link["link_id"],"candidate_ids":link["candidate_ids"],"strata":reasons,"review_status":"UNREVIEWED"})
    required_strata=("COMMON_SEQUENCE_OR_TIMESTAMP_CANDIDATE","REPEATED_98_99_LOT_STRUCTURE","POSSIBLE_REVERSAL_OR_UNWIND","DIFFERENT_EXPIRY_COMBINATION","DENSE_NVDA_ACTIVITY","LOWER_DENSITY_GOOGL_ACTIVITY","VENDOR_VS_STRUCTURAL_DISAGREEMENT","RECURRING_UNKNOWN")
    known=sum(c["match_status"]=="KNOWN_PATTERN" and not c["quarantined"] for c in candidates); amb=sum(c["match_status"]=="AMBIGUOUS" and not c["quarantined"] for c in candidates); unk=sum(c["match_status"]=="UNKNOWN" and not c["quarantined"] for c in candidates)
    for name,rows in (("raw_rows.jsonl",raw),("candidates.jsonl",candidates),("candidate_raw_map.jsonl",mapping),("linkage_same_execution.jsonl",stage_a),("linkage_execution_family.jsonl",stage_b),("unknown_recurrence.jsonl",recurrence),("human_review_queue.jsonl",strata)): write_jsonl(out/name,rows)
    strata_counts=dict(Counter(s for x in strata for s in x["strata"]))
    strata_counts.update({s:strata_counts.get(s,0) for s in required_strata})
    summary={"library_version":"pattern_library_v1","paper_only":True,"inputs":[str(x) for x in sorted(inputs)],"source_counts":dict(source_counts),"raw_rows":len(raw),"event_rows":len(events),"candidate_count":len(candidates),"eligible_candidate_count":sum(not c["quarantined"] for c in candidates),"quarantined_candidate_count":sum(c["quarantined"] for c in candidates),"known_pattern_count":known,"ambiguous_count":amb,"unknown_count":unk,"same_execution_hypothesis_count":len(stage_a),"execution_family_hypothesis_count":len(stage_b),"human_review_strata_counts":strata_counts,"vendor_vs_structural":vendor_summary(candidates),"holdout_validation":"NOT_PERFORMED — insufficient dates and no repeated holdout inspection","prospective_count":0,"no_raw_rows_dropped":True,"quarantine_excluded_from_recurrence":True}
    (out/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    (out/"manifest.json").write_text(json.dumps({**summary,"builder":"pattern_library.py","input_sha256":{str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sorted(inputs)}},indent=2,sort_keys=True)+"\n")
    top=recurrence[:10]
    report=["# Pattern Library v1 summary","","Status: PAPER ONLY; descriptive structure research, not a trading signal.","","## Counts","",f"- Source lines preserved: **{len(raw)}** (event lines {len(events)}, metadata lines {source_counts.get('_meta',0)})","- Candidates: **{len(candidates)}**; eligible **{summary['eligible_candidate_count']}**; quarantined **{summary['quarantined_candidate_count']}**","- Match status: known **{known}**, ambiguous **{amb}**, UNKNOWN **{unk}**","- Same-execution hypotheses: **{len(stage_a)}**; execution-family hypotheses: **{len(stage_b)}**","", "## Vendor versus structural evidence", "", json.dumps(summary["vendor_vs_structural"], sort_keys=True),"", "Vendor `strategy_type` is retained as evidence, never treated as truth. Sequence and timestamp are evidence, not confirmed parent-order identity.","", "## Recurring UNKNOWN fingerprints", ""]
    for x in top: report.append(f"- `{x['structural_fingerprint']}`: {x['recurrence_count']} occurrences; dates={','.join(x['dates'])}; symbols={','.join(x['symbols'])}; vendors={json.dumps(x['vendor_label_distribution'],sort_keys=True)}")
    report += ["", "## Review and validation", "", f"Review queue rows: **{len(strata)}**; strata: {json.dumps(strata_counts,sort_keys=True)}", "", "24-August observations are retained for diagnostics but excluded from eligible recurrence/ranking statistics. Holdout validation was **not performed** because the current date span is too short; no predictive performance is reported.","", "## Limitations", "", "The tape lacks reliable package-order IDs, participant identity, complete sequence semantics, stock legs, and comprehensive market coverage. Inferred spreads are modeled observations. This library cannot prove parent orders, institutional intent, strategy truth, or predictive edge.",""]
    (out/"report.md").write_text("\n".join(report),encoding="utf-8")
    return summary

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--input-glob",default="data/alerts/alerts_*.jsonl"); p.add_argument("--output",default="research/pattern_library/output/v1"); a=p.parse_args(argv)
    s=build(sorted(ROOT.glob(a.input_glob)),ROOT/a.output); print(json.dumps(s,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
