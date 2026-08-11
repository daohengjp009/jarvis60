# FUNCTION: analyze_flow(ticks)

import copy

def test_analyze_flow_normal():
    ticks = [
        {"time": "09:30", "price": 100.0, "volume": 60.0, "turnover": 6000.0, "ticker_direction": "BUY"},
        {"time": "09:30", "price": 101.0, "volume": 55.0, "turnover": 5555.0, "ticker_direction": "BUY"},
        {"time": "09:31", "price": 99.0,  "volume": 30.0, "turnover": 2970.0, "ticker_direction": "SELL"},
        {"time": "09:31", "price": 98.0,  "volume": 20.0, "turnover": 1960.0, "ticker_direction": "SELL"},
        {"time": "09:32", "price": 100.0, "volume": 10.0, "turnover": 1000.0, "ticker_direction": "NEUTRAL"},
        {"time": "09:32", "price": 100.0, "volume": 50.0, "turnover": 5000.0, "ticker_direction": "BUY"},
    ]

    result = analyze_flow(ticks)

    assert isinstance(result, dict), "result must be a dict"

    buy_notional = 6000.0 + 5555.0 + 5000.0
    sell_notional = 2970.0 + 1960.0
    net_notional = buy_notional - sell_notional
    buy_share = buy_notional / (buy_notional + sell_notional)

    assert abs(result['buy_notional'] - buy_notional) < 1e-9
    assert abs(result['sell_notional'] - sell_notional) < 1e-9
    assert abs(result['net_notional'] - net_notional) < 1e-9
    assert abs(result['buy_share'] - buy_share) < 1e-9
    assert result['total_prints'] == 6

    blocks = result['blocks']
    assert isinstance(blocks, list)
    assert len(blocks) == 3
    block_volumes = [b['volume'] for b in blocks]
    assert block_volumes == [60.0, 55.0, 50.0]
    assert all(b['volume'] >= 50.0 for b in blocks)
    assert blocks[0]['turnover'] == 6000.0
    assert blocks[1]['turnover'] == 5555.0
    assert blocks[2]['turnover'] == 5000.0

    clusters = result['clusters']
    assert isinstance(clusters, list)
    assert len(clusters) == 2

    cluster_notionals = [c['notional'] for c in clusters]
    assert cluster_notionals == sorted(cluster_notionals, reverse=True)

    buy_cluster = next((c for c in clusters if c['time'] == '09:30' and c['direction'] == 'BUY'), None)
    assert buy_cluster is not None
    assert buy_cluster['prints'] == 2
    assert abs(buy_cluster['volume'] - 115.0) < 1e-9
    assert abs(buy_cluster['notional'] - 11555.0) < 1e-9

    sell_cluster = next((c for c in clusters if c['time'] == '09:31' and c['direction'] == 'SELL'), None)
    assert sell_cluster is not None
    assert sell_cluster['prints'] == 2
    assert abs(sell_cluster['volume'] - 50.0) < 1e-9
    assert abs(sell_cluster['notional'] - 4930.0) < 1e-9

    assert result['label'] == 'UNUSUAL_BUY_PRESSURE'


def test_analyze_flow_empty():
    result = analyze_flow([])
    assert isinstance(result, dict)
    assert result['buy_notional'] == 0.0
    assert result['sell_notional'] == 0.0
    assert result['net_notional'] == 0.0
    assert result['buy_share'] == 0.0
    assert result['total_prints'] == 0
    assert result['blocks'] == []
    assert result['clusters'] == []
    assert result['label'] == 'BALANCED'


def test_analyze_flow_unusual_sell():
    ticks = [
        {"time": "10:00", "price": 50.0, "volume": 100.0, "turnover": 5000.0, "ticker_direction": "SELL"},
        {"time": "10:00", "price": 50.0, "volume": 80.0,  "turnover": 4000.0, "ticker_direction": "SELL"},
        {"time": "10:01", "price": 51.0, "volume": 10.0,  "turnover": 510.0,  "ticker_direction": "BUY"},
    ]
    result = analyze_flow(ticks)
    assert isinstance(result, dict)
    assert abs(result['buy_notional'] - 510.0) < 1e-9
    assert abs(result['sell_notional'] - 9000.0) < 1e-9
    assert abs(result['net_notional'] - (510.0 - 9000.0)) < 1e-9
    buy_share = 510.0 / 9510.0
    assert abs(result['buy_share'] - buy_share) < 1e-9
    assert result['label'] == 'UNUSUAL_SELL_PRESSURE'
    assert result['total_prints'] == 3

    blocks = result['blocks']
    assert len(blocks) == 2
    assert blocks[0]['volume'] == 100.0
    assert blocks[1]['volume'] == 80.0

    clusters = result['clusters']
    assert len(clusters) == 1
    assert clusters[0]['time'] == '10:00'
    assert clusters[0]['direction'] == 'SELL'
    assert clusters[0]['prints'] == 2
    assert abs(clusters[0]['volume'] - 180.0) < 1e-9
    assert abs(clusters[0]['notional'] - 9000.0) < 1e-9


def test_analyze_flow_blocks_capped_at_10():
    ticks = []
    for i in range(15):
        ticks.append({
            "time": f"09:{i:02d}",
            "price": 100.0,
            "volume": 50.0 + i,
            "turnover": (50.0 + i) * 100.0,
            "ticker_direction": "BUY"
        })
    result = analyze_flow(ticks)
    assert isinstance(result, dict)
    blocks = result['blocks']
    assert len(blocks) == 10
    vols = [b['volume'] for b in blocks]
    assert vols == sorted(vols, reverse=True)
    assert vols[0] == 64.0
    assert vols[9] == 55.0
    assert all(v >= 55.0 for v in vols)


def test_analyze_flow_clusters_capped_at_10():
    ticks = []
    for i in range(15):
        t = f"09:{i:02d}"
        notional = float(i * 100 + 50)
        ticks.append({"time": t, "price": 100.0, "volume": 10.0, "turnover": notional, "ticker_direction": "BUY"})
        ticks.append({"time": t, "price": 100.0, "volume": 10.0, "turnover": notional, "ticker_direction": "BUY"})

    result = analyze_flow(ticks)
    assert isinstance(result, dict)
    clusters = result['clusters']
    assert len(clusters) == 10
    notionals = [c['notional'] for c in clusters]
    assert notionals == sorted(notionals, reverse=True)
    assert abs(notionals[0] - 2900.0) < 1e-9


def test_analyze_flow_balanced():
    ticks = [
        {"time": "10:00", "price": 100.0, "volume": 10.0, "turnover": 1000.0, "ticker_direction": "BUY"},
        {"time": "10:01", "price": 100.0, "volume": 10.0, "turnover": 1000.0, "ticker_direction": "SELL"},
    ]
    result = analyze_flow(ticks)
    assert isinstance(result, dict)
    assert abs(result['buy_share'] - 0.5) < 1e-9
    assert result['label'] == 'BALANCED'
    assert result['total_prints'] == 2
    assert result['buy_notional'] == 1000.0
    assert result['sell_notional'] == 1000.0
    assert result['net_notional'] == 0.0


def test_analyze_flow_buy_share_exactly_065():
    buy_t = 0.65
    sell_t = 0.35
    ticks = [
        {"time": "10:00", "price": 1.0, "volume": 1.0, "turnover": buy_t, "ticker_direction": "BUY"},
        {"time": "10:01", "price": 1.0, "volume": 1.0, "turnover": sell_t, "ticker_direction": "SELL"},
    ]
    result = analyze_flow(ticks)
    assert isinstance(result, dict)
    assert abs(result['buy_share'] - 0.65) < 1e-9
    assert result['label'] == 'UNUSUAL_BUY_PRESSURE'


def test_analyze_flow_buy_share_exactly_035():
    buy_t = 0.35
    sell_t = 0.65
    ticks = [
        {"time": "10:00", "price": 1.0, "volume": 1.0, "turnover": buy_t, "ticker_direction": "BUY"},
        {"time": "10:01", "price": 1.0, "volume": 1.0, "turnover": sell_t, "ticker_direction": "SELL"},
    ]
    result = analyze_flow(ticks)
    assert isinstance(result, dict)
    assert abs(result['buy_share'] - 0.35) < 1e-9
    assert result['label'] == 'UNUSUAL_SELL_PRESSURE'


def test_analyze_flow_no_buy_no_sell_only_neutral():
    ticks = [
        {"time": "10:00", "price": 100.0, "volume": 10.0, "turnover": 1000.0, "ticker_direction": "NEUTRAL"},
        {"time": "10:00", "price": 100.0, "volume": 20.0, "turnover": 2000.0, "ticker_direction": "NEUTRAL"},
    ]
    result = analyze_flow(ticks)
    assert isinstance(result, dict)
    assert result['buy_notional'] == 0.0
    assert result['sell_notional'] == 0.0
    assert result['net_notional'] == 0.0
    assert result['buy_share'] == 0.0
    assert result['label'] == 'BALANCED'
    assert result['total_prints'] == 2
    assert result['blocks'] == []
    clusters = result['clusters']
    assert len(clusters) == 1
    assert clusters[0]['direction'] == 'NEUTRAL'
    assert clusters[0]['time'] == '10:00'
    assert clusters[0]['prints'] == 2
    assert abs(clusters[0]['volume'] - 30.0) < 1e-9
    assert abs(clusters[0]['notional'] - 3000.0) < 1e-9


def test_analyze_flow_does_not_mutate_input():
    ticks = [
        {"time": "09:30", "price": 100.0, "volume": 60.0, "turnover": 6000.0, "ticker_direction": "BUY"},
        {"time": "09:30", "price": 101.0, "volume": 55.0, "turnover": 5555.0, "ticker_direction": "BUY"},
    ]
    original = copy.deepcopy(ticks)
    analyze_flow(ticks)
    assert ticks == original


def test_analyze_flow_single_tick_no_cluster_no_block():
    ticks = [
        {"time": "09:00", "price": 100.0, "volume": 5.0, "turnover": 500.0, "ticker_direction": "BUY"},
    ]
    result = analyze_flow(ticks)
    assert isinstance(result, dict)
    assert result['buy_notional'] == 500.0
    assert result['sell_notional'] == 0.0
    assert result['net_notional'] == 500.0
    assert result['buy_share'] == 1.0
    assert result['total_prints'] == 1
    assert result['blocks'] == []
    assert result['clusters'] == []
    assert result['label'] == 'UNUSUAL_BUY_PRESSURE'


def test_analyze_flow_cluster_with_mixed_directions_at_same_time():
    ticks = [
        {"time": "11:00", "price": 100.0, "volume": 10.0, "turnover": 1000.0, "ticker_direction": "BUY"},
        {"time": "11:00", "price": 100.0, "volume": 12.0, "turnover": 1200.0, "ticker_direction": "BUY"},
        {"time": "11:00", "price": 99.0,  "volume": 8.0,  "turnover": 792.0,  "ticker_direction": "SELL"},
        {"time": "11:00", "price": 99.0,  "volume": 9.0,  "turnover": 891.0,  "ticker_direction": "SELL"},
    ]
    result = analyze_flow(ticks)
    assert isinstance(result, dict)
    assert result['total_prints'] == 4
    assert abs(result['buy_notional'] - 2200.0) < 1e-9
    assert abs(result['sell_notional'] - 1683.0) < 1e-9
    clusters = result['clusters']
    assert len(clusters) == 2
    notionals = [c['notional'] for c in clusters]
    assert notionals == sorted(notionals, reverse=True)

    buy_cluster = next((c for c in clusters if c['direction'] == 'BUY'), None)
    assert buy_cluster is not None
    assert buy_cluster['time'] == '11:00'
    assert buy_cluster['prints'] == 2
    assert abs(buy_cluster['volume'] - 22.0) < 1e-9
    assert abs(buy_cluster['notional'] - 2200.0) < 1e-9

    sell_cluster = next((c for c in clusters if c['direction'] == 'SELL'), None)
    assert sell_cluster is not None
    assert sell_cluster['time'] == '11:00'
    assert sell_cluster['prints'] == 2
    assert abs(sell_cluster['volume'] - 17.0) < 1e-9
    assert abs(sell_cluster['notional'] - 1683.0) < 1e-9


test_analyze_flow_normal()
test_analyze_flow_empty()
test_analyze_flow_unusual_sell()
test_analyze_flow_blocks_capped_at_10()
test_analyze_flow_clusters_capped_at_10()
test_analyze_flow_balanced()
test_analyze_flow_buy_share_exactly_065()
test_analyze_flow_buy_share_exactly_035()
test_analyze_flow_no_buy_no_sell_only_neutral()
test_analyze_flow_does_not_mutate_input()
test_analyze_flow_single_tick_no_cluster_no_block()
test_analyze_flow_cluster_with_mixed_directions_at_same_time()