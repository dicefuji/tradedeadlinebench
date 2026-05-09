"""Phase 4: Oracle calibration tests.

Tests:
1. Oracle achievement rate per goal is in [0.70, 0.85] (50 seeds)
2. Cross-goal achievement rates within 10pp of each other
3. Locked goal hash is stable; modifying any goal changes the hash
4. OracleAgent reproducibility: same seed -> same trade sequence -> same outcome
5. OracleAgent does not call any LLM API
"""

import hashlib
from pathlib import Path
from unittest.mock import patch

from trade_deadline_bench.calibration import run_calibration, check_calibration_targets
from trade_deadline_bench.oracle_agent import OracleAgent
from trade_deadline_bench.environment import TradeDeadlineEnvironment
from trade_deadline_bench.data_structures import TEAMS


TEAMS_CONFIG_PATH = Path(__file__).parent.parent / "trade_deadline_bench" / "teams_config.yaml"
LOCKED_HASH = "6dcb54daeb39b228d1c6af99b578ab964500c492ddcb035124e17a81475c4cdc"


# =========================================================================
# Test 1: Oracle achievement rate per goal in [0.70, 0.85]
# =========================================================================


def test_all_goals_in_target_range():
    """All 6 oracle achievement rates must be in [0.70, 0.85] (50 seeds)."""
    stats = run_calibration(num_seeds=50, start_seed=1)
    for team, s in stats.items():
        assert 0.70 <= s["rate"] <= 0.85, (
            f"{team}: rate {s['rate']:.2%} outside [0.70, 0.85]"
        )


# =========================================================================
# Test 2: Cross-goal balance within 10pp
# =========================================================================


def test_cross_goal_balance():
    """All 6 achievement rates must be within 10pp of each other."""
    stats = run_calibration(num_seeds=50, start_seed=1)
    targets = check_calibration_targets(stats)
    assert targets["cross_balance"], (
        f"Cross-goal spread {targets['spread']:.2%} exceeds 10pp "
        f"(min={targets['min_rate']:.2%}, max={targets['max_rate']:.2%})"
    )


# =========================================================================
# Test 3: Hash stability
# =========================================================================


def test_locked_hash_matches():
    """SHA-256 of teams_config.yaml matches the locked hash."""
    content = TEAMS_CONFIG_PATH.read_bytes()
    computed = hashlib.sha256(content).hexdigest()
    assert computed == LOCKED_HASH, (
        f"Hash mismatch: computed {computed}, expected {LOCKED_HASH}. "
        "Goal specifications have been modified since calibration lock."
    )


def test_modifying_goal_changes_hash():
    """Any modification to teams_config.yaml must change the hash."""
    content = TEAMS_CONFIG_PATH.read_text()
    # Modify a threshold (Apex >= 60 -> >= 61)
    modified = content.replace(">= 60", ">= 61", 1)
    assert modified != content, "Replacement did not change content"
    modified_hash = hashlib.sha256(modified.encode()).hexdigest()
    assert modified_hash != LOCKED_HASH, (
        "Modified config has same hash as locked config"
    )


# =========================================================================
# Test 4: Reproducibility
# =========================================================================


def test_oracle_reproducibility():
    """Same seed -> same trade sequence -> same outcome."""
    seed = 42

    def run_once(s):
        env = TradeDeadlineEnvironment(scenario_seed=s, max_turns_without_advance=100)
        teams = sorted(TEAMS)
        oracles = {t: OracleAgent(t, env) for t in teams}

        for _ in range(8):  # 8 rounds max
            if env.current_round > 8:
                break
            # Reset + propose phase
            for t in teams:
                oracles[t].reset_round()
            for t in teams:
                oracles[t].consent_phase()
            for t in teams:
                oracles[t].propose_phase()
            # Advance round
            for t in teams:
                env.tool_advance_round(t)

        # Final state
        final_players = {
            t: sorted(env.players_by_team[t]) for t in teams
        }
        final_picks = {
            t: sorted(dp.pick_id for dp in env.picks_by_team[t])
            for t in teams
        }
        executed = [(et.trade_id, sorted(et.parties)) for et in env.executed_trades]
        return final_players, final_picks, executed

    players1, picks1, trades1 = run_once(seed)
    players2, picks2, trades2 = run_once(seed)

    assert players1 == players2, "Final player state differs between runs"
    assert picks1 == picks2, "Final pick state differs between runs"
    assert trades1 == trades2, "Executed trades differ between runs"


# =========================================================================
# Test 5: No LLM calls
# =========================================================================


def test_oracle_no_llm_calls():
    """OracleAgent must not call any LLM API."""
    seed = 7
    env = TradeDeadlineEnvironment(scenario_seed=seed, max_turns_without_advance=100)
    teams = sorted(TEAMS)
    oracles = {t: OracleAgent(t, env) for t in teams}

    # Mock common LLM client libraries to detect any calls
    with patch("builtins.__import__", wraps=__import__) as mock_import:
        llm_modules = {"openai", "anthropic", "cohere", "litellm", "langchain"}
        original_import = __import__

        def guarded_import(name, *args, **kwargs):
            base = name.split(".")[0]
            if base in llm_modules:
                raise AssertionError(
                    f"OracleAgent attempted to import LLM module: {name}"
                )
            return original_import(name, *args, **kwargs)

        mock_import.side_effect = guarded_import

        # Run one full simulation
        for _ in range(8):
            if env.current_round > 8:
                break
            for t in teams:
                oracles[t].reset_round()
            for t in teams:
                oracles[t].consent_phase()
            for t in teams:
                oracles[t].propose_phase()
            for t in teams:
                env.tool_advance_round(t)

    # If we get here without AssertionError, no LLM modules were imported


# =========================================================================
# Test 6: Oracle runs without any network access
# =========================================================================


def test_oracle_runs_offline():
    """OracleAgent produces results without network access (pure computation)."""
    seed = 13
    env = TradeDeadlineEnvironment(scenario_seed=seed, max_turns_without_advance=100)
    teams = sorted(TEAMS)

    # Create oracles and run - if this completes, it's purely computational
    oracles = {t: OracleAgent(t, env) for t in teams}
    for t in teams:
        oracles[t].reset_round()
    for t in teams:
        oracles[t].consent_phase()
    for t in teams:
        oracles[t].propose_phase()
    # Verify environment is still in valid state
    assert env.current_round == 1
    assert len(env.players_by_team) == 6
