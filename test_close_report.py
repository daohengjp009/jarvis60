import json, tempfile
from pathlib import Path
import close_report

def main():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"alerts.jsonl"
        rows=[{"schema_version":2,"kind":"_meta","event":"collector_started"},
              {"schema_version":2,"kind":"own","notional":1},
              {"schema_version":2,"kind":"_meta","event":"heartbeat"},
              {"schema_version":2,"kind":"futu","price":1},
              {"schema_version":2,"kind":"_meta","event":"collector_stopped"}]
        p.write_text("\n".join(json.dumps(x) for x in rows)+"\n")
        assert close_report.count_alerts(str(p)) == 2
    print("test_close_report.py: PASS (meta rows excluded)")

if __name__ == "__main__": main()
