"""Phase 1 Checkbox 4: Hidden goals load correctly, not in public output."""

import json

from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.scenario_loader import generate_scenario


SEED = 42


class TestHiddenGoals:
    """Hidden goals load correctly and stay hidden from public output."""

    def setup_method(self):
        self.scenario = generate_scenario(SEED)

    def test_hidden_goals_loaded(self):
        for team in TEAMS:
            tc = self.scenario.team_configs[team]
            assert "description" in tc.hidden_goal
            assert len(tc.hidden_goal["description"]) > 0
            assert "bonuses" in tc.hidden_goal
            assert isinstance(tc.hidden_goal["bonuses"], list)
            assert len(tc.hidden_goal["bonuses"]) >= 1

    def test_each_team_has_distinct_goal(self):
        goals = {
            tc.hidden_goal["description"]
            for tc in self.scenario.team_configs.values()
        }
        assert len(goals) == 6

    def test_public_output_excludes_hidden_goal(self):
        for team in TEAMS:
            public = self.scenario.get_public_team_data(team)

            public_str = json.dumps(public)

            assert "hidden_goal" not in public
            assert "hidden_goal" not in public_str

            goal_text = self.scenario.team_configs[team].hidden_goal[
                "description"
            ]
            assert goal_text not in public_str

    def test_public_output_contains_expected_keys(self):
        for team in TEAMS:
            public = self.scenario.get_public_team_data(team)
            assert "name" in public
            assert "public_profile" in public
            assert "cap_room" in public
            assert "payroll" in public
            assert "players" in public
            assert "draft_picks" in public

    def test_bonus_values_present(self):
        for team in TEAMS:
            tc = self.scenario.team_configs[team]
            for bonus in tc.hidden_goal["bonuses"]:
                assert "condition" in bonus
                assert "value" in bonus
                assert isinstance(bonus["value"], (int, float))
