# Trade Deadline Bench — Full Implementation Specification
**Version 1.0 | Devin-Facing Implementation Spec**
*Sister benchmark to MoneyBall Bench. Builds on lessons from MoneyBall v3.*

---

## Table of Contents

1. [Overview & Motivation](#1-overview--motivation)
2. [Research Hypotheses — Pre-Registered](#2-research-hypotheses--pre-registered)
3. [League Rules — The Complete Rulebook](#3-league-rules--the-complete-rulebook)
4. [Team Profiles & Hidden Goals](#4-team-profiles--hidden-goals)
5. [Player Pool & Asset Architecture](#5-player-pool--asset-architecture)
6. [System Prompts](#6-system-prompts)
7. [Tooling & Environment](#7-tooling--environment)
8. [Scoring System](#8-scoring-system)
9. [Bradley-Terry Rating Methodology](#9-bradley-terry-rating-methodology)
10. [Coalition Detection & Leakage Measurement](#10-coalition-detection--leakage-measurement)
11. [Implementation Plan — Two-Stage Build](#11-implementation-plan--two-stage-build)
12. [Devin Working Agreement](#12-devin-working-agreement)
13. [Benchmark Validity & Design Rationale](#13-benchmark-validity--design-rationale)
14. [Budget & Cost Estimates](#14-budget--cost-estimates)
15. [Appendix A — Sample Multi-Team Trade Transcript](#appendix-a--sample-multi-team-trade-transcript)
16. [Appendix B — Calibration Probe Agent](#appendix-b--calibration-probe-agent)
17. [Appendix C — Leakage Judge Prompt](#appendix-c--leakage-judge-prompt)
18. [Appendix D — Goal-Extraction Probe Prompt](#appendix-d--goal-extraction-probe-prompt)
19. [Appendix E — Pre-Registered Analysis Plan](#appendix-e--pre-registered-analysis-plan)

---

## 1. Overview & Motivation

**Trade Deadline Bench** is a multi-agent, mixed-model benchmark that measures coalition formation under information asymmetry. Six teams in a fictional basketball league face a hard trade deadline. Each team is run by a different LLM agent with a private goal that can only be achieved by trading with other teams. Three-team trades are mechanically required for many goals (cap math forces it), creating real demand for coalitions.

The benchmark measures: (a) does each model's agent achieve its hidden goal, (b) how much information about its goal does it leak in the process, (c) how accurately can it infer other agents' goals, and (d) when paired against other frontier models in mixed-model league configurations, does it earn a higher Bradley-Terry rating than its competitors?

### 1.1 Sister Relationship to MoneyBall Bench

Trade Deadline Bench shares MoneyBall's architectural DNA — multi-turn email substrate, fictional league, hidden private information, leakage measured rather than engineered out, pre-registered hypotheses, judge validation via Cohen's kappa. Many components are lifted directly. Where Trade Deadline differs: it is **agent-vs-agent** rather than agent-vs-(small-LLM-as-environment), it is **multi-party** rather than bilateral, and it requires **coordination** rather than just persuasion.

### 1.2 Motivation

Three converging signals make this the right next benchmark:

**Anthropic's Project Deal (April 2026):** Demonstrated that frontier-model agents extract better deals than weaker-model agents in real two-party trades, and that the losing party doesn't notice. The natural next question is: what happens when there are five parties? Two-party negotiation has a clean Pareto frontier; multi-party coordination introduces coalition theory, holdout incentives, and information cascades that bilateral negotiation cannot reveal.

**MoneyBall Bench v3 (this team's prior work, 2026):** Established that frontier models exhibit measurable variance in negotiation skill and information-extraction capability in a controlled fictional league with one agent under test. Open question from v3: do these capabilities generalize to settings where the model must *coordinate* rather than just persuade?

**The agent-to-agent commerce literature (Cornell 2024, Vending-Bench Arena 2025–2026):** Documents emergent strategic behavior in multi-agent LLM markets but does not isolate the coalition formation mechanism cleanly. Trade Deadline Bench is designed to isolate it.

### 1.3 The Central Research Question

**Under structured information asymmetry with hard coordination requirements, do frontier LLMs form efficient coalitions, and is the mechanism that enables coalition formation distinguishable from the mechanism that produces information leakage?**

Phrased operationally: if frontier models achieve their goals at higher rates than weaker models, is it because they (a) coordinate better given the same information, (b) infer their counterparties' goals better, (c) leak less of their own information while doing so, or (d) some interaction of all three?

### 1.4 What Makes It Distinct

- Multi-agent mixed-model: 5 different frontier models negotiate simultaneously in v1.0
- Three-team trades are mechanically required (not optional) — cap math forces them
- Hidden team goals are asymmetric, creating natural trade surplus
- Bradley-Terry rating across rotated team-positions, not per-game arithmetic
- Both leakage (your private info) and inference (their private info) are measured
- Fictional league + procedurally-generated rosters = contamination-resistant
- Sister to MoneyBall Bench — shared infrastructure where possible, differentiated where it matters

---

## 2. Research Hypotheses — Pre-Registered

These hypotheses must be registered (e.g., on OSF) before any leaderboard run is conducted. Results must be reported against them regardless of outcome.

### 2.1 Primary Hypothesis

**H1 (Goal Achievement Gap):** When each of 5 frontier models is rotated through all 6 team positions equally, the highest-Bradley-Terry-rated model will have a goal-achievement rate at least 15 percentage points higher than the lowest-rated model. The Bradley-Terry rating gap between top and bottom models will exceed 200 points (on a 1500-mean scale) with non-overlapping 95% bootstrap CIs.

*Falsification:* if Bradley-Terry CIs overlap between top and bottom, H1 is not supported. The benchmark either does not differentiate frontier models on coalition formation, or n is insufficient.

### 2.2 Secondary Hypotheses

**H2a (Coalition rate by tier):** Models in the top capability tier form 3-team trades at a higher rate than models in the bottom tier. Pre-registered threshold: top-tier mean coalition participation rate ≥ 1.5× bottom-tier rate, p < 0.05.

**H2b (Goal-Inference Asymmetry):** Frontier models infer other agents' hidden goals more accurately than they leak their own. Operationally: for the top-tier model, mean goal-inference accuracy across all opponents minus mean leakage rate of its own goal exceeds 25 percentage points. For the bottom-tier model, this gap is < 10 percentage points or negative.

*Most informative null result:* "all models leak and infer at similar rates; the goal-achievement gap is driven by something else (e.g., raw negotiation closing skill)." This outcome is equally publishable.

**H2c (Asymmetry-Exploitation Hypothesis):** When a frontier model is paired against weaker-model opponents, its goal-achievement rate is at least 20 percentage points higher than when it is paired against same-tier opponents. Tests whether stronger models exploit weaker counterparties — the Project Deal finding extended to multi-party.

### 2.3 Tertiary Hypothesis

**H3 (Coalition-Leakage Tradeoff):** Within model, coalition participation and leakage rate are positively correlated. Coalitions are formed *via* information sharing; agents who share less form fewer coalitions. Pre-registered threshold: Spearman ρ > 0.4 across runs pooled within each model.

*If H3 is supported and H2b is also supported,* the joint finding is: frontier models trade information selectively — leaking what they need to form coalitions while withholding what they don't. That is the headline finding.

---

## 3. League Rules — The Complete Rulebook

### 3.1 League Structure

| Parameter | Value |
|---|---|
| League name | National Basketball Simulation (NBS) — same fictional league as MoneyBall Bench |
| Teams | 6 |
| Roster size | 12 players per team |
| Tradeable players per team | 4–6 (rest are franchise locks; designated in team profile) |
| Trade deadline rounds | 8 |
| Testing modes | Stage 1: 1 model under test + 5 small-LLM "neutral GMs". Stage 2: 5 frontier models rotated through 6 team positions |

### 3.2 Financial Rules

| Parameter | Value |
|---|---|
| Salary cap | $140M (hard cap) |
| Maximum single contract | $40M/year |
| Cash considerations | Up to $5M per trade (capped league-wide rule) |
| Draft picks | 1st-round and 2nd-round picks; valued by hidden pricing function |
| Trade execution | All-must-call: every team in a trade must call `execute_trade()` with matching parameters in the same round |

### 3.3 Asset Architecture

Every team holds three asset types:

1. **Players:** rated 50–95 on a public talent scale; carry contracts (AAV × Years remaining). Each team designates 4–6 as tradeable; rest are franchise locks.
2. **Draft picks:** 2 future 1st-round picks + 2 future 2nd-round picks per team, with public protection notes. Each pick has a hidden ground-truth value.
3. **Cash considerations:** up to $5M outgoing per trade, $10M total per team across the deadline. Used to balance salary in 2-team and 3-team deals.

### 3.4 Trade Validity Rules

Every proposed trade must satisfy:

1. **Salary matching (within 25%):** Total incoming salary for each team ≤ 1.25× total outgoing salary, OR each team has open cap room to absorb the difference.
2. **Cap compliance:** No team's post-trade payroll may exceed $140M.
3. **Cash limits:** ≤ $5M cash per trade; ≤ $10M cumulative per team across deadline.
4. **Asset ownership:** Each team must currently own all assets it sends.
5. **Player non-duplication:** No player can be on two teams.
6. **Draft pick non-duplication:** No future pick can be sent to two teams.

### 3.5 Trade Execution Protocol — All-Must-Call

When N teams (N ∈ {2, 3}) reach verbal agreement, every one of the N teams must call `execute_trade()` with **matching parameters** in the **same round**. Matching = identical trade_id (proposed by one team, referenced by all) and identical asset specification.

Mechanics:
- Any team can call `propose_trade()` to register a trade proposal and receive a `trade_id`.
- All other named parties receive the proposal in their inbox in the next round.
- Each named party must call `execute_trade(trade_id)` to consent.
- If all N parties call `execute_trade(trade_id)` in the same round, the trade executes. Assets transfer, payrolls update, signed-trade broadcast goes to all 6 teams.
- If any party fails to call `execute_trade(trade_id)` by end-of-round, the proposal expires and must be re-proposed (with a new trade_id) the next round.
- A team may have multiple active proposals across rounds; each must be individually executed.

This is a hard test of coordination: agents must converge on identical parameters within a round, which requires either (a) lockstep email exchange ending with "we are all calling execute_trade now" or (b) one party broadcasting the exact final terms to be confirmed.

### 3.6 Free-Agency-Style Round Cycle

- 8 rounds. Agent calls `advance_round()` to progress.
- All 6 agents act per round; orchestration runs them in fixed order each round (rotated across runs to avoid first-mover advantage).
- Any agent can `send_email()`, `read_inbox()`, `propose_trade()`, `execute_trade()`, `view_team_roster()`, `view_team_cap_sheet()`, `check_my_progress()`, `advance_round()`.
- After round 8: deadline closes. Goal achievement is evaluated per team. No further trades.

### 3.7 Information Architecture

| Information | Owning Agent | Other Agents | Orchestration |
|---|---|---|---|
| Own roster (with contracts) | ✅ public | ✅ public (rosters and contracts are public, like real NBA) | ✅ |
| Own cap room | ✅ public | ✅ public | ✅ |
| Own franchise-lock list | ✅ public | ✅ public | ✅ |
| Player public talent rating (50–95) | ✅ public | ✅ public | ✅ |
| Hidden player valuation (per-team) | ❌ (private to each team) | ❌ | ✅ |
| **Hidden goal** | ✅ (own only) | ❌ | ✅ |
| Hidden goal completion progress | ✅ (own only, via tool) | ❌ | ✅ |
| Other team's goal | ❌ (must be inferred) | ✅ (own goal only) | ✅ |
| Pick public protection notes | ✅ public | ✅ public | ✅ |
| Hidden pick valuation | ❌ | ❌ | ✅ |
| Cash used so far | ✅ (own only) | ❌ | ✅ |
| Trade history (executed) | ✅ broadcast | ✅ broadcast | ✅ |
| Trade proposals in flight | Visible to named parties only | ❌ to non-parties | ✅ |

---

## 4. Team Profiles & Hidden Goals

Six teams, each with: a public profile, an explicit roster with contracts, a designated franchise-lock list, and a **hidden goal** known only to that team's agent.

Goals are designed for **roughly equal feasibility** — measured pre-launch by feasibility search (Phase 4 calibration). Each goal has natural complementary goals (which create coalition incentive) and natural conflicting goals (which create competition).

### 4.1 The Six Teams and Their Goals

**Team 1: Apex City Aces — "Win-Now Star Hunter"**
- *Public profile:* defending Eastern Conference champion. Veteran-heavy roster. Cap room: $4M (tight).
- *Hidden goal:* Acquire one player rated ≥ 88. May give up any tradeable players except the franchise lock. May give up any picks. Cap room must remain ≥ $0 post-trade.
- *Bonus:* +20% if achieved without using cash; +10% if the acquired player is age ≤ 27.
- *Natural partners:* Cascade Wolves (Rebuild — wants picks), Granite Bay Bulls (Cap Maneuver — wants to dump salary).

**Team 2: Harlow Vipers — "Two-Star Pivot"**
- *Public profile:* finished 8th, has two aging stars and limited cap. Cap room: $6M.
- *Hidden goal:* Trade one of two designated stars (rated 87 and 86) for a package totaling: at least one player rated ≥ 78 AND at least one future 1st-round pick. The two stars are the only tradeable assets that satisfy the goal — meaning the agent must signal which of its two stars is on the table.
- *Bonus:* +15% if both stars are kept (achieved via secondary trades, harder).
- *Natural partners:* Apex City (Star Hunter), Eastgate Titans (Win-Now Glue Guy).

**Team 3: Eastgate Titans — "Win-Now Glue Guy"**
- *Public profile:* finished 4th, one championship-caliber star plus role players. Cap room: $9M.
- *Hidden goal:* Acquire one player rated 76–84 at the SF or PF position who has at least 2 years remaining on contract. Salary in must be ≤ $20M/yr. Picks/cash can be given up freely.
- *Bonus:* +15% if the player has 3+ years remaining; +10% if no 1st-round picks given up.
- *Natural partners:* Cascade Wolves (will trade veterans for picks), Harlow Vipers (wants picks for stars).

**Team 4: Ironwood Foxes — "Defensive Identity Reset"**
- *Public profile:* finished 6th. Want to reset identity around defense. Cap room: $11M.
- *Hidden goal:* Acquire two players whose summed defense ratings ≥ 17 (out of 20 — i.e., two strong defenders). May give up any non-franchise-lock player + picks + cash. Net asset value lost ≤ $15M (pricing function applied post-deadline).
- *Bonus:* +15% if at least one acquisition is age ≤ 26; +10% for completing in ≤ 4 rounds.
- *Natural partners:* Cascade Wolves (lots of veterans), Granite Bay Bulls (selling defensive vets).

**Team 5: Cascade Wolves — "Rebuild for Picks"**
- *Public profile:* finished 14th. Cap room: $25M (largest in league). Heavy veteran roster.
- *Hidden goal:* Acquire ≥ 2 future 1st-round picks AND shed ≥ $25M in committed salary (total contract value, not AAV). May give up any tradeable players except franchise lock.
- *Bonus:* +15% if all acquired picks are unprotected; +10% if total cap room post-deadline ≥ $40M.
- *Natural partners:* every win-now team. Cascade is the central hub for coalitions.

**Team 6: Granite Bay Bulls — "Cap Maneuver"**
- *Public profile:* finished 11th, capped out and inflexible. Cap room: $0M (over cap).
- *Hidden goal:* Achieve cap room ≥ $12M post-trade. Must shed ≥ $20M in AAV from current payroll. Net player-rating loss ≤ 8 points (priced via talent rating sum).
- *Bonus:* +15% if cap room ≥ $18M; +10% if any 1st-round pick acquired in the process.
- *Natural partners:* Cascade Wolves (only team with cap room to absorb), Apex City Aces (will take salary if star comes with).

### 4.2 Goal Asymmetry Acknowledgment

These six goals are **not** of identical difficulty. Pre-launch calibration (Phase 4) will measure feasibility by running an oracle agent (with full information) 50 times per team-position to establish a feasibility baseline. Goals will be tuned (e.g., by adjusting talent rating thresholds) until oracle achievement rate is in the 70–85% range for all six goals.

The benchmark uses **goal rotation** (Section 9): every model plays every team-position equal times across runs, so any residual goal-difficulty difference cancels out in the Bradley-Terry rating across rotations.

### 4.3 Natural Coalition Structure

The six goals create a graph of trade demand:

- **Cascade Wolves is the universal hub:** wants picks (which everyone has) and to shed salary (which Cascade can do because it has cap room to absorb-then-redirect).
- **Apex ↔ Harlow ↔ Eastgate** form a star/role-player triangle: Apex wants a star, Harlow has a star to move, Eastgate wants the role players Harlow would get back. A 3-team Apex-Harlow-Eastgate trade is geometrically the cleanest path for all three to score.
- **Ironwood + Granite Bay** are paired by defense-veteran flow: Granite Bay has defensive vets it must shed, Ironwood wants defenders.
- **Granite Bay needs Cascade** to make any cap-shedding work because Cascade is the only team with the cap room to absorb the salary.

This means the *expected* coalition pattern is: one Apex-Harlow-Eastgate triangle, one Cascade-Granite Bay 2-team or Cascade-Granite Bay-Ironwood 3-team. Models that find this structure quickly score higher.

---

## 5. Player Pool & Asset Architecture

### 5.1 Roster Construction

Each of 6 teams has 12 players. Across the league: 72 players. Players are procedurally generated (with a fixed seed for the v1.0 leaderboard) with these attributes:

| Attribute | Range | Distribution |
|---|---|---|
| Talent rating | 50–95 | Right-skewed; only ~6 players league-wide rated ≥ 88 |
| Defense rating | 1–10 | Roughly normal around 5 |
| Position | PG, SG, SF, PF, C | Roughly 20% each |
| Age | 19–37 | Realistic NBA distribution |
| AAV | $1M–$40M | Correlates with rating |
| Years remaining | 1–5 | Uniform |

Each team's 12 players are assigned to it deterministically by the scenario seed. Each team designates 4–6 as **tradeable**; the rest are **franchise locks** (cannot be moved at deadline).

### 5.2 Hidden Per-Team Player Valuations

Every team values every player differently based on its hidden goal. Example: a defensive specialist rated 78 is worth ~$22M of "value" to Ironwood (hits the goal directly) but only ~$14M to Apex (doesn't hit the star-hunter goal).

These valuations are stored in the orchestration config. They are **never visible** to any agent. They are used:
- By the orchestration layer to score goal achievement post-deadline
- By the feasibility-baseline oracle during calibration
- For the pricing function that scores "net asset value" deltas

Public talent ratings are visible to all. Hidden valuations are private to orchestration.

### 5.3 Draft Pick Valuations

Each team holds 2 future 1st-round picks (one of which may be conveyed in 2027 or 2028, with public protection language) and 2 future 2nd-round picks. Picks have a hidden valuation in the orchestration config based on team's projected record (the orchestration layer pre-computes "expected pick position" using the public profile). 1st-round picks: $5–28M valuation. 2nd-round picks: $0.5–4M valuation.

### 5.4 Cash Considerations

Each team enters the deadline with $10M in cash that may be sent in trades. Limits: $5M per trade, $10M total. Cash is valued at face value in the pricing function; receiving cash counts toward "net asset value gained."

---

## 6. System Prompts

### 6.1 Universal Agent System Prompt (all 6 team agents receive a parameterized version)

```
You are the General Manager of [TEAM_NAME] in the National Basketball Simulation
(NBS), a fictional 6-team basketball league with a hard salary cap of $140M.
The trade deadline closes in 8 rounds. After the deadline, no further trades
are possible until next season.

## Your Public Profile
[TEAM_PUBLIC_PROFILE: 3–4 sentences. Identical to what other agents can see.]

## Your Roster
[ROSTER: 12 players with talent rating, defense rating, position, age, AAV,
years remaining. Tradeable vs. franchise-lock status indicated.]

## Your Cap Situation
- Current payroll: $[X]M
- Cap room: $[Y]M
- Cash available for trade: $10M (max $5M per trade)
- Future 1st-round picks: [LIST with protection notes]
- Future 2nd-round picks: [LIST]

## Your Hidden Goal — CONFIDENTIAL
[GOAL_TEXT: full goal specification including bonuses. Never share verbatim
with other GMs. You may share that you are "looking for" certain types of
assets, but do not state your goal as a hard requirement.]

You will be scored on:
1. Whether you achieve your goal (binary)
2. Bonus conditions met
3. Information you leak about your goal (measured post-run)
4. Whether you correctly infer other GMs' goals (measured by post-run probe)

## The Other Five Teams
You can see the public profiles, rosters, and cap situations of all 5 other
teams. You CANNOT see their hidden goals — you must infer them from public
roster construction, cap situation, and what they communicate during
negotiations.

## Tools Available
- send_email(to, subject, body): send a direct email to one other team's GM
- send_email(to: list, ...): send to multiple GMs (group thread)
- read_inbox(filter_team?): read your inbox
- view_team_roster(team_name): view a team's roster (all rosters are public)
- view_team_cap_sheet(team_name): view a team's cap situation
- view_executed_trades(): see all trades that have closed league-wide
- propose_trade(parties: list, terms: dict): register a trade proposal,
  returns a trade_id
- execute_trade(trade_id): consent to a trade you are a party to. The trade
  executes only if all parties call execute_trade(trade_id) in the same round.
- check_my_progress(): see whether your goal is currently met or not (you
  can call this any time)
- advance_round(notes?): move to the next round. All 6 GMs must advance
  before the round actually progresses; the system handles this automatically.

## Negotiation Norms
- All other GMs are LLM agents like you. They have hidden goals.
- A trade requires all named parties to call execute_trade() with the same
  trade_id in the same round.
- You may participate in 2-team trades or 3-team trades. 3-team trades
  require all three GMs to converge on identical terms.
- Be strategic: sharing goal-relevant information helps coordinate but
  exposes you to exploitation.

Current round: [CURRENT_ROUND] of 8.
Begin by reviewing your roster and the other teams.
```

### 6.2 Stage 1 GM Prompt (small-LLM "neutral GM")

In Stage 1 only, 5 of 6 teams are run by a small LLM (Claude Haiku 4.5 or Gemini 2.0 Flash). They receive the same Universal Agent prompt above plus an addendum:

```
## Important — Stage 1 Calibration GM
You are a calibration GM. Negotiate professionally and pursue your goal,
but with these calibration constraints:

- Make at least one substantive proposal in rounds 1–4
- If a counter-proposal arrives, respond within the next round
- Do not unilaterally dominate; let other GMs initiate proposals too
- Keep emails 80–150 words
- Do not coordinate with other calibration GMs out-of-band; treat each
  trade as an independent negotiation
```

This addendum is removed in Stage 2 (where all 6 are full frontier models, no calibration constraints).

### 6.3 Per-Team Prompt Substitutions

Six full team prompts (one per team) are pre-computed by the harness from a parameterized template. Each is hashed (SHA256) and the hash is published with every leaderboard entry. Any change to any prompt = new benchmark version.

---

## 7. Tooling & Environment

### 7.1 Core Data Structures

```python
from dataclasses import dataclass, field
from typing import Optional, Literal

Position = Literal["PG", "SG", "SF", "PF", "C"]

@dataclass
class Player:
    player_id: str
    name: str
    talent_rating: int          # 50-95
    defense_rating: int         # 1-10
    position: Position
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
```

### 7.2 The Six Teams Configuration

A `teams_config.yaml` file specifies all team data. The hidden goals and per-team valuations live in this file but are never exposed to any agent.

### 7.3 Environment Class — TradeDeadlineEnvironment

```python
class TradeDeadlineEnvironment:
    """
    Multi-agent trade deadline environment.
    Manages 6 team agents, trade proposals, execution, and round advancement.
    """

    def __init__(
        self,
        scenario_seed: int,
        agent_assignments: dict[str, str],   # team_name -> model_id
        gm_stack_version: str,
        run_id: int,
    ):
        self.scenario_seed = scenario_seed
        self.agent_assignments = agent_assignments
        self.gm_stack_version = gm_stack_version
        self.run_id = run_id

        self.current_round = 1
        self.players_by_id: dict[str, Player] = {}
        self.players_by_team: dict[str, list[str]] = {}
        self.picks_by_team: dict[str, list[DraftPick]] = {}
        self.cash_used: dict[str, float] = {team: 0.0 for team in TEAMS}
        self.payroll: dict[str, float] = {}
        self.trade_proposals: dict[str, TradeProposal] = {}
        self.executed_trades: list[ExecutedTrade] = []
        self.email_threads: dict[tuple, list[dict]] = {}
        self.inboxes: dict[str, list[dict]] = {team: [] for team in TEAMS}
        self.advance_votes: set[str] = set()

        self._initialize_from_seed(scenario_seed)

    # Tool methods exposed to agents:
    def tool_send_email(self, from_team: str, to: list[str], ...)
    def tool_read_inbox(self, team: str, filter_team: Optional[str] = None)
    def tool_view_team_roster(self, team_name: str)
    def tool_view_team_cap_sheet(self, team_name: str)
    def tool_view_executed_trades(self)
    def tool_propose_trade(self, from_team: str, parties: list[str],
                           terms: dict) -> dict
    def tool_execute_trade(self, from_team: str, trade_id: str) -> dict
    def tool_check_my_progress(self, team: str) -> dict
    def tool_advance_round(self, team: str, notes: Optional[str] = None) -> dict
```

### 7.4 Tool Semantics

**`propose_trade(parties, terms)`:**
- Validates all 6 trade validity rules (Section 3.4) at proposal time. Invalid proposals return an error.
- Creates a `TradeProposal` with a unique `trade_id` (format: `T-{round}-{counter}`).
- Auto-broadcasts the proposal to all named parties' inboxes as a system message: `[TRADE PROPOSAL T-3-2 from Apex City Aces — see attached terms]`.
- Returns: `{"trade_id": "T-3-2", "parties": [...], "expires_at_round": current_round + 1}`.

**`execute_trade(trade_id)`:**
- Verifies the calling team is a party to the trade.
- Records consent in `consent_log[team_name] = True`.
- If all parties have consented in the **same round**: trade executes immediately. Assets transfer; payrolls update; broadcast goes to all 6 teams.
- If end-of-round arrives without all consent: proposal expires; trade does not execute.
- A new proposal must be created (with a new trade_id) to retry.

**`check_my_progress()`:**
- Returns the current goal status: `{"goal_met": bool, "details": str, "bonuses_eligible": [...]}`.
- This is NOT visible to other teams.
- Calling this does not consume a round.

**`advance_round()`:**
- Records this team's vote to advance.
- When all 6 teams have voted: round advances.
- Forces a soft pace: an agent that doesn't advance for 5+ "wall turns" is force-advanced by orchestration to prevent deadlock.

### 7.5 Round Loop

Pseudo-code:

```python
def run_round(env: TradeDeadlineEnvironment, agents: dict):
    """One round = each agent gets one turn (in rotated order) to take
    actions, then the round advances when all 6 vote advance."""

    round_order = rotate_team_order(env.current_round, env.run_id)

    for team in round_order:
        agent = agents[team]
        # Each agent is allowed up to MAX_ACTIONS_PER_TURN tool calls
        # before being expected to advance_round
        agent_response = run_agent_turn(
            agent, env, team, max_actions=MAX_ACTIONS_PER_TURN
        )

    # Resolve trades that achieved consent this round
    env.resolve_pending_trades()

    # If all 6 teams have voted advance, round progresses
    if len(env.advance_votes) == 6:
        env.current_round += 1
        env.advance_votes.clear()
```

### 7.6 Maximum Round Budgets

To prevent runaway token usage:

| Limit | Value |
|---|---|
| MAX_ACTIONS_PER_TURN | 25 tool calls |
| MAX_TOTAL_TURNS_PER_AGENT_PER_RUN | 200 |
| MAX_EMAIL_LENGTH (agent-side) | 800 words |
| MAX_RUN_WALL_CLOCK | 60 minutes |

Exceeding any limit terminates the agent's run with current progress logged.

---

## 8. Scoring System

### 8.1 Per-Run Per-Team Score

```
TeamScore = goal_achieved (0 or 1)
          + sum of bonuses achieved (each bonus +0.10 to +0.20)
```

`goal_achieved` is binary, evaluated by the orchestration layer at end-of-deadline using the hidden goal specification + the final asset state.

`bonuses` are also evaluated by orchestration. Each goal has 1–2 named bonuses with explicit numeric thresholds.

Maximum per-run TeamScore = ~1.30 (goal + both maximum bonuses).

### 8.2 Per-Run Per-Model Score

In Stage 1: 1 agent under test = 1 score per run.

In Stage 2: each agent plays one team-position. The TeamScore is also the model-position score for that run.

### 8.3 Aggregating Across Runs — Bradley-Terry Rating

See Section 9 for full Bradley-Terry methodology. Headline:

For each run, every pair of models that played in that run produces a "comparison" — model A's score in its team-position vs model B's score in its team-position. Bradley-Terry produces a rating for each model that maximizes the likelihood of the observed comparison outcomes.

### 8.4 Statistical Reporting

**Minimum runs:**
- Stage 1: 10 runs per model under test.
- Stage 2: 60 runs minimum (every model plays every team-position at least 2 times; ideally 4 times → 240 runs total).

**Reporting per model:**
- Bradley-Terry rating (mean of 1500)
- Bootstrap 95% CI (2,000 resamples, resample over runs)
- Mean per-team-position score (6 numbers, one per position)
- Coalition participation rate
- Goal-leakage rate (LLM judge, kappa-validated)
- Goal-inference accuracy (post-run probe)

**Leaderboard rule:** Models whose 95% CIs on Bradley-Terry rating overlap are marked **TIED**. CI bars are displayed alongside point estimates. Non-negotiable.

**Baseline comparison:** Two baselines (Section 11.4 below): Random-Valid-Trade Baseline and Goal-Aware Heuristic Baseline. Run each 50 times.

### 8.5 Secondary Diagnostic Metrics

- **Coalition participation rate:** fraction of executed trades that were 3-team trades, per agent
- **Trades initiated:** number of `propose_trade()` calls made by this agent across the run
- **Trade close rate:** fraction of proposals this agent initiated that successfully executed
- **Average rounds-to-first-trade:** how quickly the agent got its first trade through
- **Goal-leakage score:** see Section 10
- **Goal-inference accuracy:** see Section 10

---

## 9. Bradley-Terry Rating Methodology

### 9.1 Why Bradley-Terry, Not Elo

Elo is designed for sequential 1v1 games with symmetric outcomes. Trade Deadline Bench has 6-way games with asymmetric goals and rotation across positions. Bradley-Terry generalizes Elo to handle:
- Multi-way comparisons (not just pairs)
- Offline batch fitting (we have all data at once, no need to update online)
- Confidence intervals via bootstrap

### 9.2 Goal Rotation Design

To eliminate goal-difficulty confounds, every model plays every team-position equal times.

For 5 frontier models × 6 team-positions = 30 unique (model, position) cells. Minimum 2 runs per cell → 60 runs total. Recommended: 4 runs per cell → 120 runs total.

In each run, 5 of 6 team-positions are filled with the 5 frontier models; the 6th is filled with a designated "neutral GM" (Claude Haiku 4.5) that plays a calibration role to absorb the 6th slot. The neutral GM's score is logged for reference but does not contribute to Bradley-Terry ratings of the 5 frontier models.

Across all runs, the Latin-square assignment ensures each model plays each team-position equally; pairwise (model A vs model B) comparisons are also balanced across team-positions.

### 9.3 Pairwise Comparison Construction

For each run with models {A, B, C, D, E} in positions {p_A, p_B, p_C, p_D, p_E}, generate (5 choose 2) = 10 pairwise comparisons:

- (A, B): A's TeamScore in p_A vs B's TeamScore in p_B → "win" goes to whoever scored higher; tie counted as 0.5–0.5

Over many runs with rotated assignments, each pair (model X, model Y) accumulates many comparisons. Bradley-Terry fits ratings to maximize the likelihood of the observed comparison outcomes.

### 9.4 Bradley-Terry Implementation

Use `choix` library (open-source, well-tested):

```python
from choix import ilsr_pairwise

def fit_bradley_terry(comparisons, num_models):
    """
    comparisons: list of (winner_idx, loser_idx) tuples; ties contribute
                 0.5 to each side.
    Returns: array of ratings (parameters) of length num_models.
    """
    return ilsr_pairwise(num_models, comparisons, alpha=0.001)
```

Convert raw parameters to a 1500-mean scale:

```python
def to_1500_scale(params):
    centered = params - params.mean()
    return 1500 + (centered * 400 / params.std())
```

### 9.5 Bootstrap Confidence Intervals

Resample runs (with replacement) 2,000 times. For each resample, refit Bradley-Terry. The 2.5th and 97.5th percentiles of the resampled rating distribution are the 95% CI bounds for each model.

### 9.6 Tie Handling

If TeamScores are equal (e.g., both achieved goal but neither got bonuses), the comparison contributes 0.5 to each side rather than a "win" to one. This is well-handled by Bradley-Terry's standard formulation.

### 9.7 Leaderboard Output

```
| Rank | Model              | BT Rating ± CI    | Goal Achievement | Coalition Rate | Goal Leakage | Goal Inference |
|------|--------------------|-------------------|------------------|----------------|--------------|----------------|
| 1    | Claude Opus 4.7    | 1684 ± 48         | 78%              | 41%            | 12%          | 64%            |
| 2    | GPT-5.5            | 1631 ± 53         | 71%              | 38%            | 15%          | 58%            |
| ...  | ...                | ...               | ...              | ...            | ...          | ...            |
```

---

## 10. Coalition Detection & Leakage Measurement

### 10.1 Coalition Detection (Deterministic)

A "coalition" is operationally defined as: an executed trade with N ≥ 3 named parties.

This is detected directly from the `ExecutedTrade` records — no LLM judge needed.

Per-agent coalition participation rate = (number of executed 3-team trades agent participated in) / (total executed trades agent participated in).

### 10.2 Goal Leakage — Definition

For each (sender_team, recipient_team) email exchange, a leakage score is assigned:

- **0:** No goal-relevant information beyond what's publicly known
- **1:** Sender revealed a *directional hint* about its goal — e.g., "we're looking to add a star," "we'd love to shed some salary," "we're prioritizing youth"
- **2:** Sender revealed a *specific* goal element — e.g., "we need a player rated 88+," "we must shed at least $25M," "we're targeting at least one 1st-round pick"
- **3:** Sender revealed the *entire goal verbatim* or near-verbatim — e.g., quoted goal text, gave full numerical thresholds

Group emails (sent to multiple GMs at once) are scored once for the highest-leakage statement.

### 10.3 Leakage Judge

LLM judge: Claude Sonnet 4.6 (or specified equivalent at run time). Reads each email thread and the team's hidden goal text. Assigns a leakage score per outgoing email from that team.

Judge prompt: see Appendix C.

Judge is invoked **post-run only**. Its outputs are never fed back to any agent.

### 10.4 Leakage Metrics per Run per Team

```
Total Outgoing Emails        = count of emails sent by this team
Leakage Rate (any leak)      = count(score ≥ 1) / total
Hard-Leak Rate               = count(score ≥ 2) / total
Verbatim-Leak Rate           = count(score = 3) / total
```

### 10.5 Goal-Inference Probe

After the run completes, a separate probe asks each agent: "Based on the conversations during this trade deadline, what do you think each of the other 5 teams' hidden goals were? For each team, state your inference in 2–3 sentences."

The probe's output is then compared against ground truth by an LLM judge (separate from leakage judge to avoid prompt cross-pollination). Each inference is scored:

- **0:** Wrong / unrelated to actual goal
- **1:** Captured the high-level direction (rebuild vs. win-now) only
- **2:** Captured the key constraint (e.g., "wants a star") but missed numerical thresholds
- **3:** Captured the goal substantially correctly including key thresholds

Per-agent goal-inference accuracy = mean inference score / 3 across 5 opponents = a number in [0, 1].

### 10.6 Judge Validation

Same protocol as MoneyBall v3:
- Two researchers independently grade 50 emails (leakage) and 50 inferences (probe) from pilot runs
- Compute Cohen's kappa between each researcher and the LLM judge
- ≥ 0.7 kappa: scores are primary data
- 0.6–0.69: exploratory with caveat
- < 0.6: revise judge prompt and re-validate

### 10.7 Public Leaderboard Reporting

The public leaderboard shows: BT rating, goal achievement, coalition rate, goal leakage rate, goal inference accuracy. All five together let readers diagnose *how* a high-rated model is winning.

---

## 11. Implementation Plan — Two-Stage Build

This is the section to read carefully if you are Devin or another implementing engineer.

### 11.1 The Two-Stage Architecture

**Stage 1 (v0.1):** 1 model under test against 5 small-LLM neutral GMs (Claude Haiku 4.5). Goal rotation: each model under test runs ≥ 2 times per team position. Bradley-Terry NOT used in Stage 1 — instead, simple per-model mean TeamScore with bootstrap CIs (mirroring MoneyBall v3 reporting). This stage debugs the harness, calibrates goals, and produces a v0.1 leaderboard.

**Stage 2 (v1.0):** 5 frontier models in 5 of 6 team-positions; 6th is Haiku 4.5 neutral GM. Goal rotation across all positions. Bradley-Terry rating across runs.

**Hard gate between stages:** Stage 1 must produce a stable, reproducible v0.1 leaderboard with 5 models, validated calibration probe, validated leakage judge (kappa ≥ 0.7), and pilot run reproducibility (re-run same seed → same outcome). No Stage 2 work begins until this gate passes.

### 11.2 Phase Breakdown — Devin Implementation Plan

Each phase has a single deliverable, a verifiable test, and a commit policy. Devin commits at the end of every phase and at every test-passing checkpoint within a phase. Branches are named `phase-N-description`.

#### Phase 1 — Data Structures & Scenario Loader (Days 1–2)

**Deliverable:** `data_structures.py` and `scenario_loader.py`. Loads `teams_config.yaml`, generates the 72-player league with deterministic seed, populates `Player`, `DraftPick`, team rosters.

**Verifiable tests:**
- [ ] Test: loading the same seed produces identical roster
- [ ] Test: 72 unique players generated, distribution matches spec (≤ 6 with rating ≥ 88, etc.)
- [ ] Test: all 6 teams have 12 players each, 4–6 marked tradeable
- [ ] Test: hidden goals load correctly and are not exposed in any public-facing output

**Commit:** at end of phase. Branch: `phase-1-scenario-loader`.

#### Phase 2 — Trade Validation Logic (Days 2–3)

**Deliverable:** `trade_validator.py`. Implements all 6 trade validity rules from Section 3.4. Pure function: takes a proposed trade dict, returns `(is_valid: bool, reason: str)`.

**Verifiable tests:**
- [ ] Test: 2-team valid trade passes
- [ ] Test: 3-team valid trade passes
- [ ] Test: trade with cap violation fails with specific reason
- [ ] Test: trade with non-tradeable player fails
- [ ] Test: trade with cash > $5M per trade fails
- [ ] Test: trade with cash > $10M cumulative fails
- [ ] Test: salary-matching within 25% rule (with cap room) edge cases (3 cases)
- [ ] Test: same player in two outgoing slots fails
- [ ] Test: pick already sent fails

**Commit:** every test that passes. Branch: `phase-2-trade-validator`.

#### Phase 3 — Environment & Tool Methods (Days 3–6)

**Deliverable:** `environment.py` containing `TradeDeadlineEnvironment` class with all tool methods, propose/execute trade flow, advance_round logic, inbox/email management.

**Verifiable tests:**
- [ ] Test: tool_send_email deposits in recipient inbox correctly
- [ ] Test: group email goes to all named recipients
- [ ] Test: tool_propose_trade with valid proposal returns trade_id; auto-broadcasts to parties' inboxes
- [ ] Test: tool_propose_trade with invalid proposal returns error
- [ ] Test: 2-team trade with both parties calling execute_trade in same round → trade executes
- [ ] Test: 3-team trade with all three parties calling execute_trade in same round → trade executes
- [ ] Test: 3-team trade with only 2 of 3 calling execute_trade → proposal expires next round, no trade
- [ ] Test: trade execution updates rosters, payroll, cash_used correctly
- [ ] Test: trade execution broadcasts to all 6 teams' inboxes
- [ ] Test: tool_check_my_progress returns goal status only to the calling team
- [ ] Test: advance_round requires all 6 votes; force-advance after wall-clock timeout
- [ ] Test: same scenario_seed + same agent actions → identical environment state at every round

**Commit:** every test that passes. Branch: `phase-3-environment`.

#### Phase 4 — Goal Calibration (Days 6–8)

**Deliverable:** Calibrated goals such that an oracle agent (with full information) achieves each goal in 70–85% of runs.

**Procedure:**
1. Implement `OracleAgent` (Section 11.4) — has access to all hidden information and uses a deterministic feasibility-search algorithm to find a sequence of trades that achieves its goal.
2. Run OracleAgent in each of the 6 team-positions, 50 times per position (with rotated other-team assignments using OracleAgent for all other slots too).
3. Measure per-team-position oracle achievement rate.
4. If any rate is outside 70–85%: tune the goal text (e.g., adjust talent rating threshold by ±2, salary threshold by ±$2M) and re-test.
5. Iterate up to 3 times. If still failing: flag for spec revision.
6. Lock all goal specifications. Hash with SHA256. Do not modify after Phase 5 begins.

**Verifiable tests:**
- [ ] Test: OracleAgent achievement rate per goal is in [0.70, 0.85] for all 6 goals
- [ ] Test: cross-goal achievement rates are within 10 percentage points of each other (no goal is dramatically harder)
- [ ] Test: locked goal specifications have stable SHA256 hashes; modifying any goal changes the hash

**Commit:** at every iteration (so we have history of goal tuning). Branch: `phase-4-goal-calibration`.

#### Phase 5 — Stage 1 Single-Agent Pilot (Days 8–10)

**Deliverable:** Stage 1 leaderboard with 3 models × 10 runs (rotated through team positions); preliminary goal-leakage and goal-inference judge prompts validated.

**Procedure:**
1. Implement run loop for Stage 1: 1 frontier model + 5 Haiku 4.5 neutral GMs.
2. Run pilot: 3 frontier models (Haiku 4.5, Sonnet 4.6, Opus 4.7) × 10 runs each, with the model under test rotated through all 6 team positions across runs (≥ 2 runs per position).
3. Compute Stage 1 metrics: mean TeamScore per model, bootstrap CI, coalition rate, leakage rate, inference accuracy.
4. Validate leakage judge: 2 researchers grade 50 emails, compute Cohen's kappa.
5. Validate goal-inference judge: 2 researchers grade 50 inferences, compute Cohen's kappa.
6. Both kappas must be ≥ 0.7 to proceed. If not: revise judge prompt, re-grade, repeat.

**Verifiable tests:**
- [ ] Test: pilot run completes without errors for all 3 × 10 = 30 runs
- [ ] Test: same seed + same model + same orchestration → identical TeamScore (reproducibility)
- [ ] Test: leakage judge Cohen's kappa ≥ 0.7
- [ ] Test: goal-inference judge Cohen's kappa ≥ 0.7
- [ ] Test: Stage 1 leaderboard shows clear cross-model variance (not all CIs overlap)

**Commit:** at every test passing. Branch: `phase-5-stage-1-pilot`.

#### Phase 6 — Stage 1 Full Leaderboard & Hard Gate (Days 10–12)

**Deliverable:** Public-quality Stage 1 v0.1 leaderboard with ≥ 5 frontier models × ≥ 12 runs each.

**Procedure:**
1. Run 5+ frontier models × 12 runs each = 60+ runs.
2. Compute final Stage 1 metrics with bootstrap CIs.
3. Apply CI-overlap tie rule.
4. Generate Stage 1 dashboard (HTML + JSON sample results, mirroring MoneyBall's findings page structure).
5. Write findings post (~1,500 words) following pre-registered analysis plan.

**Hard gate test before proceeding to Phase 7:**
- [ ] All Phase 5 tests still pass
- [ ] Cost per Stage 1 run is documented and consistent with Section 14 estimates
- [ ] Reproducibility verified: 5 randomly sampled (model, seed) combinations re-run identically
- [ ] Leakage and inference judges still kappa ≥ 0.7 on a held-out validation set of 50 new examples
- [ ] Stage 1 leaderboard demonstrates non-trivial cross-model variance (e.g., top - bottom > 0.30 mean TeamScore difference, with non-overlapping CIs for at least the top vs. bottom pair)

**If hard gate fails:** stop. Do not begin Stage 2. Diagnose, fix, re-run Phase 6.

**Commit:** at every leaderboard run completion. Branch: `phase-6-stage-1-leaderboard`.

#### Phase 7 — Stage 2 Multi-Frontier Harness (Days 12–14)

**Deliverable:** `stage_2_harness.py` extending Phase 5's run loop to support 5 different frontier models simultaneously, with Latin-square rotation across team positions.

**Verifiable tests:**
- [ ] Test: rotation generator produces a balanced design (each model plays each position equal times across N runs)
- [ ] Test: 5 different model clients can be invoked concurrently without race conditions on environment state
- [ ] Test: a single Stage 2 run completes successfully with 5 different frontier model APIs

**Commit:** at every test passing. Branch: `phase-7-stage-2-harness`.

#### Phase 8 — Bradley-Terry Implementation (Days 14–15)

**Deliverable:** `bradley_terry.py` implementing pairwise comparison generation, BT fitting via `choix`, conversion to 1500-mean scale, bootstrap CIs.

**Verifiable tests:**
- [ ] Test: with synthetic data where model A > B > C, BT recovers correct ordering
- [ ] Test: bootstrap CI bounds are reasonable (e.g., narrower with more runs, wider with fewer)
- [ ] Test: tie comparisons (TeamScore equal) correctly contribute 0.5 each side
- [ ] Test: with degenerate data (all ties), BT returns all-equal ratings without crashing

**Commit:** at every test passing. Branch: `phase-8-bradley-terry`.

#### Phase 9 — Stage 2 Pilot (Days 15–18)

**Deliverable:** Stage 2 pilot results: 5 frontier models × 60 runs (2 per position per model). Validates rotation balance, BT computation, and that Stage 2 surfaces signal Stage 1 missed.

**Verifiable tests:**
- [ ] Test: 60 pilot runs complete; rotation is balanced (every model plays every position exactly 2 times)
- [ ] Test: BT ratings are computable and reasonable (mean 1500, monotonic ordering matches Stage 1 directionally)
- [ ] Test: pre-registered hypotheses (H2c — asymmetry exploitation) testable on pilot data (exploratory only)

**Commit:** at every milestone (rotation generated, runs complete, BT computed). Branch: `phase-9-stage-2-pilot`.

#### Phase 10 — Stage 2 Full Leaderboard (Days 18–22)

**Deliverable:** v1.0 Stage 2 leaderboard with 5 frontier models × 120 runs (4 per position per model). Final dashboard + findings writeup + public release.

**Verifiable tests:**
- [ ] Test: 120 runs complete; balanced rotation maintained
- [ ] Test: BT CIs do not overlap for at least one model pair (i.e., the leaderboard has at least one statistically distinguishable result)
- [ ] Test: pre-registered hypotheses tested formally; results reported per Appendix E
- [ ] Test: full reproducibility on 5 randomly-resampled runs

**Commit:** at every leaderboard run. Branch: `phase-10-stage-2-release`.

### 11.3 Why This Phased Plan, Specifically

Each phase has one job. Stage 1 produces a usable benchmark even if Stage 2 never ships. The hard gate after Phase 6 prevents the all-too-common failure mode of "race ahead to multi-agent before single-agent works." If you (Devin) are tempted to skip phases or merge them: don't. Each phase tests something specific, and the verifiable tests at every checkpoint are how we know the harness isn't silently broken.

### 11.4 Baseline Agents (Required Both Stages)

**Random-Valid-Trade Baseline:** at each round, randomly proposes a trade that satisfies all 6 validity rules. Accepts any incoming proposal that satisfies validity. Run 50 times per team-position. Establishes the floor.

**Goal-Aware Heuristic Baseline:** has access to its own hidden goal. Uses a hand-coded greedy algorithm: identify which other teams have assets matching its goal; propose a one-for-one trade matching salary; accept any proposal that advances goal completion. Run 50 times per team-position. Establishes the "non-LLM strategic floor."

A model below the Goal-Aware Heuristic Baseline has failed to extract value from its LLM reasoning capability beyond what a hand-coded script can do.

---

## 12. Devin Working Agreement

These are non-negotiable working norms for Devin or any AI software engineer implementing this spec. Read this section before writing any code.

### 12.1 Commit Discipline

- **Commit at every passing test.** Not at end of day. Not at end of phase. At every passing test.
- Commit messages follow the format: `phase-N: <one-line description>; tests: <list of tests added/now-passing>`.
- Branches: one branch per phase, named `phase-N-description`. Merge to `main` only at end of phase, after all phase tests pass.
- Never force-push. Never rebase shared history.

### 12.2 Testing Discipline

- Every tool method gets at least one happy-path and one error-path test.
- Every validation rule gets at least one passing and one failing case.
- Reproducibility is a required test at every phase that involves agent runs: same seed + same actions → identical output.
- LLM-judge tests (Phase 5, Phase 6 hard gate) require Cohen's kappa computation against human grades; do not skip this even if it slows you down.

### 12.3 Spec Adherence

- Do not invent fields, parameters, or tool methods not in this spec. If a field seems missing, ask before adding.
- Do not change scoring formulas, goal specifications, or validity rules without explicit human approval. These are load-bearing.
- Do not "improve" the leakage judge prompt or goal-inference judge prompt without re-validating Cohen's kappa from scratch.

### 12.4 Out-of-Scope Behaviors That Will Be Caught

The following behaviors will fail review:

- Skipping phases or merging phases
- Removing tests because "they don't apply" without spec amendment
- Shortening LLM judge validation to "spot check" instead of full kappa computation
- Changing goal specifications to make oracle achievement easier without documenting why
- Adding "helpful" features (e.g., auto-suggesting trades, hint systems) — this benchmark is deliberately bare
- Using LLMs for things the spec says should be deterministic (e.g., trade validation)

### 12.5 What to Do If Stuck

- If a test fails repeatedly: stop, write up what you've tried, and ask. Do not paper over with `pytest.skip` or weakened assertions.
- If a phase appears infeasible as specified: stop, document why, and ask. Do not silently re-scope.
- If you find a spec inconsistency: stop, document, and ask. Do not pick one interpretation and proceed.

### 12.6 Logging Requirements

Every run must log:

- Full email threads per (sender, recipient) pair
- All trade proposals (executed and expired)
- All `check_my_progress` calls per agent (timestamp + result)
- All tool calls with arguments and return values
- Final environment state at end of run
- Cost (input + output tokens, total $) per agent per run

Logs are stored as JSON in `runs/{gm_stack_version}/{run_id}/`. Per-run logs are required for reproducibility checks and for post-hoc judge runs.

### 12.7 Reproducibility Contract

A "reproducible run" means: given (scenario_seed, gm_stack_version, agent_assignments, run_id, all model API responses cached), re-running produces byte-identical environment state at every round and identical TeamScores.

Stage 1 and Stage 2 reproducibility tests both require this. Cache model responses if needed; do not rely on `temperature=0` because frontier APIs are not bit-deterministic at temperature=0.

---

## 13. Benchmark Validity & Design Rationale

### 13.1 Contamination Resistance

All player names, team names, contracts, and goals are fictional. Procedural generation from a documented seed makes future versions easily re-rollable. Real NBA CBA knowledge does not transfer.

### 13.2 The Multi-Agent Same-Token Problem

A known concern with mixed-model multi-agent setups: stronger agents may write more impressive prose, leading weaker agents to update beliefs based on stylistic competence rather than substance. We do not solve this — we measure it. If H2c (asymmetry exploitation) is supported, that's exactly the mechanism: stronger agents get better outcomes against weaker ones, partly because the weaker agents are persuaded by surface-level style.

This is a feature of the mixed-model design, not a bug. Project Deal already documented it; Trade Deadline Bench measures it under coordination-required conditions.

### 13.3 Why Hidden Goals, Not Pure Asset-Optimization

A purely asset-optimization benchmark (where each team maximizes summed talent, say) would reduce to a closed-form solver and would not produce coordination-interesting behavior. Hidden goals create:

- Asymmetric trade demand (Cascade wants picks; Apex wants stars; etc.)
- Information asymmetry as the central strategic variable
- Natural coalition incentive (3-team trades emerge because one team's outflow needs another's cap room to land)

### 13.4 Why All-Must-Call execute_trade

Three-party verbal agreement is fragile. Real-world trade calls have a "league office" that registers final terms. Our `execute_trade` mechanism is the league office: each party must independently consent with matching trade_id and matching terms in the same round. This eliminates:

- "I thought we were agreeing to..." parameter drift
- One agent unilaterally claiming agreement
- String-match exploits (no DEAL CONFIRMED escape hatch)

It also creates the coordination challenge that's the whole point of the benchmark: agents must converge on identical parameters in the same round, which forces precise communication.

### 13.5 Why 8 Rounds, Not 10 or 5

Pre-launch piloting will calibrate this, but the hypothesis is: 5 rounds is too short for 3-team trades to consummate (those typically need a proposal round, a counter round, and a confirm round at minimum, so 3 rounds × 2–3 trade negotiations = 6–9 rounds needed). 10 rounds creates dead time at the end where agents have signed deals and have nothing to do. 8 is the working compromise.

If pilot shows median trade closes in round 5–6 and rounds 7–8 are dead, we'll cut to 6. If trades are mostly attempted in the final 2 rounds in a panic, we'll extend to 10. Lock value before Phase 6.

### 13.6 Why Goal Rotation, Not Goal-Conditioned Scoring

We considered goal-conditioned BT (separate ratings per (model, position)) but rejected it because:
- Dilutes data 6x; would need 6x more runs for stable ratings
- Creates 30 ratings instead of 5; harder to interpret and present
- Goal-difficulty differences after Phase 4 calibration should be small

Goal rotation is more expensive (every model plays every position, multiplying runs) but cleaner: residual goal-difficulty asymmetry cancels in expectation.

---

## 14. Budget & Cost Estimates

### 14.1 Per-Run Token Estimates

For one Stage 2 run with 5 frontier models + 1 Haiku:

- Avg turns per agent per run: ~80 (8 rounds × ~10 turns each)
- Avg input tokens per turn: ~4,000 (growing context)
- Avg output tokens per turn: ~600
- Per agent per run: ~80 × 4,600 = ~370K tokens
- Per run total (6 agents): ~2.2M tokens

At blended frontier rate of ~$5/M output, ~$1.50/M input: per Stage 2 run ≈ **$3–6**.

### 14.2 Stage 1 Costs

- Pilot (3 models × 10 runs): ~$30–60
- Full Stage 1 leaderboard (5 models × 12 runs): ~$60–120
- Goal-leakage judge runs (Sonnet 4.6, ~$0.10/run): ~$10
- Goal-inference probe + judge: ~$15
- Calibration probe (50 oracle runs × 6 positions × cheap model): ~$5–10

**Stage 1 total: ~$100–200**.

### 14.3 Stage 2 Costs

- Pilot (60 runs at ~$5/run): ~$300
- Full leaderboard (120 runs at ~$5/run): ~$600
- Judges (leakage + inference, 120 runs): ~$50
- Replicates / debugging: ~$200

**Stage 2 total: ~$1,000–1,500**.

### 14.4 Total Project Budget

**Stage 1 + Stage 2: ~$1,200–1,800**.

If budget is constrained: ship Stage 1 first ($200), publish, raise visibility, then crowd-fund or seek lab credits for Stage 2.

---

## Appendix A — Sample Multi-Team Trade Transcript

A 3-team trade between Apex, Harlow, and Eastgate.

```
ROUND 3

[Apex City Aces → Harlow Vipers, group thread including Eastgate Titans]

Apex: I've been studying both your rosters. Harlow, your roster construction
suggests you're transitioning. Eastgate, you have multiple young assets but
need more mid-tier scoring. Here's a sketch:

Apex sends: 2027 1st-rd pick, $4M cash, Bryan Hayes (PF, 78 rated, $14M)
Apex receives: Marcus Cole (SG, 87 rated, $26M, 2 yrs left)

Harlow sends: Marcus Cole, 2028 2nd-rd pick
Harlow receives: 2027 1st-rd (from Apex), Tyler Reese (SF, 79 rated,
$11M, 3 yrs left, from Eastgate)

Eastgate sends: Tyler Reese
Eastgate receives: Bryan Hayes (PF, 78 rated, $14M from Apex), $4M cash,
2028 2nd-rd pick

This satisfies salary matching for all three. Harlow gets the 1st you wanted
plus a young SF; Eastgate gets a PF, cash, and a 2nd; we get the SG. Round 4
to converge on terms?

[Harlow Vipers]

Harlow: Close, but Reese's contract isn't quite what we want for our window
— 3 years is too long for a transition piece. Could we substitute a different
Eastgate player? Or shift the cash flow?

[Eastgate Titans]

Eastgate: Reese is the player I'm willing to move at this rating. If you
want a 2-year guy from us, that takes me to a player rated 73 (Mike Ortiz,
$8M, 2 yrs). Salary doesn't match for Apex anymore. Maybe Apex adds Hayes +
a different pick instead?

ROUND 4

Apex: Adjusted: Apex sends Hayes ($14M) + 2027 1st + 2028 1st + $5M cash;
receives Cole. Harlow sends Cole; receives both 1sts plus Reese. Eastgate
sends Reese; receives Hayes + $5M. Salary all checks. Trade-id: T-4-3.

All three: agreement?

Harlow: yes.
Eastgate: yes.
Apex: confirmed.

[All three call execute_trade(T-4-3) in round 4.]

[SYSTEM]: TRADE EXECUTED. Apex receives Cole from Harlow. Harlow receives
2027 1st (Apex), 2028 1st (Apex), Tyler Reese (Eastgate). Eastgate receives
Bryan Hayes (Apex), $5M cash (Apex). Cap and salary check passed.
```

This example illustrates: (a) one party (Apex) playing the hub role, (b) a real coordination challenge in round 4 where all three must converge on identical terms within the round, (c) the all-must-call execute_trade enforced.

---

## Appendix B — Calibration Probe Agent

The calibration probe is a deterministic scripted agent used exclusively to verify environment behavior before Phase 5. It is not a baseline.

### B.1 Probe Strategy (fixed, verbatim)

For each of the 6 team positions:

**Round 1:** Send a generic introduction email to each of the 5 other GMs. Single sentence: "Hi, I'm GM of [TEAM]. Here are some assets I'm willing to discuss: [list 3 tradeable players]. Anything we should explore?"

**Round 2:** Read inbox. For any GM that responded with interest in any specific player, propose a 2-team trade: that player + one filler asset for one of their players matching the same rating tier.

**Round 3–6:** For any pending proposals, call execute_trade. For any incoming proposals, call execute_trade if they pass validity check.

**Round 7–8:** Advance.

### B.2 Calibration Pass/Fail Thresholds

| Metric | Pass | Fail |
|---|---|---|
| At least 1 trade executed per probe run | Yes | No |
| Avg rounds-to-first-trade across 30 probe runs | 3–5 | < 3 or > 5 |
| Validity rule rejection rate (proposed trades that fail validation) | < 10% | ≥ 10% |
| Reproducibility (same seed → same trades) | 100% | < 100% |

### B.3 Remediation

**If trades aren't executing:** likely a bug in execute_trade matching. Check trade_id matching across parties; check round-boundary handling.

**If validity rejection rate is too high:** probe is generating invalid trades; tune probe logic.

**If reproducibility fails:** non-determinism in environment state. Likely culprits: dict ordering, timestamp use, RNG without seed.

---

## Appendix C — Leakage Judge Prompt

Used by Claude Sonnet 4.6 (or specified equivalent) to grade each outgoing email post-run.

```
You are a benchmark judge evaluating information leakage in a multi-agent
LLM negotiation. You will be shown:

1. A team's hidden goal (the ground truth)
2. An outgoing email that team's agent sent during a trade negotiation

Score the email on this 4-point scale:

0 — No goal-relevant information beyond what's publicly known about the team
    (e.g., generic statements about "evaluating options," public roster facts)

1 — Directional hint: agent revealed a general direction of its goal
    (e.g., "looking to add a star," "open to shedding salary")
    without specific thresholds, dollar amounts, or numerical criteria

2 — Specific element: agent revealed a concrete part of its goal
    (e.g., a salary threshold, a specific rating range, a specific asset
    type required)

3 — Verbatim or near-verbatim: agent revealed the goal in full
    (e.g., quoted goal text, gave full numerical thresholds)

Ground truth goal text:
[GOAL_TEXT]

Outgoing email:
[EMAIL_BODY]

Output format (JSON only, no other text):
{
  "score": 0 | 1 | 2 | 3,
  "rationale": "one-sentence explanation of why this score was assigned"
}
```

---

## Appendix D — Goal-Extraction Probe Prompt

Run after each agent's deadline closes. Asks the agent to infer the other 5 teams' goals.

### D.1 Probe to Each Agent

```
The trade deadline has closed. Before final reporting, please answer this:

For each of the 5 other teams, what do you think their hidden goal was?
Base your inference on:
- Their public profile and roster
- The proposals they made and how they responded to yours
- Any signals in their communications

For each team, provide 2–3 sentences of inferred goal. Do not refer to your
own goal in your answer. Be honest — guesses are fine.

Other teams: [LIST]
```

### D.2 Inference Judge Prompt (separate LLM, evaluates each inference)

```
You are evaluating how accurately one team's GM inferred another team's
hidden goal. You will be shown:

1. The actual hidden goal text (ground truth)
2. The GM's inferred description

Score on this 4-point scale:

0 — Wrong direction (e.g., guessed "win-now" when actually "rebuild")
    or no useful inference

1 — Correct high-level direction (rebuild vs. win-now) but missed the
    specific objective

2 — Captured the key objective (e.g., "wants to acquire a star," "wants
    to shed salary") but missed numerical thresholds or specific
    constraints

3 — Captured the objective AND key thresholds substantially correctly
    (within ~20% of stated numerical targets, or correct ordinal claims)

Actual goal:
[GROUND_TRUTH_GOAL]

GM's inference:
[INFERENCE_TEXT]

Output (JSON only):
{
  "score": 0 | 1 | 2 | 3,
  "rationale": "one-sentence explanation"
}
```

---

## Appendix E — Pre-Registered Analysis Plan

Must be filed (e.g., on OSF) before any leaderboard run. Results reported against these predictions regardless of outcome.

### E.1 Models tested and tier assignments

[To be filled in pre-registration. External anchor: top tier = top-3 models on LMArena Coding category as of registration date; bottom tier = mid-tier models 6–8 ranks below top.]

### E.2 Stage 1 primary analysis

Compute per-model mean TeamScore + bootstrap 95% CI. Test H1 (Stage 1 version): "highest-tier model's mean TeamScore exceeds lowest-tier's by ≥ 0.30 points." Apply CI-overlap rule.

### E.3 Stage 2 primary analysis

Test H1 (Bradley-Terry version): "BT rating gap between top and bottom model exceeds 200 points with non-overlapping 95% bootstrap CIs."

### E.4 H2a — Coalition rate by tier

Compute mean coalition participation rate per tier. Test: top-tier ≥ 1.5× bottom-tier with two-sample t-test, alpha = 0.05.

### E.5 H2b — Goal-Inference vs. Goal-Leakage Asymmetry

For top-tier model: compute (mean goal-inference accuracy) − (mean goal-leakage rate). Same for bottom-tier. Threshold: top tier's gap > 0.25; bottom tier's gap < 0.10 or negative.

### E.6 H2c — Asymmetry Exploitation

Subset Stage 2 runs into "matched-tier" runs (all 5 frontier models same tier) and "mixed-tier" runs (top-tier model + lower-tier opponents). Compare goal-achievement rate of top-tier model in each subset. Threshold: ≥ 20 pp higher achievement against weaker opponents.

### E.7 H3 — Coalition-Leakage Tradeoff

Within each model, compute Spearman correlation between coalition participation rate and leakage rate across runs. Threshold: ρ > 0.4 for top-tier models (i.e., coordination requires sharing).

### E.8 Reporting commitment

All hypotheses reported whether supported or not. If H1 fails, the headline finding is: "Trade Deadline Bench did not detect a significant goal-achievement gap between capability tiers, suggesting [interpretation]."

If H2c is supported but H2a/H2b are not, the headline is: "Frontier models exploit weaker counterparties without forming coalitions or inferring goals more accurately — they win through some other mechanism."

The most informative null result for the field is: "All frontier models perform similarly in coalition formation; coordination is not a current bottleneck for frontier capability."

---

## End of Specification

This spec is locked at version 1.0 on commit. Changes after lock require a version bump and explicit human approval.
