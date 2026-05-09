"""Goal evaluator tests -- 6 goal-met, 6 goal-not-met, 2+ bonus tests.

Tests exercise the evaluate_goal function by directly manipulating
environment state to simulate trades having occurred.
"""

import pytest

from trade_deadline_bench.data_structures import DraftPick, Player, TEAMS
from trade_deadline_bench.environment import TradeDeadlineEnvironment
from trade_deadline_bench.goal_evaluator import evaluate_goal


@pytest.fixture
def env():
    """Fresh environment seeded at 42."""
    return TradeDeadlineEnvironment(scenario_seed=42)


def _eval(env, team):
    """Shorthand: evaluate goal for a team using current env state."""
    goal_thresholds = env.team_configs[team].hidden_goal.get("thresholds", {})
    return evaluate_goal(
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


def _move_player(env, pid, from_team, to_team):
    """Simulate a player transfer (without full trade validation)."""
    env.players_by_team[from_team].remove(pid)
    env.players_by_team[to_team].append(pid)
    env.players_by_id[pid].current_team = to_team
    # Update payroll
    aav = env.players_by_id[pid].aav
    env.payroll[from_team] -= aav
    env.payroll[to_team] += aav


def _add_pick(env, to_team, pick_round=1, pick_id=None, protection="unprotected"):
    """Add a new pick to a team (simulating acquisition)."""
    if pick_id is None:
        pick_id = f"PICK-NEW-{len(env.picks_by_team[to_team]) + 1}"
    dp = DraftPick(
        pick_id=pick_id,
        owning_team=to_team,
        pick_round=pick_round,
        season_year=2027,
        protection_note=protection,
    )
    env.picks_by_team[to_team].append(dp)
    return dp


# =====================================================================
# Apex City Aces: Acquire one player rated >= 60
# =====================================================================


class TestApexGoal:
    def test_goal_not_met_initial_state(self, env):
        """Apex goal not met at start -- no player >= min_talent acquired."""
        result = _eval(env, "Apex City Aces")
        assert result["goal_met"] is False
        assert "No player rated >=" in result["details"]
        assert result["bonuses_eligible"] == []

    def test_goal_met_acquire_elite(self, env):
        """Apex goal met after acquiring a player rated >= 88."""
        # Find a player rated >= 88 on another team
        elite_pid = None
        source_team = None
        for team in TEAMS:
            if team == "Apex City Aces":
                continue
            for pid in env.players_by_team[team]:
                if env.players_by_id[pid].talent_rating >= 88:
                    elite_pid = pid
                    source_team = team
                    break
            if elite_pid:
                break

        assert elite_pid is not None, "No elite player found in scenario"
        _move_player(env, elite_pid, source_team, "Apex City Aces")

        result = _eval(env, "Apex City Aces")
        assert result["goal_met"] is True
        assert elite_pid in result["details"]

    def test_bonus_no_cash_used(self, env):
        """Apex bonus: achieved without using cash."""
        # Find elite player and move it
        elite_pid = None
        source_team = None
        for team in TEAMS:
            if team == "Apex City Aces":
                continue
            for pid in env.players_by_team[team]:
                if env.players_by_id[pid].talent_rating >= 88:
                    elite_pid = pid
                    source_team = team
                    break
            if elite_pid:
                break

        _move_player(env, elite_pid, source_team, "Apex City Aces")
        # cash_used is 0 by default
        assert env.cash_used["Apex City Aces"] == 0.0

        result = _eval(env, "Apex City Aces")
        assert result["goal_met"] is True
        assert "Achieved without using cash" in result["bonuses_eligible"]


# =====================================================================
# Harlow Vipers: Trade one star for package (player >= 78 + 1st round pick)
# =====================================================================


class TestHarlowGoal:
    def test_goal_not_met_initial_state(self, env):
        """Harlow goal not met at start -- no star traded."""
        result = _eval(env, "Harlow Vipers")
        assert result["goal_met"] is False
        assert "Neither designated star has been traded" in result["details"]
        assert result["bonuses_eligible"] == []

    def test_goal_met_star_traded_for_package(self, env):
        """Harlow goal met after trading a star for player >= 78 + 1st pick."""
        # Find Harlow's stars (top 2 tradeable by talent_rating)
        harlow_tradeable = sorted(
            [
                env.players_by_id[pid]
                for pid in env.players_by_team["Harlow Vipers"]
                if env.players_by_id[pid].is_tradeable
            ],
            key=lambda p: -p.talent_rating,
        )
        star = harlow_tradeable[0]

        # Create a synthetic player rated >= 78 on another team
        package_player = Player(
            player_id="P-SYNTH-HV-PKG",
            name="Strong Return Player",
            talent_rating=80,
            defense_rating=6,
            position="SG",
            age=24,
            aav=15.0,
            years_remaining=3,
            current_team="Apex City Aces",
            is_tradeable=True,
        )
        env.players_by_id["P-SYNTH-HV-PKG"] = package_player
        env.players_by_team["Apex City Aces"].append("P-SYNTH-HV-PKG")
        env.payroll["Apex City Aces"] += 15.0

        # Move star away from Harlow
        _move_player(env, star.player_id, "Harlow Vipers", "Apex City Aces")
        # Move package player to Harlow
        _move_player(env, "P-SYNTH-HV-PKG", "Apex City Aces", "Harlow Vipers")
        # Add a 1st-round pick to Harlow
        _add_pick(env, "Harlow Vipers", pick_round=1, pick_id="PICK-HV-BONUS-1")

        result = _eval(env, "Harlow Vipers")
        assert result["goal_met"] is True
        assert star.player_id in result["details"]


# =====================================================================
# Eastgate Titans: Acquire SF/PF rated 76-84, >= 2 years, salary <= $20M
# =====================================================================


class TestEastgateGoal:
    def test_goal_not_met_initial_state(self, env):
        """Eastgate goal not met at start -- no qualifying player acquired."""
        result = _eval(env, "Eastgate Titans")
        assert result["goal_met"] is False
        assert "No SF/PF player rated" in result["details"]
        assert result["bonuses_eligible"] == []

    def test_goal_met_acquire_qualifying_player(self, env):
        """Eastgate goal met after acquiring a qualifying SF/PF."""
        # Get thresholds from config
        gt = env.team_configs["Eastgate Titans"].hidden_goal.get("thresholds", {})
        min_t = gt.get("min_talent", 76)
        max_t = gt.get("max_talent", 84)
        min_yrs = gt.get("min_years", 2)
        max_sal = gt.get("max_salary", 20.0)

        # Find a qualifying SF/PF on another team
        target = None
        source_team = None
        for team in TEAMS:
            if team == "Eastgate Titans":
                continue
            for pid in env.players_by_team[team]:
                p = env.players_by_id[pid]
                if (
                    min_t <= p.talent_rating <= max_t
                    and p.position in ("SF", "PF")
                    and p.years_remaining >= min_yrs
                    and p.aav <= max_sal
                    and p.is_tradeable
                ):
                    target = p
                    source_team = team
                    break
            if target:
                break

        if target is None:
            # Create a synthetic player if none exists in this seed
            target = Player(
                player_id="P-SYNTH-ET",
                name="Synth Forward",
                talent_rating=72,
                defense_rating=7,
                position="SF",
                age=25,
                aav=8.0,
                years_remaining=3,
                current_team="Cascade Wolves",
                is_tradeable=True,
            )
            env.players_by_id["P-SYNTH-ET"] = target
            env.players_by_team["Cascade Wolves"].append("P-SYNTH-ET")
            env.payroll["Cascade Wolves"] += 8.0
            source_team = "Cascade Wolves"

        _move_player(env, target.player_id, source_team, "Eastgate Titans")

        result = _eval(env, "Eastgate Titans")
        assert result["goal_met"] is True
        assert target.player_id in result["details"]

    def test_bonus_3_plus_years(self, env):
        """Eastgate bonus: acquired player has 3+ years remaining."""
        # Create a qualifying player with 3+ years (must be in threshold range)
        target = Player(
            player_id="P-SYNTH-ET-3Y",
            name="Long Contract Forward",
            talent_rating=72,
            defense_rating=7,
            position="PF",
            age=24,
            aav=8.0,
            years_remaining=4,
            current_team="Ironwood Foxes",
            is_tradeable=True,
        )
        env.players_by_id["P-SYNTH-ET-3Y"] = target
        env.players_by_team["Ironwood Foxes"].append("P-SYNTH-ET-3Y")
        env.payroll["Ironwood Foxes"] += 8.0

        _move_player(env, "P-SYNTH-ET-3Y", "Ironwood Foxes", "Eastgate Titans")

        result = _eval(env, "Eastgate Titans")
        assert result["goal_met"] is True
        assert "Acquired player has 3+ years remaining" in result["bonuses_eligible"]


# =====================================================================
# Ironwood Foxes: Acquire two players with summed defense >= 17
# =====================================================================


class TestIronwoodGoal:
    def test_goal_not_met_initial_state(self, env):
        """Ironwood goal not met at start -- no acquisitions."""
        result = _eval(env, "Ironwood Foxes")
        assert result["goal_met"] is False
        assert "acquired" in result["details"].lower()
        assert result["bonuses_eligible"] == []

    def test_goal_met_acquire_defensive_pair(self, env):
        """Ironwood goal met after acquiring two players with defense sum >= 17."""
        # Create two high-defense players on other teams
        p1 = Player(
            player_id="P-DEF-1",
            name="Defensive Anchor",
            talent_rating=75,
            defense_rating=9,
            position="C",
            age=28,
            aav=8.0,
            years_remaining=2,
            current_team="Cascade Wolves",
            is_tradeable=True,
        )
        p2 = Player(
            player_id="P-DEF-2",
            name="Defensive Wing",
            talent_rating=73,
            defense_rating=9,
            position="SF",
            age=25,
            aav=7.0,
            years_remaining=3,
            current_team="Eastgate Titans",
            is_tradeable=True,
        )
        env.players_by_id["P-DEF-1"] = p1
        env.players_by_id["P-DEF-2"] = p2
        env.players_by_team["Cascade Wolves"].append("P-DEF-1")
        env.players_by_team["Eastgate Titans"].append("P-DEF-2")
        env.payroll["Cascade Wolves"] += 8.0
        env.payroll["Eastgate Titans"] += 7.0

        _move_player(env, "P-DEF-1", "Cascade Wolves", "Ironwood Foxes")
        _move_player(env, "P-DEF-2", "Eastgate Titans", "Ironwood Foxes")

        result = _eval(env, "Ironwood Foxes")
        assert result["goal_met"] is True
        assert "18" in result["details"]  # sum = 9+9 = 18

    def test_bonus_young_acquisition(self, env):
        """Ironwood bonus: at least one acquisition age <= 26."""
        p1 = Player(
            player_id="P-DEF-Y1",
            name="Young Defender",
            talent_rating=75,
            defense_rating=9,
            position="C",
            age=24,  # <= 26
            aav=8.0,
            years_remaining=2,
            current_team="Cascade Wolves",
            is_tradeable=True,
        )
        p2 = Player(
            player_id="P-DEF-Y2",
            name="Vet Defender",
            talent_rating=73,
            defense_rating=9,
            position="SF",
            age=30,
            aav=7.0,
            years_remaining=3,
            current_team="Eastgate Titans",
            is_tradeable=True,
        )
        env.players_by_id["P-DEF-Y1"] = p1
        env.players_by_id["P-DEF-Y2"] = p2
        env.players_by_team["Cascade Wolves"].append("P-DEF-Y1")
        env.players_by_team["Eastgate Titans"].append("P-DEF-Y2")
        env.payroll["Cascade Wolves"] += 8.0
        env.payroll["Eastgate Titans"] += 7.0

        _move_player(env, "P-DEF-Y1", "Cascade Wolves", "Ironwood Foxes")
        _move_player(env, "P-DEF-Y2", "Eastgate Titans", "Ironwood Foxes")

        result = _eval(env, "Ironwood Foxes")
        assert result["goal_met"] is True
        assert "At least one acquisition age <= 26" in result["bonuses_eligible"]


# =====================================================================
# Cascade Wolves: Acquire >= 2 first-round picks AND shed >= $25M salary
# =====================================================================


class TestCascadeGoal:
    def test_goal_not_met_initial_state(self, env):
        """Cascade goal not met at start -- no picks acquired, no salary shed."""
        result = _eval(env, "Cascade Wolves")
        assert result["goal_met"] is False
        assert result["bonuses_eligible"] == []

    def test_goal_met_picks_and_salary_shed(self, env):
        """Cascade goal met after acquiring 2 first-round picks + shedding $25M."""
        # Add 2 first-round picks to Cascade (acquired from other teams)
        _add_pick(env, "Cascade Wolves", pick_round=1, pick_id="PICK-CW-ACQ-1")
        _add_pick(env, "Cascade Wolves", pick_round=1, pick_id="PICK-CW-ACQ-2")

        # Shed salary: move expensive players away from Cascade
        # Need total_contract shed >= $25M
        # Find tradeable players on Cascade with high total_contract
        cascade_players = sorted(
            [
                env.players_by_id[pid]
                for pid in env.players_by_team["Cascade Wolves"]
                if env.players_by_id[pid].is_tradeable
            ],
            key=lambda p: -p.total_contract,
        )

        salary_shed = 0.0
        for p in cascade_players:
            if salary_shed >= 25.0:
                break
            _move_player(env, p.player_id, "Cascade Wolves", "Granite Bay Bulls")
            salary_shed += p.total_contract

        # If not enough, add a synthetic expensive player
        if salary_shed < 25.0:
            deficit = 25.0 - salary_shed + 1.0
            synth = Player(
                player_id="P-SYNTH-CW-EXP",
                name="Expensive Cascade Player",
                talent_rating=80,
                defense_rating=5,
                position="SG",
                age=30,
                aav=deficit / 2,
                years_remaining=2,
                current_team="Cascade Wolves",
                is_tradeable=True,
            )
            env.players_by_id["P-SYNTH-CW-EXP"] = synth
            env.players_by_team["Cascade Wolves"].append("P-SYNTH-CW-EXP")
            env._initial_players_by_team["Cascade Wolves"].append("P-SYNTH-CW-EXP")
            env.payroll["Cascade Wolves"] += synth.aav
            _move_player(env, "P-SYNTH-CW-EXP", "Cascade Wolves", "Granite Bay Bulls")

        result = _eval(env, "Cascade Wolves")
        assert result["goal_met"] is True
        assert "1st-round pick" in result["details"]


# =====================================================================
# Granite Bay Bulls: Cap room >= $12M, shed >= $20M AAV, rating loss <= 8
# =====================================================================


class TestGraniteBayGoal:
    def test_goal_not_met_initial_state(self, env):
        """Granite Bay goal not met at start -- no AAV shed."""
        result = _eval(env, "Granite Bay Bulls")
        assert result["goal_met"] is False
        assert result["bonuses_eligible"] == []

    def test_goal_met_shed_aav_low_rating_loss(self, env):
        """Granite Bay goal met: shed >= $20M AAV, cap room >= $12M, rating loss <= 8."""
        # GB starts at $140M payroll. To get cap room >= $12M, final payroll
        # must be <= $128M. Strategy: send expensive players away, receive
        # cheap players of similar talent back.
        # Send 4 players at $10M AAV (total $40M), receive 4 at $2M (total $8M).
        # Net AAV shed = $32M, net rating loss = 4*52 - 4*50 = 8 (just meets <= 8).
        # Final payroll = $140M - $40M + $8M = $108M, cap room = $32M.

        # Add outgoing players to initial roster (they "were" on GB at start)
        for i in range(4):
            p = Player(
                player_id=f"P-GB-OUT-{i}",
                name=f"Expensive Out {i}",
                talent_rating=52,
                defense_rating=3,
                position="PG",
                age=33,
                aav=10.0,
                years_remaining=1,
                current_team="Apex City Aces",  # they've "already moved"
                is_tradeable=True,
            )
            env.players_by_id[p.player_id] = p
            # In initial but NOT current roster (they were sent away)
            env._initial_players_by_team["Granite Bay Bulls"].append(p.player_id)

        # Add incoming players to current roster (acquired, not in initial)
        for i in range(4):
            p = Player(
                player_id=f"P-GB-IN-{i}",
                name=f"Cheap In {i}",
                talent_rating=50,
                defense_rating=3,
                position="PG",
                age=25,
                aav=2.0,
                years_remaining=2,
                current_team="Granite Bay Bulls",
                is_tradeable=True,
            )
            env.players_by_id[p.player_id] = p
            # In current but NOT initial (they were acquired)
            env.players_by_team["Granite Bay Bulls"].append(p.player_id)

        # Set payroll to reflect current state: original $140M - $40M sent + $8M received
        env.payroll["Granite Bay Bulls"] = 140.0 - 40.0 + 8.0  # = $108M
        env._initial_payroll["Granite Bay Bulls"] = 140.0

        result = _eval(env, "Granite Bay Bulls")
        assert result["goal_met"] is True
        assert "Cap room" in result["details"]
