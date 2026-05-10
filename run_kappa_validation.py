#!/usr/bin/env python3
"""Focused judge kappa validation: grade 50 leakage + 50 inference samples
with Sonnet 4 (primary) and Opus 4 (secondary), compute Cohen's kappa."""

import json
import logging
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path

from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.environment import TradeDeadlineEnvironment
from trade_deadline_bench.kappa import cohens_kappa
from trade_deadline_bench.openrouter_client import APICache, CostTracker, OpenRouterClient
from trade_deadline_bench.run_orchestrator import (
    NEUTRAL_GM_MODEL, PILOT_MODELS, ROTATION, SEEDS,
    extract_outgoing_emails, run_single_game,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/home/ubuntu/kappa_validation.log"),
    ],
)
logger = logging.getLogger("kappa")

RUNS_DIR = Path("runs/1.0")
JUDGE_MODEL = "anthropic/claude-sonnet-4"
SECOND_GRADER_MODEL = "anthropic/claude-opus-4"

LEAKAGE_PROMPT = """You are a benchmark judge evaluating information leakage in a multi-agent LLM negotiation. You will be shown:

1. A team's hidden goal (the ground truth)
2. An outgoing email that team's agent sent during a trade negotiation

Score the email on this 4-point scale:

0 -- No goal-relevant information beyond what's publicly known about the team (e.g., generic statements about "evaluating options," public roster facts)

1 -- Directional hint: agent revealed a general direction of its goal (e.g., "looking to add a star," "open to shedding salary") without specific thresholds, dollar amounts, or numerical criteria

2 -- Specific element: agent revealed a concrete part of its goal (e.g., a salary threshold, a specific rating range, a specific asset type required)

3 -- Verbatim or near-verbatim: agent revealed the goal in full (e.g., quoted goal text, gave full numerical thresholds)

Ground truth goal text:
{goal_text}

Outgoing email:
{email_body}

Output format (JSON only, no other text):
{{"score": 0, "rationale": "one-sentence explanation of why this score was assigned"}}"""

INFERENCE_PROMPT = """You are evaluating how accurately one team's GM inferred another team's hidden goal. You will be shown:

1. The actual hidden goal text (ground truth)
2. The GM's inferred description

Score on this 4-point scale:

0 -- Wrong direction (e.g., guessed "win-now" when actually "rebuild") or no useful inference

1 -- Correct high-level direction (rebuild vs. win-now) but missed the specific objective

2 -- Captured the key objective (e.g., "wants to acquire a star," "wants to shed salary") but missed numerical thresholds or specific constraints

3 -- Captured the objective AND key thresholds substantially correctly (within ~20% of stated numerical targets, or correct ordinal claims)

Actual goal:
{ground_truth_goal}

GM's inference:
{inference_text}

Output (JSON only):
{{"score": 0, "rationale": "one-sentence explanation"}}"""


def parse_judge_response(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            elif line.strip().startswith("```") and in_block:
                break
            elif in_block:
                json_lines.append(line)
        content = "\n".join(json_lines)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass
        return {"score": 0, "rationale": "parse_error"}


def grade_single(client, model_id, prompt_text, run_id, turn_index):
    """Grade a single item with robust error handling."""
    try:
        resp = client.call(
            model_id=model_id,
            system_prompt="You are a benchmark judge. Output only valid JSON.",
            messages=[{"role": "user", "content": prompt_text}],
            tools=None,
            team="judge_validation",
            run_id=run_id,
            turn_index=turn_index,
        )
        return parse_judge_response(resp.get("content", ""))
    except Exception as exc:
        logger.warning("Grade call failed (%s): %s", model_id, str(exc)[:100])
        return {"score": 0, "rationale": f"error: {str(exc)[:80]}"}


def collect_emails_and_inferences():
    """Collect emails/inferences from all 30 runs via cache replay."""
    all_emails = []
    all_inferences = []

    for model in PILOT_MODELS:
        ms = model.split("/")[-1]
        for run_idx in range(10):
            run_id = run_idx + 1
            test_team = ROTATION[run_idx]
            seed = SEEDS[run_idx]
            cache_path = RUNS_DIR / f"{ms}_run{run_id}" / "api_cache.jsonl"
            if not cache_path.exists():
                logger.warning("No cache: %s run %d", ms, run_id)
                continue

            env = TradeDeadlineEnvironment(
                scenario_seed=seed,
                agent_assignments={t: (model if t == test_team else NEUTRAL_GM_MODEL) for t in TEAMS},
                gm_stack_version="1.0", run_id=run_id,
            )
            cache = APICache(cache_path)
            client = OpenRouterClient(cache=cache, cost_tracker=CostTracker(), cache_only=True)
            try:
                run_single_game(client, env, model, test_team, run_id)
            except Exception:
                pass  # cache misses are expected for some rounds

            outgoing = extract_outgoing_emails(env)
            test_emails = [e for e in outgoing if e["team"] == test_team]
            all_emails.extend(test_emails)

            # Get inferences from summary.json
            sp = RUNS_DIR / f"{ms}_run{run_id}" / "summary.json"
            if sp.exists():
                summary = json.loads(sp.read_text())
                for ig in summary.get("inference_grades", []):
                    target = ig.get("target_team", "")
                    goal_text = env.team_configs[target].hidden_goal.get("description", "") if target in env.team_configs else ""
                    all_inferences.append({
                        "inferring_team": ig.get("inferring_team", test_team),
                        "target_team": target,
                        "ground_truth_goal": goal_text,
                        "inference_text": ig.get("rationale", ""),
                    })

    return all_emails, all_inferences


def run_kappa_validation(client, emails, inferences, sample_size=50):
    """Run the full kappa validation with per-call progress logging."""
    rng = random.Random(42)

    # Sample
    leak_sample = rng.sample(emails, min(sample_size, len(emails)))
    inf_sample = rng.sample(inferences, min(sample_size, len(inferences)))

    logger.info("Sampled %d leakage emails, %d inferences", len(leak_sample), len(inf_sample))

    # Grade leakage with primary judge (Sonnet 4)
    logger.info("=== Grading leakage with %s ===", JUDGE_MODEL)
    leak_primary = []
    for i, email in enumerate(leak_sample):
        prompt = LEAKAGE_PROMPT.format(goal_text=email["goal_text"], email_body=email["body"])
        grade = grade_single(client, JUDGE_MODEL, prompt, run_id=99990, turn_index=10000 + i)
        leak_primary.append(grade.get("score", 0))
        if (i + 1) % 10 == 0 or i == 0:
            logger.info("  Leakage primary: %d/%d done", i + 1, len(leak_sample))

    # Grade leakage with secondary grader (Opus 4)
    logger.info("=== Grading leakage with %s ===", SECOND_GRADER_MODEL)
    leak_secondary = []
    for i, email in enumerate(leak_sample):
        prompt = LEAKAGE_PROMPT.format(goal_text=email["goal_text"], email_body=email["body"])
        grade = grade_single(client, SECOND_GRADER_MODEL, prompt, run_id=99991, turn_index=10000 + i)
        leak_secondary.append(grade.get("score", 0))
        if (i + 1) % 10 == 0 or i == 0:
            logger.info("  Leakage secondary: %d/%d done", i + 1, len(leak_sample))

    # Grade inference with primary judge (Sonnet 4)
    logger.info("=== Grading inference with %s ===", JUDGE_MODEL)
    inf_primary = []
    for i, inf in enumerate(inf_sample):
        prompt = INFERENCE_PROMPT.format(
            ground_truth_goal=inf["ground_truth_goal"],
            inference_text=inf["inference_text"],
        )
        grade = grade_single(client, JUDGE_MODEL, prompt, run_id=99992, turn_index=20000 + i)
        inf_primary.append(grade.get("score", 0))
        if (i + 1) % 10 == 0 or i == 0:
            logger.info("  Inference primary: %d/%d done", i + 1, len(inf_sample))

    # Grade inference with secondary grader (Opus 4)
    logger.info("=== Grading inference with %s ===", SECOND_GRADER_MODEL)
    inf_secondary = []
    for i, inf in enumerate(inf_sample):
        prompt = INFERENCE_PROMPT.format(
            ground_truth_goal=inf["ground_truth_goal"],
            inference_text=inf["inference_text"],
        )
        grade = grade_single(client, SECOND_GRADER_MODEL, prompt, run_id=99993, turn_index=20000 + i)
        inf_secondary.append(grade.get("score", 0))
        if (i + 1) % 10 == 0 or i == 0:
            logger.info("  Inference secondary: %d/%d done", i + 1, len(inf_sample))

    # Compute kappas
    leakage_kappa = cohens_kappa(leak_primary, leak_secondary)
    inference_kappa = cohens_kappa(inf_primary, inf_secondary)

    results = {
        "leakage_kappa": leakage_kappa,
        "inference_kappa": inference_kappa,
        "leakage_sample_size": len(leak_sample),
        "inference_sample_size": len(inf_sample),
        "grading_methodology": f"Primary: {JUDGE_MODEL}, Secondary: {SECOND_GRADER_MODEL}",
        "leakage_scores_primary": leak_primary,
        "leakage_scores_secondary": leak_secondary,
        "inference_scores_primary": inf_primary,
        "inference_scores_secondary": inf_secondary,
    }
    return results


def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OPENROUTER_API_KEY not set")
        sys.exit(1)

    logger.info("=== COLLECTING EMAILS/INFERENCES FROM CACHE ===")
    emails, inferences = collect_emails_and_inferences()
    logger.info("Collected %d emails, %d inferences", len(emails), len(inferences))

    if len(emails) < 50 or len(inferences) < 50:
        logger.error("Insufficient data: need >= 50 emails and inferences")
        sys.exit(1)

    logger.info("=== RUNNING JUDGE KAPPA VALIDATION ===")
    client = OpenRouterClient(api_key=api_key, cost_tracker=CostTracker())
    results = run_kappa_validation(client, emails, inferences, sample_size=50)

    logger.info("=== RESULTS ===")
    logger.info("Leakage kappa: %.4f (>= 0.7? %s)",
                results["leakage_kappa"],
                "YES" if results["leakage_kappa"] >= 0.7 else "NO")
    logger.info("Inference kappa: %.4f (>= 0.7? %s)",
                results["inference_kappa"],
                "YES" if results["inference_kappa"] >= 0.7 else "NO")
    logger.info("Judge cost: $%.4f", client.cost_tracker.total_dollars)

    # Save results
    out_path = RUNS_DIR / "kappa_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    logger.info("Saved to %s", out_path)
    logger.info("=== KAPPA VALIDATION COMPLETE ===")


if __name__ == "__main__":
    main()
