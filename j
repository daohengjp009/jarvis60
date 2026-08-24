#!/bin/bash
PY="/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"   # pinned: bash -lc under launchd resolves python3 elsewhere
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
    nohup "$PY" collect.py $TICKERS > "logs/collect_$(date +%F).log" 2>&1 &
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
  screen) shift; "$PY" screen.py "${@:-TSLA}" ;;
  check)  "$PY" core/recheck.py ;;
  snap)   "$PY" snapshot.py ;;
  day)    "$PY" daycheck.py "$2" ;;
  gist)   command -v gh >/dev/null || { echo "gh not installed: brew install gh"; exit 1; }
          gh gist edit 55d0ce57a59fca26c8541cdf7b1732a6 -f features.md  < features.md &&
          gh gist edit 55d0ce57a59fca26c8541cdf7b1732a6 -f features.py  < features.py &&
          echo "gist updated" ;;
  fill)   for d in $(ls data/ticks/*.csv 2>/dev/null | sed -E 's/.*_([0-9]{4}-[0-9]{2}-[0-9]{2})\.csv/\1/' | sort -u); do
            for t in TSLA NVDA GOOGL; do
              [ -f "data/underlying_1m/US_${t}_${d}.csv" ] || "$PY" backfill_underlying.py $t $d 2>/dev/null | grep -E "saved|FAILED"
            done
          done; echo "fill done" ;;
  intra)  pgrep -f intraday.py >/dev/null && echo "intraday already running" || { nohup "$PY" -u intraday.py 30 > logs/intraday_$(date +%F).log 2>&1 & sleep 2; echo "intraday started"; } ;;
  nointra) pkill -f intraday.py && echo "intraday stopped" || echo "was not running" ;;
  stream) pgrep -f stream_test.py >/dev/null && echo "stream already running" || { nohup "$PY" -u stream_test.py "${2:-23400}" > logs/stream_$(date +%F).log 2>&1 & sleep 2; echo "stream started"; } ;;
  nostream) pkill -f stream_test.py && echo "stream stopped" || echo "was not running" ;;
  open)   echo "=== OPEN ==="; "$0" start ${@:2}; "$0" intra ;;   # stream dropped: option sub quota is 200
  close)  echo "=== CLOSE ==="; "$0" stop; "$0" nointra; pkill -f alert.py 2>/dev/null
          "$0" snap
          "$PY" close_report.py ;;
  morning) echo "=== CAPTURE ==="; "$0" cap; echo; echo "=== BACKFILL ==="; "$0" fill; echo; echo "=== SUMMARY ==="; "$0" day "$2" ;;
  cap)    "$PY" capture_check.py ;;
  dash)   nohup "$PY" dashboard.py > logs/dashboard.log 2>&1 & sleep 2; echo "dashboard: http://192.168.0.208:8060" ;;
  nodash) pkill -f dashboard.py && echo "dashboard stopped" || echo "was not running" ;;
  bot)    pgrep -f "$(pwd)/bot.py" >/dev/null && echo "bot already running" || { nohup "$PY" "$(pwd)/bot.py" > logs/bot.log 2>&1 & sleep 2; echo "bot started"; } ;;
  nobot)  pkill -f "$(pwd)/bot.py" && echo "bot stopped" || echo "was not running" ;;
  *)
    echo "Usage: ./j start [TICKERS] | stop | status | log | screen TICKER | check | snap | cap | dash | nodash | bot | nobot"
    ;;
esac
