"""Phase 1 Checkbox 1: Loading the same seed produces identical roster."""

from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.scenario_loader import generate_scenario


SEED = 42


class TestDeterministicSeed:
    """Same seed must produce byte-identical rosters."""

    def test_same_seed_identical_roster(self):
        s1 = generate_scenario(SEED)
        s2 = generate_scenario(SEED)

        assert s1.players_by_team == s2.players_by_team

        for pid in s1.players_by_id:
            p1 = s1.players_by_id[pid]
            p2 = s2.players_by_id[pid]
            assert p1.player_id == p2.player_id
            assert p1.name == p2.name
            assert p1.talent_rating == p2.talent_rating
            assert p1.defense_rating == p2.defense_rating
            assert p1.position == p2.position
            assert p1.age == p2.age
            assert p1.aav == p2.aav
            assert p1.years_remaining == p2.years_remaining
            assert p1.current_team == p2.current_team
            assert p1.is_tradeable == p2.is_tradeable

        for team in TEAMS:
            picks1 = s1.picks_by_team[team]
            picks2 = s2.picks_by_team[team]
            assert len(picks1) == len(picks2)
            for dp1, dp2 in zip(picks1, picks2):
                assert dp1.pick_id == dp2.pick_id
                assert dp1.owning_team == dp2.owning_team
                assert dp1.pick_round == dp2.pick_round
                assert dp1.season_year == dp2.season_year
                assert dp1.protection_note == dp2.protection_note

        assert s1.payroll == s2.payroll

    def test_different_seed_different_roster(self):
        s1 = generate_scenario(SEED)
        s2 = generate_scenario(SEED + 1)

        names_1 = {p.name for p in s1.players_by_id.values()}
        names_2 = {p.name for p in s2.players_by_id.values()}
        assert names_1 != names_2
