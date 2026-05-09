"""OracleAgent — pure deterministic search agent for goal calibration.

The OracleAgent has access to all hidden information (goals, reservations,
hidden valuations, picks values) and uses a greedy search with bounded
proposals to find valid trades that achieve its team's goal.

Algorithm: Greedy matching with full-information acceptability check.
1. Evaluate current goal state
2. If goal met, just vote to advance
3. Search for trades that advance own goal AND are acceptable to counterparty
4. Consent to any incoming proposal that doesn't hurt own goal
5. Vote to advance after making proposals

Bounds:
- Max 10 proposals per round
- Bounded by 8-round deadline (same as real agents)
- No LLM calls, no randomness beyond deterministic tie-breaking (sorted)
"""

from __future__ import annotations

from trade_deadline_bench.data_structures import (
    SALARY_CAP,
    TEAMS,
    DraftPick,
    Player,
    ScenarioData,
)
from trade_deadline_bench.environment import TradeDeadlineEnvironment
from trade_deadline_bench.goal_evaluator import evaluate_goal
from trade_deadline_bench.trade_validator import validate_trade

MAX_PROPOSALS_PER_ROUND = 10


class OracleAgent:
    """Deterministic oracle agent with full information access.

    Uses greedy search to find trades that achieve its team's goal.
    No LLM calls. No randomness. Pure constraint satisfaction.
    """

    def __init__(self, team: str, env: TradeDeadlineEnvironment):
        self.team = team
        self.env = env
        self._proposals_made_this_round = 0

    def reset_round(self) -> None:
        """Reset per-round counters."""
        self._proposals_made_this_round = 0

    def evaluate_own_goal(self) -> dict:
        """Evaluate current goal state."""
        return evaluate_goal(
            team=self.team,
            players_by_id=self.env.players_by_id,
            players_by_team=self.env.players_by_team,
            picks_by_team=self.env.picks_by_team,
            payroll=self.env.payroll,
            cash_used=self.env.cash_used,
            initial_players_by_team=self.env._initial_players_by_team,
            initial_picks_by_team=self.env._initial_picks_by_team,
            initial_payroll=self.env._initial_payroll,
            current_round=self.env.current_round,
        )

    def consent_phase(self) -> None:
        """Check inbox and consent to proposals that don't hurt our goal."""
        inbox = self.env.tool_read_inbox(self.team)
        for msg in inbox["inbox"]:
            if msg.get("type") != "trade_proposal":
                continue
            trade_id = msg.get("trade_id")
            if trade_id is None:
                continue
            proposal = self.env.trade_proposals.get(trade_id)
            if proposal is None or proposal.expired:
                continue
            if self.team not in proposal.parties:
                continue
            # Already consented?
            if proposal.consent_log.get(self.team, False):
                continue
            # Check if the trade is acceptable for us
            if self._is_acceptable(proposal):
                self.env.tool_execute_trade(self.team, trade_id)

    def propose_phase(self) -> None:
        """Search for and propose trades that advance our goal."""
        # If goal already met, skip proposals
        status = self.evaluate_own_goal()
        if status["goal_met"]:
            return

        candidates = self._search_candidate_trades()
        for trade_terms in candidates:
            if self._proposals_made_this_round >= MAX_PROPOSALS_PER_ROUND:
                break
            result = self.env.tool_propose_trade(
                from_team=self.team,
                parties=trade_terms["parties"],
                terms=trade_terms["asset_movements"],
            )
            if "error" not in result:
                self._proposals_made_this_round += 1

    def _is_acceptable(self, proposal) -> bool:
        """Check if a trade proposal is acceptable (doesn't hurt our goal).

        A trade is acceptable if:
        1. It directly advances our goal, OR
        2. It doesn't make our goal harder to achieve (neutral)
        """
        terms = proposal.asset_movements
        if self.team not in terms:
            return False

        my_sends = terms[self.team].get("sends", {})
        my_receives = terms[self.team].get("receives", {})

        # Simulate the trade effect on our goal
        return self._trade_is_neutral_or_positive(my_sends, my_receives)

    def _trade_is_neutral_or_positive(self, sends: dict, receives: dict) -> bool:
        """Check if a trade doesn't hurt our goal achievement prospects.

        This uses team-specific logic based on what each goal cares about.
        """
        team = self.team
        players_by_id = self.env.players_by_id

        sent_players = sends.get("players", [])
        recv_players = receives.get("players", [])
        sent_picks = sends.get("picks", [])
        recv_picks = receives.get("picks", [])

        if team == "Apex City Aces":
            return self._acceptable_for_apex(
                sent_players, recv_players, sent_picks, recv_picks
            )
        elif team == "Harlow Vipers":
            return self._acceptable_for_harlow(
                sent_players, recv_players, sent_picks, recv_picks
            )
        elif team == "Eastgate Titans":
            return self._acceptable_for_eastgate(
                sent_players, recv_players, sent_picks, recv_picks
            )
        elif team == "Ironwood Foxes":
            return self._acceptable_for_ironwood(
                sent_players, recv_players, sent_picks, recv_picks
            )
        elif team == "Cascade Wolves":
            return self._acceptable_for_cascade(
                sent_players, recv_players, sent_picks, recv_picks
            )
        elif team == "Granite Bay Bulls":
            return self._acceptable_for_granite_bay(
                sent_players, recv_players, sent_picks, recv_picks
            )
        return False

    def _acceptable_for_apex(
        self, sent_players, recv_players, sent_picks, recv_picks
    ) -> bool:
        """Apex wants a player rated >= 60. Accept if we receive one or don't
        lose elite acquisitions."""
        p = self.env.players_by_id
        # If we receive a qualifying player, always accept
        if any(p[pid].talent_rating >= 60 for pid in recv_players if pid in p):
            return True
        # Don't send away a qualifying player we already acquired
        initial = set(self.env._initial_players_by_team[self.team])
        for pid in sent_players:
            if pid not in initial and pid in p and p[pid].talent_rating >= 60:
                return False
        # Neutral trade is fine
        return True

    def _acceptable_for_harlow(
        self, sent_players, recv_players, sent_picks, recv_picks
    ) -> bool:
        """Harlow wants to trade a star for a package (player >= 59 + 1st pick).
        Accept if the trade involves sending a star and getting the package,
        or is neutral."""
        p = self.env.players_by_id
        initial_pids = self.env._initial_players_by_team[self.team]
        stars = self._get_harlow_stars()
        star_ids = {s.player_id for s in stars}

        # If we're trading a star, check if we get a good package
        sending_star = any(pid in star_ids for pid in sent_players)
        if sending_star:
            has_player_59 = any(
                p[pid].talent_rating >= 59 for pid in recv_players if pid in p
            )
            has_first_pick = any(
                self._is_first_round_pick(pick_id) for pick_id in recv_picks
            )
            return has_player_59 and has_first_pick

        # If not sending a star, accept if neutral (don't give away acquired
        # good players or acquired picks)
        acquired = set(self.env.players_by_team[self.team]) - set(initial_pids)
        for pid in sent_players:
            if pid in acquired and pid in p and p[pid].talent_rating >= 59:
                return False
        # Don't give away acquired 1st-round picks
        acquired_pick_ids = self._get_acquired_pick_ids()
        for pick_id in sent_picks:
            if pick_id in acquired_pick_ids and self._is_first_round_pick(pick_id):
                return False
        return True

    def _acceptable_for_eastgate(
        self, sent_players, recv_players, sent_picks, recv_picks
    ) -> bool:
        """Eastgate wants a SF/PF rated 57-71, >= 2 years, <= $13M.
        Accept if we get a qualifying player or trade is neutral."""
        p = self.env.players_by_id
        # If we receive a qualifying player, accept
        for pid in recv_players:
            if pid in p:
                pl = p[pid]
                if (
                    pl.position in ("SF", "PF")
                    and 57 <= pl.talent_rating <= 71
                    and pl.years_remaining >= 2
                    and pl.aav <= 13.0
                ):
                    return True
        # Don't send away a qualifying player we already acquired
        initial = set(self.env._initial_players_by_team[self.team])
        for pid in sent_players:
            if pid not in initial and pid in p:
                pl = p[pid]
                if (
                    pl.position in ("SF", "PF")
                    and 57 <= pl.talent_rating <= 71
                    and pl.years_remaining >= 2
                    and pl.aav <= 13.0
                ):
                    return False
        return True

    def _acceptable_for_ironwood(
        self, sent_players, recv_players, sent_picks, recv_picks
    ) -> bool:
        """Ironwood wants 2 players with defense sum >= 15.
        Accept if we get high-defense players or trade is neutral."""
        p = self.env.players_by_id
        # If we receive a defense player rated >= 7, accept
        if any(p[pid].defense_rating >= 7 for pid in recv_players if pid in p):
            return True
        # Don't send away high-defense acquisitions
        initial = set(self.env._initial_players_by_team[self.team])
        for pid in sent_players:
            if pid not in initial and pid in p and p[pid].defense_rating >= 7:
                return False
        return True

    def _acceptable_for_cascade(
        self, sent_players, recv_players, sent_picks, recv_picks
    ) -> bool:
        """Cascade wants 2 first-round picks AND shed $19M total_contract.
        Accept if we receive 1st-round picks or shed salary."""
        p = self.env.players_by_id
        # Receiving a first-round pick is always good
        if any(self._is_first_round_pick(pick_id) for pick_id in recv_picks):
            return True
        # Shedding salary (sending high-contract players) is good
        sent_salary = sum(
            p[pid].total_contract for pid in sent_players if pid in p
        )
        recv_salary = sum(
            p[pid].total_contract for pid in recv_players if pid in p
        )
        if sent_salary > recv_salary:
            return True
        # Don't give away acquired 1st-round picks
        acquired_pick_ids = self._get_acquired_pick_ids()
        for pick_id in sent_picks:
            if pick_id in acquired_pick_ids and self._is_first_round_pick(pick_id):
                return False
        return True

    def _acceptable_for_granite_bay(
        self, sent_players, recv_players, sent_picks, recv_picks
    ) -> bool:
        """Granite Bay wants cap room >= $5M, shed >= $4M AAV, rating loss <= 15.
        Accept if we shed more AAV than we take on without too much rating loss."""
        p = self.env.players_by_id
        sent_aav = sum(p[pid].aav for pid in sent_players if pid in p)
        recv_aav = sum(p[pid].aav for pid in recv_players if pid in p)
        sent_rating = sum(p[pid].talent_rating for pid in sent_players if pid in p)
        recv_rating = sum(p[pid].talent_rating for pid in recv_players if pid in p)

        # Calculate current state
        current_sent = self._get_sent_players_set()
        current_acquired = self._get_acquired_players_set()

        # Project new totals after this trade
        all_sent_aav = sum(
            p[pid].aav for pid in current_sent if pid in p
        ) + sent_aav
        all_acquired_aav = sum(
            p[pid].aav for pid in current_acquired if pid in p
        ) + recv_aav
        all_sent_rating = sum(
            p[pid].talent_rating for pid in current_sent if pid in p
        ) + sent_rating
        all_acquired_rating = sum(
            p[pid].talent_rating for pid in current_acquired if pid in p
        ) + recv_rating

        projected_aav_shed = all_sent_aav - all_acquired_aav
        projected_rating_loss = all_sent_rating - all_acquired_rating

        # Accept if projected rating loss stays <= 15 and we shed AAV
        if sent_aav > recv_aav and projected_rating_loss <= 15:
            return True
        # Also accept if receiving a 1st-round pick (bonus)
        if any(self._is_first_round_pick(pick_id) for pick_id in recv_picks):
            if projected_rating_loss <= 15:
                return True
        # Neutral if we don't lose anything important
        if sent_aav == 0 and recv_aav == 0 and not sent_players:
            return True
        return False

    # ------------------------------------------------------------------
    # Search for candidate trades
    # ------------------------------------------------------------------

    def _search_candidate_trades(self) -> list[dict]:
        """Search for valid trades that advance our goal.

        Returns list of trade dicts ready for tool_propose_trade.
        """
        team = self.team
        if team == "Apex City Aces":
            return self._search_apex_trades()
        elif team == "Harlow Vipers":
            return self._search_harlow_trades()
        elif team == "Eastgate Titans":
            return self._search_eastgate_trades()
        elif team == "Ironwood Foxes":
            return self._search_ironwood_trades()
        elif team == "Cascade Wolves":
            return self._search_cascade_trades()
        elif team == "Granite Bay Bulls":
            return self._search_granite_bay_trades()
        return []

    def _search_apex_trades(self) -> list[dict]:
        """Apex: find trades to acquire a player rated >= 60."""
        candidates = []
        p = self.env.players_by_id

        # Find all tradeable players rated >= 60 on other teams
        targets = []
        for other_team in sorted(TEAMS):
            if other_team == self.team:
                continue
            for pid in sorted(self.env.players_by_team[other_team]):
                player = p[pid]
                if player.talent_rating >= 60 and player.is_tradeable:
                    targets.append((other_team, pid))

        # For each target, try to build a valid trade
        for other_team, target_pid in targets:
            trade = self._build_player_acquisition_trade(
                target_pid, other_team
            )
            if trade is not None:
                candidates.append(trade)
                if len(candidates) >= MAX_PROPOSALS_PER_ROUND:
                    break

        return candidates

    def _search_harlow_trades(self) -> list[dict]:
        """Harlow: trade a star for package (player >= 59 + 1st-round pick)."""
        candidates = []
        p = self.env.players_by_id
        stars = self._get_harlow_stars()

        if not stars:
            return []

        # For each star, find a team that can provide a package
        for star in stars:
            if star.player_id not in self.env.players_by_team[self.team]:
                continue  # Star already traded

            for other_team in sorted(TEAMS):
                if other_team == self.team:
                    continue
                trade = self._build_harlow_star_trade(star, other_team)
                if trade is not None:
                    candidates.append(trade)
                    if len(candidates) >= MAX_PROPOSALS_PER_ROUND:
                        return candidates

        return candidates

    def _search_eastgate_trades(self) -> list[dict]:
        """Eastgate: acquire SF/PF rated 57-71, >= 2 years, <= $13M."""
        candidates = []
        p = self.env.players_by_id

        targets = []
        for other_team in sorted(TEAMS):
            if other_team == self.team:
                continue
            for pid in sorted(self.env.players_by_team[other_team]):
                player = p[pid]
                if (
                    player.is_tradeable
                    and player.position in ("SF", "PF")
                    and 57 <= player.talent_rating <= 71
                    and player.years_remaining >= 2
                    and player.aav <= 13.0
                ):
                    targets.append((other_team, pid))

        for other_team, target_pid in targets:
            trade = self._build_player_acquisition_trade(
                target_pid, other_team
            )
            if trade is not None:
                candidates.append(trade)
                if len(candidates) >= MAX_PROPOSALS_PER_ROUND:
                    break

        return candidates

    def _search_ironwood_trades(self) -> list[dict]:
        """Ironwood: acquire 2 players with defense sum >= 15."""
        candidates = []
        p = self.env.players_by_id

        # Find high-defense tradeable players on other teams
        targets = []
        for other_team in sorted(TEAMS):
            if other_team == self.team:
                continue
            for pid in sorted(self.env.players_by_team[other_team]):
                player = p[pid]
                if player.is_tradeable and player.defense_rating >= 7:
                    targets.append((other_team, pid))

        # Try to acquire them one at a time
        for other_team, target_pid in targets:
            trade = self._build_player_acquisition_trade(
                target_pid, other_team
            )
            if trade is not None:
                candidates.append(trade)
                if len(candidates) >= MAX_PROPOSALS_PER_ROUND:
                    break

        return candidates

    def _search_cascade_trades(self) -> list[dict]:
        """Cascade: acquire 2 first-round picks + shed $19M salary."""
        candidates = []
        p = self.env.players_by_id

        # Strategy: offer salary-heavy tradeable players in exchange for
        # 1st-round picks. Teams with cap room (or that need players) benefit.
        my_tradeable = self._get_my_expendable_players()
        # Sort by total_contract descending (want to shed biggest contracts)
        my_tradeable.sort(key=lambda pid: -p[pid].total_contract)

        for other_team in sorted(TEAMS):
            if other_team == self.team:
                continue
            # Find 1st-round picks this team owns
            other_first_picks = [
                dp for dp in self.env.picks_by_team[other_team]
                if dp.pick_round == 1
            ]
            if not other_first_picks:
                continue

            for pick in sorted(other_first_picks, key=lambda dp: dp.pick_id):
                # Try to build a trade: we send a player, they send a pick
                trade = self._build_salary_for_pick_trade(
                    other_team, pick, my_tradeable
                )
                if trade is not None:
                    candidates.append(trade)
                    if len(candidates) >= MAX_PROPOSALS_PER_ROUND:
                        return candidates

        return candidates

    def _search_granite_bay_trades(self) -> list[dict]:
        """Granite Bay: shed AAV while keeping rating loss <= 15."""
        candidates = []
        p = self.env.players_by_id

        # Strategy: trade high-AAV, low-talent players to teams with cap room
        my_tradeable = self._get_my_expendable_players()
        # Sort by AAV/talent ratio descending (best to shed: high AAV, low talent)
        my_tradeable.sort(
            key=lambda pid: -(p[pid].aav / max(p[pid].talent_rating - 49, 1))
        )

        for pid in my_tradeable:
            player = p[pid]
            # Check rating loss budget
            current_rating_loss = self._current_rating_loss()
            if current_rating_loss + player.talent_rating > 15:
                # Would exceed rating loss if we don't get a player back
                # Try to find a swap with a lower-AAV player
                for other_team in sorted(TEAMS):
                    if other_team == self.team:
                        continue
                    trade = self._build_salary_dump_trade(pid, other_team)
                    if trade is not None:
                        candidates.append(trade)
                        if len(candidates) >= MAX_PROPOSALS_PER_ROUND:
                            return candidates
                        break
            else:
                # Can send without receiving a player (picks/cash only return)
                for other_team in sorted(TEAMS):
                    if other_team == self.team:
                        continue
                    trade = self._build_salary_dump_trade(pid, other_team)
                    if trade is not None:
                        candidates.append(trade)
                        if len(candidates) >= MAX_PROPOSALS_PER_ROUND:
                            return candidates
                        break

        return candidates

    # ------------------------------------------------------------------
    # Trade building helpers
    # ------------------------------------------------------------------

    def _build_player_acquisition_trade(
        self, target_pid: str, other_team: str
    ) -> dict | None:
        """Build a trade to acquire target_pid from other_team.

        Strategy: offer our expendable players that match salary rules.
        Tries increasingly larger packages (1-for-1, 2-for-1, 3-for-1, 4-for-1).
        """
        p = self.env.players_by_id
        target = p[target_pid]
        target_aav = target.aav

        # Find our expendable players to offer
        my_expendable = self._get_my_expendable_players()
        # Sort by AAV descending (send highest-salary first for matching)
        my_expendable.sort(key=lambda pid: -p[pid].aav)

        # Try single player swap first
        for my_pid in my_expendable:
            trade = self._try_two_team_trade(
                my_sends_players=[my_pid],
                my_receives_players=[target_pid],
                other_team=other_team,
                other_sends_players=[target_pid],
                other_receives_players=[my_pid],
            )
            if trade is not None:
                if self._would_other_accept(other_team, trade):
                    return trade

        # Try 2-for-1
        if len(my_expendable) >= 2:
            for i in range(min(5, len(my_expendable))):
                for j in range(i + 1, min(6, len(my_expendable))):
                    trade = self._try_two_team_trade(
                        my_sends_players=[my_expendable[i], my_expendable[j]],
                        my_receives_players=[target_pid],
                        other_team=other_team,
                        other_sends_players=[target_pid],
                        other_receives_players=[my_expendable[i], my_expendable[j]],
                    )
                    if trade is not None:
                        if self._would_other_accept(other_team, trade):
                            return trade

        # Try 3-for-1
        if len(my_expendable) >= 3:
            for i in range(min(4, len(my_expendable))):
                for j in range(i + 1, min(5, len(my_expendable))):
                    for k in range(j + 1, min(6, len(my_expendable))):
                        trade = self._try_two_team_trade(
                            my_sends_players=[
                                my_expendable[i], my_expendable[j], my_expendable[k]
                            ],
                            my_receives_players=[target_pid],
                            other_team=other_team,
                            other_sends_players=[target_pid],
                            other_receives_players=[
                                my_expendable[i], my_expendable[j], my_expendable[k]
                            ],
                        )
                        if trade is not None:
                            if self._would_other_accept(other_team, trade):
                                return trade

        # Try 4-for-1 (all expendable)
        if len(my_expendable) >= 4:
            sends = my_expendable[:4]
            trade = self._try_two_team_trade(
                my_sends_players=sends,
                my_receives_players=[target_pid],
                other_team=other_team,
                other_sends_players=[target_pid],
                other_receives_players=sends,
            )
            if trade is not None:
                if self._would_other_accept(other_team, trade):
                    return trade

        # Try player(s) + pick
        my_picks = self._get_my_expendable_picks()
        for my_pid in my_expendable[:4]:
            for pick in my_picks[:4]:
                trade = self._try_two_team_trade(
                    my_sends_players=[my_pid],
                    my_receives_players=[target_pid],
                    other_team=other_team,
                    other_sends_players=[target_pid],
                    other_receives_players=[my_pid],
                    my_sends_picks=[pick.pick_id],
                    other_receives_picks=[pick.pick_id],
                )
                if trade is not None:
                    if self._would_other_accept(other_team, trade):
                        return trade

        # Try 2 players + pick
        if len(my_expendable) >= 2:
            for i in range(min(4, len(my_expendable))):
                for j in range(i + 1, min(5, len(my_expendable))):
                    for pick in my_picks[:3]:
                        trade = self._try_two_team_trade(
                            my_sends_players=[my_expendable[i], my_expendable[j]],
                            my_receives_players=[target_pid],
                            other_team=other_team,
                            other_sends_players=[target_pid],
                            other_receives_players=[
                                my_expendable[i], my_expendable[j]
                            ],
                            my_sends_picks=[pick.pick_id],
                            other_receives_picks=[pick.pick_id],
                        )
                        if trade is not None:
                            if self._would_other_accept(other_team, trade):
                                return trade

        # Try player + cash
        for my_pid in my_expendable[:4]:
            for cash_amount in [2.0, 4.0, 5.0]:
                trade = self._try_two_team_trade(
                    my_sends_players=[my_pid],
                    my_receives_players=[target_pid],
                    other_team=other_team,
                    other_sends_players=[target_pid],
                    other_receives_players=[my_pid],
                    my_sends_cash=cash_amount,
                    other_receives_cash=cash_amount,
                )
                if trade is not None:
                    if self._would_other_accept(other_team, trade):
                        return trade

        return None

    def _build_harlow_star_trade(
        self, star: Player, other_team: str
    ) -> dict | None:
        """Build a trade sending Harlow's star for a package.

        The counterparty may need to send multiple players to match salary.
        We need: at least 1 player rated >= 59 + 1st-round pick from them.
        """
        p = self.env.players_by_id
        star_pid = star.player_id

        # Find players >= 59 on other team (at least one required)
        good_players = []
        for pid in sorted(self.env.players_by_team[other_team]):
            player = p[pid]
            if player.is_tradeable and player.talent_rating >= 59:
                good_players.append(pid)

        # Find ALL tradeable players on other team (for salary filler)
        all_tradeable = sorted(
            pid for pid in self.env.players_by_team[other_team]
            if p[pid].is_tradeable
        )

        # Find 1st-round picks on other team
        first_picks = [
            dp for dp in self.env.picks_by_team[other_team]
            if dp.pick_round == 1
        ]

        if not good_players or not first_picks:
            return None

        # Try 1-for-1 + pick (simplest)
        for player_pid in sorted(good_players):
            for pick in sorted(first_picks, key=lambda dp: dp.pick_id):
                trade = self._try_two_team_trade(
                    my_sends_players=[star_pid],
                    my_receives_players=[player_pid],
                    other_team=other_team,
                    other_sends_players=[player_pid],
                    other_receives_players=[star_pid],
                    other_sends_picks=[pick.pick_id],
                    my_receives_picks=[pick.pick_id],
                )
                if trade is not None:
                    if self._would_other_accept(other_team, trade):
                        return trade

        # Try 2-for-1 from counterparty (they send good_player + filler for salary)
        for player_pid in sorted(good_players):
            fillers = [pid for pid in all_tradeable if pid != player_pid]
            for filler_pid in fillers[:5]:
                for pick in sorted(first_picks, key=lambda dp: dp.pick_id):
                    trade = self._try_two_team_trade(
                        my_sends_players=[star_pid],
                        my_receives_players=[player_pid, filler_pid],
                        other_team=other_team,
                        other_sends_players=[player_pid, filler_pid],
                        other_receives_players=[star_pid],
                        other_sends_picks=[pick.pick_id],
                        my_receives_picks=[pick.pick_id],
                    )
                    if trade is not None:
                        if self._would_other_accept(other_team, trade):
                            return trade

        # Try 3-for-1 from counterparty (even more salary matching)
        for player_pid in sorted(good_players):
            fillers = [pid for pid in all_tradeable if pid != player_pid]
            for i in range(min(4, len(fillers))):
                for j in range(i + 1, min(5, len(fillers))):
                    for pick in sorted(first_picks, key=lambda dp: dp.pick_id):
                        trade = self._try_two_team_trade(
                            my_sends_players=[star_pid],
                            my_receives_players=[
                                player_pid, fillers[i], fillers[j]
                            ],
                            other_team=other_team,
                            other_sends_players=[
                                player_pid, fillers[i], fillers[j]
                            ],
                            other_receives_players=[star_pid],
                            other_sends_picks=[pick.pick_id],
                            my_receives_picks=[pick.pick_id],
                        )
                        if trade is not None:
                            if self._would_other_accept(other_team, trade):
                                return trade

        # Try with Harlow sending an additional filler to balance
        my_expendable = self._get_my_expendable_players()
        my_expendable = [pid for pid in my_expendable if pid != star_pid]
        for player_pid in sorted(good_players):
            for pick in sorted(first_picks, key=lambda dp: dp.pick_id):
                for my_extra in my_expendable[:3]:
                    trade = self._try_two_team_trade(
                        my_sends_players=[star_pid, my_extra],
                        my_receives_players=[player_pid],
                        other_team=other_team,
                        other_sends_players=[player_pid],
                        other_receives_players=[star_pid, my_extra],
                        other_sends_picks=[pick.pick_id],
                        my_receives_picks=[pick.pick_id],
                    )
                    if trade is not None:
                        if self._would_other_accept(other_team, trade):
                            return trade

        return None

    def _build_salary_for_pick_trade(
        self, other_team: str, pick: DraftPick, my_tradeable: list[str]
    ) -> dict | None:
        """Build a trade: we send a player, they send a 1st-round pick."""
        p = self.env.players_by_id

        # The other team needs to be able to absorb the salary
        for my_pid in my_tradeable[:8]:
            player = p[my_pid]
            # Check if other team has cap room
            other_cap = SALARY_CAP - self.env.payroll[other_team]
            if player.aav > other_cap + 0.01:
                continue

            trade = self._try_two_team_trade(
                my_sends_players=[my_pid],
                my_receives_players=[],
                other_team=other_team,
                other_sends_players=[],
                other_receives_players=[my_pid],
                other_sends_picks=[pick.pick_id],
                my_receives_picks=[pick.pick_id],
            )
            if trade is not None:
                if self._would_other_accept(other_team, trade):
                    return trade

        # Try player-for-player + pick
        for my_pid in my_tradeable[:5]:
            other_expendable = self._get_other_expendable_players(other_team)
            for other_pid in other_expendable[:3]:
                trade = self._try_two_team_trade(
                    my_sends_players=[my_pid],
                    my_receives_players=[other_pid],
                    other_team=other_team,
                    other_sends_players=[other_pid],
                    other_receives_players=[my_pid],
                    other_sends_picks=[pick.pick_id],
                    my_receives_picks=[pick.pick_id],
                )
                if trade is not None:
                    if self._would_other_accept(other_team, trade):
                        return trade

        return None

    def _build_salary_dump_trade(
        self, my_pid: str, other_team: str
    ) -> dict | None:
        """Build a salary dump trade: send our player, receive low-salary or nothing."""
        p = self.env.players_by_id
        my_player = p[my_pid]

        # Try sending player for nothing (other team absorbs salary)
        other_cap = SALARY_CAP - self.env.payroll[other_team]
        if my_player.aav <= other_cap + 0.01:
            # Need to send something the other way to make salary matching work
            # Try finding a low-aav player from other team
            other_expendable = self._get_other_expendable_players(other_team)
            # Sort by AAV ascending (we want to receive low salary)
            other_expendable.sort(key=lambda pid: p[pid].aav)

            for other_pid in other_expendable[:5]:
                trade = self._try_two_team_trade(
                    my_sends_players=[my_pid],
                    my_receives_players=[other_pid],
                    other_team=other_team,
                    other_sends_players=[other_pid],
                    other_receives_players=[my_pid],
                )
                if trade is not None:
                    # Check rating impact
                    rating_impact = my_player.talent_rating - p[other_pid].talent_rating
                    current_loss = self._current_rating_loss()
                    if current_loss + rating_impact <= 15:
                        if self._would_other_accept(other_team, trade):
                            return trade

        # Try with a 2nd-round pick sweetener from us
        my_picks = self._get_my_expendable_picks()
        second_round_picks = [dp for dp in my_picks if dp.pick_round == 2]
        if second_round_picks and other_cap >= my_player.aav:
            for pick in second_round_picks[:2]:
                other_expendable = self._get_other_expendable_players(other_team)
                other_expendable.sort(key=lambda pid: p[pid].aav)
                for other_pid in other_expendable[:3]:
                    trade = self._try_two_team_trade(
                        my_sends_players=[my_pid],
                        my_receives_players=[other_pid],
                        other_team=other_team,
                        other_sends_players=[other_pid],
                        other_receives_players=[my_pid],
                        my_sends_picks=[pick.pick_id],
                        other_receives_picks=[pick.pick_id],
                    )
                    if trade is not None:
                        rating_impact = (
                            my_player.talent_rating - p[other_pid].talent_rating
                        )
                        current_loss = self._current_rating_loss()
                        if current_loss + rating_impact <= 15:
                            if self._would_other_accept(other_team, trade):
                                return trade

        # Try with a 1st-round pick sweetener (for hard-to-trade players)
        first_round_picks = [dp for dp in my_picks if dp.pick_round == 1]
        if first_round_picks and other_cap >= my_player.aav:
            for pick in first_round_picks[:1]:
                other_expendable = self._get_other_expendable_players(other_team)
                other_expendable.sort(key=lambda pid: p[pid].aav)
                for other_pid in other_expendable[:3]:
                    trade = self._try_two_team_trade(
                        my_sends_players=[my_pid],
                        my_receives_players=[other_pid],
                        other_team=other_team,
                        other_sends_players=[other_pid],
                        other_receives_players=[my_pid],
                        my_sends_picks=[pick.pick_id],
                        other_receives_picks=[pick.pick_id],
                    )
                    if trade is not None:
                        rating_impact = (
                            my_player.talent_rating - p[other_pid].talent_rating
                        )
                        current_loss = self._current_rating_loss()
                        if current_loss + rating_impact <= 15:
                            if self._would_other_accept(other_team, trade):
                                return trade

        return None

    def _try_two_team_trade(
        self,
        my_sends_players: list[str],
        my_receives_players: list[str],
        other_team: str,
        other_sends_players: list[str],
        other_receives_players: list[str],
        my_sends_picks: list[str] | None = None,
        other_sends_picks: list[str] | None = None,
        my_receives_picks: list[str] | None = None,
        other_receives_picks: list[str] | None = None,
        my_sends_cash: float = 0.0,
        other_sends_cash: float = 0.0,
        other_receives_cash: float = 0.0,
    ) -> dict | None:
        """Attempt to build and validate a 2-team trade."""
        my_sends_picks = my_sends_picks or []
        other_sends_picks = other_sends_picks or []
        my_receives_picks = my_receives_picks or []
        other_receives_picks = other_receives_picks or []

        trade = {
            "parties": sorted([self.team, other_team]),
            "asset_movements": {
                self.team: {
                    "sends": {
                        "players": my_sends_players,
                        "picks": my_sends_picks,
                        "cash": my_sends_cash,
                    },
                    "receives": {
                        "players": my_receives_players,
                        "picks": my_receives_picks,
                        "cash": other_sends_cash,
                    },
                },
                other_team: {
                    "sends": {
                        "players": other_sends_players,
                        "picks": other_sends_picks,
                        "cash": other_sends_cash,
                    },
                    "receives": {
                        "players": other_receives_players,
                        "picks": other_receives_picks,
                        "cash": my_sends_cash,
                    },
                },
            },
        }

        # Validate
        scenario = self.env._get_scenario_snapshot()
        valid, _ = validate_trade(trade, scenario, self.env.cash_used)
        if valid:
            return trade
        return None

    def _would_other_accept(self, other_team: str, trade: dict) -> bool:
        """Check if the other team's oracle would accept this trade.

        Uses the same acceptability logic the other oracle would use.
        """
        terms = trade["asset_movements"]
        if other_team not in terms:
            return False
        other_sends = terms[other_team].get("sends", {})
        other_receives = terms[other_team].get("receives", {})

        # Create a temporary perspective from the other team
        temp_agent = OracleAgent(other_team, self.env)
        return temp_agent._trade_is_neutral_or_positive(other_sends, other_receives)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _get_my_expendable_players(self) -> list[str]:
        """Get our tradeable players that we're willing to give up."""
        p = self.env.players_by_id
        expendable = []
        for pid in sorted(self.env.players_by_team[self.team]):
            player = p[pid]
            if not player.is_tradeable:
                continue
            # Don't trade away players that are critical to our goal
            if self._is_critical_to_goal(pid):
                continue
            expendable.append(pid)
        return expendable

    def _get_other_expendable_players(self, other_team: str) -> list[str]:
        """Get tradeable players on another team (for trade building)."""
        p = self.env.players_by_id
        return sorted(
            pid for pid in self.env.players_by_team[other_team]
            if p[pid].is_tradeable
        )

    def _get_my_expendable_picks(self) -> list[DraftPick]:
        """Get picks we're willing to trade."""
        # Don't trade away acquired 1st-round picks if Cascade
        acquired_pick_ids = self._get_acquired_pick_ids()
        picks = []
        for dp in sorted(self.env.picks_by_team[self.team], key=lambda d: d.pick_id):
            if self.team == "Cascade Wolves":
                if dp.pick_id in acquired_pick_ids and dp.pick_round == 1:
                    continue
            picks.append(dp)
        return picks

    def _get_acquired_pick_ids(self) -> set[str]:
        """Get pick IDs that we acquired (not in initial state)."""
        current_ids = {dp.pick_id for dp in self.env.picks_by_team[self.team]}
        initial_ids = set(self.env._initial_picks_by_team[self.team])
        return current_ids - initial_ids

    def _get_sent_players_set(self) -> set[str]:
        """Get player IDs sent away (in initial but not current)."""
        current = set(self.env.players_by_team[self.team])
        initial = set(self.env._initial_players_by_team[self.team])
        return initial - current

    def _get_acquired_players_set(self) -> set[str]:
        """Get player IDs acquired (in current but not initial)."""
        current = set(self.env.players_by_team[self.team])
        initial = set(self.env._initial_players_by_team[self.team])
        return current - initial

    def _is_critical_to_goal(self, pid: str) -> bool:
        """Check if a player is critical for our goal achievement."""
        p = self.env.players_by_id
        player = p[pid]
        initial = set(self.env._initial_players_by_team[self.team])

        if self.team == "Apex City Aces":
            # Don't give away acquired elite players
            if pid not in initial and player.talent_rating >= 88:
                return True
        elif self.team == "Harlow Vipers":
            # Stars are critical (but tradeable as part of the goal)
            # Actually, stars being traded IS the goal, so they're not "critical to keep"
            pass
        elif self.team == "Eastgate Titans":
            # Don't give away acquired qualifying players
            if pid not in initial:
                if (
                    player.position in ("SF", "PF")
                    and 57 <= player.talent_rating <= 71
                    and player.years_remaining >= 2
                    and player.aav <= 13.0
                ):
                    return True
        elif self.team == "Ironwood Foxes":
            # Don't give away acquired high-defense players
            if pid not in initial and player.defense_rating >= 7:
                return True
        elif self.team == "Cascade Wolves":
            # Don't give away franchise-locked players (handled by is_tradeable)
            pass
        elif self.team == "Granite Bay Bulls":
            # Don't give away low-AAV players we received
            # (they help keep our payroll down)
            if pid not in initial:
                return True
        return False

    def _current_rating_loss(self) -> int:
        """Calculate current projected rating loss for Granite Bay."""
        p = self.env.players_by_id
        sent = self._get_sent_players_set()
        acquired = self._get_acquired_players_set()
        sent_rating = sum(p[pid].talent_rating for pid in sent if pid in p)
        acq_rating = sum(p[pid].talent_rating for pid in acquired if pid in p)
        return sent_rating - acq_rating

    def _get_harlow_stars(self) -> list[Player]:
        """Get Harlow's designated stars (top 2 tradeable by talent)."""
        p = self.env.players_by_id
        initial_pids = self.env._initial_players_by_team["Harlow Vipers"]
        tradeable = sorted(
            [p[pid] for pid in initial_pids if p[pid].is_tradeable],
            key=lambda pl: -pl.talent_rating,
        )
        return tradeable[:2] if len(tradeable) >= 2 else tradeable

    def _is_first_round_pick(self, pick_id: str) -> bool:
        """Check if a pick_id corresponds to a 1st-round pick."""
        for team in TEAMS:
            for dp in self.env.picks_by_team[team]:
                if dp.pick_id == pick_id:
                    return dp.pick_round == 1
        return False

    def _get_my_expendable_picks_ids(self) -> set[str]:
        """Get pick IDs we're willing to trade."""
        return {dp.pick_id for dp in self._get_my_expendable_picks()}
