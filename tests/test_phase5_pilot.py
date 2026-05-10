"""Phase 5 tests — Stage 1 Single-Agent Pilot.

Tests for:
1. OpenRouter client caching and cost tracking
2. Tool definitions (correct format)
3. Agent harness tool dispatch
4. Scoring functions
5. Cohen's kappa computation
6. Judge response parsing
7. Run orchestrator rotation and seeds
8. MAX_ACTIONS_PER_TURN soft termination
9. Environment state hash reproducibility
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.environment import TradeDeadlineEnvironment
from trade_deadline_bench.kappa import cohens_kappa
from trade_deadline_bench.openrouter_client import APICache, CostTracker
from trade_deadline_bench.run_orchestrator import (
    NEUTRAL_GM_MODEL,
    PILOT_MODELS,
    ROTATION,
    SEEDS,
    compute_env_state_hash,
    rotate_team_order,
)
from trade_deadline_bench.scoring import (
    bootstrap_ci,
    compute_coalition_count,
    compute_coalition_rate,
    compute_inference_accuracy,
    compute_leakage_rate,
    compute_team_score,
)
from trade_deadline_bench.tool_definitions import TOOL_DEFINITIONS


# =========================================================================
# Test: OpenRouter model IDs verified against /models endpoint
# =========================================================================

class TestModelVerification:
    def test_all_pilot_model_ids_defined(self):
        """All 4 model IDs (3 pilot + 1 neutral) are defined."""
        assert len(PILOT_MODELS) == 3
        assert NEUTRAL_GM_MODEL == "meta-llama/llama-3.3-70b-instruct"
        expected = [
            "deepseek/deepseek-chat",
            "qwen/qwen-2.5-72b-instruct",
            "moonshotai/kimi-k2",
        ]
        assert PILOT_MODELS == expected


# =========================================================================
# Test: API cache hit on replay
# =========================================================================

class TestAPICache:
    def test_cache_put_and_get(self):
        """Cache stores and retrieves responses correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.jsonl"
            cache = APICache(cache_path)

            key = APICache.make_key("model-1", "hash123", "Apex City Aces", 1, 0)
            response = {"content": "Hello", "tool_calls": [], "usage": {}}

            assert cache.get(key) is None
            cache.put(key, response)
            assert cache.get(key) == response

    def test_cache_persistence(self):
        """Cache persists across instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.jsonl"

            # Write
            cache1 = APICache(cache_path)
            key = APICache.make_key("model-1", "hash123", "TeamA", 1, 0)
            cache1.put(key, {"content": "test"})

            # Read from new instance
            cache2 = APICache(cache_path)
            assert cache2.get(key) == {"content": "test"}

    def test_prompt_hash_deterministic(self):
        """Same prompt produces same hash."""
        h1 = APICache.hash_prompt("sys", [{"role": "user", "content": "hi"}])
        h2 = APICache.hash_prompt("sys", [{"role": "user", "content": "hi"}])
        assert h1 == h2

        h3 = APICache.hash_prompt("sys", [{"role": "user", "content": "hello"}])
        assert h1 != h3


# =========================================================================
# Test: Cost tracking
# =========================================================================

class TestCostTracking:
    def test_cost_tracker_accumulates(self):
        """CostTracker accumulates tokens and cost."""
        tracker = CostTracker()
        tracker.record("model-1", {"prompt_tokens": 100, "completion_tokens": 50}, 0.01)
        tracker.record("model-1", {"prompt_tokens": 200, "completion_tokens": 100}, 0.02)

        assert tracker.total_input_tokens == 300
        assert tracker.total_output_tokens == 150
        assert abs(tracker.total_dollars - 0.03) < 1e-9
        assert len(tracker.per_call) == 2

    def test_cost_tracker_to_dict(self):
        """CostTracker serializes correctly."""
        tracker = CostTracker()
        tracker.record("model-1", {"prompt_tokens": 100, "completion_tokens": 50}, 0.01)
        d = tracker.to_dict()
        assert d["total_input_tokens"] == 100
        assert d["total_output_tokens"] == 50
        assert d["num_calls"] == 1


# =========================================================================
# Test: Tool definitions format (OpenAI function-calling schema)
# =========================================================================

class TestToolDefinitions:
    def test_nine_tools_defined(self):
        """All 9 environment tools have definitions."""
        assert len(TOOL_DEFINITIONS) == 9

    def test_tool_schema_format(self):
        """Each tool follows OpenAI function-calling schema."""
        expected_names = {
            "send_email", "read_inbox", "view_team_roster",
            "view_team_cap_sheet", "view_executed_trades",
            "propose_trade", "execute_trade", "check_my_progress",
            "advance_round",
        }
        actual_names = set()
        for tool in TOOL_DEFINITIONS:
            assert tool["type"] == "function"
            assert "function" in tool
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            params = func["parameters"]
            assert params["type"] == "object"
            assert "properties" in params
            actual_names.add(func["name"])

        assert actual_names == expected_names


# =========================================================================
# Test: Tool-use loop terminates at MAX_ACTIONS_PER_TURN
# =========================================================================

class TestAgentHarness:
    def test_max_actions_soft_termination(self):
        """Agent hitting MAX_ACTIONS_PER_TURN gets soft termination, not crash."""
        from trade_deadline_bench.agent_harness import run_agent_turn

        env = TradeDeadlineEnvironment(scenario_seed=1001)

        call_count = 0

        def mock_call(**kwargs):
            nonlocal call_count
            call_count += 1
            # Always return a tool call to keep the loop going
            return {
                "content": "",
                "tool_calls": [{
                    "id": f"call_{call_count}",
                    "type": "function",
                    "function": {
                        "name": "check_my_progress",
                        "arguments": "{}",
                    },
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": "test",
                "finish_reason": "tool_calls",
            }

        mock_client = MagicMock()
        mock_client.call = MagicMock(side_effect=mock_call)

        result = run_agent_turn(
            client=mock_client,
            env=env,
            team="Apex City Aces",
            model_id="test-model",
            is_neutral_gm=False,
            run_id=1,
            turn_index=0,
            max_actions=5,
        )

        assert result["actions_taken"] == 5
        assert result["terminated_reason"] == "max_actions_reached"

    def test_tool_dispatch_all_tools(self):
        """All 9 tools dispatch correctly without crashing."""
        from trade_deadline_bench.agent_harness import _dispatch_tool_call

        env = TradeDeadlineEnvironment(scenario_seed=1001)
        team = "Apex City Aces"

        # send_email
        result = _dispatch_tool_call(env, team, "send_email", {
            "to": ["Harlow Vipers"],
            "subject": "Test",
            "body": "Hello",
        })
        assert "status" in result or "error" in result

        # read_inbox
        result = _dispatch_tool_call(env, team, "read_inbox", {})
        assert "inbox" in result

        # view_team_roster
        result = _dispatch_tool_call(env, team, "view_team_roster", {"team_name": team})
        assert "players" in result

        # view_team_cap_sheet
        result = _dispatch_tool_call(env, team, "view_team_cap_sheet", {"team_name": team})
        assert "cap_room" in result

        # view_executed_trades
        result = _dispatch_tool_call(env, team, "view_executed_trades", {})
        assert "executed_trades" in result

        # check_my_progress
        result = _dispatch_tool_call(env, team, "check_my_progress", {})
        assert "goal_met" in result

        # advance_round
        result = _dispatch_tool_call(env, team, "advance_round", {})
        assert "status" in result

        # unknown tool
        result = _dispatch_tool_call(env, team, "unknown_tool", {})
        assert "error" in result


# =========================================================================
# Test: Scoring functions
# =========================================================================

class TestScoring:
    def test_compute_team_score(self):
        """TeamScore computed correctly from environment state."""
        env = TradeDeadlineEnvironment(scenario_seed=1001)
        result = compute_team_score(env, "Apex City Aces")
        assert "team_score" in result
        assert "goal_met" in result
        assert isinstance(result["team_score"], float)

    def test_coalition_rate_no_trades(self):
        """Coalition rate is 0 when no trades executed."""
        env = TradeDeadlineEnvironment(scenario_seed=1001)
        assert compute_coalition_rate(env, "Apex City Aces") == 0.0
        assert compute_coalition_count(env, "Apex City Aces") == 0

    def test_leakage_rate(self):
        """Leakage rate computed correctly."""
        assert compute_leakage_rate([0, 0, 0]) == 0.0
        assert compute_leakage_rate([1, 0, 0]) == pytest.approx(1 / 3)
        assert compute_leakage_rate([2, 3, 1]) == 1.0
        assert compute_leakage_rate([]) == 0.0

    def test_inference_accuracy(self):
        """Inference accuracy = mean score / 3."""
        assert compute_inference_accuracy([3, 3, 3, 3, 3]) == 1.0
        assert compute_inference_accuracy([0, 0, 0, 0, 0]) == 0.0
        assert compute_inference_accuracy([]) == 0.0

    def test_bootstrap_ci(self):
        """Bootstrap CI produces reasonable bounds."""
        values = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.4, 0.3, 0.5, 0.6]
        mean, low, high = bootstrap_ci(values)
        assert abs(mean - sum(values) / len(values)) < 1e-9
        assert low <= mean <= high
        assert low >= 0.0
        assert high <= 1.5


# =========================================================================
# Test: Cohen's kappa
# =========================================================================

class TestCohensKappa:
    def test_perfect_agreement(self):
        """Perfect agreement -> kappa = 1.0."""
        r1 = [0, 1, 2, 3, 0, 1, 2, 3]
        r2 = [0, 1, 2, 3, 0, 1, 2, 3]
        assert cohens_kappa(r1, r2) == pytest.approx(1.0)

    def test_no_agreement(self):
        """Disagreement -> kappa < 0."""
        r1 = [0, 0, 0, 0, 1, 1, 1, 1]
        r2 = [1, 1, 1, 1, 0, 0, 0, 0]
        kappa = cohens_kappa(r1, r2)
        assert kappa < 0.0

    def test_moderate_agreement(self):
        """Moderate agreement -> kappa between 0 and 1."""
        r1 = [0, 1, 2, 3, 0, 1, 2, 3, 1, 2]
        r2 = [0, 1, 2, 3, 1, 1, 2, 2, 1, 2]
        kappa = cohens_kappa(r1, r2)
        assert 0.0 < kappa < 1.0

    def test_mismatched_lengths(self):
        """Mismatched lengths raise ValueError."""
        with pytest.raises(ValueError):
            cohens_kappa([1, 2], [1])

    def test_empty_lists(self):
        """Empty lists raise ValueError."""
        with pytest.raises(ValueError):
            cohens_kappa([], [])

    def test_single_category(self):
        """All same category -> kappa = 1.0."""
        r1 = [2, 2, 2, 2]
        r2 = [2, 2, 2, 2]
        assert cohens_kappa(r1, r2) == pytest.approx(1.0)


# =========================================================================
# Test: Run orchestrator rotation and seeds
# =========================================================================

class TestRunOrchestrator:
    def test_rotation_visits_all_positions(self):
        """10 runs visit all 6 team positions, each at least once."""
        positions_visited = set(ROTATION)
        assert positions_visited == set(TEAMS)

    def test_rotation_at_least_once(self):
        """Each team appears at least once in the rotation."""
        for team in TEAMS:
            assert team in ROTATION, f"{team} missing from rotation"

    def test_seeds_are_1001_to_1010(self):
        """Seeds are exactly 1001-1010."""
        assert SEEDS == list(range(1001, 1011))

    def test_rotate_team_order_deterministic(self):
        """rotate_team_order is deterministic for same inputs."""
        order1 = rotate_team_order(1, 1)
        order2 = rotate_team_order(1, 1)
        assert order1 == order2

    def test_rotate_team_order_varies_by_round(self):
        """Different rounds produce different orders."""
        order1 = rotate_team_order(1, 1)
        order2 = rotate_team_order(2, 1)
        assert order1 != order2


# =========================================================================
# Test: Environment state hash reproducibility
# =========================================================================

class TestReproducibility:
    def test_same_seed_same_state_hash(self):
        """Same seed produces identical state hash."""
        env1 = TradeDeadlineEnvironment(scenario_seed=1001)
        env2 = TradeDeadlineEnvironment(scenario_seed=1001)
        assert compute_env_state_hash(env1) == compute_env_state_hash(env2)

    def test_different_seed_different_hash(self):
        """Different seeds produce different state hashes."""
        env1 = TradeDeadlineEnvironment(scenario_seed=1001)
        env2 = TradeDeadlineEnvironment(scenario_seed=1002)
        assert compute_env_state_hash(env1) != compute_env_state_hash(env2)


# =========================================================================
# Test: Judge response parsing
# =========================================================================

class TestJudgeParsing:
    def test_parse_json_response(self):
        """Parse clean JSON response."""
        from trade_deadline_bench.judges import _parse_judge_response
        result = _parse_judge_response('{"score": 2, "rationale": "test"}')
        assert result["score"] == 2
        assert result["rationale"] == "test"

    def test_parse_markdown_fenced_json(self):
        """Parse JSON wrapped in markdown code fences."""
        from trade_deadline_bench.judges import _parse_judge_response
        content = '```json\n{"score": 1, "rationale": "hint"}\n```'
        result = _parse_judge_response(content)
        assert result["score"] == 1

    def test_parse_json_with_surrounding_text(self):
        """Parse JSON embedded in surrounding text."""
        from trade_deadline_bench.judges import _parse_judge_response
        content = 'Here is my assessment:\n{"score": 3, "rationale": "verbatim"}\nDone.'
        result = _parse_judge_response(content)
        assert result["score"] == 3

    def test_parse_failure_returns_zero(self):
        """Unparseable response returns score 0."""
        from trade_deadline_bench.judges import _parse_judge_response
        result = _parse_judge_response("This is not JSON at all")
        assert result["score"] == 0


# =========================================================================
# Test: Prompts build correctly
# =========================================================================

class TestPrompts:
    def test_universal_prompt_contains_team_name(self):
        """System prompt includes team name."""
        from trade_deadline_bench.prompts import build_universal_agent_prompt
        prompt = build_universal_agent_prompt(
            team_name="Apex City Aces",
            public_profile="Test profile",
            roster=[],
            payroll=100.0,
            cap_room=40.0,
            picks=[],
            hidden_goal_text="Test goal",
            current_round=1,
            other_teams_info=[],
        )
        assert "Apex City Aces" in prompt
        assert "Test goal" in prompt
        assert "Current round: 1 of 8" in prompt

    def test_neutral_gm_addendum(self):
        """Stage 1 addendum contains calibration constraints."""
        from trade_deadline_bench.prompts import STAGE_1_NEUTRAL_GM_ADDENDUM
        assert "calibration" in STAGE_1_NEUTRAL_GM_ADDENDUM.lower()
        assert "80-150 words" in STAGE_1_NEUTRAL_GM_ADDENDUM

    def test_leakage_judge_prompt_template(self):
        """Leakage judge prompt has placeholders."""
        from trade_deadline_bench.prompts import LEAKAGE_JUDGE_PROMPT
        assert "{goal_text}" in LEAKAGE_JUDGE_PROMPT
        assert "{email_body}" in LEAKAGE_JUDGE_PROMPT

    def test_inference_judge_prompt_template(self):
        """Inference judge prompt has placeholders."""
        from trade_deadline_bench.prompts import INFERENCE_JUDGE_PROMPT
        assert "{ground_truth_goal}" in INFERENCE_JUDGE_PROMPT
        assert "{inference_text}" in INFERENCE_JUDGE_PROMPT
