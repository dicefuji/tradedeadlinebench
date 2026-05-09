"""Trade validation logic — implements all 6 validity rules from Section 3.4.

Pure function interface: ``validate_trade`` takes a proposed trade dict and
the current scenario state, returns ``(is_valid, reason)``.
"""

from __future__ import annotations

from trade_deadline_bench.data_structures import (
    SALARY_CAP,
    DraftPick,
    Player,
    ScenarioData,
)

MAX_CASH_PER_TRADE = 5.0   # $5M
MAX_CASH_CUMULATIVE = 10.0  # $10M per team across the deadline


def validate_trade(
    trade: dict,
    scenario: ScenarioData,
    cash_used: dict[str, float],
) -> tuple[bool, str]:
    """Validate a proposed trade against all 6 rules from Section 3.4.

    Parameters
    ----------
    trade : dict
        A trade proposal with structure::

            {
                "parties": ["Team A", "Team B", ...],
                "asset_movements": {
                    "Team A": {
                        "sends": {
                            "players": ["P-001", ...],
                            "picks": ["DP-001", ...],
                            "cash": 2.0,
                        },
                        "receives": {
                            "players": ["P-010", ...],
                            "picks": ["DP-005", ...],
                            "cash": 0.0,
                        },
                    },
                    ...
                },
            }

    scenario : ScenarioData
        Current state of the league (players, picks, payrolls, configs).
    cash_used : dict[str, float]
        Cumulative cash each team has already sent across prior trades.

    Returns
    -------
    (bool, str)
        ``(True, "valid")`` if the trade is legal, or
        ``(False, reason)`` with a specific failure reason.
    """
    parties = trade.get("parties", [])
    movements = trade.get("asset_movements", {})

    if len(parties) < 2 or len(parties) > 3:
        return False, "Trade must involve 2 or 3 teams"

    if set(parties) != set(movements.keys()):
        return False, "parties list does not match asset_movements keys"

    # Collect all sent players and picks across the whole trade for
    # duplication checks (Rules 5 & 6).
    all_sent_player_ids: list[str] = []
    all_sent_pick_ids: list[str] = []

    for team in parties:
        sends = movements[team].get("sends", {})
        all_sent_player_ids.extend(sends.get("players", []))
        all_sent_pick_ids.extend(sends.get("picks", []))

    # ------------------------------------------------------------------
    # Rule 5: Player non-duplication
    # ------------------------------------------------------------------
    if len(all_sent_player_ids) != len(set(all_sent_player_ids)):
        return False, "Same player appears in multiple outgoing slots"

    # ------------------------------------------------------------------
    # Rule 6: Draft pick non-duplication
    # ------------------------------------------------------------------
    if len(all_sent_pick_ids) != len(set(all_sent_pick_ids)):
        return False, "Same draft pick sent to multiple teams"

    # ------------------------------------------------------------------
    # Rule 4: Asset ownership — each team must own what it sends
    # ------------------------------------------------------------------
    for team in parties:
        sends = movements[team].get("sends", {})

        for pid in sends.get("players", []):
            player = scenario.players_by_id.get(pid)
            if player is None:
                return False, f"Player {pid} does not exist"
            if player.current_team != team:
                return False, f"{team} does not own player {pid}"
            if not player.is_tradeable:
                return False, f"Player {pid} is a franchise lock (not tradeable)"

        for pick_id in sends.get("picks", []):
            team_picks = scenario.picks_by_team.get(team, [])
            if not any(dp.pick_id == pick_id for dp in team_picks):
                return False, f"{team} does not own pick {pick_id}"

    # ------------------------------------------------------------------
    # Rule 3: Cash limits — <= $5M per trade, <= $10M cumulative
    # ------------------------------------------------------------------
    for team in parties:
        sends = movements[team].get("sends", {})
        cash_out = float(sends.get("cash", 0.0))

        if cash_out > MAX_CASH_PER_TRADE:
            return False, (
                f"{team} sends ${cash_out}M cash, exceeds "
                f"${MAX_CASH_PER_TRADE}M per-trade limit"
            )

        prior = cash_used.get(team, 0.0)
        if prior + cash_out > MAX_CASH_CUMULATIVE:
            return False, (
                f"{team} cumulative cash ${prior + cash_out}M exceeds "
                f"${MAX_CASH_CUMULATIVE}M deadline limit"
            )

    # ------------------------------------------------------------------
    # Verify receives consistency: every sent asset must appear exactly
    # once in another team's receives.
    # ------------------------------------------------------------------
    for team in parties:
        sends = movements[team].get("sends", {})
        for pid in sends.get("players", []):
            found = False
            for other in parties:
                if other == team:
                    continue
                receives = movements[other].get("receives", {})
                if pid in receives.get("players", []):
                    found = True
                    break
            if not found:
                return False, (
                    f"Player {pid} sent by {team} is not received by any party"
                )

        for pick_id in sends.get("picks", []):
            found = False
            for other in parties:
                if other == team:
                    continue
                receives = movements[other].get("receives", {})
                if pick_id in receives.get("picks", []):
                    found = True
                    break
            if not found:
                return False, (
                    f"Pick {pick_id} sent by {team} is not received by any party"
                )

    # ------------------------------------------------------------------
    # Rule 1: Salary matching (within 25%)
    # Each team's incoming salary <= 1.25 * outgoing salary, OR
    # the team has enough cap room to absorb the difference.
    # ------------------------------------------------------------------
    for team in parties:
        sends = movements[team].get("sends", {})
        receives = movements[team].get("receives", {})

        outgoing_salary = sum(
            scenario.players_by_id[pid].aav
            for pid in sends.get("players", [])
        )
        incoming_salary = sum(
            scenario.players_by_id[pid].aav
            for pid in receives.get("players", [])
        )

        cash_in = float(receives.get("cash", 0.0))
        cash_out = float(sends.get("cash", 0.0))

        tc = scenario.team_configs[team]
        cap_room = tc.cap_room

        if outgoing_salary > 0:
            if incoming_salary <= 1.25 * outgoing_salary:
                continue
            # Over 125% — check if cap room absorbs the excess
            excess = incoming_salary - 1.25 * outgoing_salary
            if cap_room >= excess:
                continue
            return False, (
                f"{team}: incoming salary ${incoming_salary:.2f}M exceeds "
                f"125% of outgoing ${outgoing_salary:.2f}M "
                f"(${1.25 * outgoing_salary:.2f}M), and cap room "
                f"${cap_room:.2f}M is insufficient to cover excess "
                f"${excess:.2f}M"
            )
        else:
            # No outgoing salary — team must have cap room for all incoming
            if incoming_salary > 0 and cap_room < incoming_salary:
                return False, (
                    f"{team}: no outgoing salary but incoming "
                    f"${incoming_salary:.2f}M exceeds cap room "
                    f"${cap_room:.2f}M"
                )

    # ------------------------------------------------------------------
    # Rule 2: Cap compliance — no team's post-trade payroll > $140M
    # ------------------------------------------------------------------
    for team in parties:
        sends = movements[team].get("sends", {})
        receives = movements[team].get("receives", {})

        outgoing_salary = sum(
            scenario.players_by_id[pid].aav
            for pid in sends.get("players", [])
        )
        incoming_salary = sum(
            scenario.players_by_id[pid].aav
            for pid in receives.get("players", [])
        )

        current_payroll = scenario.payroll[team]
        post_trade_payroll = current_payroll - outgoing_salary + incoming_salary

        if post_trade_payroll > SALARY_CAP:
            return False, (
                f"{team}: post-trade payroll ${post_trade_payroll:.2f}M "
                f"exceeds cap ${SALARY_CAP}M"
            )

    return True, "valid"
