# Phase 1 — 確認數據收集可靠

狀態：進行中
擁有人：Leo（senior PM）／Claude（PM）／Vera（verifier）／Luna（coder）／Sol（coordinator）

---

## 一句講晒

Phase 1 唯一要答嘅問題：**收集返嚟嘅數據，可唔可以信？**

唔做交易結論。唔數大戶。唔搵 pattern。只答呢一句。

---

## Batch 基準

| | 值 |
|---|---|
| T1 commit | `73ab2f4ae87d7642494080f3809a5224f3742849` |
| `alert.py` source_sha256 | `9d115afa806323c9391b5fa39efa3ea4248f0c0aab18bdec91e91376992b9abe` |
| Day 1 | **未開始**（2026-09-01 = day 0） |

---

## 2026-09-01 — Day 0（紅燈）

### 綠燈檢查結果

| 條件 | 結果 |
|---|---|
| tape 存在、有 `collector_started` | PASS |
| `source_sha256` = 基準 | PASS（兩次啟動都對） |
| 心跳覆蓋 ≥ 6 小時 | PASS（6h10m） |
| 最大心跳空窗 < 15 分鐘 | PASS（最大 6m07s） |
| `last_api_ok` 新鮮 | PASS（最大落後 2 秒） |
| 最後一條係 `collector_stopped` | PASS（16:00:03 ET，SIGTERM） |
| **全日只有一個 pid** | **FAIL**（50404、51441） |

### 事故

```
09:15:06 ET  ./j open 起 alert.py（pid 50404）
09:15:09 ET  SIGTERM，uptime 2s
09:42:18 ET  人手起返（pid 51441）
16:00:03 ET  ./j close 收工，uptime 22664s，62 條 alert
```

**市內損失 12m18s**（09:30:00–09:42:18）。停機共 27 分鐘，但 09:15–09:30 係開市前。

同時被殺嘅仲有 `collect.py`（10:12 ET 先起返）同 `intraday.py`（10:40 ET 先起返）。

推測原因（未驗證）：launchd 喺 job 結束時 SIGTERM 成個 process group，除非 plist 有 `AbandonProcessGroup=true`。

### collect.py 停機係可以救返嘅（已量度）

今日 tick 檔案最早時間戳 = `09:30:00.188` = 開市第一秒。collect.py 10:12 先起身，但訂閱時回補到開市，所以 `own` / `inferred_spread` 嘅輸入**冇缺失**。

`own` 由 8/31 嘅 15 跌到 5，係當日真係少咗合資格 cluster，唔係收集問題。

（`futu` event 會唔會同樣回補 —— **未量度，未知。**）

### Contamination 違規（Claude 自報，兩次）

1. `tail logs/alert_*.log` 吐出一張成交
2. Telegram 截圖包含多張成交同推斷結構

實際損害為零（今日係 day 0，冇計數中嘅日子受影響），但程序要喺 day 1 之前修好。

**根本原因**：`logs/alert_*.log` 同 Telegram 都會運送成交內容。

---

## 綠燈規則有窿（今日發現，必須改）

**今日紅燈係靠「一個 pid」捉到，唔係靠「空窗 < 15 分鐘」。**

第一次啟動只活咗 2 秒，**一條心跳都未寫過**。所以 09:15–09:42 嗰段喺「心跳與心跳之間」呢個量度入面根本唔存在，最大空窗計出嚟只有 6 分鐘。

如果同類事故發生喺同一個 pid 之內（例如程式內部重連），呢條規則會**畀綠燈畀一個缺咗 12 分鐘市內數據嘅日子**。

### 正確嘅量法

唔好比較心跳之間，要比較 **market window**：

```
覆蓋 = Σ (collector_started → collector_stopped) ∩ [09:30, 16:00] ET
損失 = 6h30m − 覆蓋
```

今日：覆蓋 6h17m42s，損失 **12m18s**。

**T2 `phase1_check.py` 要用呢條，唔好用原本嗰條。**

---

## 待辦（順序）

### 1. 修 launchd 殺 process group（最優先）

`./j open` = `"$0" start`（collect.py）+ `"$0" intra`（intraday.py）+ alert.py。**三個都死。**

**額外發現**：`j` 第 49–59 行嘅啟動驗證（`sleep 3` 然後 `pgrep`）**結構上唔可能捉到呢種死法** —— 殺佢哋嘅正正係 `j` 自己嘅退出，而驗證喺退出之前。修正必須包括一個由 `j` 外部、喺 `j` 退出之後執行嘅檢查。

### 2. `j` 兩個缺陷（同一次修）

- 第 13 行 collect.py 冇 idempotence guard（第 44、68 行有）→ 行兩次會有兩個 collector
- 同一行用 `>` 唔係 `>>` → 重啟會抹走當日 log

### 3. Batch 期間 Telegram 只推操作訊息，唔推成交內容

### 4. 查 `all_count=2364 > fetched=300`

可能漏咗 87% 嘅 option event。如果 8/24–8/31 都係咁，成個歷史數據集係 ~13% 樣本。

### 5. T1b — 真行為測試

Vera 證明 8 個測試入面 **5 個冇掂過 `main()`**：`test_crash_guard_source_shape`、`test_heartbeat_due_arithmetic`、`test_30_minute_quiet_loop`、`test_stop_is_last_and_flushed`、`test_alert_and_heartbeat_share_tape`。

### 6. `alertpipe.py` 未入 git（`?? alertpipe.py`）

### 7. 兩個收集層 universe 唔一致

`alert.py` 3 隻／`snapshot.py` 28 隻／`features.md` 凍結 28 隻。改 pre-registration 要申報。

---

## 每日綠燈條件

- [ ] alert tape 存在，size > 0
- [ ] 有 `collector_started`
- [ ] `source_sha256` = batch 基準值
- [ ] **market window 覆蓋損失 < 15 分鐘**（見上面「正確嘅量法」）
- [ ] 最大心跳空窗 < 15 分鐘
- [ ] 每條心跳嘅 `last_api_ok` 距 `observed_at` < 10 分鐘
- [ ] 當日最後一條係 `collector_stopped`
- [ ] 全日只有一個 alert.py pid
- [ ] parse 失敗 = 0 ／ dedup_key 重複 = 0 ／ 錯日嘅行 = 0
- [ ] schema 停留喺 v2
- [ ] chain snapshot 資料夾存在，覆蓋 0–365 日
- [ ] 三個 launchd job status = 0

### 門檻依據

**空窗 15 分鐘**（原寫 10 分鐘）
`POLL=120`、`HEARTBEAT_INTERVAL=300` 唔整除，心跳只喺 poll 完成後檢查。今日實測間隔 4m02s–6m07s。

**必須查 `last_api_ok`**
內層 `except Exception` 會吞低 Futu API 失敗然後照行 —— API 死晒一日，心跳一樣跳足 6 個鐘。

**`source_sha256` 做 gate，`git_sha` 只做參考**
`git status` 掃全 repo 會令無關檔案觸發 dirty，日日紅嘅警報等於冇警報。Luna 實作用 `git diff --quiet HEAD -- alert.py`，範圍收窄到 alert.py 係啱嘅（alert.py 冇本地 import）。

---

## Contamination rule

2026-09-01 或之後嘅 alert tape 同 log：

- **可以睇**：檔案有冇、幾大、mtime、行數、`_meta` 行、process 生存
- **唔可以睇**：邊隻股、邊張單、幾多錢、邊個方向
- **唔可以 `tail` `logs/alert_*.log`**（會印成交內容）
- **唔可以貼 Telegram 截圖**（同上）

8/31 或之前唔受限。

---

## 團隊

```
Luna 寫代碼 → Vera 機械驗 claim → Claude review 條件本身 → Leo 批准 → commit
```

- Vera 唔同 Luna 對話（單向，只見 artifact）
- **能夠用 script 做嘅，唔准用 agent**
- Vera 同 Luna 行同一個 model（`gpt-5.6-luna`），有相關盲點
- 超過 30 行嘅輸出一律上傳檔案，唔好貼
- jarvis60 喺 MacBook A（192.168.0.208），Leo 由 B 用 `scp` 攞檔案

### Claude 今日犯嘅錯（記低，唔好重複）

- 八項驗收條件寫壞三項（dirty 範圍、第 8 項寫成任務唔係閘、contamination 指示過闊）
- 由「collect.py 死咗」直接推論「`own` 冇咗輸入」，冇量度就斷言 —— 一條命令就推翻咗
- 兩次 contamination 違規
- 每次回覆結尾加多樣「順便」，違反一次講一件事

**規則：唔知就講「唔知，測佢」，唔好用推理填窿。**

---

## 結果代表乜

- **連續 10 個交易日全綠** → Phase 1 完，入 Phase 2
- **有紅** → 修完先繼續

Phase 1 唔會產生任何交易結論。唯一產出係一句：「呢 10 日嘅數據可唔可以信」。

---

## 已知限制

- OpenD 同 lin-signal-bot、OpenClaw 共用，未問過唔可以重啟
- 14:00–21:30 UK 時間內唔可以改 collect.py / snapshot.py / intraday.py / alert.py
