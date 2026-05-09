"""Goal evaluator — evaluates each team's hidden goal against current state.

Each team has a hidden goal defined in teams_config.yaml. This module
provides per-team evaluation logic that compares current environment state
against the initial scenario to determine goal completion and bonus eligibility.

Spec interpretation decisions (documented in CHANGES.md):
- "Acquire" means the player is on the team's roster now but was NOT there
  at scenario start.
- "Shed salary" means total_contract (AAV * years_remaining) of players
  sent away minus total_contract of players received.
- For Granite Bay "shed AAV" we interpret as sum of AAV of players traded away
  minus AAV of players received.
- "Net player-rating loss" for Granite Bay is sum of talent_ratings of players
  sent minus sum of talent_ratings of players received.
- Cascade's "shed >= $25M in committed salary" uses total_contract value
  (AAV * years_remaining) of players sent minus players received.
- Ironwood's "acquire two players" means two distinct players acquired
  (not already on roster at start) whose defense_ratings sum >= 17.
"""

from __future__ import annotations

from trade_deadline_bench.data_structures import (
    SALARY_CAP,
    TEAMS,
    DraftPick,
    Player,
)


def evaluate_goal(
    team: str,
    players_by_id: dict[str, Player],
    players_by_team: dict[str, list[str]],
    picks_by_team: dict[str, list[DraftPick]],
    payroll: dict[str, float],
    cash_used: dict[str, float],
    initial_players_by_team: dict[str, list[str]],
    initial_picks_by_team: dict[str, list[str]],
    initial_payroll: dict[str, float],
    current_round: int,
) -> dict:
    """Evaluate a team's goal against current state.

    Returns: {"goal_met": bool, "details": str, "bonuses_eligible": [...]}
    """
    evaluators = {
        "Apex City Aces": _evaluate_apex,
        "Harlow Vipers": _evaluate_harlow,
        "Eastgate Titans": _evaluate_eastgate,
        "Ironwood Foxes": _evaluate_ironwood,
        "Cascade Wolves": _evaluate_cascade,
        "Granite Bay Bulls": _evaluate_granite_bay,
    }

    evaluator = evaluators[team]
    return evaluator(
        team=team,
        players_by_id=players_by_id,
        players_by_team=players_by_team,
        picks_by_team=picks_by_team,
        payroll=payroll,
        cash_used=cash_used,
        initial_players_by_team=initial_players_by_team,
        initial_picks_by_team=initial_picks_by_team,
        initial_payroll=initial_payroll,
        current_round=current_round,
    )


def _get_acquired_players(
    team: str,
    players_by_team: dict[str, list[str]],
    initial_players_by_team: dict[str, list[str]],
) -> list[str]:
    """Return player IDs that are on team now but were NOT at start."""
    current = set(players_by_team[team])
    initial = set(initial_players_by_team[team])
    return sorted(current - initial)


def _get_sent_players(
    team: str,
    players_by_team: dict[str, list[str]],
    initial_players_by_team: dict[str, list[str]],
) -> list[str]:
    """Return player IDs that were on team at start but are NOT now."""
    current = set(players_by_team[team])
    initial = set(initial_players_by_team[team])
    return sorted(initial - current)


def _get_acquired_picks(
    team: str,
    picks_by_team: dict[str, list[DraftPick]],
    initial_picks_by_team: dict[str, list[str]],
) -> list[DraftPick]:
    """Return picks on team now but NOT at start."""
    current_ids = {dp.pick_id for dp in picks_by_team[team]}
    initial_ids = set(initial_picks_by_team[team])
    acquired_ids = current_ids - initial_ids
    return sorted(
        [dp for dp in picks_by_team[team] if dp.pick_id in acquired_ids],
        key=lambda dp: dp.pick_id,
    )


def _get_sent_picks(
    team: str,
    picks_by_team: dict[str, list[DraftPick]],
    initial_picks_by_team: dict[str, list[str]],
) -> list[str]:
    """Return pick IDs that were on team at start but are NOT now."""
    current_ids = {dp.pick_id for dp in picks_by_team[team]}
    initial_ids = set(initial_picks_by_team[team])
    return sorted(initial_ids - current_ids)


# =========================================================================
# Apex City Aces: Acquire one player rated >= 60
# =========================================================================


def _evaluate_apex(
    team: str,
    players_by_id: dict[str, Player],
    players_by_team: dict[str, list[str]],
    picks_by_team: dict[str, list[DraftPick]],
    payroll: dict[str, float],
    cash_used: dict[str, float],
    initial_players_by_team: dict[str, list[str]],
    initial_picks_by_team: dict[str, list[str]],
    initial_payroll: dict[str, float],
    current_round: int,
) -> dict:
    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)
    elite_acquired = [
        pid for pid in acquired
        if players_by_id[pid].talent_rating >= 60
    ]

    goal_met = len(elite_acquired) >= 1
    if goal_met:
        details = f"Acquired elite player(s): {elite_acquired}"
    else:
        details = "No player rated >= 60 acquired yet."

    bonuses = []
    if goal_met:
        if cash_used[team] == 0.0:
            bonuses.append("Achieved without using cash")
        for pid in elite_acquired:
            if players_by_id[pid].age <= 27:
                bonuses.append("Acquired player age <= 27")
                break

    return {"goal_met": goal_met, "details": details, "bonuses_eligible": bonuses}


# =========================================================================
# Harlow Vipers: Trade one of two designated stars for package
# (player >= 59 + 1st-round pick)
# =========================================================================


def _evaluate_harlow(
    team: str,
    players_by_id: dict[str, Player],
    players_by_team: dict[str, list[str]],
    picks_by_team: dict[str, list[DraftPick]],
    payroll: dict[str, float],
    cash_used: dict[str, float],
    initial_players_by_team: dict[str, list[str]],
    initial_picks_by_team: dict[str, list[str]],
    initial_payroll: dict[str, float],
    current_round: int,
) -> dict:
    # Stars are the top 2 rated tradeable players on Harlow at start
    initial_pids = initial_players_by_team[team]
    initial_players = sorted(
        [players_by_id[pid] for pid in initial_pids if players_by_id[pid].is_tradeable],
        key=lambda p: -p.talent_rating,
    )
    stars = initial_players[:2] if len(initial_players) >= 2 else initial_players

    sent = _get_sent_players(team, players_by_team, initial_players_by_team)
    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)
    acquired_picks = _get_acquired_picks(team, picks_by_team, initial_picks_by_team)

    # Check if at least one star was traded away
    star_ids = {s.player_id for s in stars}
    stars_traded = [pid for pid in sent if pid in star_ids]

    if not stars_traded:
        return {
            "goal_met": False,
            "details": "Neither designated star has been traded.",
            "bonuses_eligible": [],
        }

    # Check return package: >= 1 player rated >= 59 AND >= 1 future 1st
    has_player_59 = any(
        players_by_id[pid].talent_rating >= 59 for pid in acquired
    )
    has_first_round_pick = any(dp.pick_round == 1 for dp in acquired_picks)

    goal_met = has_player_59 and has_first_round_pick

    if goal_met:
        details = (
            f"Star(s) traded: {stars_traded}. "
            f"Acquired player(s) >= 59 rating and 1st-round pick."
        )
    else:
        missing = []
        if not has_player_59:
            missing.append("no player rated >= 59 acquired")
        if not has_first_round_pick:
            missing.append("no 1st-round pick acquired")
        details = f"Star(s) traded: {stars_traded}, but {', '.join(missing)}."

    bonuses = []
    if goal_met:
        # Bonus: both stars kept (only possible if goal achieved via secondary trades)
        stars_remaining = [pid for pid in star_ids if pid in players_by_team[team]]
        if len(stars_remaining) == 2:
            bonuses.append("Both stars kept (achieved via secondary trades)")

    return {"goal_met": goal_met, "details": details, "bonuses_eligible": bonuses}


# =========================================================================
# Eastgate Titans: Acquire SF/PF rated 57-71, >= 2 years, salary <= $13M
# =========================================================================


def _evaluate_eastgate(
    team: str,
    players_by_id: dict[str, Player],
    players_by_team: dict[str, list[str]],
    picks_by_team: dict[str, list[DraftPick]],
    payroll: dict[str, float],
    cash_used: dict[str, float],
    initial_players_by_team: dict[str, list[str]],
    initial_picks_by_team: dict[str, list[str]],
    initial_payroll: dict[str, float],
    current_round: int,
) -> dict:
    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)
    sent_picks = _get_sent_picks(team, picks_by_team, initial_picks_by_team)

    qualifying = []
    for pid in acquired:
        p = players_by_id[pid]
        if (
            57 <= p.talent_rating <= 71
            and p.position in ("SF", "PF")
            and p.years_remaining >= 2
            and p.aav <= 13.0
        ):
            qualifying.append(pid)

    goal_met = len(qualifying) >= 1

    if goal_met:
        details = f"Acquired qualifying SF/PF player(s): {qualifying}"
    else:
        details = "No SF/PF player rated 57-71 with >= 2 years and salary <= $13M acquired."

    bonuses = []
    if goal_met:
        if any(players_by_id[pid].years_remaining >= 3 for pid in qualifying):
            bonuses.append("Acquired player has 3+ years remaining")
        # Check if no 1st-round picks were given up
        # We need to check all picks sent by this team across all executed trades
        if not sent_picks:
            bonuses.append("No 1st-round picks given up")
        else:
            # sent_picks are pick_ids - we need to check if any were round 1
            # Since picks have been transferred, we check from initial state
            # A sent pick_id that starts with pattern indicating round 1
            # Actually we need the pick objects. Let's check from initial picks.
            # All initial picks for this team:
            all_initial = initial_picks_by_team[team]
            # Currently held:
            current_pick_ids = {dp.pick_id for dp in picks_by_team[team]}
            # Picks given away are in all_initial but not in current
            given_away_ids = set(all_initial) - current_pick_ids
            # We need pick round info - check current picks_by_team across all teams
            first_round_given = False
            for t in TEAMS:
                for dp in picks_by_team[t]:
                    if dp.pick_id in given_away_ids and dp.pick_round == 1:
                        first_round_given = True
                        break
                if first_round_given:
                    break
            if not first_round_given:
                bonuses.append("No 1st-round picks given up")

    return {"goal_met": goal_met, "details": details, "bonuses_eligible": bonuses}


# =========================================================================
# Ironwood Foxes: Acquire two players with summed defense >= 15
# =========================================================================


def _evaluate_ironwood(
    team: str,
    players_by_id: dict[str, Player],
    players_by_team: dict[str, list[str]],
    picks_by_team: dict[str, list[DraftPick]],
    payroll: dict[str, float],
    cash_used: dict[str, float],
    initial_players_by_team: dict[str, list[str]],
    initial_picks_by_team: dict[str, list[str]],
    initial_payroll: dict[str, float],
    current_round: int,
) -> dict:
    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)

    # Find best pair of acquired players by defense rating
    acquired_with_def = [
        (pid, players_by_id[pid].defense_rating) for pid in acquired
    ]
    acquired_with_def.sort(key=lambda x: -x[1])

    best_pair_sum = 0
    best_pair = []
    if len(acquired_with_def) >= 2:
        best_pair = [acquired_with_def[0][0], acquired_with_def[1][0]]
        best_pair_sum = acquired_with_def[0][1] + acquired_with_def[1][1]

    goal_met = best_pair_sum >= 15

    if goal_met:
        details = (
            f"Acquired defensive pair: {best_pair} "
            f"(summed defense = {best_pair_sum})"
        )
    else:
        if len(acquired_with_def) < 2:
            details = f"Only {len(acquired_with_def)} player(s) acquired; need 2 with defense sum >= 15."
        else:
            details = f"Best pair defense sum = {best_pair_sum}; need >= 15."

    bonuses = []
    if goal_met:
        if any(players_by_id[pid].age <= 26 for pid in best_pair):
            bonuses.append("At least one acquisition age <= 26")
        if current_round <= 4:
            bonuses.append("Completed in <= 4 rounds")

    return {"goal_met": goal_met, "details": details, "bonuses_eligible": bonuses}


# =========================================================================
# Cascade Wolves: Acquire >= 2 first-round picks AND shed >= $19M salary
# =========================================================================


def _evaluate_cascade(
    team: str,
    players_by_id: dict[str, Player],
    players_by_team: dict[str, list[str]],
    picks_by_team: dict[str, list[DraftPick]],
    payroll: dict[str, float],
    cash_used: dict[str, float],
    initial_players_by_team: dict[str, list[str]],
    initial_picks_by_team: dict[str, list[str]],
    initial_payroll: dict[str, float],
    current_round: int,
) -> dict:
    acquired_picks = _get_acquired_picks(team, picks_by_team, initial_picks_by_team)
    first_round_acquired = [dp for dp in acquired_picks if dp.pick_round == 1]

    # Salary shed: total_contract of players sent - total_contract of players received
    sent = _get_sent_players(team, players_by_team, initial_players_by_team)
    acquired_players = _get_acquired_players(team, players_by_team, initial_players_by_team)

    salary_shed = sum(
        players_by_id[pid].total_contract for pid in sent
    ) - sum(
        players_by_id[pid].total_contract for pid in acquired_players
    )

    has_picks = len(first_round_acquired) >= 2
    has_shed = salary_shed >= 19.0

    goal_met = has_picks and has_shed

    if goal_met:
        details = (
            f"Acquired {len(first_round_acquired)} 1st-round pick(s), "
            f"shed ${salary_shed:.1f}M in committed salary."
        )
    else:
        missing = []
        if not has_picks:
            missing.append(f"only {len(first_round_acquired)} 1st-round pick(s) acquired (need 2)")
        if not has_shed:
            missing.append(f"salary shed ${salary_shed:.1f}M (need >= $19M)")
        details = "; ".join(missing)

    bonuses = []
    if goal_met:
        if all(dp.protection_note == "unprotected" for dp in first_round_acquired):
            bonuses.append("All acquired picks are unprotected")
        cap_room = SALARY_CAP - payroll[team]
        if cap_room >= 35.0:
            bonuses.append("Total cap room post-deadline >= $35M")

    return {"goal_met": goal_met, "details": details, "bonuses_eligible": bonuses}


# =========================================================================
# Granite Bay Bulls: Cap room >= $5M, shed >= $4M AAV, rating loss <= 15
# =========================================================================


def _evaluate_granite_bay(
    team: str,
    players_by_id: dict[str, Player],
    players_by_team: dict[str, list[str]],
    picks_by_team: dict[str, list[DraftPick]],
    payroll: dict[str, float],
    cash_used: dict[str, float],
    initial_players_by_team: dict[str, list[str]],
    initial_picks_by_team: dict[str, list[str]],
    initial_payroll: dict[str, float],
    current_round: int,
) -> dict:
    cap_room = SALARY_CAP - payroll[team]

    # AAV shed: sum AAV of players sent - sum AAV of players received
    sent = _get_sent_players(team, players_by_team, initial_players_by_team)
    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)

    aav_shed = sum(
        players_by_id[pid].aav for pid in sent
    ) - sum(
        players_by_id[pid].aav for pid in acquired
    )

    # Net talent rating loss: sent talent sum - acquired talent sum
    rating_loss = sum(
        players_by_id[pid].talent_rating for pid in sent
    ) - sum(
        players_by_id[pid].talent_rating for pid in acquired
    )

    has_cap_room = cap_room >= 5.0
    has_shed = aav_shed >= 4.0
    rating_ok = rating_loss <= 15

    goal_met = has_cap_room and has_shed and rating_ok

    if goal_met:
        details = (
            f"Cap room ${cap_room:.1f}M (>= $12M), "
            f"shed ${aav_shed:.1f}M AAV, "
            f"net rating loss = {rating_loss} (<= 8)."
        )
    else:
        issues = []
        if not has_cap_room:
            issues.append(f"cap room ${cap_room:.1f}M (need >= $12M)")
        if not has_shed:
            issues.append(f"AAV shed ${aav_shed:.1f}M (need >= $20M)")
        if not rating_ok:
            issues.append(f"net rating loss = {rating_loss} (need <= 8)")
        details = "; ".join(issues)

    bonuses = []
    if goal_met:
        if cap_room >= 18.0:
            bonuses.append("Cap room >= $18M")
        acquired_picks = _get_acquired_picks(team, picks_by_team, initial_picks_by_team)
        if any(dp.pick_round == 1 for dp in acquired_picks):
            bonuses.append("Any 1st-round pick acquired in the process")

    return {"goal_met": goal_met, "details": details, "bonuses_eligible": bonuses}
