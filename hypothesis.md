# Jarvis_60 — Pre-Registered Hypothesis v1
Committed before data collection. Changing anything below mid-experiment voids the test.

## Hypothesis
Large aggressive same-timestamp option clusters predict the underlying stock's
direction over the following 60 minutes.

## Event definition (the trigger)
A cluster is 2+ ticks sharing an identical timestamp AND identical ticker_direction.
An EVENT is a cluster where:
- notional >= $250,000
- direction is BUY or SELL (never NEUTRAL)
- contract has DTE > 1
- the contract's tick sequence for that day has no gaps (Layer 0 clean)

## Signed signal (the naive reading being tested)
BULLISH-implied: CALL BUY, PUT SELL
BEARISH-implied: PUT BUY, CALL SELL
signed_return = underlying return x (+1 if bullish-implied, -1 if bearish-implied)

## Target variable
Underlying stock return, close-to-close of 1-minute bars, +60 minutes after the
event timestamp. ONE horizon. Not option returns. Not IV.

## Control
For each event: 20 random timestamps from the SAME symbol, SAME calendar day,
SAME hour of day. Control return computed identically.
excess = mean(event signed_return) - mean(matched control signed_return)

## Data completeness rule (added 2026-08-14, before any result was examined)
Capture rate = our summed tick volume / the contract's daily K-line volume.
- Any single contract-day with capture < 95% is EXCLUDED from the event count.
- Other contracts on the same day are unaffected.
- Capture is measured for every contract-day before the primary test is run.
Rationale: a partial tape understates flow unevenly, so events drawn from it are
not comparable. Fixed now so the threshold cannot be chosen to suit the outcome.

## Stopping rule
AMENDED 2026-08-14, before any result was examined.
Original: 150 events OR 6 weeks, whichever came first.
Pace check showed ~26 events/day, so 150 events would arrive in ~6 trading days.
Events cluster heavily within a day (same contract, same hour, same underlying
move), so 150 events over 6 days is close to 6 independent observations - the
same confound that invalidated the pilot.

Revised: stop only when BOTH are true:
  - at least 150 qualifying events, AND
  - at least 20 distinct trading days collected
Hard cap remains 6 weeks (2026-09-23) regardless.
No analysis of the primary metric before the stopping rule is met.

## Decision thresholds (fixed now)
GO      : excess >= +0.15%, t-stat >= 2.5, and excess is positive in ALL 3 symbols (tightened from 60% due to small symbol count)
KILL    : |excess| < 0.10%, OR t-stat < 2.0, OR sign flips across the majority of symbols
AMBIGUOUS: anything between -> collect one more month, then decide once

## Anti-p-hacking rules
- ONE primary test: signed excess at +60m. Nothing else decides GO/KILL.
- Other horizons, groupings, or filters may be computed but are EXPLORATORY only
  and cannot be used for the decision.
- No adding, removing, or reweighting symbols after collection starts.
- If a bug forces a rule change, the event count resets to zero.

## Known limitations accepted in advance
- ticker_direction is exchange-inferred, not ground truth
- clusters may be one order or several participants reacting simultaneously
- single legs of spreads/rolls/hedges are indistinguishable from outright bets
- OI is net, so opening/closing cannot be attributed per participant
- effect size must exceed option bid-ask costs (2-3%) to be tradable at all

## Data requirements
- 3 liquid underlyings: TSLA, NVDA, GOOGL
- AMENDED 2026-08-11 before any collection: original v1 required >= 10 underlyings.
  Reduced to 3 to keep contract count near the level where 100% tick capture was
  verified (32 contracts on 2026-08-11). Accepted cost: single-name effects cannot
  be fully ruled out, so a GO result means "worth a larger test", never "tradable".
  To compensate, the symbol-agreement rule below is TIGHTENED, not relaxed.
- watchlist rule unchanged for the whole experiment
- underlying 1-minute bars backfilled for every collection day

## Pilot result (2026-08-10, NOT part of this experiment)
36 events, 2 symbols. CALL BUY indistinguishable from control; signs flipped
between NVDA (-0.22%) and TSLA (+0.37%). No edge demonstrated. Sample far too
small and confounded by symbol. Recorded here so it cannot be quietly reused
as supporting evidence later.
