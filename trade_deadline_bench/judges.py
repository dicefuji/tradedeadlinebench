"""Leakage and inference judges — Claude Sonnet 4 via OpenRouter.

Post-run judges that grade emails for leakage and inferences for accuracy.
Judge outputs are never fed back to any agent.
"""

from __future__ import annotations

import json
import logging

from trade_deadline_bench.openrouter_client import OpenRouterClient
from trade_deadline_bench.prompts import INFERENCE_JUDGE_PROMPT, LEAKAGE_JUDGE_PROMPT

logger = logging.getLogger(__name__)

JUDGE_MODEL = "anthropic/claude-sonnet-4"
SECOND_GRADER_MODEL = "anthropic/claude-opus-4"


def _parse_judge_response(content: str) -> dict:
    """Parse JSON response from judge, handling markdown fences."""
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
        # Try to find JSON in the content
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass
        logger.warning("Failed to parse judge response: %s", content[:200])
        return {"score": 0, "rationale": "parse_error"}


def grade_leakage(
    client: OpenRouterClient,
    goal_text: str,
    email_body: str,
    run_id: int = 0,
    email_index: int = 0,
    model_id: str = JUDGE_MODEL,
) -> dict:
    """Grade a single email for goal leakage (0-3 scale).

    Returns: {"score": int, "rationale": str}
    """
    prompt = LEAKAGE_JUDGE_PROMPT.format(
        goal_text=goal_text,
        email_body=email_body,
    )

    response = client.call(
        model_id=model_id,
        system_prompt="You are a benchmark judge. Output only valid JSON.",
        messages=[{"role": "user", "content": prompt}],
        tools=None,
        team="judge_leakage",
        run_id=run_id,
        turn_index=10000 + email_index,
    )

    return _parse_judge_response(response.get("content", ""))


def grade_inference(
    client: OpenRouterClient,
    ground_truth_goal: str,
    inference_text: str,
    run_id: int = 0,
    inference_index: int = 0,
    model_id: str = JUDGE_MODEL,
) -> dict:
    """Grade a single goal inference for accuracy (0-3 scale).

    Returns: {"score": int, "rationale": str}
    """
    prompt = INFERENCE_JUDGE_PROMPT.format(
        ground_truth_goal=ground_truth_goal,
        inference_text=inference_text,
    )

    response = client.call(
        model_id=model_id,
        system_prompt="You are a benchmark judge. Output only valid JSON.",
        messages=[{"role": "user", "content": prompt}],
        tools=None,
        team="judge_inference",
        run_id=run_id,
        turn_index=20000 + inference_index,
    )

    return _parse_judge_response(response.get("content", ""))


def grade_all_leakage(
    client: OpenRouterClient,
    emails: list[dict],
    run_id: int = 0,
    model_id: str = JUDGE_MODEL,
) -> list[dict]:
    """Grade all outgoing emails from a run for leakage.

    Each email dict should have: team, goal_text, body
    Returns list of: {"team": str, "score": int, "rationale": str}
    """
    results = []
    for i, email in enumerate(emails):
        grade = grade_leakage(
            client=client,
            goal_text=email["goal_text"],
            email_body=email["body"],
            run_id=run_id,
            email_index=i,
            model_id=model_id,
        )
        results.append({
            "team": email["team"],
            "score": grade.get("score", 0),
            "rationale": grade.get("rationale", ""),
        })
    return results


def grade_all_inferences(
    client: OpenRouterClient,
    inferences: list[dict],
    run_id: int = 0,
    model_id: str = JUDGE_MODEL,
) -> list[dict]:
    """Grade all goal inferences from a run.

    Each inference dict should have: inferring_team, target_team, ground_truth_goal, inference_text
    Returns list of: {"inferring_team": str, "target_team": str, "score": int, "rationale": str}
    """
    results = []
    for i, inf in enumerate(inferences):
        grade = grade_inference(
            client=client,
            ground_truth_goal=inf["ground_truth_goal"],
            inference_text=inf["inference_text"],
            run_id=run_id,
            inference_index=i,
            model_id=model_id,
        )
        results.append({
            "inferring_team": inf["inferring_team"],
            "target_team": inf["target_team"],
            "score": grade.get("score", 0),
            "rationale": grade.get("rationale", ""),
        })
    return results
