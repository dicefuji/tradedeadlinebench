# Calibration Notes — Phase 4 Goal Calibration

Pre-registered analysis record for `trade_deadline_bench` v1 goal calibration.

## Methodology

- **Oracle**: Pure deterministic constraint-satisfaction search (no LLM, no
  randomness beyond tie-breaking). Greedy with bounded proposals per round
  (N=10). All 6 oracles have full information of their own goals.
- **Procedure**: 50 seeds (1-50), one full 8-round game per seed, all 6 team
  positions evaluated simultaneously.
- **Target**: All 6 achievement rates in [0.70, 0.85]; cross-goal spread <= 10pp.

## Path C Resolution

The original calibration (Iterations 0-4 below) suffered from three structural
issues identified during review:

1. **YAML was not source of truth** — thresholds were hardcoded in
   `goal_evaluator.py` and `oracle_agent.py`. The YAML hash was decorative.
2. **Franchise-lock rule was generic** — "lock top-N by talent" locked 82% of
   elite players, making acquisition goals infeasible at original thresholds.
3. **Granite Bay numbers were inconsistent** — thresholds appeared in multiple
   places with different values.

**Resolution (Path C):**
- Replaced generic "lock top-N" with goal-aware franchise-lock slots per team
- Added `lock_rule` field to TeamConfig: `youngest` (Cascade) and `lowest_aav`
  (Granite Bay) implement goal-specific locking strategies
- Refactored goal_evaluator.py and oracle_agent.py to read ALL thresholds from
  teams_config.yaml at construction time (YAML-as-source-of-truth)
- Changed elite player distribution from round-robin to random clustering
- Calibrated thresholds iteratively against restoration targets and cross-goal
  balance constraints

## Iteration History

### Iteration 0 (original spec thresholds, pre-Path-C)

| Team | Threshold | Rate |
|------|-----------|------|
| Apex City Aces | >= 88 | ~4% |
| Harlow Vipers | >= 78 + 1st pick | ~8% |
| Eastgate Titans | 76-84/SF-PF/2yr/$20M | ~6% |
| Ironwood Foxes | defense sum >= 17 | ~10% |
| Cascade Wolves | >= $25M shed | ~2% |
| Granite Bay Bulls | cap >= $12M/shed >= $20M | ~4% |

**Result**: All goals far below target. Root cause: generic franchise-lock rule
locked 82% of elite players, leaving ~0.9 tradeable elite league-wide.

### Iterations 1-4 (pre-Path-C, generic lock rule)

These iterations lowered thresholds dramatically to compensate for the broken
lock rule. Final pre-Path-C thresholds (Apex >= 60, Harlow >= 59, etc.) achieved
[0.78, 0.82] rates but:
- Thresholds were far from original spec intent
- YAML was decorative (hash didn't bind behavior)
- Lock rule conflicted with goal designs

### Iteration 5 (Path C — goal-aware locks, YAML-as-source-of-truth)

After fixing the franchise-lock rule and YAML-as-source-of-truth:

**New franchise-lock slots (goal-aware):**
- Apex: lock slot 0 only (1 identity player), leave stars tradeable
- Harlow: lock slots 2-8 (7 mid-tier), do NOT lock the two stars
- Eastgate: lock slot 0 only (1 franchise player)
- Ironwood: lock slot 0 only (1 identity player)
- Cascade: lock slot 0, `lock_rule: youngest` (lock youngest among top-3 by
  talent — young cornerstone for rebuild)
- Granite Bay: lock slot 0, `lock_rule: lowest_aav` (lock lowest-AAV player,
  leave high-AAV veterans tradeable for cap maneuver goal)

**Tradeable elite counts (mean across 50 seeds):**
- Tradeable players >= 88: ~2.8 league-wide (target: 3-4)
- Min: 1, Max: 5

### Iteration 6 (restoration threshold investigation)

Tested restoration thresholds (Apex >=86, Eastgate [76-84], Cascade $25M,
GB cap$12M/shed$20M/loss<=8) with the corrected lock rules:

| Team | Threshold | Rate |
|------|-----------|------|
| Apex City Aces | >= 86 | 92% (OUT — too easy) |
| Harlow Vipers | >= 73 + 1st pick | 84% (OK) |
| Eastgate Titans | [76-84] SF/PF | 10% (OUT — infeasible) |
| Ironwood Foxes | defense sum >= 17 | 70% (OK) |
| Cascade Wolves | >= $25M shed | 60% (OUT — too hard) |
| Granite Bay Bulls | cap$12M/shed$20M/loss<=8 | 88% (OUT — slightly over) |

**Root causes for restoration threshold infeasibility:**

1. **Eastgate [76-84] SF/PF**: Beta(2,5) non-elite distribution produces almost
   no players in [76-84]. Mean tradeable candidates meeting all criteria
   (SF/PF, [76-84], >=2yr, <=$20M AAV): **0.1 per seed** (45/50 seeds have
   ZERO candidates). This range is structurally infeasible.

2. **Cascade $25M shed**: Cascade's rate is flat at 60% regardless of threshold
   ($18M-$25M all give 60%). In 40% of seeds, the oracle ends up GAINING salary
   (mean shed = -$9.7M) because other teams' oracles send expensive players to
   Cascade in exchange for picks. Cascade's cooperative consent logic (accepting
   trades with 1st-round picks even when salary-increasing) is essential for
   cross-goal balance — tightening it breaks Granite Bay's ability to shed AAV.

3. **Cross-goal coupling**: Cascade acts as the league's "salary absorber" — it
   accepts expensive players from other teams (especially Granite Bay) in exchange
   for picks. This is necessary for GB's goal but hurts Cascade's own salary shed.
   Fixing Cascade's consent logic to reject salary-gaining trades improved Cascade
   to 100% but dropped GB from 88% to 34%.

### Iteration 7 (final calibration — v1.0 thresholds)

Systematic threshold sweep to find balanced values:

| Team | Threshold | Rate |
|------|-----------|------|
| Apex City Aces | >= 90 | **80%** |
| Harlow Vipers | >= 73 + 1st pick | **80%** |
| Eastgate Titans | [68-82] SF/PF | **72%** |
| Ironwood Foxes | defense sum >= 17 | **74%** |
| Cascade Wolves | >= $22M shed | **72%** |
| Granite Bay Bulls | cap$12M/shed$20M/loss<=6 | **76%** |

**Result**: All 6 in [0.70, 0.85]. Cross-goal spread = 8pp. PASS.

## Final Calibrated Thresholds (v1.0)

| Team | Goal | Threshold |
|------|------|-----------|
| Apex City Aces | Acquire one elite player | talent_rating >= 90 |
| Harlow Vipers | Trade star for package | player >= 73 + 1st-round pick |
| Eastgate Titans | Acquire role player | rated 68-82, SF/PF, 2+ yrs, <= $20M AAV |
| Ironwood Foxes | Acquire defensive players | 2 players with summed defense >= 17 |
| Cascade Wolves | Rebuild (picks + salary shed) | >= 2 first-round picks + shed >= $22M |
| Granite Bay Bulls | Create cap flexibility | cap room >= $12M, shed >= $20M AAV, rating loss <= 6 |

## Final Achievement Rates (50 seeds)

| Team | Achieved | Total | Rate |
|------|----------|-------|------|
| Apex City Aces | 40 | 50 | 80% |
| Harlow Vipers | 40 | 50 | 80% |
| Eastgate Titans | 36 | 50 | 72% |
| Ironwood Foxes | 37 | 50 | 74% |
| Cascade Wolves | 36 | 50 | 72% |
| Granite Bay Bulls | 38 | 50 | 76% |

- Min rate: 72% (Eastgate Titans, Cascade Wolves)
- Max rate: 80% (Apex City Aces, Harlow Vipers)
- Cross-goal spread: 8pp
- All rates in [0.70, 0.85]: YES
- Cross-balance (spread <= 10pp): YES

## Locked Hash

SHA-256 of `trade_deadline_bench/teams_config.yaml`:
```
3e336db00f11306ddc125233b8f7d408c6f7b509ae2f8d8891ba2819eac2433e
```

Any future modification to goal specifications constitutes a new benchmark version.

## Key Findings

1. **Franchise-lock rule is the critical variable**: The generic "lock top-N"
   rule locked 82% of elite players, making talent-acquisition goals infeasible.
   Goal-aware locking (Path C) with `lock_rule` strategies (`youngest` for
   Cascade, `lowest_aav` for Granite Bay) restores liquidity while preserving
   team identity.

2. **YAML-as-source-of-truth is essential**: Without it, the SHA-256 hash is
   decorative. After the refactor, modifying any threshold in YAML produces a
   measurable change in calibration rates (verified by regression test).

3. **Beta(2,5) produces ~5 elite (>=88) players league-wide**: This matches spec
   Section 5.1 (~6 players). With goal-aware locks, ~2.8 are tradeable,
   sufficient for 70-85% feasibility at threshold >= 90.

4. **Cross-goal coupling**: All 6 teams trade in the same market simultaneously.
   Cascade acts as the league's "salary absorber" — essential for Granite Bay's
   cap maneuver goal but limiting Cascade's own salary shed. This coupling
   prevents restoration thresholds from being simultaneously feasible.

5. **Restoration thresholds are infeasible**: Eastgate [76-84] has zero
   candidates in 90% of seeds. Cascade's salary shed is structurally capped by
   cross-goal dynamics. The v1.0 thresholds represent the closest achievable
   values to original spec while maintaining [0.70, 0.85] balance.

6. **Random elite clustering**: Distributing elite players randomly (instead of
   round-robin) creates natural variance in availability, producing realistic
   [0.70, 0.85] rates rather than binary 0/100%.
