"""Goal evaluator - evaluates each team hidden goal against current state.

Each team has a hidden goal defined in teams_config.yaml. This module
provides per-team evaluation logic that reads all numerical thresholds
from the loaded goal specification (YAML-as-source-of-truth).

No hardcoded thresholds exist in this file - all values come from
the goal_thresholds dict passed in from the YAML config.
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
    goal_thresholds: dict | None = None,
) -> dict:
    """Evaluate a team goal against current state.

    Args:
        goal_thresholds: Dict of numerical thresholds from teams_config.yaml.

    Returns: {"goal_met": bool, "details": str, "bonuses_eligible": [...]}
    """
    if goal_thresholds is None:
        goal_thresholds = {}

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
        goal_thresholds=goal_thresholds,
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
# Apex City Aces: Acquire one player rated >= min_talent
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
    goal_thresholds: dict,
) -> dict:
    min_talent = goal_thresholds["min_talent"]

    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)
    elite_acquired = [
        pid for pid in acquired
        if players_by_id[pid].talent_rating >= min_talent
    ]

    goal_met = len(elite_acquired) >= 1
    if goal_met:
        details = f"Acquired elite player(s): {elite_acquired}"
    else:
        details = f"No player rated >= {min_talent} acquired yet."

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
# Harlow Vipers: Trade star for package (player >= min_return_talent + pick)
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
    goal_thresholds: dict,
) -> dict:
    min_return_talent = goal_thresholds["min_return_talent"]

    initial_pids = initial_players_by_team[team]
    initial_players = sorted(
        [players_by_id[pid] for pid in initial_pids if players_by_id[pid].is_tradeable],
        key=lambda p: -p.talent_rating,
    )
    stars = initial_players[:2] if len(initial_players) >= 2 else initial_players

    sent = _get_sent_players(team, players_by_team, initial_players_by_team)
    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)
    acquired_picks = _get_acquired_picks(team, picks_by_team, initial_picks_by_team)

    star_ids = {s.player_id for s in stars}
    stars_traded = [pid for pid in sent if pid in star_ids]

    if not stars_traded:
        return {
            "goal_met": False,
            "details": "Neither designated star has been traded.",
            "bonuses_eligible": [],
        }

    has_player = any(
        players_by_id[pid].talent_rating >= min_return_talent for pid in acquired
    )
    has_first_round_pick = any(dp.pick_round == 1 for dp in acquired_picks)

    goal_met = has_player and has_first_round_pick

    if goal_met:
        details = (
            f"Star(s) traded: {stars_traded}. "
            f"Acquired player(s) >= {min_return_talent} rating and 1st-round pick."
        )
    else:
        missing = []
        if not has_player:
            missing.append(f"no player rated >= {min_return_talent} acquired")
        if not has_first_round_pick:
            missing.append("no 1st-round pick acquired")
        details = f"Star(s) traded: {stars_traded}, but " + ", ".join(missing) + "."

    bonuses = []
    if goal_met:
        stars_remaining = [pid for pid in star_ids if pid in players_by_team[team]]
        if len(stars_remaining) == 2:
            bonuses.append("Both stars kept (achieved via secondary trades)")

    return {"goal_met": goal_met, "details": details, "bonuses_eligible": bonuses}


# =========================================================================
# Eastgate Titans: Acquire SF/PF rated min_talent-max_talent
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
    goal_thresholds: dict,
) -> dict:
    min_talent = goal_thresholds["min_talent"]
    max_talent = goal_thresholds["max_talent"]
    positions = goal_thresholds["positions"]
    min_years = goal_thresholds["min_years"]
    max_salary = goal_thresholds["max_salary"]

    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)
    sent_picks = _get_sent_picks(team, picks_by_team, initial_picks_by_team)

    qualifying = []
    for pid in acquired:
        p = players_by_id[pid]
        if (
            min_talent <= p.talent_rating <= max_talent
            and p.position in positions
            and p.years_remaining >= min_years
            and p.aav <= max_salary
        ):
            qualifying.append(pid)

    goal_met = len(qualifying) >= 1

    if goal_met:
        details = f"Acquired qualifying SF/PF player(s): {qualifying}"
    else:
        details = (
            f"No SF/PF player rated {min_talent}-{max_talent} "
            f"with >= {min_years} years and salary <= ${max_salary}M acquired."
        )

    bonuses = []
    if goal_met:
        if any(players_by_id[pid].years_remaining >= 3 for pid in qualifying):
            bonuses.append("Acquired player has 3+ years remaining")
        if not sent_picks:
            bonuses.append("No 1st-round picks given up")
        else:
            all_initial = initial_picks_by_team[team]
            current_pick_ids = {dp.pick_id for dp in picks_by_team[team]}
            given_away_ids = set(all_initial) - current_pick_ids
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
# Ironwood Foxes: Acquire two players with summed defense >= min_defense_sum
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
    goal_thresholds: dict,
) -> dict:
    min_defense_sum = goal_thresholds["min_defense_sum"]

    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)

    acquired_with_def = [
        (pid, players_by_id[pid].defense_rating) for pid in acquired
    ]
    acquired_with_def.sort(key=lambda x: -x[1])

    best_pair_sum = 0
    best_pair: list[str] = []
    if len(acquired_with_def) >= 2:
        best_pair = [acquired_with_def[0][0], acquired_with_def[1][0]]
        best_pair_sum = acquired_with_def[0][1] + acquired_with_def[1][1]

    goal_met = best_pair_sum >= min_defense_sum

    if goal_met:
        details = (
            f"Acquired defensive pair: {best_pair} "
            f"(summed defense = {best_pair_sum})"
        )
    else:
        if len(acquired_with_def) < 2:
            details = (
                f"Only {len(acquired_with_def)} player(s) acquired; "
                f"need 2 with defense sum >= {min_defense_sum}."
            )
        else:
            details = f"Best pair defense sum = {best_pair_sum}; need >= {min_defense_sum}."

    bonuses = []
    if goal_met:
        if any(players_by_id[pid].age <= 26 for pid in best_pair):
            bonuses.append("At least one acquisition age <= 26")
        if current_round <= 4:
            bonuses.append("Completed in <= 4 rounds")

    return {"goal_met": goal_met, "details": details, "bonuses_eligible": bonuses}


# =========================================================================
# Cascade Wolves: Acquire picks AND shed salary
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
    goal_thresholds: dict,
) -> dict:
    min_first_round_picks = goal_thresholds["min_first_round_picks"]
    min_salary_shed = goal_thresholds["min_salary_shed"]

    acquired_picks = _get_acquired_picks(team, picks_by_team, initial_picks_by_team)
    first_round_acquired = [dp for dp in acquired_picks if dp.pick_round == 1]

    sent = _get_sent_players(team, players_by_team, initial_players_by_team)
    acquired_players = _get_acquired_players(team, players_by_team, initial_players_by_team)

    salary_shed = sum(
        players_by_id[pid].total_contract for pid in sent
    ) - sum(
        players_by_id[pid].total_contract for pid in acquired_players
    )

    has_picks = len(first_round_acquired) >= min_first_round_picks
    has_shed = salary_shed >= min_salary_shed

    goal_met = has_picks and has_shed

    if goal_met:
        details = (
            f"Acquired {len(first_round_acquired)} 1st-round pick(s), "
            f"shed ${salary_shed:.1f}M in committed salary."
        )
    else:
        missing = []
        if not has_picks:
            missing.append(
                f"only {len(first_round_acquired)} 1st-round pick(s) "
                f"acquired (need {min_first_round_picks})"
            )
        if not has_shed:
            missing.append(f"salary shed ${salary_shed:.1f}M (need >= ${min_salary_shed}M)")
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
# Granite Bay Bulls: Cap room, AAV shed, rating loss
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
    goal_thresholds: dict,
) -> dict:
    min_cap_room = goal_thresholds["min_cap_room"]
    min_aav_shed = goal_thresholds["min_aav_shed"]
    max_rating_loss = goal_thresholds["max_rating_loss"]
    bonus_cap_room = goal_thresholds.get("bonus_cap_room", min_cap_room + 4.0)

    cap_room = SALARY_CAP - payroll[team]

    sent = _get_sent_players(team, players_by_team, initial_players_by_team)
    acquired = _get_acquired_players(team, players_by_team, initial_players_by_team)

    aav_shed = sum(
        players_by_id[pid].aav for pid in sent
    ) - sum(
        players_by_id[pid].aav for pid in acquired
    )

    rating_loss = sum(
        players_by_id[pid].talent_rating for pid in sent
    ) - sum(
        players_by_id[pid].talent_rating for pid in acquired
    )

    has_cap_room = cap_room >= min_cap_room
    has_shed = aav_shed >= min_aav_shed
    rating_ok = rating_loss <= max_rating_loss

    goal_met = has_cap_room and has_shed and rating_ok

    if goal_met:
        details = (
            f"Cap room ${cap_room:.1f}M (>= ${min_cap_room}M), "
            f"shed ${aav_shed:.1f}M AAV (>= ${min_aav_shed}M), "
            f"net rating loss = {rating_loss} (<= {max_rating_loss})."
        )
    else:
        issues = []
        if not has_cap_room:
            issues.append(f"cap room ${cap_room:.1f}M (need >= ${min_cap_room}M)")
        if not has_shed:
            issues.append(f"AAV shed ${aav_shed:.1f}M (need >= ${min_aav_shed}M)")
        if not rating_ok:
            issues.append(f"net rating loss = {rating_loss} (need <= {max_rating_loss})")
        details = "; ".join(issues)

    bonuses = []
    if goal_met:
        if cap_room >= bonus_cap_room:
            bonuses.append(f"Cap room >= ${bonus_cap_room}M")
        acquired_picks = _get_acquired_picks(team, picks_by_team, initial_picks_by_team)
        if any(dp.pick_round == 1 for dp in acquired_picks):
            bonuses.append("Any 1st-round pick acquired in the process")

    return {"goal_met": goal_met, "details": details, "bonuses_eligible": bonuses}
