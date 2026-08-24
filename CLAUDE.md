# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Two independent subsystems sharing a project root:

1. **`core/` — Jarvis_60 self-building agent.** Given a task, it tries to reuse an
   existing tool, then compose owned tools, then solve from scratch — every
   accepted solution is examined by a generated test before being saved
   permanently to `tools/`.
2. **Root-level scripts — an options-market research pipeline.** Collects live
   option tick data and daily/intraday chain snapshots from Futu OpenD for a
   pre-registered statistical experiment (signed order-flow predicting short-term
   underlying direction), plus a second, feature-table-based hypothesis (HYP-002).

These two halves do not import each other. Don't conflate them.

## Running things

No test runner, linter, or build system is configured (no requirements.txt/pyproject.toml).
Dependencies observed in imports: `anthropic`, `python-dotenv`, `futu` (Futu OpenAPI SDK),
`pandas`, `numpy` — install into whatever environment `python3` resolves to.

Secrets live in `.env` (gitignored): `ANTHROPIC_API_KEY`, `TELEGRAM_TOKEN`,
`TELEGRAM_CHAT_ID`. Futu OpenD must be running locally on `127.0.0.1:11112` for
anything that touches `futu`; the RSA key path is hardcoded as
`/Users/leolo/.openclaw/futu/conn_key_1024.pem` in every fetch script.

### The `./j` launcher (root-level pipeline)
```
./j start [TICKERS]   # start tick collector (background, logs to logs/collect_<date>.log)
./j stop               # stop collector
./j status              # running? recent log tail, tick count
./j log                 # tail today's collector log
./j screen TICKER       # one-shot option screener (screen.py)
./j check               # run core/recheck.py — re-verify every owned tool's exam
./j snap                # daily full-watchlist chain snapshot (run once after US open)
./j cap                 # capture_check.py — tick completeness vs K-line truth (run next morning)
./j fill                # backfill missing 1-min underlying bars
./j intra [mins]        # start intraday chain-state capture (default 30 min cadence)
./j nointra             # stop it
./j stream [secs]       # push-vs-poll streaming test, writes only to data/ticks_stream/
./j nostream            # stop it
./j day [DATE]          # one-screen summary of a collection day (today by default)
./j open [TICKERS]      # 14:15 routine: start + stream? + intra together (see script comment)
./j close               # 21:00 routine: stop + nointra + snap
./j morning [DATE]      # next-day routine: cap + fill + day summary
./j dash / nodash        # dashboard.py on http://192.168.0.208:8060
./j bot / nobot          # Telegram front-end (bot.py) on the pinned interpreter
```
`bot.py` is a Telegram front-end exposing the same command set (fixed menu,
whitelisted `TELEGRAM_CHAT_ID`, no shell strings — always `subprocess` with an
argument list). Start it with `./j bot`, not bare `python3 bot.py` — a bare
`python3` can resolve to an interpreter without `pandas` depending on shell
config (this bit `intraday.py` under launchd once already), whereas `./j bot`
launches it on `$PY`, the interpreter pinned at the top of `./j`.

### The agent (`core/`)
```
python3 jarvis.py "task in plain English"
```
Dispatch order: `find_tool` (exact reuse) → `find_components` + `compose`
(glue existing tools) → `solve` (from scratch). Every path goes through
`core/examiner.py` first, which must produce a test a do-nothing stub fails
with `AssertionError` (not too weak, not broken) before any code is accepted.
Accepted code + its exam are saved by `core/toolbelt.py` to `tools/<name>.py`
and `tools/<name>.exam.py`, registered in `tools/registry.json`.
`core/executor.py` re-runs an owned tool against new input behind a permission
wall (`RISKY_PATTERNS`: network, subprocess/system calls, file writes, paths
outside the project) — anything risky requires an interactive y/N.
`core/recheck.py` (`./j check`) re-runs every tool's stored exam and marks it
`ok`/`broken`/`unverified` in the registry; the dispatcher must skip broken
tools. There is no separate pytest suite — a tool's `.exam.py` file *is* its test.

### Feature table (HYP-002)
```
python3 features.py    # writes data/features/symbol_days.csv from data/symbol_history/frozen/
```
Behavior is a strict implementation of `features.md` — read that file before
touching `features.py`. Key invariants enforced by assertions at import time,
not just documentation:
- The symbol holdout (`SYMBOL_HOLDOUT`/`SYMBOL_DISCOVERY`) is a **frozen** draw
  (`random.Random(20260822)`); the script asserts it still reproduces from the
  seed rather than silently redrawing if the universe changes.
- Time split: discovery `<= 2026-05-21`, holdout `>= 2026-05-22`.
- Neither holdout may be inspected, tuned against, or used for feature
  selection before being tested once — this is a hard experimental-integrity
  rule, not a style preference.

## Architectural notes worth knowing before editing

- **Look-ahead discipline is the central concern of the research code.**
  Rolling stats use `shift(1)` before windowing (`features.py:zscore`,
  `ratio_to_median`); open-interest columns are shifted one day at build time
  because Futu publishes OI T-1 delayed (`features.md` §5); a symbol-day needs
  ≥60 trading days of history before `min_history_ok` is set. If you add a
  feature, check whether it needs the same treatment before it goes into
  `features.py`.
- **`features.md` / `hypothesis.md` are pre-registration documents, not just
  docs.** Both explicitly forbid changing rules (thresholds, splits, universe,
  stopping rule) after any outcome has been computed/inspected — an amendment
  is only legitimate if logged in the file *before* analysis. When asked to
  modify feature or hypothesis logic, check whether the change would violate
  this and flag it rather than silently complying.
- **Raw tick data cannot be backfilled; everything else can.** `collect.py`
  writes append-only per-contract-per-day CSVs to `data/ticks/` — comments in
  the code call these files "sealed" once the trading date has passed; ticks
  from a stale date are dropped, never rewritten. `data/symbol_history/`,
  `data/underlying_1m/`, and chain snapshots are all retrievable after the
  fact via the `backfill_*` scripts, so treat `data/ticks/` and
  `data/ticks_stream/` with more care than the rest of `data/`.
- **`data/symbol_history/frozen/`** exists because Futu only serves a rolling
  252-day window — `backfill_symbol_history.py` must be run regularly or
  history silently ages out; `features.py` reads only from the frozen copy,
  never live.
- **HYP-001 (tick/order-flow) and HYP-002 (feature-table) are sealed from each
  other.** `features.md` §11 states no forward returns for the HYP-001 tick
  symbols are examined until HYP-001's own stopping rule is met. Don't wire
  outcome computation across the two without noticing this.
- **`core/notify.py` (outbound-only Telegram) vs `bot.py` (inbound command
  bot)** are separate: notify.py never raises (collection must not die on a
  failed push) and accepts no commands; bot.py is the only inbound surface and
  restricts execution to a fixed dispatch table of whitelisted functions —
  never shells out to arbitrary text.
- **Dashboard deliberately shows no forward returns** (`dashboard.py` docstring)
  — it's a collection/quality monitor, not an analysis surface, by design.

## Operational safety

- launchd runs `./j open` at 14:15, `./j close` at 21:00, `./j morning` at
  08:00 on weekdays. Never modify `collect.py`, `snapshot.py`, or
  `intraday.py` between 14:00 and 21:30 UK time — a live session cannot be
  recovered.
- OpenD is SHARED with a separate project (`~/lin-signal-bot` and OpenClaw).
  Never restart OpenD without asking.
- Options have their own quotas: 200 subscriptions and 200 historical
  K-lines, separate from the 1000 stock pool. The collector uses ~50. Adding
  subscriptions can silently break collection mid-session.
- Never run `./j open` outside US market hours — it writes junk data files.
- `data/symbol_history/frozen/` is a frozen copy. Never regenerate it without
  being asked; `features.py` reads only from it.
