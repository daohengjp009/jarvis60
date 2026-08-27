#!/usr/bin/env python3
"""Standalone regression and boundary tests for Whale Strategy Engine v0.3.3."""
import json
import os
import tempfile
import datetime as dt

import whale as W


def _print(second, premium=0.80, lots=100.0, legs="B C230 / S C240", sym="NVDA"):
    raw = W._fake_spread(legs, net=premium * lots * 100.0, sym=sym)
    when = dt.datetime(2026, 8, 25, 12, 0, 0) + dt.timedelta(seconds=second)
    raw["mkt_time"] = when.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    rec = W.normalize_inferred_spread("2026-08-25", raw)
    rec["link_confidence_band"] = "MODERATE"
    return rec


def _clusters(rows):
    return W.build_execution_clusters("2026-08-25", rows)


def test_cluster_boundaries_and_anti_bridging():
    assert len(_clusters([_print(0), _print(300)])) == 1
    assert len(_clusters([_print(0), _print(300.001)])) == 2
    assert len(_clusters([_print(0), _print(300), _print(600), _print(900)])) == 1
    # Adjacent gaps remain valid; this one fails specifically on total span.
    assert len(_clusters([_print(0), _print(300), _print(600), _print(900), _print(900.001)])) == 2
    assert len(_clusters([_print(0, .80), _print(1, .85)])) == 1
    assert len(_clusters([_print(0, .80), _print(1, .850001)])) == 2
    assert len(_clusters([_print(0, .80), _print(1, .85), _print(2, .85), _print(3, .90)])) == 1
    assert len(_clusters([_print(0, .80), _print(1, .85), _print(2, .85), _print(3, .900001)])) == 2
    # Adjacent values alone cannot bridge a range/median breach.
    assert len(_clusters([_print(0, .80), _print(1, .84), _print(2, .88), _print(3, .92)])) == 2


def test_orientation_conflict_is_clustered_then_suppressed():
    bull = _print(0, legs="B C230 / S C240")
    bear = _print(1, legs="S C230 / B C240")
    rows = [bull, bear]
    clusters = _clusters(rows)
    index = {r["print_id"]: r for r in rows}
    orientations = W.build_orientation_theses("2026-08-25", clusters, index)
    activities = W.build_contract_set_activities("2026-08-25", orientations, index)
    assert len(clusters) == 2
    assert len(orientations) == 2
    assert len(activities) == 1
    assert activities[0]["direction_status"] == "DIRECTION_CONFLICT"
    assert activities[0]["directional_bias_eligible"] is False


def test_premium_activity_fields_are_not_gross_weighting():
    rows = [_print(0, .80), _print(1, .80)]
    rows[1]["net_premium"] = -8000.0
    rows[1]["premium_per_spread"] = -0.80
    rows[1]["premium_form"] = "CREDIT"
    rows[1]["canonical_signature"] = "260828:C:230:B|260828:C:240:S"
    clusters = _clusters(rows)
    assert sum(x["signed_net_premium_sum"] for x in clusters) == 0.0
    assert sum(x["premium_turnover_sum"] for x in clusters) == 16000.0
    assert sum(x["gross_leg_turnover_sum"] for x in clusters) > 0.0


def test_real_nvda_regression_and_hierarchy():
    base = os.path.dirname(os.path.abspath(__file__))
    records = W.analyze("2026-08-25", os.path.join(base, "data", "alerts", "alerts_2026-08-25.jsonl"),
                        os.path.join(base, "data", "whale"))
    pk = "NVDA|260828:C:230|260828:C:240"
    clusters = [r for r in records if r.get("kind") == "execution_cluster" and r.get("position_key") == pk]
    assert len(clusters) == 1
    c = clusters[0]
    assert c["print_count"] == 12
    assert c["lots_sum"] == 70959.0 and c["lots_min"] == 811.0 and c["lots_max"] == 15000.0
    assert c["gross_leg_turnover_sum"] == 11607601.0
    assert c["signed_net_premium_sum"] == 6049957.0 and c["premium_turnover_sum"] == 6049957.0
    assert c["premium_per_spread_min"] == .80 and c["premium_per_spread_max"] == .87
    assert c["first_mkt_time"] == "2026-08-25 12:21:48.682"
    assert c["last_mkt_time"] == "2026-08-25 12:34:03.449" and c["duration_seconds"] == 734.767
    assert c["participant_identity"] == c["parent_order"] == "UNKNOWN"


def test_quarantined_history_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "whale_2026-08-24.jsonl")
        W.write_records(path, [{"kind": "contract_set_activity", "whale_schema_version": W.WHALE_SCHEMA_VERSION,
                                "analysis_date": "2026-08-24", "position_key": "NVDA|x",
                                "canonical_signatures": ["x"], "structures": {"bull_call_spread": 1},
                                "source_file_sha256": "source"}])
        idx, audit = W.prior_activity_index([path])
        assert not idx and audit[0]["eligible"] is False
        assert "EXPLICITLY_QUARANTINED_TRANSITION_TAPE" in audit[0]["reasons"]


def test_determinism_and_raw_print_preservation():
    rows = [_print(3, .83), _print(0, .80), _print(1, .80)]
    original_ids = {r["print_id"] for r in rows}
    first = _clusters(rows)
    second = _clusters(list(reversed(rows)))
    assert [x["execution_cluster_id"] for x in first] == [x["execution_cluster_id"] for x in second]
    assert {r["print_id"] for r in rows} == original_ids
    assert all(r["kind"] == "strategy_candidate" for r in rows)


def test_event_time_price_and_multileg_moneyness_propagation():
    raw = W._fake_spread("B C230 / S C240", net=8000.0)
    raw["underlying_price"] = 235.0
    raw["underlying_price_source"] = "US_NVDA_2026-08-25.csv:update_time/last_price"
    raw["underlying_price_observed_at"] = "2026-08-25T11:59:55.000"
    raw["underlying_price_age_seconds"] = 5.0
    rec = W.normalize_inferred_spread("2026-08-25", raw)
    assert rec["underlying_price_at_event"] == 235.0
    assert rec["underlying_price_source"] == raw["underlying_price_source"]
    assert rec["underlying_price_observed_at"] == raw["underlying_price_observed_at"]
    assert rec["underlying_price_age_seconds"] == 5.0
    assert [x["strike_distance_dollars"] for x in rec["strike_distance"]] == [5.0, -5.0]
    assert [x["moneyness"] for x in rec["strike_distance"]] == ["ITM", "OTM"]
    clusters = W.build_execution_clusters("2026-08-25", [rec])
    idx = {rec["print_id"]: rec}
    orientations = W.build_orientation_theses("2026-08-25", clusters, idx)
    activities = W.build_contract_set_activities("2026-08-25", orientations, idx)
    for derived in (clusters[0], orientations[0], activities[0]):
        assert derived["underlying_price_at_event"] == 235.0
        assert derived["underlying_price_source"] == raw["underlying_price_source"]
        assert derived["underlying_price_observed_at"] == raw["underlying_price_observed_at"]
        assert derived["underlying_price_age_seconds"] == 5.0
        assert len(derived["strike_distance"]) == 2


def test_missing_price_stays_unknown_and_replay_does_not_use_current_price():
    rec = W.normalize_inferred_spread("2026-08-25", W._fake_spread("B C230 / S C240"))
    assert rec["underlying_price_at_event"] is None
    assert rec["underlying_price_source"] == "UNKNOWN"
    assert all(x["moneyness"] == "UNKNOWN" for x in rec["strike_distance"])
    # A live/current-price-like field is not consulted by historical replay.
    W._fake_spread("B C230 / S C240")["current_price"] = 999.0
    assert rec["underlying_price_at_event"] is None
    legacy = W._fake_spread("B C230 / S C240")
    legacy["underlying_last"] = 999.0
    legacy["last_underlying_price"] = 998.0
    legacy["underlying_price_at_event"] = None
    assert W.normalize_inferred_spread("2026-08-25", legacy)["underlying_price_at_event"] is None


def test_itm_atm_otm_calculation():
    legs = [W.Leg("BUY", "C", 100), W.Leg("BUY", "P", 100), W.Leg("C", "C", 110)]
    assert [x["moneyness"] for x in W.leg_price_metrics(legs, 100)] == ["ATM", "ATM", "OTM"]
    assert W.leg_price_metrics([W.Leg("BUY", "P", 100)], 101)[0]["moneyness"] == "OTM"


def test_monitoring_state_machine_and_outcome_disables_high_frequency():
    activity = {"monitoring_state": "DETECTED", "monitoring_history": [], "analysis_created_at": "2026-08-25T12:00:00"}
    W.advance_monitoring_state(activity, "start")
    assert activity["monitoring_state"] == "ACTIVE_MONITOR"
    W.advance_monitoring_state(activity, "outcome_captured", "BULLISH_FOLLOW_THROUGH", "2026-08-26T12:00:00")
    assert activity["monitoring_state"] == "OUTCOME_CAPTURED"
    assert activity["high_frequency_monitoring_active"] is False
    assert activity["low_frequency_lifecycle_active"] is True
    W.advance_monitoring_state(activity, "low_frequency", at="2026-08-27T12:00:00")
    assert activity["monitoring_state"] == "LOW_FREQUENCY_LIFECYCLE"
    assert activity["high_frequency_monitoring_active"] is False
    assert activity["low_frequency_lifecycle_active"] is True
    W.advance_monitoring_state(activity, "expiry", at="2026-08-28T12:00:00")
    assert activity["monitoring_state"] == "CLOSED_OR_EXPIRED"


def test_abnormal_activity_seeds_monitoring_and_normal_activity_does_not():
    rows = [_print(0, legs="B C230 / S C240"), _print(1, legs="S C230 / B C240")]
    clusters = _clusters(rows)
    idx = {r["print_id"]: r for r in rows}
    orientations = W.build_orientation_theses("2026-08-25", clusters, idx)
    activities = W.build_contract_set_activities("2026-08-25", orientations, idx)
    assert activities[0]["direction_status"] == "DIRECTION_CONFLICT"
    assert activities[0]["monitoring_state"] == "ACTIVE_MONITOR"
    assert activities[0]["monitoring_history"][0]["state"] == "DETECTED"
    assert activities[0]["low_frequency_monitoring_scope"] == [
        "repeated_flow", "opposite_flow", "t_plus_1_open_interest", "expiry"]
    W.advance_monitoring_state(activities[0], "outcome_captured", "BULLISH_FOLLOW_THROUGH",
                                "2026-08-26T12:00:00")
    assert activities[0]["outcome_label"] == "NO_DIRECTIONAL_FOLLOW_THROUGH_LABEL"
    assert activities[0]["high_frequency_monitoring_active"] is False
    assert activities[0]["low_frequency_lifecycle_active"] is True
    normal = W.build_contract_set_activities("2026-08-25", W.build_orientation_theses("2026-08-25", _clusters([_print(0)]), {rows[0]["print_id"]: rows[0]}), idx)
    assert normal[0]["direction_status"] == "CONSISTENT"
    assert normal[0]["monitoring_state"] == "ACTIVE_MONITOR"
    assert normal[0]["underlying_price_at_event"] is None


def test_weak_directional_structure_is_not_monitorable():
    rec = _print(0, legs="B C230 / S C240")
    rec["link_confidence_band"] = "WEAK"
    clusters = _clusters([rec])
    idx = {rec["print_id"]: rec}
    orientations = W.build_orientation_theses("2026-08-25", clusters, idx)
    activities = W.build_contract_set_activities("2026-08-25", orientations, idx)
    assert activities == []


def test_expiry_closes_monitoring():
    activity = {"monitoring_state": "ACTIVE_MONITOR", "monitoring_history": [], "analysis_created_at": "2026-08-25T12:00:00",
                "legs": [{"expiry": "250825"}]}
    assert W.monitoring_expired(activity, "2026-08-25") is True
    W.advance_monitoring_state(activity, "expiry")
    assert activity["monitoring_state"] == "CLOSED_OR_EXPIRED"


def test_no_trade_and_paper_only_contract():
    rows = W.analyze("2026-08-25", os.path.join(os.path.dirname(__file__), "data/alerts/alerts_2026-08-25.jsonl"),
                     os.path.join(os.path.dirname(__file__), "data/whale"))
    assert all(r.get("paper_only") is True for r in rows)
    assert all("trade" not in str(r.get("action", "")).lower() or r.get("action") == "NO_TRADE_FROM_WHALE_V0_3_3" for r in rows)


def test_byte_identical_replay_under_frozen_time():
    base = os.path.dirname(os.path.abspath(__file__))
    alerts = os.path.join(base, "data/alerts/alerts_2026-08-25.jsonl")
    W.set_run_time("2026-08-27T09:00:00")
    first = [W.json_dump_line(r) for r in W.analyze("2026-08-25", alerts, os.path.join(base, "data/whale"))]
    W.set_run_time("2026-08-27T09:00:00")
    second = [W.json_dump_line(r) for r in W.analyze("2026-08-25", alerts, os.path.join(base, "data/whale"))]
    assert first == second


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"test_whale.py: PASS ({len(tests)} tests)")


if __name__ == "__main__":
    main()
