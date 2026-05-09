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

## Phase 2

### Approved structural-invariant validations

The following validations enforce structural invariants implied by the spec but
not explicitly enumerated as numbered rules in Section 3.4. They are permitted
under the same precedent as structural containers: they prevent impossible or
malformed states, not new business rules.

- **Bidirectional receives-consistency checks** — every sent asset must appear
  in exactly one other party's receives (sends→receives), and every received
  asset must appear in exactly one other party's sends (receives→sends). This
  prevents phantom transfers where a team "receives" a player nobody sent.

- **Cash conservation (Rule 7)** — the sum of cash sent across all parties must
  equal the sum of cash received. Cash cannot be created or destroyed in a
  trade. This is the monetary analog of player non-duplication.

**Precedent:** structural-invariant validations that prevent logically impossible
trade states are acceptable. New business rules (e.g. trade windows, veto
mechanics, league-approval thresholds) are not.

### Salary matching — Reading B (clarified)

Section 3.4 Rule 1 states that incoming salary must be within 125% of outgoing
salary, or the team must have cap room to absorb the difference. "Reading B"
interprets "absorb the difference" as: cap room must cover the **full positive
difference** (incoming − outgoing), not merely the excess above the 125%
threshold. This is the stricter interpretation and is now the implemented
behavior.

## Phase 3

### Proposal broadcast 1-round delay (spec Section 3.5)

Proposals created in round N are **not** delivered to parties' inboxes until
round N+1 (when the round advances). Consent (calling `execute_trade`) is
only permitted in the consent window (round N+1); attempts in the same round
as the proposal are rejected with an error. If not all parties consent by the
end of round N+1, the proposal expires.

**Implementation:** `tool_propose_trade` queues the broadcast message in
`_pending_broadcasts`. The `_advance_round` method delivers pending broadcasts
and expires proposals whose consent window has passed.

### Goal evaluator rules (spec Section 7.4)

`tool_check_my_progress` returns `{goal_met: bool, details: str,
bonuses_eligible: [...]}` with the goal evaluated against current environment
state. Interpretation decisions for each team:

- **Apex City Aces** — "Acquire" means a player rated >= 88 is on the current
  roster but was NOT on the initial roster (i.e., came via trade).
- **Harlow Vipers** — "Stars" are the top 2 tradeable players by talent_rating
  on Harlow's initial roster. "Package" requires both a player rated >= 78
  acquired AND a 1st-round pick acquired.
- **Eastgate Titans** — Qualifying player must be SF or PF, rated 76-84, have
  >= 2 years remaining, and AAV <= $20M. Must be acquired (not originally on
  roster).
- **Ironwood Foxes** — Must acquire (not originally on roster) at least 2
  players whose combined defense_rating >= 17.
- **Cascade Wolves** — Must acquire >= 2 first-round picks (not in initial
  picks) AND shed >= $25M in total_contract (sum of sent players'
  total_contract minus sum of received players' total_contract).
- **Granite Bay Bulls** — "Shed AAV" = sum AAV of sent players minus sum AAV
  of received players (not total_contract). Cap room = $140M - current payroll.
  Net rating loss = sum talent_rating of sent - sum talent_rating of received.

**Precedent:** goal evaluation is a Phase 3 deliverable (Phase 4's oracle
depends on it). The evaluator does not modify environment state.
