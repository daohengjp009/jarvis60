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

## Stopping rule
Stop at 150 qualifying events OR 6 weeks of collection, whichever comes first.
No analysis of the primary metric before the stopping rule is met.

## Decision thresholds (fixed now)
GO      : excess >= +0.15%, t-stat >= 2.5, and excess is positive in >= 60% of symbols
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
- >= 10 liquid underlyings (not 2 - the pilot showed single-name effects dominate)
- watchlist rule unchanged for the whole experiment
- underlying 1-minute bars backfilled for every collection day

## Pilot result (2026-08-10, NOT part of this experiment)
36 events, 2 symbols. CALL BUY indistinguishable from control; signs flipped
between NVDA (-0.22%) and TSLA (+0.37%). No edge demonstrated. Sample far too
small and confounded by symbol. Recorded here so it cannot be quietly reused
as supporting evidence later.
