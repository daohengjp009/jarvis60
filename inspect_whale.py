#!/usr/bin/env python3
"""Audit the PRINT -> CLUSTER -> ORIENTATION -> CONTRACT_SET hierarchy."""
import collections
import json
import sys

path = sys.argv[1]
sym = sys.argv[2] if len(sys.argv) > 2 else None
rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
if sym:
    rows = [r for r in rows if r.get("symbol") == sym]

prints = [r for r in rows if r.get("observation_level") == "PRINT" or r.get("kind") == "strategy_candidate"]
clusters = [r for r in rows if r.get("kind") == "execution_cluster"]
orientations = [r for r in rows if r.get("kind") == "orientation_thesis"]
activities = [r for r in rows if r.get("kind") == "contract_set_activity"]
print(f"{len(prints)} PRINT records" + (f" for {sym}" if sym else ""))
print("bands:", dict(collections.Counter(r.get("link_confidence_band") for r in prints)))
print(f"hierarchy: {len(clusters)} execution clusters -> {len(orientations)} orientation theses -> {len(activities)} contract-set activities")

eligible = [r for r in activities if r.get("directional_bias_eligible")]
print(f"directionally eligible contract sets: {len(eligible)}; conflicts excluded: {len(activities) - len(eligible)}")
print("\nper contract-set activity:")
for activity in sorted(activities, key=lambda r: r.get("position_key") or ""):
    ids = set(activity.get("orientation_thesis_ids") or [])
    cs = [r for r in orientations if r.get("orientation_thesis_id") in ids]
    print(f"  {activity.get('position_key')}")
    print(f"    status={activity.get('direction_status')} prints={activity.get('raw_print_count')} clusters={activity.get('execution_cluster_count')} orientations={len(cs)}")
    print(f"    signed_net_premium={activity.get('signed_net_premium_sum', 0):,.0f} premium_turnover={activity.get('premium_turnover_sum', 0):,.0f} gross_leg_turnover={activity.get('gross_leg_turnover_sum', 0):,.0f} (diagnostic)")
    cluster_ids = {cid for x in cs for cid in (x.get("execution_cluster_ids") or [])}
    for cluster in clusters:
        if cluster.get("execution_cluster_id") in cluster_ids:
            print(f"    cluster {cluster['execution_cluster_id']}: n={cluster['print_count']} lots={cluster['lots_sum']:,.0f} {cluster['first_mkt_time']}..{cluster['last_mkt_time']} premium={cluster['premium_per_spread_min']:.2f}..{cluster['premium_per_spread_max']:.2f}")
