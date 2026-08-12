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
  *)
    echo "Usage: ./j start [TICKERS] | stop | status | log | screen TICKER | check | snap"
    ;;
esac
