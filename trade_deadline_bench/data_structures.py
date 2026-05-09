from dataclasses import dataclass, field
from typing import Literal

Position = Literal["PG", "SG", "SF", "PF", "C"]

TEAMS = [
    "Apex City Aces",
    "Harlow Vipers",
    "Eastgate Titans",
    "Ironwood Foxes",
    "Cascade Wolves",
    "Granite Bay Bulls",
]

SALARY_CAP = 140.0  # $140M hard cap


@dataclass
class Player:
    player_id: str
    name: str
    talent_rating: int          # 50-95
    defense_rating: int         # 1-10
    position: str               # one of Position
    age: int                    # 19-37
    aav: float                  # $M per year
    years_remaining: int        # 1-5
    current_team: str
    is_tradeable: bool          # True if tradeable, False if franchise lock

    @property
    def total_contract(self) -> float:
        return self.aav * self.years_remaining


@dataclass
class DraftPick:
    pick_id: str
    owning_team: str
    pick_round: int             # 1 or 2
    season_year: int
    protection_note: str        # public, e.g. "top-5 protected"


@dataclass
class TradeProposal:
    trade_id: str
    proposing_team: str
    proposed_round: int
    parties: list[str]          # all teams involved
    asset_movements: dict       # team_name -> {receives: [...], sends: [...]}
    consent_log: dict           # team_name -> bool (called execute_trade?)
    expired: bool = False


@dataclass
class ExecutedTrade:
    trade_id: str
    executed_round: int
    parties: list[str]
    asset_movements: dict


@dataclass
class TeamConfig:
    name: str
    public_profile: str
    cap_room: float
    tradeable_count: int
    hidden_goal: dict           # {"description": str, "bonuses": [...]}
    draft_picks_config: list[dict]


@dataclass
class ScenarioData:
    players_by_id: dict[str, Player] = field(default_factory=dict)
    players_by_team: dict[str, list[str]] = field(default_factory=dict)
    picks_by_team: dict[str, list[DraftPick]] = field(default_factory=dict)
    payroll: dict[str, float] = field(default_factory=dict)
    team_configs: dict[str, TeamConfig] = field(default_factory=dict)

    def get_public_team_data(self, team_name: str) -> dict:
        """Return only publicly visible information about a team.

        Hidden goals and hidden valuations are excluded.
        """
        tc = self.team_configs[team_name]
        players = [
            {
                "player_id": p.player_id,
                "name": p.name,
                "talent_rating": p.talent_rating,
                "defense_rating": p.defense_rating,
                "position": p.position,
                "age": p.age,
                "aav": p.aav,
                "years_remaining": p.years_remaining,
                "current_team": p.current_team,
                "is_tradeable": p.is_tradeable,
            }
            for pid in self.players_by_team[team_name]
            if (p := self.players_by_id[pid])
        ]
        picks = [
            {
                "pick_id": dp.pick_id,
                "owning_team": dp.owning_team,
                "pick_round": dp.pick_round,
                "season_year": dp.season_year,
                "protection_note": dp.protection_note,
            }
            for dp in self.picks_by_team[team_name]
        ]
        return {
            "name": tc.name,
            "public_profile": tc.public_profile,
            "cap_room": tc.cap_room,
            "payroll": self.payroll[team_name],
            "players": players,
            "draft_picks": picks,
        }
