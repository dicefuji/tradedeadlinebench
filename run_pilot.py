#!/usr/bin/env python3
"""Execute Phase 5 Stage 1 pilot runs.

Usage:
    python run_pilot.py                    # Run all 30 pilot runs
    python run_pilot.py --model 0 --run 0  # Run single (model_index, run_index)
    python run_pilot.py --test             # Single test run (model 0, run 0)
"""

import argparse
import json
import logging
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from trade_deadline_bench.run_orchestrator import (
    PILOT_MODELS,
    ROTATION,
    SEEDS,
    run_pilot_run,
)

# Force immediate flushing so log lines appear in real time even when
# output is redirected to a file.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
for _h in logging.root.handlers:
    if hasattr(_h, "stream"):
        import functools as _ft
        _orig_emit = _h.emit
        @_ft.wraps(_orig_emit)
        def _flushing_emit(record, _oe=_orig_emit, _hh=_h):
            _oe(record)
            if hasattr(_hh, "stream"):
                _hh.stream.flush()
        _h.emit = _flushing_emit
logger = logging.getLogger("pilot_runner")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=int, default=None, help="Model index (0-2)")
    parser.add_argument("--run", type=int, default=None, help="Run index (0-9)")
    parser.add_argument("--test", action="store_true", help="Single test run")
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OPENROUTER_API_KEY not set")
        sys.exit(1)

    runs_dir = "runs"
    gm_stack_version = "1.0"

    if args.test:
        logger.info("=== TEST RUN: model=0 run=0 ===")
        summary = run_pilot_run(
            test_model=PILOT_MODELS[0],
            run_index=0,
            api_key=api_key,
            runs_dir=runs_dir,
            gm_stack_version=gm_stack_version,
        )
        logger.info("Test run complete: score=%.2f cost=$%.4f", summary["team_score"], summary["cost_dollars"])
        print(json.dumps(summary, indent=2))
        return

    if args.model is not None and args.run is not None:
        model = PILOT_MODELS[args.model]
        logger.info("=== Single run: model=%s run=%d ===", model, args.run)
        summary = run_pilot_run(
            test_model=model,
            run_index=args.run,
            api_key=api_key,
            runs_dir=runs_dir,
            gm_stack_version=gm_stack_version,
        )
        logger.info("Run complete: score=%.2f cost=$%.4f", summary["team_score"], summary["cost_dollars"])
        print(json.dumps(summary, indent=2))
        return

    # Run all 30 pilot runs (with resume support)
    all_summaries = []
    cumulative_cost = 0.0

    # Check for already-completed runs and load their summaries
    for model_idx, model in enumerate(PILOT_MODELS):
        model_short = model.split("/")[-1]
        for run_idx in range(10):
            run_id = run_idx + 1
            run_dir = os.path.join(runs_dir, gm_stack_version, f"{model_short}_run{run_id}")
            summary_path = os.path.join(run_dir, "summary.json")
            if os.path.exists(summary_path):
                with open(summary_path) as f:
                    summary = json.load(f)
                cumulative_cost += summary.get("cost_dollars", 0.0)
                all_summaries.append(summary)
                logger.info(
                    "RESUME: Loaded %s run %d (score=%.2f cost=$%.4f)",
                    model, run_id, summary["team_score"], summary["cost_dollars"],
                )

    logger.info("Resumed %d completed runs, cumulative cost=$%.4f", len(all_summaries), cumulative_cost)

    for model_idx, model in enumerate(PILOT_MODELS):
        model_short = model.split("/")[-1]
        for run_idx in range(10):
            run_id = run_idx + 1
            team = ROTATION[run_idx]
            seed = SEEDS[run_idx]

            # Skip already-completed runs
            run_dir = os.path.join(runs_dir, gm_stack_version, f"{model_short}_run{run_id}")
            summary_path = os.path.join(run_dir, "summary.json")
            if os.path.exists(summary_path):
                continue

            logger.info(
                "=== Model %d/%d Run %d/10: %s as %s (seed %d) ===",
                model_idx + 1, len(PILOT_MODELS), run_id, model, team, seed,
            )
            try:
                summary = run_pilot_run(
                    test_model=model,
                    run_index=run_idx,
                    api_key=api_key,
                    runs_dir=runs_dir,
                    gm_stack_version=gm_stack_version,
                    cumulative_cost=cumulative_cost,
                )
                cumulative_cost += summary["cost_dollars"]
                all_summaries.append(summary)
                logger.info(
                    "  -> score=%.2f goal=%s cost=$%.4f cumulative=$%.4f",
                    summary["team_score"],
                    summary["goal_met"],
                    summary["cost_dollars"],
                    cumulative_cost,
                )

                if cumulative_cost > 40.0:
                    logger.error("HALTING: Cumulative cost $%.2f > $40", cumulative_cost)
                    break

            except Exception as e:
                logger.error("Run failed: %s", e)
                traceback.print_exc()
                all_summaries.append({
                    "model": model,
                    "run_id": run_id,
                    "error": str(e),
                })

        if cumulative_cost > 40.0:
            break

    # Write aggregate results
    os.makedirs(f"{runs_dir}/{gm_stack_version}", exist_ok=True)
    with open(f"{runs_dir}/{gm_stack_version}/all_summaries.json", "w") as f:
        json.dump(all_summaries, f, indent=2)

    logger.info("=== ALL RUNS COMPLETE ===")
    logger.info("Total runs: %d", len(all_summaries))
    logger.info("Total cost: $%.4f", cumulative_cost)

    # Print per-model summary
    by_model = {}
    for s in all_summaries:
        m = s.get("model", "unknown")
        if m not in by_model:
            by_model[m] = []
        by_model[m].append(s)

    for model, runs in sorted(by_model.items()):
        valid = [r for r in runs if "team_score" in r]
        if valid:
            scores = [r["team_score"] for r in valid]
            costs = [r["cost_dollars"] for r in valid]
            goals = [1 if r["goal_met"] else 0 for r in valid]
            logger.info(
                "%s: %d runs, mean_score=%.3f, goal_rate=%.1f%%, total_cost=$%.4f",
                model, len(valid),
                sum(scores) / len(scores),
                100 * sum(goals) / len(goals),
                sum(costs),
            )


if __name__ == "__main__":
    main()
