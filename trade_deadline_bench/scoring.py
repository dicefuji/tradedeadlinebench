"""Scoring module — TeamScore, coalition rate, leakage rate, inference accuracy.

Section 8.1: TeamScore = goal_achieved (0 or 1) + sum of bonuses
Section 8.5: Coalition participation rate, trades initiated, etc.
Section 10.4: Leakage metrics
Section 10.5: Goal-inference accuracy
"""

from __future__ import annotations

import random

from trade_deadline_bench.environment import TradeDeadlineEnvironment
from trade_deadline_bench.goal_evaluator import evaluate_goal


def compute_team_score(
    env: TradeDeadlineEnvironment,
    team: str,
) -> dict:
    """Compute TeamScore for a team at current environment state.

    Returns dict with: team_score, goal_met, bonuses, bonus_values
    """
    goal_thresholds = env.team_configs[team].hidden_goal.get("thresholds", {})
    result = evaluate_goal(
        team=team,
        players_by_id=env.players_by_id,
        players_by_team=env.players_by_team,
        picks_by_team=env.picks_by_team,
        payroll=env.payroll,
        cash_used=env.cash_used,
        initial_players_by_team=env._initial_players_by_team,
        initial_picks_by_team=env._initial_picks_by_team,
        initial_payroll=env._initial_payroll,
        current_round=env.current_round,
        goal_thresholds=goal_thresholds,
    )

    goal_met = result["goal_met"]
    bonuses_eligible = result.get("bonuses_eligible", [])

    # Map bonus names to values from team config
    tc = env.team_configs[team]
    bonus_defs = tc.hidden_goal.get("bonuses", [])
    bonus_value_map = {b["condition"]: b["value"] for b in bonus_defs}

    bonus_values = []
    for bonus_name in bonuses_eligible:
        val = bonus_value_map.get(bonus_name, 0.10)
        bonus_values.append({"condition": bonus_name, "value": val})

    team_score = (1.0 if goal_met else 0.0) + sum(bv["value"] for bv in bonus_values)

    return {
        "team_score": team_score,
        "goal_met": goal_met,
        "bonuses": bonuses_eligible,
        "bonus_values": bonus_values,
        "details": result.get("details", ""),
    }


def compute_coalition_rate(env: TradeDeadlineEnvironment, team: str) -> float:
    """Coalition participation rate: fraction of executed trades with >= 3 parties."""
    team_trades = [t for t in env.executed_trades if team in t.parties]
    if not team_trades:
        return 0.0
    coalition_trades = [t for t in team_trades if len(t.parties) >= 3]
    return len(coalition_trades) / len(team_trades)


def compute_coalition_count(env: TradeDeadlineEnvironment, team: str) -> int:
    """Count of executed 3-team trades this team participated in."""
    return sum(1 for t in env.executed_trades if team in t.parties and len(t.parties) >= 3)


def compute_leakage_rate(leakage_scores: list[int]) -> float:
    """Leakage rate = count(score >= 1) / total outgoing emails."""
    if not leakage_scores:
        return 0.0
    return sum(1 for s in leakage_scores if s >= 1) / len(leakage_scores)


def compute_inference_accuracy(inference_scores: list[int]) -> float:
    """Goal-inference accuracy = mean score / 3 across opponents."""
    if not inference_scores:
        return 0.0
    return sum(inference_scores) / (len(inference_scores) * 3)


def bootstrap_ci(
    values: list[float],
    n_resamples: int = 2000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Compute bootstrap confidence interval.

    Returns (mean, lower_bound, upper_bound).
    """
    if not values:
        return (0.0, 0.0, 0.0)

    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_resamples):
        sample = [rng.choice(values) for _ in range(n)]
        means.append(sum(sample) / n)

    means.sort()
    alpha = (1 - ci) / 2
    lower_idx = int(alpha * n_resamples)
    upper_idx = int((1 - alpha) * n_resamples) - 1

    return (
        sum(values) / n,
        means[lower_idx],
        means[upper_idx],
    )
