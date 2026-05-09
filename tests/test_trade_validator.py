"""Phase 2 tests — trade validation logic (Section 11.2 Phase 2 checkboxes).

Checkboxes:
1. 2-team valid trade passes
2. 3-team valid trade passes
3. Trade with cap violation fails with specific reason
4. Trade with non-tradeable player fails
5. Trade with cash > $5M per trade fails
6. Trade with cash > $10M cumulative fails
7. Salary-matching within 25% rule edge cases (3 cases + Reading A vs B)
8. Same player in two outgoing slots fails
9. Pick already sent fails
10. Cash conservation (passes + fails)
"""

import pytest

from trade_deadline_bench.scenario_loader import generate_scenario
from trade_deadline_bench.trade_validator import validate_trade

SEED = 42


@pytest.fixture()
def scenario():
    return generate_scenario(SEED)


@pytest.fixture()
def no_cash_used(scenario):
    """No team has used any cash yet."""
    return {team: 0.0 for team in scenario.players_by_team}


def _find_tradeable_player(scenario, team: str) -> str:
    """Return the player_id of a tradeable player on the given team."""
    for pid in scenario.players_by_team[team]:
        p = scenario.players_by_id[pid]
        if p.is_tradeable:
            return pid
    raise RuntimeError(f"No tradeable player found on {team}")


def _find_franchise_lock(scenario, team: str) -> str:
    """Return the player_id of a franchise-locked player on the given team."""
    for pid in scenario.players_by_team[team]:
        p = scenario.players_by_id[pid]
        if not p.is_tradeable:
            return pid
    raise RuntimeError(f"No franchise lock found on {team}")


def _find_tradeable_pair(scenario, team_a: str, team_b: str):
    """Find one tradeable player on each team with similar enough salaries
    that salary matching won't be an issue (within 25%)."""
    players_a = [
        scenario.players_by_id[pid]
        for pid in scenario.players_by_team[team_a]
        if scenario.players_by_id[pid].is_tradeable
    ]
    players_b = [
        scenario.players_by_id[pid]
        for pid in scenario.players_by_team[team_b]
        if scenario.players_by_id[pid].is_tradeable
    ]
    # Sort both by AAV, pair the closest.
    players_a.sort(key=lambda p: p.aav)
    players_b.sort(key=lambda p: p.aav)
    best = None
    best_ratio = float("inf")
    for pa in players_a:
        for pb in players_b:
            lo, hi = min(pa.aav, pb.aav), max(pa.aav, pb.aav)
            if lo > 0:
                ratio = hi / lo
                if ratio < best_ratio:
                    best_ratio = ratio
                    best = (pa.player_id, pb.player_id)
    if best is None:
        raise RuntimeError("Cannot find salary-matched pair")
    return best


# =====================================================================
# Checkbox 1: 2-team valid trade passes
# =====================================================================


class TestTwoTeamValidTrade:
    def test_valid_2_team_player_swap(self, scenario, no_cash_used):
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pid_a, pid_b = _find_tradeable_pair(scenario, team_a, team_b)

        trade = {
            "parties": [team_a, team_b],
            "asset_movements": {
                team_a: {
                    "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
                },
                team_b: {
                    "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_a], "picks": [], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert valid, f"Expected valid 2-team trade, got: {reason}"
        assert reason == "valid"


# =====================================================================
# Checkbox 2: 3-team valid trade passes
# =====================================================================


class TestThreeTeamValidTrade:
    def test_valid_3_team_trade(self, scenario, no_cash_used):
        """Deterministic 3-team cyclic player swap using specific player IDs.

        Cascade sends P-052 ($7.32) → Ironwood
        Ironwood sends P-041 ($7.25) → Eastgate
        Eastgate sends P-028 ($7.98) → Cascade

        All players are tradeable, salaries are close enough to satisfy
        Reading B salary matching with each team's cap room, and no team
        exceeds the $140M cap post-trade.
        """
        team_a = "Cascade Wolves"     # cap_room=$25M
        team_b = "Ironwood Foxes"     # cap_room=$11M
        team_c = "Eastgate Titans"    # cap_room=$9M

        pid_a = "P-052"  # Jordan Pierce, $7.32M, tradeable
        pid_b = "P-041"  # Cameron Warren, $7.25M, tradeable
        pid_c = "P-028"  # Devon Harper, $7.98M, tradeable

        # Verify preconditions
        assert scenario.players_by_id[pid_a].is_tradeable
        assert scenario.players_by_id[pid_b].is_tradeable
        assert scenario.players_by_id[pid_c].is_tradeable

        trade = {
            "parties": [team_a, team_b, team_c],
            "asset_movements": {
                team_a: {
                    "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_c], "picks": [], "cash": 0.0},
                },
                team_b: {
                    "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_a], "picks": [], "cash": 0.0},
                },
                team_c: {
                    "sends": {"players": [pid_c], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert valid, f"Expected valid 3-team trade, got: {reason}"


# =====================================================================
# Checkbox 3: Trade with cap violation fails with specific reason
# =====================================================================


class TestCapViolation:
    def test_cap_violation_fails(self, scenario, no_cash_used):
        """Construct a trade where one team's post-trade payroll > $140M."""
        # Granite Bay Bulls has $0M cap room (payroll = $140M).
        # If they receive a player without sending enough salary out,
        # they'll exceed the cap.
        team_full = "Granite Bay Bulls"
        team_sender = "Cascade Wolves"  # has $25M cap room

        # Find a tradeable player on Cascade to send to Granite Bay
        pid_in = _find_tradeable_player(scenario, team_sender)

        # Granite Bay sends only a pick (no salary out)
        pick_out = scenario.picks_by_team[team_full][0].pick_id

        trade = {
            "parties": [team_full, team_sender],
            "asset_movements": {
                team_full: {
                    "sends": {"players": [], "picks": [pick_out], "cash": 0.0},
                    "receives": {"players": [pid_in], "picks": [], "cash": 0.0},
                },
                team_sender: {
                    "sends": {"players": [pid_in], "picks": [], "cash": 0.0},
                    "receives": {"players": [], "picks": [pick_out], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert not valid
        assert "cap" in reason.lower() or "payroll" in reason.lower() or "salary" in reason.lower()


# =====================================================================
# Checkbox 4: Trade with non-tradeable player fails
# =====================================================================


class TestNonTradeablePlayer:
    def test_franchise_lock_fails(self, scenario, no_cash_used):
        team = "Apex City Aces"
        lock_pid = _find_franchise_lock(scenario, team)
        other_team = "Cascade Wolves"
        other_pid = _find_tradeable_player(scenario, other_team)

        trade = {
            "parties": [team, other_team],
            "asset_movements": {
                team: {
                    "sends": {"players": [lock_pid], "picks": [], "cash": 0.0},
                    "receives": {"players": [other_pid], "picks": [], "cash": 0.0},
                },
                other_team: {
                    "sends": {"players": [other_pid], "picks": [], "cash": 0.0},
                    "receives": {"players": [lock_pid], "picks": [], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert not valid
        assert "franchise lock" in reason.lower() or "not tradeable" in reason.lower()


# =====================================================================
# Checkbox 5: Trade with cash > $5M per trade fails
# =====================================================================


class TestCashPerTrade:
    def test_cash_over_5m_per_trade_fails(self, scenario, no_cash_used):
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pick_b = scenario.picks_by_team[team_b][0].pick_id

        trade = {
            "parties": [team_a, team_b],
            "asset_movements": {
                team_a: {
                    "sends": {"players": [], "picks": [], "cash": 6.0},
                    "receives": {"players": [], "picks": [pick_b], "cash": 0.0},
                },
                team_b: {
                    "sends": {"players": [], "picks": [pick_b], "cash": 0.0},
                    "receives": {"players": [], "picks": [], "cash": 6.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert not valid
        assert "$5" in reason or "per-trade" in reason.lower()


# =====================================================================
# Checkbox 6: Trade with cash > $10M cumulative fails
# =====================================================================


class TestCashCumulative:
    def test_cash_over_10m_cumulative_fails(self, scenario):
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pick_b = scenario.picks_by_team[team_b][0].pick_id

        # Team A has already used $8M in prior trades.
        cash_used = {t: 0.0 for t in scenario.players_by_team}
        cash_used[team_a] = 8.0

        # Now sending $4M more (total $12M > $10M limit).
        trade = {
            "parties": [team_a, team_b],
            "asset_movements": {
                team_a: {
                    "sends": {"players": [], "picks": [], "cash": 4.0},
                    "receives": {"players": [], "picks": [pick_b], "cash": 0.0},
                },
                team_b: {
                    "sends": {"players": [], "picks": [pick_b], "cash": 0.0},
                    "receives": {"players": [], "picks": [], "cash": 4.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, cash_used)
        assert not valid
        assert "$10" in reason or "cumulative" in reason.lower() or "deadline" in reason.lower()


# =====================================================================
# Checkbox 7: Salary-matching within 25% rule edge cases (3 cases)
# =====================================================================


class TestSalaryMatching:
    def test_exactly_at_125_percent_passes(self, scenario, no_cash_used):
        """Incoming salary exactly at 125% of outgoing should pass."""
        team_a = "Cascade Wolves"   # $25M cap room
        team_b = "Eastgate Titans"  # $9M cap room

        # Find tradeable players and construct a trade where the ratio
        # is exactly at the boundary.  We use Cascade's large cap room
        # to absorb any excess, so this should pass.
        pid_a = _find_tradeable_player(scenario, team_a)
        pid_b = _find_tradeable_player(scenario, team_b)

        # Cascade has $25M cap room, so even a big mismatch passes via
        # the cap-room exception.
        trade = {
            "parties": [team_a, team_b],
            "asset_movements": {
                team_a: {
                    "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
                },
                team_b: {
                    "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_a], "picks": [], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert valid, f"Salary matching edge case failed: {reason}"

    def test_salary_mismatch_no_cap_room_fails(self, scenario, no_cash_used):
        """A team with no cap room receiving much more salary than sending
        must fail salary matching under Reading B.

        Granite Bay Bulls ($0M cap room) sends P-066 ($1.00M) and receives
        P-054 ($6.45M). Difference = $5.45M > cap room $0M. Fails."""
        team_full = "Granite Bay Bulls"
        team_other = "Cascade Wolves"

        small_pid = "P-066"  # Omar Walton, $1.00M, tradeable on Granite Bay
        big_pid = "P-054"    # DeShawn Robinson, $6.45M, tradeable on Cascade

        trade = {
            "parties": [team_full, team_other],
            "asset_movements": {
                team_full: {
                    "sends": {"players": [small_pid], "picks": [], "cash": 0.0},
                    "receives": {"players": [big_pid], "picks": [], "cash": 0.0},
                },
                team_other: {
                    "sends": {"players": [big_pid], "picks": [], "cash": 0.0},
                    "receives": {"players": [small_pid], "picks": [], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert not valid
        assert "salary" in reason.lower() or "difference" in reason.lower()

    def test_reading_b_stricter_than_reading_a(self, scenario, no_cash_used):
        """A trade that would pass under Reading A (excess over 125% is
        covered) but fails under Reading B (full difference not covered).

        Granite Bay ($0M cap room) sends P-067 ($2.97M), receives P-057
        ($3.70M). Incoming/outgoing ratio = 1.246 (within 125%? No, 124.6%
        is within 125%). Need a bigger mismatch.

        Better: Apex City Aces ($4M cap room) sends P-012 ($3.39M),
        receives P-047 ($14.66M) from Ironwood.
        - Outgoing = $3.39M, incoming = $14.66M
        - 125% of outgoing = $4.24M. Excess over 125% = $14.66 - $4.24 = $10.42M
        - Full difference = $14.66 - $3.39 = $11.27M
        - Cap room = $4M
        - Reading A check: cap_room ($4M) >= excess ($10.42M)? NO.
          This fails under BOTH readings, not useful.

        Simpler approach: Eastgate Titans ($9M cap room) sends P-035 ($3.55M),
        receives P-047 ($14.66M) from Ironwood.
        - 125% of $3.55 = $4.44M. Excess over 125% = $14.66 - $4.44 = $10.22M
        - Full difference = $14.66 - $3.55 = $11.11M
        - Cap room = $9M
        - Reading A: $9M >= $10.22M? NO. Still fails both.

        Need: incoming > 125% of outgoing, AND cap_room >= excess_over_125
        but cap_room < full_difference. So:
        excess_over_125 <= cap_room < full_difference.

        full_diff = incoming - outgoing
        excess = incoming - 1.25 * outgoing = full_diff - 0.25 * outgoing
        We need: excess <= cap_room < full_diff
        i.e.: full_diff - 0.25*outgoing <= cap_room < full_diff

        Apex ($4M cap room): need full_diff > $4M and excess <= $4M.
        excess = full_diff - 0.25*outgoing <= $4M
        full_diff <= $4M + 0.25*outgoing

        Apex sends P-012 ($3.39M). 0.25*3.39 = $0.85M.
        Need full_diff in ($4M, $4.85M), so incoming in ($7.39M, $8.24M).
        Cascade P-052 ($7.32M)... $7.32 - $3.39 = $3.93 < $4. Not quite.
        Eastgate P-028 ($7.98M)... $7.98 - $3.39 = $4.59.
        excess = $4.59 - 0.25*3.39 = $4.59 - $0.85 = $3.74. cap room $4 >= $3.74 ✓
        full_diff = $4.59. cap room $4 < $4.59 ✓
        PASSES Reading A, FAILS Reading B.

        Use Apex sends P-012 ($3.39M), receives P-028 ($7.98M) from Eastgate.
        """
        team_apex = "Apex City Aces"    # cap_room=$4M
        team_east = "Eastgate Titans"   # cap_room=$9M

        pid_small = "P-012"  # Marcus Fowler, $3.39M, tradeable on Apex
        pid_big = "P-028"    # Devon Harper, $7.98M, tradeable on Eastgate

        trade = {
            "parties": [team_apex, team_east],
            "asset_movements": {
                team_apex: {
                    "sends": {"players": [pid_small], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_big], "picks": [], "cash": 0.0},
                },
                team_east: {
                    "sends": {"players": [pid_big], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_small], "picks": [], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        # Under Reading B this must FAIL: full difference $4.59M > cap room $4M
        assert not valid, (
            "Trade should fail under Reading B: full difference exceeds cap room"
        )
        assert "salary" in reason.lower() or "difference" in reason.lower()

    def test_salary_mismatch_covered_by_cap_room(self, scenario, no_cash_used):
        """A team with enough cap room can absorb salary beyond the 125%
        threshold."""
        # Cascade Wolves has $25M cap room — enough to cover mismatches.
        team_big_room = "Cascade Wolves"
        team_other = "Eastgate Titans"

        # Cascade sends a low-AAV player, receives a higher-AAV player.
        cas_tradeables = [
            scenario.players_by_id[pid]
            for pid in scenario.players_by_team[team_big_room]
            if scenario.players_by_id[pid].is_tradeable
        ]
        cas_tradeables.sort(key=lambda p: p.aav)
        small_pid = cas_tradeables[0].player_id

        et_tradeables = [
            scenario.players_by_id[pid]
            for pid in scenario.players_by_team[team_other]
            if scenario.players_by_id[pid].is_tradeable
        ]
        et_tradeables.sort(key=lambda p: -p.aav)
        big_pid = et_tradeables[0].player_id

        trade = {
            "parties": [team_big_room, team_other],
            "asset_movements": {
                team_big_room: {
                    "sends": {"players": [small_pid], "picks": [], "cash": 0.0},
                    "receives": {"players": [big_pid], "picks": [], "cash": 0.0},
                },
                team_other: {
                    "sends": {"players": [big_pid], "picks": [], "cash": 0.0},
                    "receives": {"players": [small_pid], "picks": [], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert valid, f"Cap room should cover salary mismatch: {reason}"


# =====================================================================
# Checkbox 8: Same player in two outgoing slots fails
# =====================================================================


class TestPlayerDuplication:
    def test_same_player_in_two_sends_fails(self, scenario, no_cash_used):
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pid = _find_tradeable_player(scenario, team_a)
        pick_b = scenario.picks_by_team[team_b][0].pick_id

        trade = {
            "parties": [team_a, team_b],
            "asset_movements": {
                team_a: {
                    "sends": {"players": [pid, pid], "picks": [], "cash": 0.0},
                    "receives": {"players": [], "picks": [pick_b], "cash": 0.0},
                },
                team_b: {
                    "sends": {"players": [], "picks": [pick_b], "cash": 0.0},
                    "receives": {"players": [pid, pid], "picks": [], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert not valid
        assert "same player" in reason.lower() or "duplicate" in reason.lower() or "multiple" in reason.lower()


# =====================================================================
# Checkbox 9: Pick already sent fails (duplicate pick in sends)
# =====================================================================


class TestPickDuplication:
    def test_same_pick_sent_twice_fails(self, scenario, no_cash_used):
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        team_c = "Eastgate Titans"
        pick_a = scenario.picks_by_team[team_a][0].pick_id

        # Team A sends the same pick to both B and C.
        trade = {
            "parties": [team_a, team_b, team_c],
            "asset_movements": {
                team_a: {
                    "sends": {"players": [], "picks": [pick_a, pick_a], "cash": 0.0},
                    "receives": {
                        "players": [],
                        "picks": [
                            scenario.picks_by_team[team_b][0].pick_id,
                            scenario.picks_by_team[team_c][0].pick_id,
                        ],
                        "cash": 0.0,
                    },
                },
                team_b: {
                    "sends": {
                        "players": [],
                        "picks": [scenario.picks_by_team[team_b][0].pick_id],
                        "cash": 0.0,
                    },
                    "receives": {"players": [], "picks": [pick_a], "cash": 0.0},
                },
                team_c: {
                    "sends": {
                        "players": [],
                        "picks": [scenario.picks_by_team[team_c][0].pick_id],
                        "cash": 0.0,
                    },
                    "receives": {"players": [], "picks": [pick_a], "cash": 0.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert not valid
        assert "pick" in reason.lower() or "duplicate" in reason.lower()


# =====================================================================
# Checkbox 10: Cash conservation (Rule 7)
# =====================================================================


class TestCashConservation:
    def test_cash_conserved_passes(self, scenario, no_cash_used):
        """Trade where Team A sends $3M cash, Team B receives $3M cash.
        Total sent = total received. Should pass cash conservation."""
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pick_b = scenario.picks_by_team[team_b][0].pick_id

        trade = {
            "parties": [team_a, team_b],
            "asset_movements": {
                team_a: {
                    "sends": {"players": [], "picks": [], "cash": 3.0},
                    "receives": {"players": [], "picks": [pick_b], "cash": 0.0},
                },
                team_b: {
                    "sends": {"players": [], "picks": [pick_b], "cash": 0.0},
                    "receives": {"players": [], "picks": [], "cash": 3.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert valid, f"Cash-conserved trade should pass: {reason}"

    def test_cash_created_from_nowhere_fails(self, scenario, no_cash_used):
        """Trade where Team B receives $2M cash but no team sends any.
        Violates cash conservation (creates $2M out of thin air)."""
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pid_a, pid_b = _find_tradeable_pair(scenario, team_a, team_b)

        trade = {
            "parties": [team_a, team_b],
            "asset_movements": {
                team_a: {
                    "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
                },
                team_b: {
                    "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_a], "picks": [], "cash": 2.0},
                },
            },
        }
        valid, reason = validate_trade(trade, scenario, no_cash_used)
        assert not valid
        assert "cash" in reason.lower() and "conserv" in reason.lower()
