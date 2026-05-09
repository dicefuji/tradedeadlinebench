"""Phase 1 Checkbox 3: All 6 teams have 12 players each, 4-6 tradeable."""

from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.scenario_loader import generate_scenario


SEED = 42


class TestTeamStructure:
    """Each team has 12 players with 4-6 tradeable."""

    def setup_method(self):
        self.scenario = generate_scenario(SEED)

    def test_six_teams(self):
        assert set(self.scenario.players_by_team.keys()) == set(TEAMS)

    def test_twelve_players_per_team(self):
        for team in TEAMS:
            pids = self.scenario.players_by_team[team]
            assert len(pids) == 12, f"{team} has {len(pids)} players"

    def test_tradeable_count_per_team(self):
        for team in TEAMS:
            pids = self.scenario.players_by_team[team]
            players = [self.scenario.players_by_id[pid] for pid in pids]
            tradeable = [p for p in players if p.is_tradeable]
            assert 4 <= len(tradeable) <= 6, (
                f"{team} has {len(tradeable)} tradeable (expected 4-6)"
            )

    def test_four_draft_picks_per_team(self):
        for team in TEAMS:
            picks = self.scenario.picks_by_team[team]
            assert len(picks) == 4, f"{team} has {len(picks)} picks"

    def test_draft_pick_rounds(self):
        for team in TEAMS:
            picks = self.scenario.picks_by_team[team]
            first_round = [dp for dp in picks if dp.pick_round == 1]
            second_round = [dp for dp in picks if dp.pick_round == 2]
            assert len(first_round) == 2, (
                f"{team}: expected 2 first-round picks, got {len(first_round)}"
            )
            assert len(second_round) == 2, (
                f"{team}: expected 2 second-round picks, got {len(second_round)}"
            )

    def test_players_assigned_to_correct_team(self):
        for team in TEAMS:
            pids = self.scenario.players_by_team[team]
            for pid in pids:
                player = self.scenario.players_by_id[pid]
                assert player.current_team == team

    def test_payroll_matches_cap_situation(self):
        for team in TEAMS:
            tc = self.scenario.team_configs[team]
            expected_payroll = 140.0 - tc.cap_room
            actual_payroll = self.scenario.payroll[team]
            assert abs(actual_payroll - expected_payroll) < 0.10, (
                f"{team}: payroll {actual_payroll} != "
                f"expected {expected_payroll}"
            )
