"""LLM agent harness — tool dispatch loop for one agent's turn.

Implements the agent loop: receive situation -> call LLM -> if tool_calls,
execute each tool, append results, call LLM again -> loop until no tool_calls
or MAX_ACTIONS_PER_TURN hit.
"""

from __future__ import annotations

import json
import logging

from trade_deadline_bench.data_structures import SALARY_CAP, TEAMS
from trade_deadline_bench.environment import MAX_ACTIONS_PER_TURN, TradeDeadlineEnvironment
from trade_deadline_bench.openrouter_client import OpenRouterClient
from trade_deadline_bench.prompts import (
    STAGE_1_NEUTRAL_GM_ADDENDUM,
    build_goal_inference_probe,
    build_universal_agent_prompt,
)
from trade_deadline_bench.tool_definitions import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

# Maximum messages to keep in the tool-call loop conversation.
# The first user message is always retained; older assistant/tool pairs
# are dropped so the payload stays within provider context limits.
_MAX_CONVERSATION_MESSAGES = 40


def _build_system_prompt(
    env: TradeDeadlineEnvironment,
    team: str,
    is_neutral_gm: bool,
) -> str:
    """Build the full system prompt for a team's agent."""
    tc = env.team_configs[team]

    roster = []
    for pid in sorted(env.players_by_team[team]):
        p = env.players_by_id[pid]
        roster.append({
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

    picks = []
    for dp in env.picks_by_team[team]:
        picks.append({
            "pick_id": dp.pick_id,
            "pick_round": dp.pick_round,
            "season_year": dp.season_year,
            "protection_note": dp.protection_note,
        })

    payroll = env.payroll[team]
    cap_room = SALARY_CAP - payroll

    other_teams_info = []
    for other_team in TEAMS:
        if other_team == team:
            continue
        otc = env.team_configs[other_team]
        other_payroll = env.payroll[other_team]
        other_cap = SALARY_CAP - other_payroll
        other_teams_info.append({
            "name": other_team,
            "public_profile": otc.public_profile,
            "payroll": other_payroll,
            "cap_room": other_cap,
        })

    prompt = build_universal_agent_prompt(
        team_name=team,
        public_profile=tc.public_profile,
        roster=roster,
        payroll=payroll,
        cap_room=cap_room,
        picks=picks,
        hidden_goal_text=tc.hidden_goal.get("description", ""),
        current_round=env.current_round,
        other_teams_info=other_teams_info,
    )

    if is_neutral_gm:
        prompt += STAGE_1_NEUTRAL_GM_ADDENDUM

    return prompt


def _dispatch_tool_call(
    env: TradeDeadlineEnvironment,
    team: str,
    function_name: str,
    arguments: dict,
) -> dict:
    """Dispatch a tool call to the environment."""
    if function_name == "send_email":
        return env.tool_send_email(
            from_team=team,
            to=arguments.get("to", []),
            subject=arguments.get("subject", ""),
            body=arguments.get("body", ""),
        )
    elif function_name == "read_inbox":
        return env.tool_read_inbox(
            team=team,
            filter_team=arguments.get("filter_team"),
        )
    elif function_name == "view_team_roster":
        return env.tool_view_team_roster(
            team_name=arguments.get("team_name", team),
        )
    elif function_name == "view_team_cap_sheet":
        return env.tool_view_team_cap_sheet(
            team_name=arguments.get("team_name", team),
        )
    elif function_name == "view_executed_trades":
        return env.tool_view_executed_trades()
    elif function_name == "propose_trade":
        return env.tool_propose_trade(
            from_team=team,
            parties=arguments.get("parties", []),
            terms=arguments.get("terms", {}),
        )
    elif function_name == "execute_trade":
        return env.tool_execute_trade(
            from_team=team,
            trade_id=arguments.get("trade_id", ""),
        )
    elif function_name == "check_my_progress":
        return env.tool_check_my_progress(team=team)
    elif function_name == "advance_round":
        return env.tool_advance_round(
            team=team,
            notes=arguments.get("notes"),
        )
    else:
        return {"error": f"Unknown tool: {function_name}"}


def run_agent_turn(
    client: OpenRouterClient,
    env: TradeDeadlineEnvironment,
    team: str,
    model_id: str,
    is_neutral_gm: bool,
    run_id: int,
    turn_index: int,
    max_actions: int = MAX_ACTIONS_PER_TURN,
) -> dict:
    """Run one agent's turn: LLM call -> tool dispatch loop.

    Returns a dict with turn metadata:
      actions_taken, advanced_round, tool_calls_log, terminated_reason
    """
    system_prompt = _build_system_prompt(env, team, is_neutral_gm)

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"It is round {env.current_round} of 8. You are {team}. "
                f"Take your actions for this round. When done, call advance_round."
            ),
        }
    ]

    actions_taken = 0
    advanced_round = False
    tool_calls_log: list[dict] = []
    terminated_reason = "completed"

    while actions_taken < max_actions:
        # Truncate conversation if it grows too long (keep first user
        # message + most recent messages) to avoid provider 400 errors.
        if len(messages) > _MAX_CONVERSATION_MESSAGES:
            messages = [messages[0]] + messages[-(_MAX_CONVERSATION_MESSAGES - 1):]

        response = client.call(
            model_id=model_id,
            system_prompt=system_prompt,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            team=team,
            run_id=run_id,
            turn_index=turn_index + actions_taken,
        )

        tool_calls = response.get("tool_calls", [])

        if not tool_calls:
            # No tool calls — agent is done or just sent text
            if response.get("content"):
                messages.append({
                    "role": "assistant",
                    "content": response["content"],
                })
            break

        # Build assistant message with tool calls
        assistant_msg: dict = {"role": "assistant", "content": response.get("content") or ""}
        assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # Execute each tool call
        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, TypeError):
                args = {}

            try:
                result = _dispatch_tool_call(env, team, func_name, args)
            except Exception as exc:
                logger.warning("Tool %s raised %s: %s", func_name, type(exc).__name__, exc)
                result = {"error": f"Tool '{func_name}' failed: {exc}"}
            actions_taken += 1

            tool_calls_log.append({
                "tool": func_name,
                "args": args,
                "result": result,
            })

            # Append tool result message
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result),
            })

            if func_name == "advance_round":
                advanced_round = True

            if actions_taken >= max_actions:
                terminated_reason = "max_actions_reached"
                break

    if actions_taken >= max_actions and not advanced_round:
        terminated_reason = "max_actions_reached"

    return {
        "team": team,
        "model_id": model_id,
        "actions_taken": actions_taken,
        "advanced_round": advanced_round,
        "tool_calls_log": tool_calls_log,
        "terminated_reason": terminated_reason,
    }


def run_goal_inference_probe(
    client: OpenRouterClient,
    env: TradeDeadlineEnvironment,
    team: str,
    model_id: str,
    run_id: int,
) -> dict[str, str]:
    """Run the post-deadline goal-inference probe (Appendix D.1).

    Returns a dict mapping other_team -> inference_text.
    """
    other_teams = [t for t in TEAMS if t != team]
    probe_text = build_goal_inference_probe(team, other_teams)

    system_prompt = _build_system_prompt(env, team, is_neutral_gm=False)

    response = client.call(
        model_id=model_id,
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": probe_text}],
        tools=None,
        team=team,
        run_id=run_id,
        turn_index=9999,
    )

    content = response.get("content", "")

    # Parse per-team inferences from the response
    inferences: dict[str, str] = {}
    current_team = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        matched_team = None
        for t in other_teams:
            if t.lower() in line.lower() and (line.strip().startswith("#") or line.strip().startswith("**") or t in line):
                matched_team = t
                break

        if matched_team is not None:
            if current_team is not None:
                inferences[current_team] = "\n".join(current_lines).strip()
            current_team = matched_team
            current_lines = []
            # Include the rest of the line after the team name
            after_name = line.split(matched_team, 1)[-1].strip().lstrip(":").lstrip("*").strip()
            if after_name:
                current_lines.append(after_name)
        elif current_team is not None:
            current_lines.append(line)

    if current_team is not None:
        inferences[current_team] = "\n".join(current_lines).strip()

    # If parsing failed, assign entire content to each team
    if not inferences:
        for t in other_teams:
            inferences[t] = content

    return inferences
