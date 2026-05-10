"""Run orchestrator — manages Stage 1 pilot runs.

Handles team-position rotation, seed management, round orchestration,
per-run summary generation, cost tracking, and judge invocation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from trade_deadline_bench.agent_harness import run_agent_turn, run_goal_inference_probe
from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.environment import MAX_ROUNDS, TradeDeadlineEnvironment
from trade_deadline_bench.judges import (
    JUDGE_MODEL,
    SECOND_GRADER_MODEL,
    grade_all_inferences,
    grade_all_leakage,
)
from trade_deadline_bench.kappa import cohens_kappa
from trade_deadline_bench.openrouter_client import APICache, CostTracker, OpenRouterClient
from trade_deadline_bench.scoring import (
    bootstrap_ci,
    compute_coalition_count,
    compute_coalition_rate,
    compute_inference_accuracy,
    compute_leakage_rate,
    compute_team_score,
)

logger = logging.getLogger(__name__)

# Pilot models (open-source via OpenRouter)
PILOT_MODELS = [
    "deepseek/deepseek-chat",
    "qwen/qwen-2.5-72b-instruct",
    "moonshotai/kimi-k2",
]

NEUTRAL_GM_MODEL = "meta-llama/llama-3.3-70b-instruct"

# Team-position rotation per NOTE 5 (same for all 3 pilot models)
ROTATION = [
    "Apex City Aces",       # Run 1
    "Harlow Vipers",        # Run 2
    "Eastgate Titans",      # Run 3
    "Ironwood Foxes",       # Run 4
    "Cascade Wolves",       # Run 5
    "Granite Bay Bulls",    # Run 6
    "Apex City Aces",       # Run 7
    "Harlow Vipers",        # Run 8
    "Cascade Wolves",       # Run 9
    "Eastgate Titans",      # Run 10
]

# Scenario seeds: 1001-1010 (one per run)
SEEDS = list(range(1001, 1011))

# Cost guardrails
COST_ALERT_PER_RUN = 2.0
COST_HALT_CUMULATIVE = 40.0


def rotate_team_order(current_round: int, run_id: int) -> list[str]:
    """Rotate the order in which teams act each round."""
    teams = list(TEAMS)
    offset = (current_round - 1 + run_id) % len(teams)
    return teams[offset:] + teams[:offset]


def compute_env_state_hash(env: TradeDeadlineEnvironment) -> str:
    """Compute a SHA-256 hash of the full environment state for reproducibility."""
    state = {
        "current_round": env.current_round,
        "players_by_team": {
            t: sorted(pids) for t, pids in sorted(env.players_by_team.items())
        },
        "players_by_id": {
            pid: {
                "talent_rating": p.talent_rating,
                "current_team": p.current_team,
                "aav": round(p.aav, 4),
            }
            for pid, p in sorted(env.players_by_id.items())
        },
        "picks_by_team": {
            t: sorted([dp.pick_id for dp in picks])
            for t, picks in sorted(env.picks_by_team.items())
        },
        "payroll": {t: round(v, 4) for t, v in sorted(env.payroll.items())},
        "cash_used": {t: round(v, 4) for t, v in sorted(env.cash_used.items())},
        "executed_trades": [
            {
                "trade_id": et.trade_id,
                "parties": sorted(et.parties),
            }
            for et in env.executed_trades
        ],
        "advance_votes": sorted(env.advance_votes),
    }
    state_json = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(state_json.encode()).hexdigest()


def run_single_game(
    client: OpenRouterClient,
    env: TradeDeadlineEnvironment,
    test_model: str,
    test_team: str,
    run_id: int,
) -> dict:
    """Run a single 8-round game with one model under test + 5 neutral GMs.

    Returns per-round metadata and final state.
    """
    turn_counter = 0
    round_logs = []

    for round_num in range(1, MAX_ROUNDS + 1):
        if env.current_round > MAX_ROUNDS:
            break

        round_order = rotate_team_order(env.current_round, run_id)
        round_log = {"round": env.current_round, "turns": []}

        for team in round_order:
            is_test_model = (team == test_team)
            model_id = test_model if is_test_model else NEUTRAL_GM_MODEL
            is_neutral = not is_test_model

            turn_result = run_agent_turn(
                client=client,
                env=env,
                team=team,
                model_id=model_id,
                is_neutral_gm=is_neutral,
                run_id=run_id,
                turn_index=turn_counter,
            )
            turn_counter += turn_result["actions_taken"] + 1

            round_log["turns"].append({
                "team": team,
                "model": model_id,
                "actions": turn_result["actions_taken"],
                "advanced": turn_result["advanced_round"],
                "terminated": turn_result["terminated_reason"],
            })

            # Force-advance check for stuck agents
            if not turn_result["advanced_round"]:
                force_advanced = env.force_advance_check(team)
                if force_advanced:
                    logger.info("Force-advanced round after %s stuck", team)

        # Check if all teams have voted to advance
        if len(env.advance_votes) == len(TEAMS):
            env._advance_round()

        round_logs.append(round_log)

    return {
        "rounds_played": len(round_logs),
        "round_logs": round_logs,
        "final_round": env.current_round,
    }


def extract_outgoing_emails(env: TradeDeadlineEnvironment) -> list[dict]:
    """Extract all agent-sent emails (not SYSTEM) for leakage grading."""
    emails = []
    seen = set()
    for team in TEAMS:
        for msg in env.inboxes[team]:
            if msg.get("from") == "SYSTEM":
                continue
            # Deduplicate by (from, timestamp)
            key = (msg["from"], str(msg.get("timestamp")))
            if key in seen:
                continue
            seen.add(key)

            sender = msg["from"]
            goal_text = env.team_configs[sender].hidden_goal.get("description", "")
            emails.append({
                "team": sender,
                "goal_text": goal_text,
                "body": msg.get("body", ""),
                "subject": msg.get("subject", ""),
            })
    return emails


def run_pilot_run(
    test_model: str,
    run_index: int,
    api_key: str | None = None,
    runs_dir: str = "runs",
    gm_stack_version: str = "1.0",
    cumulative_cost: float = 0.0,
) -> dict:
    """Execute a single pilot run.

    Args:
        test_model: OpenRouter model ID for the model under test
        run_index: 0-indexed run number (0-9)
        api_key: OpenRouter API key (or from env)
        runs_dir: base directory for run artifacts
        gm_stack_version: version string
        cumulative_cost: running total cost for halt check

    Returns:
        Per-run summary dict.
    """
    test_team = ROTATION[run_index]
    seed = SEEDS[run_index]
    run_id = run_index + 1

    model_short = test_model.split("/")[-1]
    run_dir = Path(runs_dir) / gm_stack_version / f"{model_short}_run{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    cache = APICache(run_dir / "api_cache.jsonl")
    cost_tracker = CostTracker()
    client = OpenRouterClient(
        api_key=api_key,
        cache=cache,
        cost_tracker=cost_tracker,
    )

    env = TradeDeadlineEnvironment(
        scenario_seed=seed,
        agent_assignments={
            t: (test_model if t == test_team else NEUTRAL_GM_MODEL) for t in TEAMS
        },
        gm_stack_version=gm_stack_version,
        run_id=run_id,
    )

    logger.info(
        "Starting run %d: model=%s team=%s seed=%d",
        run_id, test_model, test_team, seed,
    )

    game_result = run_single_game(client, env, test_model, test_team, run_id)

    # Compute scores for the test team
    score_result = compute_team_score(env, test_team)
    coalition_rate = compute_coalition_rate(env, test_team)
    coalition_count = compute_coalition_count(env, test_team)

    # Run goal-inference probe on the test model
    inferences = run_goal_inference_probe(
        client, env, test_team, test_model, run_id
    )

    # Extract emails for leakage grading
    outgoing_emails = extract_outgoing_emails(env)
    test_emails = [e for e in outgoing_emails if e["team"] == test_team]

    # Grade leakage for test team emails
    leakage_grades = []
    if test_emails:
        leakage_grades = grade_all_leakage(
            client, test_emails, run_id=run_id
        )

    leakage_scores = [g["score"] for g in leakage_grades]
    leakage_rate = compute_leakage_rate(leakage_scores)

    # Grade inferences
    inference_items = []
    for target_team, inference_text in inferences.items():
        goal_text = env.team_configs[target_team].hidden_goal.get("description", "")
        inference_items.append({
            "inferring_team": test_team,
            "target_team": target_team,
            "ground_truth_goal": goal_text,
            "inference_text": inference_text,
        })

    inference_grades = []
    if inference_items:
        inference_grades = grade_all_inferences(
            client, inference_items, run_id=run_id
        )

    inference_scores_list = [g["score"] for g in inference_grades]
    inference_accuracy = compute_inference_accuracy(inference_scores_list)

    # Cost tracking
    run_cost = cost_tracker.total_dollars
    if run_cost > COST_ALERT_PER_RUN:
        logger.warning("Run %d cost $%.2f exceeds $%.2f alert threshold", run_id, run_cost, COST_ALERT_PER_RUN)

    new_cumulative = cumulative_cost + run_cost
    if new_cumulative > COST_HALT_CUMULATIVE:
        logger.error(
            "Cumulative cost $%.2f exceeds $%.2f halt threshold",
            new_cumulative, COST_HALT_CUMULATIVE,
        )

    # Build summary
    summary = {
        "model": test_model,
        "position": test_team,
        "seed": seed,
        "run_id": run_id,
        "team_score": score_result["team_score"],
        "goal_met": score_result["goal_met"],
        "bonuses": score_result["bonuses"],
        "coalition_count": coalition_count,
        "coalition_rate": coalition_rate,
        "leakage_rate": leakage_rate,
        "inference_accuracy": inference_accuracy,
        "cost_dollars": run_cost,
        "cost_details": cost_tracker.to_dict(),
        "rounds_played": game_result["rounds_played"],
        "env_state_hash": compute_env_state_hash(env),
        "leakage_grades": leakage_grades,
        "inference_grades": inference_grades,
    }

    # Write summary.json
    summary_path = run_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Write cost.json
    cost_path = run_dir / "cost.json"
    cost_data = {
        "model": test_model,
        "total_input_tokens": cost_tracker.total_input_tokens,
        "total_output_tokens": cost_tracker.total_output_tokens,
        "total_dollars": run_cost,
    }
    with open(cost_path, "w") as f:
        json.dump(cost_data, f, indent=2)

    logger.info(
        "Run %d complete: score=%.2f goal_met=%s cost=$%.4f",
        run_id, score_result["team_score"], score_result["goal_met"], run_cost,
    )

    return summary


def run_all_pilot_runs(
    api_key: str | None = None,
    runs_dir: str = "runs",
    gm_stack_version: str = "1.0",
) -> list[dict]:
    """Execute all 30 pilot runs (3 models x 10 runs each).

    Returns list of all 30 run summaries.
    """
    all_summaries = []
    cumulative_cost = 0.0

    for model in PILOT_MODELS:
        model_summaries = []
        for run_index in range(10):
            summary = run_pilot_run(
                test_model=model,
                run_index=run_index,
                api_key=api_key,
                runs_dir=runs_dir,
                gm_stack_version=gm_stack_version,
                cumulative_cost=cumulative_cost,
            )
            cumulative_cost += summary["cost_dollars"]
            model_summaries.append(summary)

            if cumulative_cost > COST_HALT_CUMULATIVE:
                logger.error(
                    "HALTING: Cumulative cost $%.2f exceeds $%.2f",
                    cumulative_cost, COST_HALT_CUMULATIVE,
                )
                all_summaries.extend(model_summaries)
                return all_summaries

        all_summaries.extend(model_summaries)

    return all_summaries


def validate_judge_kappas(
    client: OpenRouterClient,
    all_emails: list[dict],
    all_inferences: list[dict],
    sample_size: int = 50,
) -> dict:
    """Validate leakage and inference judges via Cohen's kappa.

    Uses Claude Sonnet 4 as primary judge and Claude Opus 4 as second grader.
    Returns kappa values and grading details.
    """
    import random
    rng = random.Random(42)

    # Sample emails for leakage validation
    leakage_sample = rng.sample(all_emails, min(sample_size, len(all_emails)))
    leakage_primary = grade_all_leakage(
        client, leakage_sample, run_id=99990, model_id=JUDGE_MODEL
    )
    leakage_secondary = grade_all_leakage(
        client, leakage_sample, run_id=99991, model_id=SECOND_GRADER_MODEL
    )

    leakage_scores_1 = [g["score"] for g in leakage_primary]
    leakage_scores_2 = [g["score"] for g in leakage_secondary]
    leakage_kappa = cohens_kappa(leakage_scores_1, leakage_scores_2)

    # Sample inferences for inference validation
    inference_sample = rng.sample(all_inferences, min(sample_size, len(all_inferences)))
    inference_primary = grade_all_inferences(
        client, inference_sample, run_id=99992, model_id=JUDGE_MODEL
    )
    inference_secondary = grade_all_inferences(
        client, inference_sample, run_id=99993, model_id=SECOND_GRADER_MODEL
    )

    inference_scores_1 = [g["score"] for g in inference_primary]
    inference_scores_2 = [g["score"] for g in inference_secondary]
    inference_kappa = cohens_kappa(inference_scores_1, inference_scores_2)

    return {
        "leakage_kappa": leakage_kappa,
        "inference_kappa": inference_kappa,
        "leakage_sample_size": len(leakage_sample),
        "inference_sample_size": len(inference_sample),
        "grading_methodology": f"Primary: {JUDGE_MODEL}, Secondary: {SECOND_GRADER_MODEL}",
        "leakage_scores_primary": leakage_scores_1,
        "leakage_scores_secondary": leakage_scores_2,
        "inference_scores_primary": inference_scores_1,
        "inference_scores_secondary": inference_scores_2,
    }


def generate_pilot_report(summaries: list[dict], kappa_results: dict) -> dict:
    """Generate the final Phase 5 pilot report.

    Returns a structured report with all required metrics.
    """
    # Group by model
    by_model: dict[str, list[dict]] = {}
    for s in summaries:
        model = s["model"]
        if model not in by_model:
            by_model[model] = []
        by_model[model].append(s)

    model_reports = []
    for model, runs in sorted(by_model.items()):
        scores = [r["team_score"] for r in runs]
        mean_score, ci_low, ci_high = bootstrap_ci(scores)

        goal_rates = [1.0 if r["goal_met"] else 0.0 for r in runs]
        coalition_rates = [r["coalition_rate"] for r in runs]
        leakage_rates = [r["leakage_rate"] for r in runs]
        inference_accs = [r["inference_accuracy"] for r in runs]
        costs = [r["cost_dollars"] for r in runs]

        model_reports.append({
            "model": model,
            "num_runs": len(runs),
            "mean_team_score": mean_score,
            "ci_95_low": ci_low,
            "ci_95_high": ci_high,
            "goal_achievement_rate": sum(goal_rates) / len(goal_rates),
            "mean_coalition_rate": sum(coalition_rates) / len(coalition_rates) if coalition_rates else 0.0,
            "mean_leakage_rate": sum(leakage_rates) / len(leakage_rates) if leakage_rates else 0.0,
            "mean_inference_accuracy": sum(inference_accs) / len(inference_accs) if inference_accs else 0.0,
            "total_cost": sum(costs),
            "mean_cost_per_run": sum(costs) / len(costs) if costs else 0.0,
        })

    total_cost = sum(s["cost_dollars"] for s in summaries)

    # Check for anomalies
    anomalies = []
    for s in summaries:
        if s["cost_dollars"] > COST_ALERT_PER_RUN:
            anomalies.append(f"Run {s['run_id']} ({s['model']}): cost ${s['cost_dollars']:.2f} > ${COST_ALERT_PER_RUN}")

    return {
        "model_reports": model_reports,
        "total_cost": total_cost,
        "total_runs": len(summaries),
        "leakage_judge_kappa": kappa_results["leakage_kappa"],
        "inference_judge_kappa": kappa_results["inference_kappa"],
        "grading_methodology": kappa_results["grading_methodology"],
        "anomalies": anomalies,
    }
