import random
from pathlib import Path

import yaml

from trade_deadline_bench.data_structures import (
    SALARY_CAP,
    TEAMS,
    DraftPick,
    Player,
    ScenarioData,
    TeamConfig,
)

POSITIONS = ["PG", "SG", "SF", "PF", "C"]

# Name pools for deterministic player-name generation.
FIRST_NAMES = [
    "Marcus", "Tyler", "Bryan", "James", "Andre", "Devon", "Chris", "Kevin",
    "Isaiah", "Malik", "Jordan", "Terrence", "Kyle", "Brandon", "Darius",
    "Michael", "Jaylen", "Anthony", "Omar", "Trey", "Lamar", "Dante",
    "Xavier", "Rashad", "Elijah", "Zion", "Jamal", "Cameron", "Eric",
    "DeShawn", "Corey", "Travis", "Kendrick", "Aaron", "Miles", "Donovan",
    "Shawn", "Marquis", "Quincy", "Jalen",
]

LAST_NAMES = [
    "Cole", "Hayes", "Reese", "Ortiz", "Johnson", "Williams", "Carter",
    "Thompson", "Mitchell", "Robinson", "Henderson", "Brooks", "Foster",
    "Palmer", "Warren", "Morgan", "Richardson", "Grant", "Dixon", "Pierce",
    "Barrett", "Parks", "Santos", "Cross", "Chambers", "Simmons", "Burke",
    "Harper", "Stone", "Walton", "Garrett", "Benson", "Hawkins", "Ingram",
    "Dawson", "Norris", "Gibbs", "Dunn", "Fowler", "Allison",
]

MAX_ELITE_PLAYERS = 6
ELITE_THRESHOLD = 88


def load_teams_config(config_path: str) -> list[TeamConfig]:
    """Load team configurations from a YAML file."""
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    configs = []
    for team_data in raw["teams"]:
        config = TeamConfig(
            name=team_data["name"],
            public_profile=team_data["public_profile"],
            cap_room=float(team_data["cap_room"]),
            tradeable_count=int(team_data["tradeable_count"]),
            hidden_goal=team_data["hidden_goal"],
            draft_picks_config=team_data["draft_picks"],
        )
        configs.append(config)

    if len(configs) != len(TEAMS):
        raise ValueError(
            f"Expected {len(TEAMS)} teams in config, got {len(configs)}"
        )

    for config in configs:
        if config.name not in TEAMS:
            raise ValueError(f"Unknown team name in config: {config.name}")
        if not 4 <= config.tradeable_count <= 6:
            raise ValueError(
                f"tradeable_count for {config.name} must be 4-6, "
                f"got {config.tradeable_count}"
            )

    return configs


def generate_scenario(seed: int, config_path: str | None = None) -> ScenarioData:
    """Generate a full league scenario deterministically from a seed.

    Loads team configs from YAML, procedurally generates 72 players (12 per
    team) and draft picks. The same seed always produces the identical
    scenario.
    """
    if config_path is None:
        config_path = str(Path(__file__).parent / "teams_config.yaml")

    rng = random.Random(seed)
    team_configs = load_teams_config(config_path)

    players_by_id: dict[str, Player] = {}
    players_by_team: dict[str, list[str]] = {tc.name: [] for tc in team_configs}
    picks_by_team: dict[str, list[DraftPick]] = {tc.name: [] for tc in team_configs}
    payroll: dict[str, float] = {}

    # Decide how many elite players (talent >= 88) league-wide: 4-6
    num_elite = rng.randint(4, MAX_ELITE_PLAYERS)

    # Distribute elite slots across teams.  Shuffle team indices and assign
    # one elite per team until the budget is exhausted.
    team_elite_counts: dict[str, int] = {tc.name: 0 for tc in team_configs}
    elite_pool = list(range(len(team_configs)))
    rng.shuffle(elite_pool)
    for i in range(num_elite):
        team_idx = elite_pool[i % len(elite_pool)]
        team_elite_counts[team_configs[team_idx].name] += 1

    used_names: set[str] = set()
    player_counter = 0

    for tc in team_configs:
        team_name = tc.name
        target_payroll = SALARY_CAP - tc.cap_room
        num_elite_for_team = team_elite_counts[team_name]

        team_players: list[Player] = []
        for i in range(12):
            player_counter += 1
            is_elite = i < num_elite_for_team
            player = _generate_player(
                rng, player_counter, team_name, is_elite, used_names
            )
            team_players.append(player)

        # Assign tradeable status: sort by talent descending, franchise-lock
        # the top (12 - tradeable_count) players.
        team_players.sort(
            key=lambda p: (-p.talent_rating, p.player_id)
        )
        num_locks = 12 - tc.tradeable_count
        for j, p in enumerate(team_players):
            p.is_tradeable = j >= num_locks

        # Scale AAVs so team payroll matches target.
        _scale_aavs(team_players, target_payroll)

        payroll[team_name] = round(sum(p.aav for p in team_players), 2)

        for p in team_players:
            players_by_id[p.player_id] = p
            players_by_team[team_name].append(p.player_id)

    # Generate draft picks.
    pick_counter = 0
    for tc in team_configs:
        for pick_cfg in tc.draft_picks_config:
            pick_counter += 1
            pick = DraftPick(
                pick_id=f"DP-{pick_counter:03d}",
                owning_team=tc.name,
                pick_round=int(pick_cfg["round"]),
                season_year=int(pick_cfg["season_year"]),
                protection_note=str(pick_cfg["protection_note"]),
            )
            picks_by_team[tc.name].append(pick)

    tc_dict = {tc.name: tc for tc in team_configs}

    return ScenarioData(
        players_by_id=players_by_id,
        players_by_team=players_by_team,
        picks_by_team=picks_by_team,
        payroll=payroll,
        team_configs=tc_dict,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_player(
    rng: random.Random,
    counter: int,
    team_name: str,
    is_elite: bool,
    used_names: set[str],
) -> Player:
    """Generate a single player with seeded RNG."""
    player_id = f"P-{counter:03d}"
    name = _unique_name(rng, used_names)

    if is_elite:
        talent_rating = rng.randint(ELITE_THRESHOLD, 95)
    else:
        # Right-skewed distribution in [50, 87].
        talent_rating = int(50 + rng.betavariate(2, 5) * 37)
        talent_rating = max(50, min(87, talent_rating))

    defense_rating = max(1, min(10, round(rng.gauss(5, 2))))
    position = rng.choice(POSITIONS)
    age = max(19, min(37, round(rng.gauss(26, 4))))

    # AAV correlates with talent rating.
    base_aav = (talent_rating - 45) * 0.7
    noise = rng.gauss(0, 3)
    aav = max(1.0, min(40.0, round(base_aav + noise, 1)))

    years_remaining = rng.randint(1, 5)

    return Player(
        player_id=player_id,
        name=name,
        talent_rating=talent_rating,
        defense_rating=defense_rating,
        position=position,
        age=age,
        aav=aav,
        years_remaining=years_remaining,
        current_team=team_name,
        is_tradeable=True,  # reassigned after all players generated
    )


def _unique_name(rng: random.Random, used: set[str]) -> str:
    """Return a deterministic unique player name."""
    for _ in range(200):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        name = f"{first} {last}"
        if name not in used:
            used.add(name)
            return name
    raise RuntimeError("Exhausted name generation attempts")


def _scale_aavs(players: list[Player], target_payroll: float) -> None:
    """Scale player AAVs proportionally so they sum to target_payroll.

    Keeps each AAV in [1.0, 40.0] and rounds to 2 decimal places.
    """
    total = sum(p.aav for p in players)
    if total <= 0:
        return

    scale = target_payroll / total
    for p in players:
        p.aav = max(1.0, min(40.0, round(p.aav * scale, 2)))

    # Fix rounding residual on the first player.
    residual = round(target_payroll - sum(p.aav for p in players), 2)
    if residual != 0.0:
        players[0].aav = round(players[0].aav + residual, 2)
