#!/usr/bin/env python3
"""Post-pilot validation: cache replay + judge kappas + final report."""

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path

from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.environment import TradeDeadlineEnvironment
from trade_deadline_bench.openrouter_client import APICache, CostTracker, OpenRouterClient
from trade_deadline_bench.run_orchestrator import (
    NEUTRAL_GM_MODEL, PILOT_MODELS, ROTATION, SEEDS,
    compute_env_state_hash, extract_outgoing_emails,
    generate_pilot_report, run_single_game, validate_judge_kappas,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("validation")
RUNS_DIR = Path("runs/1.0")


def load_all_summaries():
    summaries = []
    for model in PILOT_MODELS:
        ms = model.split("/")[-1]
        for rid in range(1, 11):
            p = RUNS_DIR / f"{ms}_run{rid}" / "summary.json"
            if p.exists():
                summaries.append(json.loads(p.read_text()))
    return summaries


def replay_run_from_cache(model, run_idx):
    ms = model.split("/")[-1]
    run_id = run_idx + 1
    test_team = ROTATION[run_idx]
    seed = SEEDS[run_idx]
    cache_path = RUNS_DIR / f"{ms}_run{run_id}" / "api_cache.jsonl"
    if not cache_path.exists():
        return None, "no cache file"
    env = TradeDeadlineEnvironment(
        scenario_seed=seed,
        agent_assignments={t: (model if t == test_team else NEUTRAL_GM_MODEL) for t in TEAMS},
        gm_stack_version="1.0", run_id=run_id,
    )
    cache = APICache(cache_path)
    client = OpenRouterClient(cache=cache, cost_tracker=CostTracker(), cache_only=True)
    try:
        run_single_game(client, env, model, test_team, run_id)
        return env, ""
    except Exception as exc:
        return None, str(exc)[:200]


def verify_cache_replay(sample_runs):
    results = []
    for model, run_idx in sample_runs:
        ms = model.split("/")[-1]
        run_id = run_idx + 1
        sp = RUNS_DIR / f"{ms}_run{run_id}" / "summary.json"
        if not sp.exists():
            results.append({"model": model, "run_id": run_id, "status": "SKIP"})
            continue
        original_hash = json.loads(sp.read_text()).get("env_state_hash", "")
        t0 = time.time()
        env, err = replay_run_from_cache(model, run_idx)
        elapsed = round(time.time() - t0, 1)
        if env is None:
            results.append({"model": model, "run_id": run_id, "status": "ERROR", "reason": err, "elapsed_seconds": elapsed})
            logger.warning("Cache replay %s run %d: ERROR (%s)", ms, run_id, err[:80])
            continue
        replay_hash = compute_env_state_hash(env)
        match = replay_hash == original_hash
        results.append({"model": model, "run_id": run_id, "status": "PASS" if match else "FAIL",
                        "original_hash": original_hash, "replay_hash": replay_hash, "match": match, "elapsed_seconds": elapsed})
        logger.info("Cache replay %s run %d: %s in %.1fs", ms, run_id, "PASS" if match else "FAIL", elapsed)
    return results


def collect_emails_for_kappa(run_indices):
    all_emails, all_inferences = [], []
    for model, run_idx in run_indices:
        ms = model.split("/")[-1]
        run_id = run_idx + 1
        test_team = ROTATION[run_idx]
        env, err = replay_run_from_cache(model, run_idx)
        if env is None:
            logger.warning("Skipping %s run %d: %s", ms, run_id, err[:80])
            continue
        outgoing = extract_outgoing_emails(env)
        all_emails.extend([e for e in outgoing if e["team"] == test_team])
        sp = RUNS_DIR / f"{ms}_run{run_id}" / "summary.json"
        if sp.exists():
            summary = json.loads(sp.read_text())
            for ig in summary.get("inference_grades", []):
                target = ig.get("target_team", "")
                goal_text = env.team_configs[target].hidden_goal.get("description", "") if target in env.team_configs else ""
                all_inferences.append({"inferring_team": ig.get("inferring_team", test_team),
                                       "target_team": target, "ground_truth_goal": goal_text,
                                       "inference_text": ig.get("rationale", "")})
    return all_emails, all_inferences


def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OPENROUTER_API_KEY not set")
        sys.exit(1)
    summaries = load_all_summaries()
    logger.info("Loaded %d summaries", len(summaries))

    # Step 1: Cache replay
    logger.info("=== CACHE REPLAY VERIFICATION ===")
    sample_runs = [
        (PILOT_MODELS[0], 0), (PILOT_MODELS[0], 4),
        (PILOT_MODELS[1], 2), (PILOT_MODELS[1], 7),
        (PILOT_MODELS[2], 5),
    ]
    replay_results = verify_cache_replay(sample_runs)
    (RUNS_DIR / "cache_replay_results.json").write_text(json.dumps(replay_results, indent=2))

    # Step 2: Collect emails/inferences
    logger.info("=== COLLECTING EMAILS/INFERENCES ===")
    all_run_indices = [(m, i) for m in PILOT_MODELS for i in range(10)]
    all_emails, all_inferences = collect_emails_for_kappa(all_run_indices)
    logger.info("Collected %d emails, %d inferences", len(all_emails), len(all_inferences))

    # Step 3: Judge kappa validation
    logger.info("=== JUDGE KAPPA VALIDATION ===")
    judge_client = OpenRouterClient(api_key=api_key, cost_tracker=CostTracker())
    kappa_results = validate_judge_kappas(judge_client, all_emails, all_inferences, sample_size=50)
    logger.info("Leakage kappa: %.4f (>= 0.7? %s)", kappa_results["leakage_kappa"],
                "YES" if kappa_results["leakage_kappa"] >= 0.7 else "NO")
    logger.info("Inference kappa: %.4f (>= 0.7? %s)", kappa_results["inference_kappa"],
                "YES" if kappa_results["inference_kappa"] >= 0.7 else "NO")
    (RUNS_DIR / "kappa_results.json").write_text(json.dumps(kappa_results, indent=2))

    # Step 4: Final report
    logger.info("=== GENERATING FINAL REPORT ===")
    report = generate_pilot_report(summaries, kappa_results)
    report["cache_replay_results"] = replay_results
    (RUNS_DIR / "pilot_report.json").write_text(json.dumps(report, indent=2))

    logger.info("Total runs: %d, Total cost: \$%.4f", report["total_runs"], report["total_cost"])
    logger.info("Leakage kappa: %.4f, Inference kappa: %.4f", report["leakage_judge_kappa"], report["inference_judge_kappa"])
    for mr in report["model_reports"]:
        logger.info("%s: mean=%.3f [%.3f, %.3f] goal=%.0f%% leak=%.3f inf=%.3f cost=\$%.2f",
                    mr["model"], mr["mean_team_score"], mr["ci_95_low"], mr["ci_95_high"],
                    mr["goal_achievement_rate"]*100, mr["mean_leakage_rate"], mr["mean_inference_accuracy"], mr["total_cost"])
    cache_pass = sum(1 for r in replay_results if r["status"] == "PASS")
    logger.info("Cache replay: %d/%d passed", cache_pass, len(replay_results))
    logger.info("=== VALIDATION COMPLETE ===")


if __name__ == "__main__":
    main()
