"""Phase 1 Checkbox 2: 72 unique players, distribution matches spec."""

from collections import Counter

from trade_deadline_bench.scenario_loader import generate_scenario


SEED = 42


class TestPlayerDistribution:
    """72 unique players with spec-compliant distributions."""

    def setup_method(self):
        self.scenario = generate_scenario(SEED)
        self.players = list(self.scenario.players_by_id.values())

    def test_72_unique_players(self):
        assert len(self.players) == 72
        ids = [p.player_id for p in self.players]
        assert len(set(ids)) == 72

    def test_unique_names(self):
        names = [p.name for p in self.players]
        assert len(set(names)) == 72

    def test_elite_count_at_most_6(self):
        elite = [p for p in self.players if p.talent_rating >= 88]
        assert len(elite) <= 6

    def test_talent_rating_range(self):
        for p in self.players:
            assert 50 <= p.talent_rating <= 95, (
                f"{p.name} talent {p.talent_rating} out of range"
            )

    def test_defense_rating_range(self):
        for p in self.players:
            assert 1 <= p.defense_rating <= 10, (
                f"{p.name} defense {p.defense_rating} out of range"
            )

    def test_position_values(self):
        valid = {"PG", "SG", "SF", "PF", "C"}
        for p in self.players:
            assert p.position in valid, f"{p.name} position {p.position}"

    def test_position_roughly_even(self):
        counts = Counter(p.position for p in self.players)
        for pos in ["PG", "SG", "SF", "PF", "C"]:
            assert 5 <= counts.get(pos, 0) <= 25, (
                f"Position {pos} count {counts.get(pos, 0)} outside [5, 25]"
            )

    def test_age_range(self):
        for p in self.players:
            assert 19 <= p.age <= 37, f"{p.name} age {p.age} out of range"

    def test_aav_range(self):
        for p in self.players:
            assert 1.0 <= p.aav <= 40.0, (
                f"{p.name} aav {p.aav} out of range"
            )

    def test_years_remaining_range(self):
        for p in self.players:
            assert 1 <= p.years_remaining <= 5, (
                f"{p.name} years {p.years_remaining} out of range"
            )

    def test_total_contract_property(self):
        for p in self.players:
            expected = p.aav * p.years_remaining
            assert abs(p.total_contract - expected) < 0.01
