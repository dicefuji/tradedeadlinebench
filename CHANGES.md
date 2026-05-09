# Changes & Spec Deviation Log

This file documents approved deviations from `trade_deadline_bench_v1.md` and
the rationale for each. Referenced by future phases to avoid re-litigating
settled decisions.

## Phase 1

### `TeamConfig` and `ScenarioData` dataclasses (approved)

Section 7.1 defines four dataclasses: `Player`, `DraftPick`, `TradeProposal`,
`ExecutedTrade`. The scenario loader requires two additional structural
containers to hold the loaded team configurations and the fully-populated
scenario state:

- **`TeamConfig`** — holds per-team metadata loaded from `teams_config.yaml`
  (name, public profile, cap room, tradeable count, hidden goal, draft pick
  config). These are the fields the spec defines across Sections 4 and 7.2;
  `TeamConfig` is the container, not a new benchmark mechanic.

- **`ScenarioData`** — holds the full loaded scenario (players by ID, players
  by team, picks by team, payroll, team configs). Maps directly to the fields
  `TradeDeadlineEnvironment.__init__` would populate (Section 7.3).

**Precedent:** structural containers around spec-defined fields are acceptable.
New benchmark mechanics (scoring formulas, validity rules, tool methods) are
not.

### Harlow bonus paraphrase (approved)

The bonus condition for Harlow Vipers is written as `"Both stars kept (achieved
via secondary trades)"` in `teams_config.yaml`. The spec says `"+15% if both
stars are kept (achieved via secondary trades, harder)"`. The paraphrase omits
the editorial note "(harder)" which is not a machine-evaluated condition. This
is accepted as written.
