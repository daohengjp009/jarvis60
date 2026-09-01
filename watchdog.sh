#!/bin/bash
# watchdog.sh — 由獨立 launchd job 觸發，喺 j 退出之後查三個 collector 仲喺唔喺度。
# 唔喺就寫 log 兼發 Telegram。
# 只喺平日 14:10–20:55 UK 之間先運作，其餘時間靜靜地退出。

cd "$(dirname "$0")" || exit 1
[ -f .env ] && { set -a; . ./.env; set +a; }

# --- 只喺交易時段運作 ---
DOW=$(date +%u)
[ "$DOW" -gt 5 ] && exit 0

H=$(date +%H); M=$(date +%M)
T=$((10#$H * 60 + 10#$M))
[ "$T" -lt 850 ]  && exit 0   # 14:10 之前
[ "$T" -ge 1255 ] && exit 0   # 20:55 之後

# --- 查三個 process ---
mkdir -p logs
LOG="logs/watchdog_$(date +%F).log"

MISSING=""
for name in alert collect intraday; do
  pgrep -f " ${name}\.py" >/dev/null 2>&1 || MISSING="${MISSING} ${name}.py"
done

if [ -z "$MISSING" ]; then
  echo "$(date '+%F %H:%M:%S') OK" >> "$LOG"
  exit 0
fi

# --- 有嘢死咗 ---
echo "$(date '+%F %H:%M:%S') DOWN:${MISSING}" >> "$LOG"

MSG="jarvis60 WATCHDOG $(date '+%H:%M') — 唔見咗:${MISSING}"

if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
  curl -s -m 10 -X POST \
    "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    --data-urlencode text="${MSG}" > /dev/null
else
  echo "$(date '+%F %H:%M:%S') ERROR: TELEGRAM_TOKEN / TELEGRAM_CHAT_ID 未設定，發唔到通知" >> "$LOG"
fi

exit 1
