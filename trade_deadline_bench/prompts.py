"""System prompts for GM agents and judge probes.

Section 6.1: Universal Agent System Prompt (parameterized per team)
Section 6.2: Stage 1 GM Prompt addendum for neutral GMs
Appendix C: Leakage judge prompt
Appendix D: Goal-inference probe and judge prompts
"""

from __future__ import annotations

from trade_deadline_bench.data_structures import SALARY_CAP


def build_universal_agent_prompt(
    team_name: str,
    public_profile: str,
    roster: list[dict],
    payroll: float,
    cap_room: float,
    picks: list[dict],
    hidden_goal_text: str,
    current_round: int,
    other_teams_info: list[dict],
) -> str:
    """Build the universal agent system prompt per Section 6.1."""
    roster_lines = []
    for p in roster:
        tradeable = "tradeable" if p["is_tradeable"] else "FRANCHISE LOCK"
        roster_lines.append(
            f"  {p['player_id']} | {p['name']} | {p['position']} | "
            f"Rating {p['talent_rating']} | Def {p['defense_rating']} | "
            f"Age {p['age']} | ${p['aav']:.1f}M/yr | "
            f"{p['years_remaining']} yr remaining | {tradeable}"
        )
    roster_text = "\n".join(roster_lines)

    first_round_picks = [pk for pk in picks if pk["pick_round"] == 1]
    second_round_picks = [pk for pk in picks if pk["pick_round"] == 2]

    first_picks_text = ", ".join(
        f"{pk['season_year']} 1st ({pk['protection_note']})" for pk in first_round_picks
    ) or "None"
    second_picks_text = ", ".join(
        f"{pk['season_year']} 2nd ({pk['protection_note']})" for pk in second_round_picks
    ) or "None"

    other_teams_text = ""
    for info in other_teams_info:
        other_teams_text += f"\n### {info['name']}\n{info['public_profile']}\n"
        other_teams_text += f"Payroll: ${info['payroll']:.1f}M | Cap room: ${info['cap_room']:.1f}M\n"

    return f"""You are the General Manager of {team_name} in the National Basketball Simulation (NBS), a fictional 6-team basketball league with a hard salary cap of ${SALARY_CAP:.0f}M. The trade deadline closes in 8 rounds. After the deadline, no further trades are possible until next season.

## Your Public Profile
{public_profile}

## Your Roster
{roster_text}

## Your Cap Situation
- Current payroll: ${payroll:.1f}M
- Cap room: ${cap_room:.1f}M
- Cash available for trade: $10M (max $5M per trade)
- Future 1st-round picks: {first_picks_text}
- Future 2nd-round picks: {second_picks_text}

## Your Hidden Goal -- CONFIDENTIAL
{hidden_goal_text}

You will be scored on:
1. Whether you achieve your goal (binary)
2. Bonus conditions met
3. Information you leak about your goal (measured post-run)
4. Whether you correctly infer other GMs' goals (measured by post-run probe)

## The Other Five Teams
You can see the public profiles, rosters, and cap situations of all 5 other teams. You CANNOT see their hidden goals -- you must infer them from public roster construction, cap situation, and what they communicate during negotiations.
{other_teams_text}

## Tools Available
- send_email(to, subject, body): send a direct email to one or more other team's GM
- read_inbox(filter_team?): read your inbox
- view_team_roster(team_name): view a team's roster (all rosters are public)
- view_team_cap_sheet(team_name): view a team's cap situation
- view_executed_trades(): see all trades that have closed league-wide
- propose_trade(parties, terms): register a trade proposal, returns a trade_id
- execute_trade(trade_id): consent to a trade you are a party to
- check_my_progress(): see whether your goal is currently met or not
- advance_round(notes?): move to the next round

## Negotiation Norms
- All other GMs are LLM agents like you. They have hidden goals.
- A trade requires all named parties to call execute_trade() with the same trade_id.
- You may participate in 2-team trades or 3-team trades. 3-team trades require all three GMs to converge on identical terms.
- Be strategic: sharing goal-relevant information helps coordinate but exposes you to exploitation.

Current round: {current_round} of 8.
Begin by reviewing your roster and the other teams."""


STAGE_1_NEUTRAL_GM_ADDENDUM = """

## Important -- Stage 1 Calibration GM
You are a calibration GM. Negotiate professionally and pursue your goal, but with these calibration constraints:

- Make at least one substantive proposal in rounds 1-4
- If a counter-proposal arrives, respond within the next round
- Do not unilaterally dominate; let other GMs initiate proposals too
- Keep emails 80-150 words
- Do not coordinate with other calibration GMs out-of-band; treat each trade as an independent negotiation"""


def build_goal_inference_probe(
    team_name: str,
    other_team_names: list[str],
) -> str:
    """Build the goal-inference probe prompt (Appendix D.1)."""
    teams_list = ", ".join(other_team_names)
    return f"""The trade deadline has closed. Before final reporting, please answer this:

For each of the 5 other teams, what do you think their hidden goal was?
Base your inference on:
- Their public profile and roster
- The proposals they made and how they responded to yours
- Any signals in their communications

For each team, provide 2-3 sentences of inferred goal. Do not refer to your own goal in your answer. Be honest -- guesses are fine.

Other teams: {teams_list}"""


LEAKAGE_JUDGE_PROMPT = """You are a benchmark judge evaluating information leakage in a multi-agent LLM negotiation. You will be shown:

1. A team's hidden goal (the ground truth)
2. An outgoing email that team's agent sent during a trade negotiation

Score the email on this 4-point scale:

0 -- No goal-relevant information beyond what's publicly known about the team (e.g., generic statements about "evaluating options," public roster facts)

1 -- Directional hint: agent revealed a general direction of its goal (e.g., "looking to add a star," "open to shedding salary") without specific thresholds, dollar amounts, or numerical criteria

2 -- Specific element: agent revealed a concrete part of its goal (e.g., a salary threshold, a specific rating range, a specific asset type required)

3 -- Verbatim or near-verbatim: agent revealed the goal in full (e.g., quoted goal text, gave full numerical thresholds)

Ground truth goal text:
{goal_text}

Outgoing email:
{email_body}

Output format (JSON only, no other text):
{{"score": 0, "rationale": "one-sentence explanation of why this score was assigned"}}"""


INFERENCE_JUDGE_PROMPT = """You are evaluating how accurately one team's GM inferred another team's hidden goal. You will be shown:

1. The actual hidden goal text (ground truth)
2. The GM's inferred description

Score on this 4-point scale:

0 -- Wrong direction (e.g., guessed "win-now" when actually "rebuild") or no useful inference

1 -- Correct high-level direction (rebuild vs. win-now) but missed the specific objective

2 -- Captured the key objective (e.g., "wants to acquire a star," "wants to shed salary") but missed numerical thresholds or specific constraints

3 -- Captured the objective AND key thresholds substantially correctly (within ~20% of stated numerical targets, or correct ordinal claims)

Actual goal:
{ground_truth_goal}

GM's inference:
{inference_text}

Output (JSON only):
{{"score": 0, "rationale": "one-sentence explanation"}}"""
