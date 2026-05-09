"""Phase 3 tests -- environment & tool methods (Section 11.2 Phase 3 checkboxes).

Checkboxes:
1. tool_send_email deposits in recipient inbox correctly
2. group email goes to all named recipients
3. tool_propose_trade with valid proposal returns trade_id; auto-broadcasts (in N+1)
4. tool_propose_trade with invalid proposal returns error
5. 2-team trade with both parties calling execute_trade in consent window
6. 3-team trade with all three calling execute_trade in consent window
7. 3-team trade with only 2 of 3 calling -- expires next round, no trade
8. trade execution updates rosters, payroll, cash_used correctly
9. trade execution broadcasts to all 6 teams inboxes
10. tool_check_my_progress returns evaluated goal status to calling team
11. advance_round requires all 6 votes; force-advance after timeout
12. same scenario_seed + same agent actions -- identical state at every round

Extra: non-matching trade_id, pick transfer regression, re-validation regression,
       proposal delay tests, goal evaluator tests, extended deterministic replay
"""

import hashlib
import json

import pytest

from trade_deadline_bench.data_structures import TEAMS
from trade_deadline_bench.environment import TradeDeadlineEnvironment


@pytest.fixture
def env():
    """Fresh environment seeded at 42."""
    return TradeDeadlineEnvironment(scenario_seed=42)


def _advance_round(env: TradeDeadlineEnvironment) -> None:
    """Helper: all 6 teams vote to advance round."""
    for team in TEAMS:
        env.tool_advance_round(team=team)


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


def _propose_and_advance(env, from_team, parties, terms):
    """Propose a trade in current round, advance to consent window (N+1)."""
    result = env.tool_propose_trade(from_team=from_team, parties=parties, terms=terms)
    assert "trade_id" in result, f"Proposal failed: {result}"
    _advance_round(env)
    return result["trade_id"]


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
# Checkbox 3: tool_propose_trade valid -- trade_id + auto-broadcasts in N+1
# =====================================================================


class TestProposeTrade:
    def test_valid_proposal_returns_trade_id(self, env):
        """Valid proposal returns trade_id; broadcast arrives in round N+1."""
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

        # NOT in inbox yet (1-round delay)
        for team in [team_a, team_b]:
            msgs = [m for m in env.inboxes[team] if m["type"] == "trade_proposal"]
            assert len(msgs) == 0

        # Advance round -- broadcast delivered
        _advance_round(env)

        for team in [team_a, team_b]:
            msgs = [m for m in env.inboxes[team] if m["type"] == "trade_proposal"]
            assert len(msgs) == 1
            assert msgs[0]["trade_id"] == "T-1-1"

    # =================================================================
    # Checkbox 4: tool_propose_trade invalid -- error
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
# Checkbox 5: 2-team execute_trade in consent window
# =====================================================================


class TestExecuteTrade:
    def test_2_team_execute_same_round(self, env):
        """Both parties call execute_trade in consent window -- trade executes."""
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

        # Propose in round 1, advance to round 2 (consent window)
        trade_id = _propose_and_advance(env, team_a, [team_a, team_b], terms)

        # Team A consents
        r1 = env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        assert r1["status"] == "consent_recorded"

        # Team B consents -- trade executes
        r2 = env.tool_execute_trade(from_team=team_b, trade_id=trade_id)
        assert r2["status"] == "executed"
        assert r2["trade_id"] == trade_id

    # =================================================================
    # Checkbox 6: 3-team execute_trade in consent window
    # =================================================================

    def test_3_team_execute_same_round(self, env):
        """All three parties call execute_trade in consent window -- executes."""
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

        trade_id = _propose_and_advance(
            env, team_a, [team_a, team_b, team_c], terms
        )

        r1 = env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        assert r1["status"] == "consent_recorded"
        r2 = env.tool_execute_trade(from_team=team_b, trade_id=trade_id)
        assert r2["status"] == "consent_recorded"
        r3 = env.tool_execute_trade(from_team=team_c, trade_id=trade_id)
        assert r3["status"] == "executed"

    # =================================================================
    # Checkbox 7: 3-team trade, only 2 of 3 call -- expires, no trade
    # =================================================================

    def test_3_team_only_2_consent_expires(self, env):
        """2 of 3 teams consent, round advances -- proposal expires."""
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

        # Propose in round 1, advance to round 2 (consent window)
        trade_id = _propose_and_advance(
            env, team_a, [team_a, team_b, team_c], terms
        )

        # Only A and B consent in round 2
        env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        env.tool_execute_trade(from_team=team_b, trade_id=trade_id)

        # Advance round 2 -> 3 (expires proposal from round 1)
        _advance_round(env)

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

        # Propose the same trade twice in round 1
        r1 = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b, team_c], terms=terms
        )
        trade_id_1 = r1["trade_id"]

        r2 = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b, team_c], terms=terms
        )
        trade_id_2 = r2["trade_id"]
        assert trade_id_1 != trade_id_2

        # Advance to consent window
        _advance_round(env)

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

        trade_id = _propose_and_advance(env, team_a, [team_a, team_b], terms)
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
    # Checkbox 9: trade execution broadcasts to all 6 teams inboxes
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

        trade_id = _propose_and_advance(env, team_a, [team_a, team_b], terms)
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
# Checkbox 10: tool_check_my_progress returns evaluated goal status
# =====================================================================


class TestCheckProgress:
    def test_check_my_progress_returns_evaluated_goal(self, env):
        """check_my_progress returns evaluated goal with goal_met bool."""
        result = env.tool_check_my_progress(team="Harlow Vipers")

        assert result["team"] == "Harlow Vipers"
        assert "goal_met" in result
        assert isinstance(result["goal_met"], bool)
        assert "details" in result
        assert "bonuses_eligible" in result
        # At start, no trades have happened, so goal should NOT be met
        assert result["goal_met"] is False

    def test_check_my_progress_different_teams_different_results(self, env):
        """Each team gets its own evaluated goal from check_my_progress."""
        results = {}
        for team in TEAMS:
            result = env.tool_check_my_progress(team=team)
            results[team] = result
            assert "goal_met" in result
            assert "details" in result
            assert "bonuses_eligible" in result

        # All details should be distinct (different goals)
        details = [r["details"] for r in results.values()]
        assert len(set(details)) == len(TEAMS)


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

        # The 6th team doesn't vote. Simulate turns.
        stuck_team = sorted(TEAMS)[5]

        # First turn: count=1, not yet at threshold
        advanced = env.force_advance_check(stuck_team)
        assert not advanced
        assert env.current_round == 1

        # Second turn: count=2 >= threshold -- force-advance
        advanced = env.force_advance_check(stuck_team)
        assert advanced
        assert env.current_round == 2


# =====================================================================
# Checkbox 12: same seed + same actions -- identical state at every round
# =====================================================================


class TestDeterministicReplay:
    def test_identical_replay(self):
        """Two environments with same seed + same actions produce
        identical state at every step."""
        env1 = TradeDeadlineEnvironment(scenario_seed=42)
        env2 = TradeDeadlineEnvironment(scenario_seed=42)

        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"

        # --- Round 1: send emails + propose trade ---
        for e in [env1, env2]:
            e.tool_send_email(
                from_team=team_a,
                to=[team_b],
                subject="Let's trade",
                body="I have picks to offer.",
            )

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

        # Advance round 1 -> 2
        for e in [env1, env2]:
            for team in TEAMS:
                e.tool_advance_round(team=team)

        assert env1.current_round == env2.current_round == 2

        # --- Round 2: execute trade ---
        for e in [env1, env2]:
            e.tool_execute_trade(from_team=team_a, trade_id="T-1-1")
            e.tool_execute_trade(from_team=team_b, trade_id="T-1-1")

        # Check state is identical after trade
        assert env1.players_by_team == env2.players_by_team
        assert env1.payroll == env2.payroll
        assert env1.cash_used == env2.cash_used
        assert len(env1.executed_trades) == len(env2.executed_trades)
        assert env1.executed_trades[0].trade_id == env2.executed_trades[0].trade_id

        # Advance round 2 -> 3
        for e in [env1, env2]:
            for team in TEAMS:
                e.tool_advance_round(team=team)

        assert env1.current_round == env2.current_round == 3

        # --- Round 3: check progress ---
        for e in [env1, env2]:
            e.tool_check_my_progress(team=team_a)

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


# =====================================================================
# Item 2: Proposal broadcast delay tests
# =====================================================================


class TestProposalBroadcastDelay:
    def test_proposal_not_visible_same_round(self, env):
        """Proposal made in round N is NOT visible in inboxes in round N."""
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

        env.tool_propose_trade(from_team=team_a, parties=[team_a, team_b], terms=terms)

        # NOT in inbox in round 1 (same round as proposal)
        for team in [team_a, team_b]:
            proposal_msgs = [
                m for m in env.inboxes[team] if m["type"] == "trade_proposal"
            ]
            assert len(proposal_msgs) == 0

    def test_proposal_visible_in_next_round(self, env):
        """Proposal made in round N is visible at start of round N+1."""
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

        env.tool_propose_trade(from_team=team_a, parties=[team_a, team_b], terms=terms)
        _advance_round(env)  # Round 1 -> 2

        # NOW visible in round 2
        for team in [team_a, team_b]:
            proposal_msgs = [
                m for m in env.inboxes[team] if m["type"] == "trade_proposal"
            ]
            assert len(proposal_msgs) == 1

    def test_same_round_consent_rejected(self, env):
        """Consent attempted in same round as proposal is rejected."""
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

        # Try to consent in same round -- rejected
        r = env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        assert "error" in r
        assert "proposed this round" in r["error"]

    def test_proposal_expires_end_of_consent_window(self, env):
        """Proposal expires end of round N+1 if not all parties consent."""
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

        # Advance to round 2 (consent window)
        _advance_round(env)

        # Only team_a consents
        env.tool_execute_trade(from_team=team_a, trade_id=trade_id)

        # Advance to round 3 -- expires
        _advance_round(env)

        proposal = env.trade_proposals[trade_id]
        assert proposal.expired
        assert len(env.executed_trades) == 0


# =====================================================================
# Item 3: Pick transfer regression test
# =====================================================================


class TestPickTransfer:
    def test_pick_transfer_between_teams(self, env):
        """Pick transfer correctly moves picks between teams.

        This test would have failed before the pre-collect fix (commit 54513a1).
        """
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"

        # Find a pick on team_a and a tradeable player on team_b
        pick_a = env.picks_by_team[team_a][0]
        pid_b = _find_tradeable_player(env, team_b)

        # Also find a tradeable player on team_a to balance salary
        pid_a = _find_tradeable_player(env, team_a)

        terms = {
            team_a: {
                "sends": {"players": [pid_a], "picks": [pick_a.pick_id], "cash": 0.0},
                "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
            },
            team_b: {
                "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                "receives": {
                    "players": [pid_a],
                    "picks": [pick_a.pick_id],
                    "cash": 0.0,
                },
            },
        }

        trade_id = _propose_and_advance(env, team_a, [team_a, team_b], terms)
        env.tool_execute_trade(from_team=team_a, trade_id=trade_id)
        r = env.tool_execute_trade(from_team=team_b, trade_id=trade_id)
        assert r["status"] == "executed"

        # Verify pick moved correctly
        team_a_pick_ids = {dp.pick_id for dp in env.picks_by_team[team_a]}
        team_b_pick_ids = {dp.pick_id for dp in env.picks_by_team[team_b]}

        assert pick_a.pick_id not in team_a_pick_ids
        assert pick_a.pick_id in team_b_pick_ids
        assert pick_a.owning_team == team_b

        # No picks lost or duplicated
        total_picks = sum(len(p) for p in env.picks_by_team.values())
        assert total_picks == 24  # 6 teams x 4 picks


# =====================================================================
# Item 4: Re-validation regression test
# =====================================================================


class TestRevalidation:
    def test_stale_proposal_fails_revalidation(self, env):
        """Two proposals for same player; first executes, second fails.

        This test would have failed before the re-validation fix (commit 54513a1).
        """
        team_a = "Cascade Wolves"
        team_b = "Ironwood Foxes"
        team_c = "Eastgate Titans"

        pid_a = _find_tradeable_player(env, team_a)
        pid_b = _find_tradeable_player(env, team_b)
        pid_c = _find_tradeable_player(env, team_c)

        # Trade 1: A sends pid_a to B
        terms_1 = {
            team_a: {
                "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
            },
            team_b: {
                "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_a], "picks": [], "cash": 0.0},
            },
        }

        # Trade 2: A sends same pid_a to C (both valid at proposal time)
        terms_2 = {
            team_a: {
                "sends": {"players": [pid_a], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_c], "picks": [], "cash": 0.0},
            },
            team_c: {
                "sends": {"players": [pid_c], "picks": [], "cash": 0.0},
                "receives": {"players": [pid_a], "picks": [], "cash": 0.0},
            },
        }

        # Both proposals created in round 1 (both valid)
        r1 = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_b], terms=terms_1
        )
        trade_id_1 = r1["trade_id"]

        r2 = env.tool_propose_trade(
            from_team=team_a, parties=[team_a, team_c], terms=terms_2
        )
        trade_id_2 = r2["trade_id"]

        # Advance to consent window
        _advance_round(env)

        # Trade 1 executes successfully
        env.tool_execute_trade(from_team=team_a, trade_id=trade_id_1)
        r = env.tool_execute_trade(from_team=team_b, trade_id=trade_id_1)
        assert r["status"] == "executed"

        # Trade 2: A already sent pid_a, so re-validation should fail
        env.tool_execute_trade(from_team=team_a, trade_id=trade_id_2)
        r = env.tool_execute_trade(from_team=team_c, trade_id=trade_id_2)
        assert "error" in r
        assert "no longer valid" in r["error"].lower()

        # Player is on team_b only (not duplicated on team_c)
        assert pid_a in env.players_by_team[team_b]
        assert pid_a not in env.players_by_team[team_c]
        assert pid_a not in env.players_by_team[team_a]


# =====================================================================
# Item 5: Extended deterministic replay
# =====================================================================


class TestExtendedDeterministicReplay:
    def test_5_round_replay_with_hash(self):
        """5-round scenario covering picks, cash, expiry, force-advance.
        State hash must match between two independent runs."""

        def _run_scenario(seed: int) -> str:
            env = TradeDeadlineEnvironment(
                scenario_seed=seed, max_turns_without_advance=2
            )
            team_a = "Cascade Wolves"
            team_b = "Ironwood Foxes"
            team_c = "Eastgate Titans"

            # --- Round 1: propose two trades (one will expire) ---
            pid_a = "P-052"
            pid_b = "P-041"
            pid_c = "P-028"

            # Trade that will execute (cash transfer included)
            terms_exec = {
                team_a: {
                    "sends": {"players": [pid_a], "picks": [], "cash": 1.0},
                    "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
                },
                team_b: {
                    "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_a], "picks": [], "cash": 1.0},
                },
            }
            env.tool_propose_trade(
                from_team=team_a, parties=[team_a, team_b], terms=terms_exec
            )

            # Trade that will expire (no consent in consent window)
            terms_expire = {
                team_b: {
                    "sends": {"players": [pid_b], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_c], "picks": [], "cash": 0.0},
                },
                team_c: {
                    "sends": {"players": [pid_c], "picks": [], "cash": 0.0},
                    "receives": {"players": [pid_b], "picks": [], "cash": 0.0},
                },
            }
            env.tool_propose_trade(
                from_team=team_b, parties=[team_b, team_c], terms=terms_expire
            )

            # Advance round 1 -> 2
            for team in TEAMS:
                env.tool_advance_round(team=team)

            # --- Round 2: execute first trade, let second expire ---
            env.tool_execute_trade(from_team=team_a, trade_id="T-1-1")
            env.tool_execute_trade(from_team=team_b, trade_id="T-1-1")

            # Advance round 2 -> 3 (T-1-2 expires because no consent)
            for team in TEAMS:
                env.tool_advance_round(team=team)

            # --- Round 3: pick transfer trade ---
            pick_a = env.picks_by_team[team_a][0]
            pid_c2 = _find_tradeable_player(env, team_c)

            terms_pick = {
                team_a: {
                    "sends": {"players": [], "picks": [pick_a.pick_id], "cash": 0.0},
                    "receives": {"players": [pid_c2], "picks": [], "cash": 0.0},
                },
                team_c: {
                    "sends": {"players": [pid_c2], "picks": [], "cash": 0.0},
                    "receives": {
                        "players": [],
                        "picks": [pick_a.pick_id],
                        "cash": 0.0,
                    },
                },
            }
            env.tool_propose_trade(
                from_team=team_a, parties=[team_a, team_c], terms=terms_pick
            )

            # Advance round 3 -> 4
            for team in TEAMS:
                env.tool_advance_round(team=team)

            # --- Round 4: execute pick trade + force-advance test ---
            env.tool_execute_trade(from_team=team_a, trade_id="T-3-3")
            env.tool_execute_trade(from_team=team_c, trade_id="T-3-3")

            # Only 5 teams vote; 6th gets force-advanced
            for team in sorted(TEAMS)[:5]:
                env.tool_advance_round(team=team)
            stuck_team = sorted(TEAMS)[5]
            env.force_advance_check(stuck_team)
            env.force_advance_check(stuck_team)  # hits threshold=2

            # --- Round 5: final state ---
            env.tool_send_email(
                from_team=team_a,
                to=[team_b, team_c],
                subject="Final",
                body="Done trading.",
            )
            env.tool_check_my_progress(team=team_a)

            # Build state hash
            state = {
                "round": env.current_round,
                "players_by_team": {
                    t: sorted(pids)
                    for t, pids in sorted(env.players_by_team.items())
                },
                "picks_by_team": {
                    t: sorted(dp.pick_id for dp in picks)
                    for t, picks in sorted(env.picks_by_team.items())
                },
                "payroll": {
                    t: round(v, 4) for t, v in sorted(env.payroll.items())
                },
                "cash_used": {
                    t: round(v, 4) for t, v in sorted(env.cash_used.items())
                },
                "executed_count": len(env.executed_trades),
                "trade_counter": env._trade_counter,
                "email_counter": env._email_counter,
                "inbox_lengths": {
                    t: len(msgs) for t, msgs in sorted(env.inboxes.items())
                },
            }
            return hashlib.sha256(
                json.dumps(state, sort_keys=True).encode()
            ).hexdigest()

        hash1 = _run_scenario(42)
        hash2 = _run_scenario(42)
        assert hash1 == hash2, f"State diverged: {hash1} != {hash2}"

        # Different seed should produce different hash
        hash3 = _run_scenario(99)
        assert hash1 != hash3
