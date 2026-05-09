"""Phase 3 tests — environment & tool methods (Section 11.2 Phase 3 checkboxes).

Checkboxes:
1. tool_send_email deposits in recipient inbox correctly
2. group email goes to all named recipients
3. tool_propose_trade with valid proposal returns trade_id; auto-broadcasts
4. tool_propose_trade with invalid proposal returns error
5. 2-team trade with both parties calling execute_trade in same round → executes
6. 3-team trade with all three calling execute_trade in same round → executes
7. 3-team trade with only 2 of 3 calling → expires next round, no trade
8. trade execution updates rosters, payroll, cash_used correctly
9. trade execution broadcasts to all 6 teams' inboxes
10. tool_check_my_progress returns goal status only to calling team
11. advance_round requires all 6 votes; force-advance after timeout
12. same scenario_seed + same agent actions → identical state at every round

Extra: non-matching trade_id edge case
"""

import pytest

from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.environment import TradeDeadlineEnvironment


@pytest.fixture
def env():
    """Fresh environment seeded at 42."""
    return TradeDeadlineEnvironment(scenario_seed=42)


def _find_tradeable_player(env: TradeDeadlineEnvironment, team: str) -> str:
    """Return the first tradeable player_id on a team (sorted for determinism)."""
    for pid in sorted(env.players_by_team[team]):
        if env.players_by_id[pid].is_tradeable:
            return pid
    raise ValueError(f"No tradeable player found on {team}")


def _find_tradeable_pair(
    env: TradeDeadlineEnvironment, team_a: str, team_b: str
) -> tuple[str, str]:
    """Find two tradeable players (one per team) with similar AAV."""
    players_a = [
        env.players_by_id[pid]
        for pid in sorted(env.players_by_team[team_a])
        if env.players_by_id[pid].is_tradeable
    ]
    players_b = [
        env.players_by_id[pid]
        for pid in sorted(env.players_by_team[team_b])
        if env.players_by_id[pid].is_tradeable
    ]
    players_a.sort(key=lambda p: p.aav)
    players_b.sort(key=lambda p: p.aav)

    for pa in players_a:
        for pb in players_b:
            if abs(pa.aav - pb.aav) < 3.0:
                return pa.player_id, pb.player_id

    return players_a[0].player_id, players_b[0].player_id


# =====================================================================
# Checkbox 1: tool_send_email deposits in recipient inbox correctly
# =====================================================================


class TestSendEmail:
    def test_send_email_deposits_in_inbox(self, env):
        """Single recipient email appears in their inbox."""
        result = env.tool_send_email(
            from_team="Cascade Wolves",
            to=["Ironwood Foxes"],
            subject="Trade interest",
            body="We want to discuss a trade.",
        )
        assert result["status"] == "sent"
        inbox = env.inboxes["Ironwood Foxes"]
        assert len(inbox) == 1
        msg = inbox[0]
        assert msg["type"] == "email"
        assert msg["from"] == "Cascade Wolves"
        assert msg["subject"] == "Trade interest"
        assert msg["body"] == "We want to discuss a trade."
        assert msg["timestamp"] == (1, 1)

    # =================================================================
    # Checkbox 2: group email goes to all named recipients
    # =================================================================

    def test_group_email_all_recipients(self, env):
        """Group email deposits in every named recipient's inbox."""
        recipients = ["Ironwood Foxes", "Eastgate Titans", "Harlow Vipers"]
        result = env.tool_send_email(
            from_team="Cascade Wolves",
            to=recipients,
            subject="Group discussion",
            body="Let's talk 3-team trade.",
        )
        assert result["status"] == "sent"
        assert len(result["recipients"]) == 3

        for team in recipients:
            inbox = env.inboxes[team]
            assert len(inbox) == 1
            assert inbox[0]["subject"] == "Group discussion"

        # Sender does NOT receive the email
        assert len(env.inboxes["Cascade Wolves"]) == 0


# =====================================================================
# Checkbox 3: tool_propose_trade valid → trade_id + auto-broadcasts
# =====================================================================


class TestProposeTrade:
    def test_valid_proposal_returns_trade_id(self, env):
        """Valid proposal returns trade_id and broadcasts to parties."""
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pid_a, pid_b = _find_tradeable_pair(env, team_a, team_b)

        terms = {
            team_a: {
                "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
            },
            team_b: {
                "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_a], "picks": [], "cash": 0.0},
            },
        }

        result = env.tool_propose_trade(
            from_team=team_a,
            parties=[team_a, team_b],
            terms=terms,
        )

        assert "trade_id" in result
        assert result["trade_id"] == "T-1-1"
        assert sorted(result["parties"]) == sorted([team_a, team_b])
        assert result["expires_at_round"] == 2

        # Both parties should have proposal in inbox
        for team in [team_a, team_b]:
            msgs = [m for m in env.inboxes[team] if m["type"] == "trade_proposal"]
            assert len(msgs) == 1
            assert msgs[0]["trade_id"] == "T-1-1"

    # =================================================================
    # Checkbox 4: tool_propose_trade invalid → error
    # =================================================================

    def test_invalid_proposal_returns_error(self, env):
        """Proposing a trade with a franchise-lock player returns error."""
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"

        # Find a franchise-lock player on team_a
        lock_pid = None
        for pid in sorted(env.players_by_team[team_a]):
            if not env.players_by_id[pid].is_tradeable:
                lock_pid = pid
                break
        assert lock_pid is not None

        pid_b = _find_tradeable_player(env, team_b)

        terms = {
            team_a: {
                "sends": {"players": [lock_pid], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
            },
            team_b: {
                "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                "receives": {"players": [lock_pid], "picks": [], "cash": 0.0},
            },
        }

        result = env.tool_propose_trade(
            from_team=team_a,
            parties=[team_a, team_b],
            terms=terms,
        )

        assert "error" in result


# =====================================================================
# Checkbox 5: 2-team execute_trade same round → executes
# =====================================================================


class TestExecuteTrade:
    def test_2_team_execute_same_round(self, env):
        """Both parties call execute_trade → trade executes."""
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pid_a, pid_b = _find_tradeable_pair(env, team_a, team_b)

        terms = {
            team_a: {
                "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
            },
            team_b: {
                "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_a], "picks": [], "cash": 0.0},
            },
        }

        result = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b], terms=terms
        )
        trade_id = result["trade_id"]

        # Team A consents
        r1 = env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        assert r1["status"] == "consent_recorded"

        # Team B consents → trade executes
        r2 = env.tool_execute_trade(from_team=team_b, trade_id=trade_id)
        assert r2["status"] == "executed"
        assert r2["trade_id"] == trade_id

    # =================================================================
    # Checkbox 6: 3-team execute_trade same round → executes
    # =================================================================

    def test_3_team_execute_same_round(self, env):
        """All three parties call execute_trade → trade executes."""
        team_a = "Cascade Wolves"     # cap_room=$25M
        team_b = "Ironwood Foxes"     # cap_room=$11M
        team_c = "Eastgate Titans"    # cap_room=$9M

        pid_a = "P-052"  # Jordan Pierce, $7.32M, tradeable
        pid_b = "P-041"  # Cameron Warren, $7.25M, tradeable
        pid_c = "P-028"  # Devon Harper, $7.98M, tradeable

        terms = {
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
        }

        result = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b, team_c], terms=terms
        )
        trade_id = result["trade_id"]

        # All three consent in same round
        r1 = env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        assert r1["status"] == "consent_recorded"
        r2 = env.tool_execute_trade(from_team=team_b, trade_id=trade_id)
        assert r2["status"] == "consent_recorded"
        r3 = env.tool_execute_trade(from_team=team_c, trade_id=trade_id)
        assert r3["status"] == "executed"

    # =================================================================
    # Checkbox 7: 3-team trade, only 2 of 3 call → expires, no trade
    # =================================================================

    def test_3_team_only_2_consent_expires(self, env):
        """2 of 3 teams consent, round advances → proposal expires."""
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        team_c = "Eastgate Titans"

        pid_a = "P-052"
        pid_b = "P-041"
        pid_c = "P-028"

        terms = {
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
        }

        result = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b, team_c], terms=terms
        )
        trade_id = result["trade_id"]

        # Only A and B consent
        env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        env.tool_execute_trade(from_team=team_b, trade_id=trade_id)

        # Round advances (simulate all 6 voting)
        for team in TEAMS:
            env.tool_advance_round(team=team)

        # Proposal should be expired
        proposal = env.trade_proposals[trade_id]
        assert proposal.expired

        # No trade executed
        assert len(env.executed_trades) == 0

        # Trying to execute now should fail
        r = env.tool_execute_trade(from_team=team_c, trade_id=trade_id)
        assert "error" in r
        assert "expired" in r["error"].lower()

    # =================================================================
    # Extra: non-matching trade_id edge case
    # =================================================================

    def test_3_team_non_matching_trade_id_no_execute(self, env):
        """3 teams each call execute_trade but with different trade_ids."""
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        team_c = "Eastgate Titans"

        pid_a = "P-052"
        pid_b = "P-041"
        pid_c = "P-028"

        terms = {
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
        }

        # Propose the same trade twice to get two different trade_ids
        r1 = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b, team_c], terms=terms
        )
        trade_id_1 = r1["trade_id"]

        r2 = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b, team_c], terms=terms
        )
        trade_id_2 = r2["trade_id"]

        assert trade_id_1 != trade_id_2

        # Team A and B consent to trade_id_1, Team C consents to trade_id_2
        env.tool_execute_trade(from_team=team_a, trade_id=trade_id_1)
        env.tool_execute_trade(from_team=team_b, trade_id=trade_id_1)
        env.tool_execute_trade(from_team=team_c, trade_id=trade_id_2)

        # Neither trade should execute (each needs all 3 parties on SAME id)
        assert len(env.executed_trades) == 0


# =====================================================================
# Checkbox 8: trade execution updates rosters, payroll, cash_used
# =====================================================================


class TestTradeExecution:
    def test_execution_updates_state(self, env):
        """After trade executes, rosters/payroll/cash reflect transfers."""
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pid_a = "P-052"  # $7.32M on Cascade
        pid_b = "P-046"  # $1.00M on Ironwood

        payroll_a_before = env.payroll[team_a]
        payroll_b_before = env.payroll[team_b]

        terms = {
            team_a: {
                "sends": {"players": [pid_a], "picks": [], "cash": 2.0},
                "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
            },
            team_b: {
                "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_a], "picks": [], "cash": 2.0},
            },
        }

        result = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b], terms=terms
        )
        trade_id = result["trade_id"]
        env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        env.tool_execute_trade(from_team=team_b, trade_id=trade_id)

        # Roster checks
        assert pid_a not in env.players_by_team[team_a]
        assert pid_a in env.players_by_team[team_b]
        assert pid_b not in env.players_by_team[team_b]
        assert pid_b in env.players_by_team[team_a]

        # Player current_team updated
        assert env.players_by_id[pid_a].current_team == team_b
        assert env.players_by_id[pid_b].current_team == team_a

        # Payroll: A lost $7.32, gained $1.00; B lost $1.00, gained $7.32
        aav_a = 7.32
        aav_b = 1.00
        assert abs(env.payroll[team_a] - (payroll_a_before - aav_a + aav_b)) < 0.01
        assert abs(env.payroll[team_b] - (payroll_b_before - aav_b + aav_a)) < 0.01

        # Cash used: A sent $2M
        assert env.cash_used[team_a] == 2.0
        assert env.cash_used[team_b] == 0.0

    # =================================================================
    # Checkbox 9: trade execution broadcasts to all 6 teams' inboxes
    # =================================================================

    def test_execution_broadcasts_to_all_6(self, env):
        """Trade execution sends broadcast message to all 6 teams."""
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        pid_a, pid_b = _find_tradeable_pair(env, team_a, team_b)

        terms = {
            team_a: {
                "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
            },
            team_b: {
                "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_a], "picks": [], "cash": 0.0},
            },
        }

        result = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b], terms=terms
        )
        trade_id = result["trade_id"]
        env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        env.tool_execute_trade(from_team=team_b, trade_id=trade_id)

        # All 6 teams should have the execution broadcast
        for team in TEAMS:
            exec_msgs = [
                m for m in env.inboxes[team] if m["type"] == "trade_executed"
            ]
            assert len(exec_msgs) == 1
            assert exec_msgs[0]["trade_id"] == trade_id


# =====================================================================
# Checkbox 10: tool_check_my_progress returns goal status to calling team
# =====================================================================


class TestCheckProgress:
    def test_check_my_progress_returns_own_goal(self, env):
        """check_my_progress returns the calling team's hidden goal."""
        result = env.tool_check_my_progress(team="Harlow Vipers")

        assert result["team"] == "Harlow Vipers"
        assert "goal_description" in result
        assert len(result["goal_description"]) > 0
        assert "bonuses" in result

    def test_check_my_progress_different_teams_different_goals(self, env):
        """Each team gets its own unique goal from check_my_progress."""
        goals = {}
        for team in TEAMS:
            result = env.tool_check_my_progress(team=team)
            goals[team] = result["goal_description"]

        # All goals should be distinct
        assert len(set(goals.values())) == len(TEAMS)


# =====================================================================
# Checkbox 11: advance_round requires all 6 votes; force-advance
# =====================================================================


class TestAdvanceRound:
    def test_all_6_votes_advances_round(self, env):
        """Round advances only when all 6 teams vote."""
        assert env.current_round == 1

        # First 5 votes don't advance
        for team in sorted(TEAMS)[:5]:
            result = env.tool_advance_round(team=team)
            assert result["status"] == "vote_recorded"
            assert env.current_round == 1

        # 6th vote advances
        result = env.tool_advance_round(team=sorted(TEAMS)[5])
        assert result["status"] == "round_advanced"
        assert result["new_round"] == 2
        assert env.current_round == 2

    def test_force_advance_after_timeout(self, env):
        """Team that doesn't advance for max_turns is force-advanced."""
        # Set low threshold for testing
        env.max_turns_without_advance = 2

        # 5 teams vote normally
        for team in sorted(TEAMS)[:5]:
            env.tool_advance_round(team=team)

        assert env.current_round == 1

        # The 6th team (sorted[-1]) doesn't vote. Simulate turns.
        stuck_team = sorted(TEAMS)[5]

        # First turn: count=1, not yet at threshold
        advanced = env.force_advance_check(stuck_team)
        assert not advanced
        assert env.current_round == 1

        # Second turn: count=2 >= threshold → force-advance
        advanced = env.force_advance_check(stuck_team)
        assert advanced
        assert env.current_round == 2


# =====================================================================
# Checkbox 12: same seed + same actions → identical state at every round
# =====================================================================


class TestDeterministicReplay:
    def test_identical_replay(self):
        """Two environments with same seed + same actions produce
        identical state at every step."""
        env1 = TradeDeadlineEnvironment(scenario_seed=42)
        env2 = TradeDeadlineEnvironment(scenario_seed=42)

        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        team_c = "Eastgate Titans"

        # --- Round 1 actions ---
        # Send emails
        for e in [env1, env2]:
            e.tool_send_email(
                from_team=team_a,
                to=[team_b, team_c],
                subject="Let's trade",
                body="I have picks to offer.",
            )

        # Propose a trade
        pid_a = "P-052"
        pid_b = "P-041"
        terms = {
            team_a: {
                "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
            },
            team_b: {
                "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_a], "picks": [], "cash": 0.0},
            },
        }
        for e in [env1, env2]:
            e.tool_propose_trade(
                from_team=team_a, parties=[team_a, team_b], terms=terms
            )

        # Execute trade
        for e in [env1, env2]:
            e.tool_execute_trade(from_team=team_a, trade_id="T-1-1")
            e.tool_execute_trade(from_team=team_b, trade_id="T-1-1")

        # Check state is identical after trade
        assert env1.players_by_team == env2.players_by_team
        assert env1.payroll == env2.payroll
        assert env1.cash_used == env2.cash_used
        assert len(env1.executed_trades) == len(env2.executed_trades)
        assert env1.executed_trades[0].trade_id == env2.executed_trades[0].trade_id

        # Advance round
        for e in [env1, env2]:
            for team in TEAMS:
                e.tool_advance_round(team=team)

        assert env1.current_round == env2.current_round == 2

        # --- Round 2 actions ---
        for e in [env1, env2]:
            e.tool_send_email(
                from_team=team_c,
                to=[team_a],
                subject="Follow up",
                body="Interested in P-041?",
            )
            e.tool_check_my_progress(team=team_c)

        # Verify inboxes are identical
        for team in TEAMS:
            assert len(env1.inboxes[team]) == len(env2.inboxes[team])
            for m1, m2 in zip(env1.inboxes[team], env2.inboxes[team]):
                assert m1["timestamp"] == m2["timestamp"]
                assert m1["subject"] == m2["subject"]
                assert m1["from"] == m2["from"]

        # Final state comparison
        assert env1.current_round == env2.current_round
        assert env1._trade_counter == env2._trade_counter
        assert env1._email_counter == env2._email_counter
