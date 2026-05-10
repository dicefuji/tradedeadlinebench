"""OpenAI function-calling tool definitions for the 9 environment tools.

Each tool definition follows the OpenAI function-calling schema so that
all models (routed via OpenRouter) use the same tool interface.
"""

from __future__ import annotations

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Send an email to one or more other teams' GMs. "
                "Use for negotiation, proposals, counter-offers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of team names to send to.",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body text (max 800 words).",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_inbox",
            "description": "Read your team's inbox. Optionally filter by sender team.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_team": {
                        "type": "string",
                        "description": "Optional: only show emails from this team.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_team_roster",
            "description": "View a team's current roster (all rosters are public).",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": "Name of the team to view.",
                    },
                },
                "required": ["team_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_team_cap_sheet",
            "description": "View a team's cap situation (payroll, cap room, cash used).",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": "Name of the team to view.",
                    },
                },
                "required": ["team_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_executed_trades",
            "description": "View all trades that have been executed league-wide this deadline.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_trade",
            "description": (
                "Register a formal trade proposal. Validates all trade rules. "
                "Returns a trade_id if valid. The proposal is broadcast to all "
                "named parties next round."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "parties": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "All teams involved (including your team).",
                    },
                    "terms": {
                        "type": "object",
                        "description": (
                            "Asset movements dict. Keys are team names, values are "
                            "objects with 'sends' and 'receives'. Each contains optional "
                            "'players' (list of player_ids), 'picks' (list of pick_ids), "
                            "and 'cash' (float, dollars in millions)."
                        ),
                    },
                },
                "required": ["parties", "terms"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_trade",
            "description": (
                "Consent to a trade you are a party to. The trade executes "
                "only when ALL parties call execute_trade with the same trade_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trade_id": {
                        "type": "string",
                        "description": "The trade_id returned by propose_trade.",
                    },
                },
                "required": ["trade_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_my_progress",
            "description": (
                "Check whether your hidden goal is currently met. "
                "Returns goal status, details, and eligible bonuses. "
                "This is private -- not visible to other teams."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "advance_round",
            "description": (
                "Vote to advance to the next round. When all 6 teams vote, "
                "the round progresses. Call this when you are done with your "
                "actions for this round."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about your round strategy.",
                    },
                },
                "required": [],
            },
        },
    },
]
