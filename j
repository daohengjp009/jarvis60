#!/bin/bash
# Jarvis_60 launcher.  Usage:  ./j start TSLA NVDA  |  ./j stop  |  ./j status  |  ./j log
cd "$(dirname "$0")"
case "$1" in
  start)
    shift
    TICKERS="${@:-TSLA NVDA GOOGL}"
    if pgrep -f "collect.py" > /dev/null; then
      echo "already running (use ./j stop first)"; exit 1
    fi
    mkdir -p logs
    nohup python3 collect.py $TICKERS > "logs/collect_$(date +%F).log" 2>&1 &
    sleep 3
    echo "collector started on: $TICKERS"
    tail -5 "logs/collect_$(date +%F).log"
    ;;
  stop)
    pkill -f collect.py && echo "collector stopped" || echo "was not running"
    ;;
  status)
    if pgrep -f "collect.py" > /dev/null; then
      echo "RUNNING"
      tail -3 "logs/collect_$(date +%F).log" 2>/dev/null
      echo "ticks on disk: $(cat data/ticks/*.csv 2>/dev/null | wc -l)"
    else
      echo "not running"
    fi
    ;;
  log)    tail -f "logs/collect_$(date +%F).log" ;;
  screen) shift; python3 screen.py "${@:-TSLA}" ;;
  check)  python3 core/recheck.py ;;
  snap)   python3 snapshot.py ;;
  day)    python3 daycheck.py "$2" ;;
  fill)   for d in $(ls data/ticks/*.csv 2>/dev/null | sed -E 's/.*_([0-9]{4}-[0-9]{2}-[0-9]{2})\.csv/\1/' | sort -u); do
            for t in TSLA NVDA GOOGL; do
              [ -f "data/underlying_1m/US_${t}_${d}.csv" ] || python3 backfill_underlying.py $t $d 2>/dev/null | grep -E "saved|FAILED"
            done
          done; echo "fill done" ;;
  intra)  pgrep -f intraday.py >/dev/null && echo "intraday already running" || { nohup python3 -u intraday.py 30 > logs/intraday_$(date +%F).log 2>&1 & sleep 2; echo "intraday started"; } ;;
  nointra) pkill -f intraday.py && echo "intraday stopped" || echo "was not running" ;;
  stream) pgrep -f stream_test.py >/dev/null && echo "stream already running" || { nohup python3 -u stream_test.py "${2:-23400}" > logs/stream_$(date +%F).log 2>&1 & sleep 2; echo "stream started"; } ;;
  nostream) pkill -f stream_test.py && echo "stream stopped" || echo "was not running" ;;
  open)   echo "=== OPEN ==="; "$0" start ${@:2}; "$0" stream; "$0" intra ;;
  close)  echo "=== CLOSE ==="; "$0" stop; "$0" nointra; "$0" snap ;;
  morning) echo "=== CAPTURE ==="; "$0" cap; echo; echo "=== BACKFILL ==="; "$0" fill; echo; echo "=== SUMMARY ==="; "$0" day "$2" ;;
  cap)    python3 capture_check.py ;;
  dash)   nohup python3 dashboard.py > logs/dashboard.log 2>&1 & sleep 2; echo "dashboard: http://192.168.0.208:8060" ;;
  nodash) pkill -f dashboard.py && echo "dashboard stopped" || echo "was not running" ;;
  *)
    echo "Usage: ./j start [TICKERS] | stop | status | log | screen TICKER | check | snap | cap | dash | nodash"
    ;;
esac
