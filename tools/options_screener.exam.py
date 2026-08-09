# FUNCTION: screen_options(rows)

import copy

def make_row(option_type='CALL', strike=100, oi=500, iv=0.3, premium=2.5,
             delta=0.30, expiry=14, bid=2.4, ask=2.6, volume=200):
    return {
        'option_type': option_type,
        'option_strike_price': strike,
        'option_open_interest': oi,
        'option_implied_volatility': iv,
        'option_premium': premium,
        'option_delta': delta,
        'option_expiry_date_distance': expiry,
        'bid_price': bid,
        'ask_price': ask,
        'volume': volume,
    }

# Helper to compute expected spread_pct and liquidity_score
def compute_spread_pct(bid, ask):
    return 100 * (ask - bid) / ((ask + bid) / 2)

def compute_liquidity_score(oi, volume, spread_pct):
    return oi + volume - (spread_pct * 100)

# --- Normal case: several valid calls and puts, check top 5 sorting ---

valid_calls = []
for i in range(7):
    oi = 1000 + i * 100
    vol = 300 + i * 50
    row = make_row(option_type='CALL', oi=oi, volume=vol)
    valid_calls.append(row)

valid_puts = []
for i in range(7):
    oi = 800 + i * 120
    vol = 250 + i * 40
    row = make_row(option_type='PUT', oi=oi, volume=vol, delta=-0.30)
    valid_puts.append(row)

# Rows that should be filtered out
filtered_rows = [
    make_row(premium=0),                         # premium <= 0
    make_row(iv=0),                               # iv <= 0
    make_row(oi=50),                              # oi < 100
    make_row(bid=0),                              # bid <= 0
    make_row(ask=0),                              # ask <= 0
    make_row(expiry=6),                           # expiry < 7
    make_row(expiry=22),                          # expiry > 21
    make_row(delta=0.20),                         # |delta| < 0.25
    make_row(delta=0.50),                         # |delta| > 0.40
    make_row(bid=1.0, ask=1.5),                   # spread_pct > 10: (0.5/1.25)*100 = 40%
    make_row(premium=-1),                         # premium <= 0
]

all_rows = valid_calls + valid_puts + filtered_rows
result = screen_options(all_rows)

assert isinstance(result, dict), "Result must be a dict"
assert 'calls' in result and 'puts' in result, "Result must have 'calls' and 'puts' keys"

# Check calls
calls_result = result['calls']
assert isinstance(calls_result, list), "'calls' must be a list"
assert len(calls_result) == 5, f"Expected 5 calls, got {len(calls_result)}"

# Verify calls are sorted by liquidity_score descending
call_scores = [r['liquidity_score'] for r in calls_result]
assert call_scores == sorted(call_scores, reverse=True), "Calls not sorted by liquidity_score descending"

# Check each call has spread_pct and liquidity_score computed correctly
for r in calls_result:
    assert r['option_type'] == 'CALL'
    sp = compute_spread_pct(r['bid_price'], r['ask_price'])
    assert abs(r['spread_pct'] - sp) < 1e-9, "spread_pct mismatch"
    ls = compute_liquidity_score(r['option_open_interest'], r['volume'], sp)
    assert abs(r['liquidity_score'] - ls) < 1e-9, "liquidity_score mismatch"

# Verify top 5 are the ones with highest liquidity_score among valid_calls
expected_call_scores = []
for row in valid_calls:
    sp = compute_spread_pct(row['bid_price'], row['ask_price'])
    ls = compute_liquidity_score(row['option_open_interest'], row['volume'], sp)
    expected_call_scores.append(ls)
top5_call_scores = sorted(expected_call_scores, reverse=True)[:5]
assert call_scores == top5_call_scores, "Top 5 calls don't match expected"

# Check puts
puts_result = result['puts']
assert isinstance(puts_result, list), "'puts' must be a list"
assert len(puts_result) == 5, f"Expected 5 puts, got {len(puts_result)}"

put_scores = [r['liquidity_score'] for r in puts_result]
assert put_scores == sorted(put_scores, reverse=True), "Puts not sorted by liquidity_score descending"

for r in puts_result:
    assert r['option_type'] == 'PUT'
    sp = compute_spread_pct(r['bid_price'], r['ask_price'])
    assert abs(r['spread_pct'] - sp) < 1e-9
    ls = compute_liquidity_score(r['option_open_interest'], r['volume'], sp)
    assert abs(r['liquidity_score'] - ls) < 1e-9

# --- Edge case: fewer than 5 valid rows of a type ---
few_rows = [
    make_row(option_type='CALL'),
    make_row(option_type='CALL'),
    make_row(option_type='PUT', delta=-0.35),
]
result2 = screen_options(few_rows)
assert len(result2['calls']) == 2, f"Expected 2 calls, got {len(result2['calls'])}"
assert len(result2['puts']) == 1, f"Expected 1 put, got {len(result2['puts'])}"

# --- Edge case: empty input ---
result3 = screen_options([])
assert result3 == {'calls': [], 'puts': []}, "Empty input should return empty lists"

# --- Edge case: all rows filtered out ---
bad_rows = [make_row(premium=0), make_row(iv=0), make_row(expiry=5)]
result4 = screen_options(bad_rows)
assert result4['calls'] == [], "All filtered calls should be empty"
assert result4['puts'] == [], "All filtered puts should be empty"

# --- Edge case: boundary values ---
# expiry exactly 7 and 21 should pass
boundary_row_7 = make_row(option_type='CALL', expiry=7)
boundary_row_21 = make_row(option_type='CALL', expiry=21)
# delta exactly 0.25 and 0.40 should pass
boundary_delta_025 = make_row(option_type='PUT', delta=0.25)
boundary_delta_040 = make_row(option_type='PUT', delta=-0.40)

result5 = screen_options([boundary_row_7, boundary_row_21, boundary_delta_025, boundary_delta_040])
assert len(result5['calls']) == 2, f"Expected 2 boundary calls, got {len(result5['calls'])}"
assert len(result5['puts']) == 2, f"Expected 2 boundary puts, got {len(result5['puts'])}"

# --- Edge case: original dicts are not mutated (result rows are copies with added keys) ---
original = make_row(option_type='CALL')
original_copy = copy.deepcopy(original)
result6 = screen_options([original])
# The original should not have been mutated
assert 'spread_pct' not in original, "Original row should not be mutated"
assert 'liquidity_score' not in original, "Original row should not be mutated"
# The returned row should have the added keys
assert 'spread_pct' in result6['calls'][0]
assert 'liquidity_score' in result6['calls'][0]

# --- Edge case: spread_pct exactly at boundary (10) should pass ---
# bid=1.8, ask=2.2 => spread_pct = 100*(0.4/2.0) = 20% => filtered
# bid=1.9, ask=2.1 => spread_pct = 100*(0.2/2.0) = 10% => pass
boundary_spread = make_row(option_type='CALL', bid=1.9, ask=2.1)
sp_boundary = compute_spread_pct(1.9, 2.1)
assert abs(sp_boundary - 10.0) < 1e-9

result7 = screen_options([boundary_spread])
assert len(result7['calls']) == 1, "Row with spread_pct exactly 10 should pass"

# spread_pct just over 10 => filtered
over_spread = make_row(option_type='CALL', bid=1.89, ask=2.11)
result8 = screen_options([over_spread])
sp_over = compute_spread_pct(1.89, 2.11)
if sp_over > 10:
    assert len(result8['calls']) == 0, "Row with spread_pct > 10 should be filtered"