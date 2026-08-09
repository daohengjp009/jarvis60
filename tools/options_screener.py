"""Tool: options_screener
Task: Write a function screen_options(rows) that takes a list of dicts, each with keys: option_type ('CALL' or 'PUT'), option_strike_price, option_open_interest, option_implied_volatility, option_premium, option_delta, option_expiry_date_distance, bid_price, ask_price, volume. FILTER OUT any row where: premium <= 0, implied volatility <= 0, open interest < 100, bid <= 0, ask <= 0, expiry distance is outside 7 to 21 inclusive, absolute delta outside 0.25 to 0.40 inclusive, or spread_pct > 10 where spread_pct = 100 * (ask - bid) / ((ask + bid) / 2). For surviving rows compute liquidity_score = open_interest + volume - (spread_pct * 100). Return a dict with keys 'calls' and 'puts', each a list of the top 5 surviving rows of that option_type sorted by liquidity_score descending, each row being the original dict plus added keys 'spread_pct' and 'liquidity_score'.
Born after 2 attempt(s)."""

import copy

def screen_options(rows):
    calls = []
    puts = []
    
    for row in rows:
        premium = row['option_premium']
        iv = row['option_implied_volatility']
        oi = row['option_open_interest']
        bid = row['bid_price']
        ask = row['ask_price']
        expiry = row['option_expiry_date_distance']
        delta = row['option_delta']
        volume = row['volume']
        option_type = row['option_type']
        
        if premium <= 0:
            continue
        if iv <= 0:
            continue
        if oi < 100:
            continue
        if bid <= 0:
            continue
        if ask <= 0:
            continue
        if expiry < 7 or expiry > 21:
            continue
        if abs(delta) < 0.25 or abs(delta) > 0.40:
            continue
        
        spread_pct = 100 * (ask - bid) / ((ask + bid) / 2)
        
        if spread_pct > 10 + 1e-9:
            continue
        
        liquidity_score = oi + volume - (spread_pct * 100)
        
        new_row = copy.deepcopy(row)
        new_row['spread_pct'] = spread_pct
        new_row['liquidity_score'] = liquidity_score
        
        if option_type == 'CALL':
            calls.append(new_row)
        elif option_type == 'PUT':
            puts.append(new_row)
    
    calls.sort(key=lambda x: x['liquidity_score'], reverse=True)
    puts.sort(key=lambda x: x['liquidity_score'], reverse=True)
    
    return {
        'calls': calls[:5],
        'puts': puts[:5]
    }
