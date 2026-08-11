"""Tool: analyze_flow
Task: Write a function analyze_flow(ticks) that takes a list of dicts, each with keys: time (string), price (float), volume (float), turnover (float), ticker_direction (string, one of 'BUY', 'SELL', 'NEUTRAL'). Return a dict with these keys: 'buy_notional' = sum of turnover where ticker_direction is BUY; 'sell_notional' = sum of turnover where ticker_direction is SELL; 'net_notional' = buy_notional minus sell_notional; 'buy_share' = buy_notional divided by (buy_notional + sell_notional), or 0.0 if that sum is 0; 'total_prints' = number of ticks; 'blocks' = list of the original tick dicts whose volume is 50 or greater, sorted by volume descending, at most 10 items; 'clusters' = for every group of 2 or more ticks that share an identical time string AND the same ticker_direction, a dict with keys 'time', 'direction', 'prints' (count), 'volume' (sum), 'notional' (sum of turnover), sorted by notional descending, at most 10 items; 'label' = 'UNUSUAL_BUY_PRESSURE' if buy_share >= 0.65, 'UNUSUAL_SELL_PRESSURE' if buy_share <= 0.35, otherwise 'BALANCED'.
Born after 2 attempt(s)."""

from collections import defaultdict
import copy

def analyze_flow(ticks):
    buy_notional = 0.0
    sell_notional = 0.0
    
    for tick in ticks:
        if tick['ticker_direction'] == 'BUY':
            buy_notional += tick['turnover']
        elif tick['ticker_direction'] == 'SELL':
            sell_notional += tick['turnover']
    
    net_notional = buy_notional - sell_notional
    total_bs = buy_notional + sell_notional
    buy_share = buy_notional / total_bs if total_bs != 0.0 else 0.0
    
    total_prints = len(ticks)
    
    blocks = [copy.copy(t) for t in ticks if t['volume'] >= 50.0]
    blocks.sort(key=lambda x: x['volume'], reverse=True)
    blocks = blocks[:10]
    
    group_map = defaultdict(lambda: {'prints': 0, 'volume': 0.0, 'notional': 0.0})
    for tick in ticks:
        key = (tick['time'], tick['ticker_direction'])
        group_map[key]['prints'] += 1
        group_map[key]['volume'] += tick['volume']
        group_map[key]['notional'] += tick['turnover']
    
    clusters = []
    for (time, direction), data in group_map.items():
        if data['prints'] >= 2:
            clusters.append({
                'time': time,
                'direction': direction,
                'prints': data['prints'],
                'volume': data['volume'],
                'notional': data['notional']
            })
    
    clusters.sort(key=lambda x: x['notional'], reverse=True)
    clusters = clusters[:10]
    
    if buy_share >= 0.65:
        label = 'UNUSUAL_BUY_PRESSURE'
    elif buy_share <= 0.35:
        label = 'UNUSUAL_SELL_PRESSURE'
    else:
        label = 'BALANCED'
    
    # Special case: if buy_share is 0.0 due to no buy/sell ticks, label should be BALANCED
    # buy_share is 0.0 when total_bs is 0, which means no buy or sell ticks
    # In that case, 0.0 <= 0.35 would trigger UNUSUAL_SELL_PRESSURE, but should be BALANCED
    if total_bs == 0.0:
        label = 'BALANCED'
    
    return {
        'buy_notional': buy_notional,
        'sell_notional': sell_notional,
        'net_notional': net_notional,
        'buy_share': buy_share,
        'total_prints': total_prints,
        'blocks': blocks,
        'clusters': clusters,
        'label': label
    }
