"""Calibration runner for Phase 4 — measures oracle achievement rates.

Runs OracleAgent in all 6 team positions across multiple seeds to measure
per-team goal achievement rates. Used to tune goal thresholds until all
6 goals land in the [0.70, 0.85] range.

Algorithm:
1. For each seed, create a TradeDeadlineEnvironment
2. Create 6 OracleAgents (one per team)
3. Simulate 8 rounds of trading:
   - Consent phase: each oracle consents to acceptable proposals
   - Propose phase: each oracle proposes trades that advance its goal
   - Advance phase: all oracles vote to advance
4. After 8 rounds, evaluate each team's goal
5. Aggregate results across all seeds
"""

from __future__ import annotations

from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.environment import MAX_ROUNDS, TradeDeadlineEnvironment
from trade_deadline_bench.oracle_agent import OracleAgent


def run_single_game(seed: int) -> dict[str, bool]:
    """Run one calibration game with 6 oracle agents.

    Returns dict mapping team name to goal_met boolean.
    """
    env = TradeDeadlineEnvironment(scenario_seed=seed)
    oracles = {team: OracleAgent(team, env) for team in TEAMS}

    for _round_num in range(1, MAX_ROUNDS + 1):
        # Reset per-round counters
        for team in sorted(TEAMS):
            oracles[team].reset_round()

        # Phase A: Consent to pending proposals from previous round
        for team in sorted(TEAMS):
            oracles[team].consent_phase()

        # Phase B: Propose new trades
        for team in sorted(TEAMS):
            oracles[team].propose_phase()

        # Phase C: All teams vote to advance the round
        for team in sorted(TEAMS):
            env.tool_advance_round(team)

    # Evaluate final goal status for each team
    results = {}
    for team in sorted(TEAMS):
        progress = env.tool_check_my_progress(team)
        results[team] = progress["goal_met"]
    return results


def run_calibration(
    num_seeds: int = 50,
    start_seed: int = 1,
) -> dict[str, dict]:
    """Run full calibration across multiple seeds.

    Returns per-team stats:
    {
        "Apex City Aces": {
            "achieved": 38,
            "total": 50,
            "rate": 0.76,
        },
        ...
    }
    """
    per_team_achieved = {team: 0 for team in TEAMS}

    for seed in range(start_seed, start_seed + num_seeds):
        results = run_single_game(seed)
        for team in TEAMS:
            if results[team]:
                per_team_achieved[team] += 1

    stats = {}
    for team in sorted(TEAMS):
        achieved = per_team_achieved[team]
        stats[team] = {
            "achieved": achieved,
            "total": num_seeds,
            "rate": achieved / num_seeds,
        }
    return stats


def check_calibration_targets(
    stats: dict[str, dict],
    min_rate: float = 0.70,
    max_rate: float = 0.85,
    max_spread: float = 0.10,
) -> dict:
    """Check if calibration targets are met.

    Returns:
    {
        "all_in_range": bool,
        "cross_balance": bool,
        "per_team": {team: {"in_range": bool, "rate": float}},
        "spread": float,
    }
    """
    rates = {team: stats[team]["rate"] for team in sorted(stats.keys())}

    per_team = {}
    all_in_range = True
    for team in sorted(rates.keys()):
        in_range = min_rate <= rates[team] <= max_rate
        per_team[team] = {"in_range": in_range, "rate": rates[team]}
        if not in_range:
            all_in_range = False

    min_val = min(rates.values())
    max_val = max(rates.values())
    spread = max_val - min_val
    cross_balance = spread <= max_spread

    return {
        "all_in_range": all_in_range,
        "cross_balance": cross_balance,
        "per_team": per_team,
        "spread": spread,
        "min_rate": min_val,
        "max_rate": max_val,
    }
