"""TradeDeadlineEnvironment — Phase 3 implementation (Section 7.3).

Multi-agent trade deadline environment managing 6 team agents, trade
proposals, execution, and round advancement.

Reproducibility guarantees:
- No reliance on dict iteration order for state-affecting logic.
- No wall-clock values in state; timestamps are (round, sequence_counter).
- RNG seeded from scenario_seed and threaded deterministically.
- advance_votes iterated sorted by team name.
"""

from __future__ import annotations

from trade_deadline_bench.data_structures import (
    TEAMS,
    DraftPick,
    ExecutedTrade,
    Player,
    ScenarioData,
    TradeProposal,
)
from trade_deadline_bench.goal_evaluator import evaluate_goal
from trade_deadline_bench.scenario_loader import generate_scenario
from trade_deadline_bench.trade_validator import validate_trade

MAX_ROUNDS = 8
MAX_ACTIONS_PER_TURN = 25


class TradeDeadlineEnvironment:
    """Multi-agent trade deadline environment."""

    def __init__(
        self,
        scenario_seed: int,
        agent_assignments: dict[str, str] | None = None,
        gm_stack_version: str = "1.0",
        run_id: int = 0,
        max_turns_without_advance: int = 5,
    ):
        self.scenario_seed = scenario_seed
        self.agent_assignments = agent_assignments or {t: "default" for t in TEAMS}
        self.gm_stack_version = gm_stack_version
        self.run_id = run_id
        self.max_turns_without_advance = max_turns_without_advance

        self.current_round = 1
        self.players_by_id: dict[str, Player] = {}
        self.players_by_team: dict[str, list[str]] = {}
        self.picks_by_team: dict[str, list[DraftPick]] = {}
        self.cash_used: dict[str, float] = {team: 0.0 for team in TEAMS}
        self.payroll: dict[str, float] = {}
        self.team_configs: dict = {}
        self.trade_proposals: dict[str, TradeProposal] = {}
        self.executed_trades: list[ExecutedTrade] = []
        self.inboxes: dict[str, list[dict]] = {team: [] for team in TEAMS}
        self.advance_votes: set[str] = set()

        # Counters for deterministic IDs
        self._trade_counter = 0
        self._email_counter = 0

        # Track turns without advance per team (for force-advance)
        self._turns_without_advance: dict[str, int] = {t: 0 for t in TEAMS}

        # Initial state snapshots for goal evaluation
        self._initial_players_by_team: dict[str, list[str]] = {}
        self._initial_picks_by_team: dict[str, list[str]] = {}
        self._initial_payroll: dict[str, float] = {}

        # Pending proposal broadcasts (delivered at start of next round)
        self._pending_broadcasts: list[dict] = []

        self._initialize_from_seed(scenario_seed)

    def _initialize_from_seed(self, seed: int) -> None:
        scenario = generate_scenario(seed)
        self.players_by_id = dict(scenario.players_by_id)
        self.players_by_team = {
            t: list(pids) for t, pids in scenario.players_by_team.items()
        }
        self.picks_by_team = {
            t: list(picks) for t, picks in scenario.picks_by_team.items()
        }
        self.payroll = dict(scenario.payroll)
        self.team_configs = dict(scenario.team_configs)

        # Snapshot initial state for goal evaluation
        self._initial_players_by_team = {
            t: list(pids) for t, pids in self.players_by_team.items()
        }
        self._initial_picks_by_team = {
            t: [dp.pick_id for dp in picks]
            for t, picks in self.picks_by_team.items()
        }
        self._initial_payroll = dict(self.payroll)

    def _get_scenario_snapshot(self) -> ScenarioData:
        """Build a ScenarioData from current mutable state for validation."""
        return ScenarioData(
            players_by_id=self.players_by_id,
            players_by_team=self.players_by_team,
            picks_by_team=self.picks_by_team,
            payroll=self.payroll,
            team_configs=self.team_configs,
        )

    # ------------------------------------------------------------------
    # Tool: send_email
    # ------------------------------------------------------------------

    def tool_send_email(
        self,
        from_team: str,
        to: list[str],
        subject: str,
        body: str,
    ) -> dict:
        """Send an email to one or more teams.

        Deposits in each recipient's inbox. Uses (round, counter) as
        timestamp for reproducibility.
        """
        if from_team not in TEAMS:
            return {"error": f"Unknown sender: {from_team}"}
        for recipient in to:
            if recipient not in TEAMS:
                return {"error": f"Unknown recipient: {recipient}"}

        self._email_counter += 1
        message = {
            "type": "email",
            "from": from_team,
            "to": sorted(to),
            "subject": subject,
            "body": body,
            "timestamp": (self.current_round, self._email_counter),
        }

        for recipient in sorted(to):
            self.inboxes[recipient].append(message)

        return {"status": "sent", "recipients": sorted(to)}

    # ------------------------------------------------------------------
    # Tool: read_inbox
    # ------------------------------------------------------------------

    def tool_read_inbox(
        self,
        team: str,
        filter_team: str | None = None,
    ) -> dict:
        """Read a team's inbox, optionally filtering by sender."""
        if team not in TEAMS:
            return {"error": f"Unknown team: {team}"}

        messages = self.inboxes[team]
        if filter_team is not None:
            messages = [m for m in messages if m.get("from") == filter_team]

        return {"inbox": messages}

    # ------------------------------------------------------------------
    # Tool: view_team_roster
    # ------------------------------------------------------------------

    def tool_view_team_roster(self, team_name: str) -> dict:
        """Return the current roster for a team (public information)."""
        if team_name not in TEAMS:
            return {"error": f"Unknown team: {team_name}"}

        players = []
        for pid in sorted(self.players_by_team[team_name]):
            p = self.players_by_id[pid]
            players.append({
                "player_id": p.player_id,
                "name": p.name,
                "talent_rating": p.talent_rating,
                "defense_rating": p.defense_rating,
                "position": p.position,
                "age": p.age,
                "aav": p.aav,
                "years_remaining": p.years_remaining,
                "is_tradeable": p.is_tradeable,
            })

        return {"team": team_name, "players": players}

    # ------------------------------------------------------------------
    # Tool: view_team_cap_sheet
    # ------------------------------------------------------------------

    def tool_view_team_cap_sheet(self, team_name: str) -> dict:
        """Return cap information for a team."""
        if team_name not in TEAMS:
            return {"error": f"Unknown team: {team_name}"}

        from trade_deadline_bench.data_structures import SALARY_CAP

        current_payroll = self.payroll[team_name]
        cap_room = SALARY_CAP - current_payroll
        return {
            "team": team_name,
            "payroll": current_payroll,
            "cap_room": cap_room,
            "salary_cap": SALARY_CAP,
            "cash_used": self.cash_used[team_name],
        }

    # ------------------------------------------------------------------
    # Tool: view_executed_trades
    # ------------------------------------------------------------------

    def tool_view_executed_trades(self) -> dict:
        """Return list of all executed trades (public broadcast)."""
        return {
            "executed_trades": [
                {
                    "trade_id": t.trade_id,
                    "executed_round": t.executed_round,
                    "parties": t.parties,
                    "asset_movements": t.asset_movements,
                }
                for t in self.executed_trades
            ]
        }

    # ------------------------------------------------------------------
    # Tool: propose_trade
    # ------------------------------------------------------------------

    def tool_propose_trade(
        self,
        from_team: str,
        parties: list[str],
        terms: dict,
    ) -> dict:
        """Propose a trade. Validates, assigns trade_id, broadcasts.

        Parameters
        ----------
        from_team : str
            Team proposing the trade.
        parties : list[str]
            All teams involved (including from_team).
        terms : dict
            Asset movements dict: {team: {sends: {...}, receives: {...}}}

        Returns
        -------
        dict with trade_id on success, or error on failure.
        """
        if from_team not in TEAMS:
            return {"error": f"Unknown team: {from_team}"}
        if from_team not in parties:
            return {"error": "Proposing team must be in parties list"}

        # Build the trade dict for validation
        trade_dict = {
            "parties": parties,
            "asset_movements": terms,
        }

        # Validate using Phase 2 trade_validator
        scenario = self._get_scenario_snapshot()
        valid, reason = validate_trade(trade_dict, scenario, self.cash_used)
        if not valid:
            return {"error": reason}

        # Assign trade_id: T-{round}-{counter}
        self._trade_counter += 1
        trade_id = f"T-{self.current_round}-{self._trade_counter}"

        # Create TradeProposal
        consent_log = {team: False for team in parties}
        proposal = TradeProposal(
            trade_id=trade_id,
            proposing_team=from_team,
            proposed_round=self.current_round,
            parties=sorted(parties),
            asset_movements=terms,
            consent_log=consent_log,
            expired=False,
        )
        self.trade_proposals[trade_id] = proposal

        # Queue broadcast for delivery at start of next round (1-round delay)
        self._email_counter += 1
        broadcast_msg = {
            "type": "trade_proposal",
            "from": "SYSTEM",
            "to": sorted(parties),
            "subject": f"[TRADE PROPOSAL {trade_id} from {from_team} — see attached terms]",
            "body": f"Trade proposal {trade_id} involving {', '.join(sorted(parties))}.",
            "trade_id": trade_id,
            "terms": terms,
            "timestamp": (self.current_round, self._email_counter),
        }
        self._pending_broadcasts.append(broadcast_msg)

        return {
            "trade_id": trade_id,
            "parties": sorted(parties),
            "expires_at_round": self.current_round + 1,
        }

    # ------------------------------------------------------------------
    # Tool: execute_trade
    # ------------------------------------------------------------------

    def tool_execute_trade(self, from_team: str, trade_id: str) -> dict:
        """Record consent for a trade. If all parties consent, execute.

        Returns status dict indicating consent recorded or trade executed.
        """
        if from_team not in TEAMS:
            return {"error": f"Unknown team: {from_team}"}

        proposal = self.trade_proposals.get(trade_id)
        if proposal is None:
            return {"error": f"Trade {trade_id} not found"}
        if proposal.expired:
            return {"error": f"Trade {trade_id} has expired"}
        if from_team not in proposal.parties:
            return {"error": f"{from_team} is not a party to trade {trade_id}"}

        # Reject same-round consent (proposal broadcast has 1-round delay)
        if proposal.proposed_round == self.current_round:
            return {
                "error": (
                    f"Trade {trade_id} was proposed this round. "
                    f"Consent is only allowed starting round "
                    f"{proposal.proposed_round + 1}."
                )
            }

        # Record consent
        proposal.consent_log[from_team] = True

        # Check if all parties have consented
        all_consented = all(
            proposal.consent_log[team] for team in sorted(proposal.parties)
        )

        if all_consented:
            # Re-validate against current state before executing
            trade_dict = {
                "parties": proposal.parties,
                "asset_movements": proposal.asset_movements,
            }
            scenario = self._get_scenario_snapshot()
            valid, reason = validate_trade(
                trade_dict, scenario, self.cash_used
            )
            if not valid:
                proposal.expired = True
                return {"error": f"Trade {trade_id} is no longer valid: {reason}"}
            return self._execute_trade(proposal)

        return {
            "status": "consent_recorded",
            "trade_id": trade_id,
            "consents": {
                team: proposal.consent_log[team]
                for team in sorted(proposal.parties)
            },
        }

    def _execute_trade(self, proposal: TradeProposal) -> dict:
        """Execute a fully-consented trade: transfer assets, update state."""
        terms = proposal.asset_movements

        # Transfer players
        for team in sorted(proposal.parties):
            sends = terms[team].get("sends", {})
            for pid in sends.get("players", []):
                # Remove from sending team
                if pid in self.players_by_team[team]:
                    self.players_by_team[team].remove(pid)

        for team in sorted(proposal.parties):
            receives = terms[team].get("receives", {})
            for pid in receives.get("players", []):
                # Add to receiving team
                self.players_by_team[team].append(pid)
                # Update player's current_team
                self.players_by_id[pid].current_team = team

        # Transfer picks: pre-collect objects before removing
        pick_objects_by_id: dict[str, DraftPick] = {}
        for team in sorted(proposal.parties):
            sends = terms[team].get("sends", {})
            for pick_id in sends.get("picks", []):
                for dp in self.picks_by_team.get(team, []):
                    if dp.pick_id == pick_id:
                        pick_objects_by_id[pick_id] = dp
                        break

        # Remove picks from senders
        for team in sorted(proposal.parties):
            sends = terms[team].get("sends", {})
            sent_pick_ids = set(sends.get("picks", []))
            if sent_pick_ids:
                self.picks_by_team[team] = [
                    dp for dp in self.picks_by_team[team]
                    if dp.pick_id not in sent_pick_ids
                ]

        # Add picks to receivers
        for team in sorted(proposal.parties):
            receives = terms[team].get("receives", {})
            for pick_id in receives.get("picks", []):
                pick_obj = pick_objects_by_id.get(pick_id)
                if pick_obj is not None:
                    pick_obj.owning_team = team
                    self.picks_by_team[team].append(pick_obj)

        # Update payrolls and cash_used
        for team in sorted(proposal.parties):
            sends = terms[team].get("sends", {})
            receives = terms[team].get("receives", {})

            outgoing_salary = sum(
                self.players_by_id[pid].aav
                for pid in sends.get("players", [])
            )
            incoming_salary = sum(
                self.players_by_id[pid].aav
                for pid in receives.get("players", [])
            )

            cash_out = float(sends.get("cash", 0.0))
            self.payroll[team] = self.payroll[team] - outgoing_salary + incoming_salary
            self.cash_used[team] += cash_out

        # Record executed trade
        executed = ExecutedTrade(
            trade_id=proposal.trade_id,
            executed_round=self.current_round,
            parties=sorted(proposal.parties),
            asset_movements=proposal.asset_movements,
        )
        self.executed_trades.append(executed)

        # Broadcast to all 6 teams
        self._email_counter += 1
        broadcast_msg = {
            "type": "trade_executed",
            "from": "SYSTEM",
            "to": sorted(TEAMS),
            "subject": f"[TRADE EXECUTED {proposal.trade_id}]",
            "body": (
                f"Trade {proposal.trade_id} executed between "
                f"{', '.join(sorted(proposal.parties))}."
            ),
            "trade_id": proposal.trade_id,
            "terms": proposal.asset_movements,
            "timestamp": (self.current_round, self._email_counter),
        }
        for team in sorted(TEAMS):
            self.inboxes[team].append(broadcast_msg)

        return {
            "status": "executed",
            "trade_id": proposal.trade_id,
            "parties": sorted(proposal.parties),
        }

    # ------------------------------------------------------------------
    # Tool: check_my_progress
    # ------------------------------------------------------------------

    def tool_check_my_progress(self, team: str) -> dict:
        """Return evaluated goal status for the calling team only.

        This is private — not visible to other teams.
        Returns: {goal_met: bool, details: str, bonuses_eligible: [...]}
        """
        if team not in TEAMS:
            return {"error": f"Unknown team: {team}"}

        result = evaluate_goal(
            team=team,
            players_by_id=self.players_by_id,
            players_by_team=self.players_by_team,
            picks_by_team=self.picks_by_team,
            payroll=self.payroll,
            cash_used=self.cash_used,
            initial_players_by_team=self._initial_players_by_team,
            initial_picks_by_team=self._initial_picks_by_team,
            initial_payroll=self._initial_payroll,
            current_round=self.current_round,
        )
        result["team"] = team
        return result

    # ------------------------------------------------------------------
    # Tool: advance_round
    # ------------------------------------------------------------------

    def tool_advance_round(
        self,
        team: str,
        notes: str | None = None,
    ) -> dict:
        """Record team's vote to advance. When all 6 vote, round advances."""
        if team not in TEAMS:
            return {"error": f"Unknown team: {team}"}

        self.advance_votes.add(team)
        self._turns_without_advance[team] = 0

        if len(self.advance_votes) == len(TEAMS):
            return self._advance_round()

        return {
            "status": "vote_recorded",
            "team": team,
            "votes_so_far": sorted(self.advance_votes),
            "votes_needed": len(TEAMS) - len(self.advance_votes),
        }

    def force_advance_check(self, team: str) -> bool:
        """Check if a team should be force-advanced due to inactivity.

        Called by orchestration after each turn. If a team has gone
        max_turns_without_advance turns without voting, auto-vote.
        Returns True if the round advanced as a result.
        """
        self._turns_without_advance[team] += 1

        if self._turns_without_advance[team] >= self.max_turns_without_advance:
            self.advance_votes.add(team)
            self._turns_without_advance[team] = 0

            if len(self.advance_votes) == len(TEAMS):
                self._advance_round()
                return True

        return False

    def _advance_round(self) -> dict:
        """Advance to the next round: expire pending proposals, reset votes."""
        # Expire proposals from round N-1 (consent window was this round)
        # A proposal proposed in round N has consent window in round N+1.
        # At round advance from N+1 to N+2, proposals from N expire.
        for trade_id in sorted(self.trade_proposals.keys()):
            proposal = self.trade_proposals[trade_id]
            if proposal.expired:
                continue
            # Already executed?
            if any(et.trade_id == trade_id for et in self.executed_trades):
                continue
            # Proposals whose consent window is this round (proposed_round + 1 == current_round)
            if proposal.proposed_round + 1 <= self.current_round:
                all_consented = all(
                    proposal.consent_log[t] for t in sorted(proposal.parties)
                )
                if not all_consented:
                    proposal.expired = True

        self.current_round += 1
        self.advance_votes.clear()

        # Deliver pending proposal broadcasts (proposals from round N-1
        # are now visible in round N)
        for msg in self._pending_broadcasts:
            for team in sorted(msg["to"]):
                self.inboxes[team].append(msg)
        self._pending_broadcasts.clear()

        return {
            "status": "round_advanced",
            "new_round": self.current_round,
        }

    # ------------------------------------------------------------------
    # Resolve pending trades at end of round (called by orchestration)
    # ------------------------------------------------------------------

    def resolve_pending_trades(self) -> None:
        """Expire proposals that didn't get full consent this round."""
        for trade_id in sorted(self.trade_proposals.keys()):
            proposal = self.trade_proposals[trade_id]
            if proposal.expired:
                continue
            # Check if already executed
            if any(et.trade_id == trade_id for et in self.executed_trades):
                continue
            all_consented = all(
                proposal.consent_log[t] for t in sorted(proposal.parties)
            )
            if not all_consented:
                proposal.expired = True
