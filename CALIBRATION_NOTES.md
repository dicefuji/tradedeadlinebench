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
- Refactored goal_evaluator.py and oracle_agent.py to read ALL thresholds from
  teams_config.yaml at construction time (YAML-as-source-of-truth)
- Changed elite player distribution from round-robin to random clustering
- Restored thresholds toward original spec values (see final thresholds below)
- Re-calibrated from scratch with the structural fixes in place

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

### Iteration 5 (Path C — goal-aware locks, restored thresholds)

After fixing the franchise-lock rule and YAML-as-source-of-truth:

**New franchise-lock slots (goal-aware):**
- Apex: lock slot 0 only (1 identity player), leave stars tradeable
- Harlow: lock slots 2-8 (7 mid-tier), do NOT lock the two stars
- Eastgate: lock slot 0 only (1 franchise player)
- Ironwood: lock slot 0 only (1 identity player)
- Cascade: lock slot 0 only (1 young cornerstone)
- Granite Bay: lock slot 0 only (1 identity player)

**Tradeable elite counts (mean across 50 seeds):**
- Tradeable players >= 88: ~1.8-2.0 league-wide
- Tradeable players >= 80: ~2.0 league-wide

### Iteration 6 (Path C — calibrated thresholds, final)

Tuned talent thresholds to account for actual Beta(2,5) distribution:
- Apex: 86 -> 78 (accounts for ~1.8 tradeable elite per seed)
- Harlow: 76 -> 73 (accounts for tradeable star availability)
- Eastgate: [76-84] -> [67-78] SF/PF (feasible range for role players)
- Cascade: $25M -> $22M (feasible with current veteran salaries)
- Granite Bay: cap >= $11M (tightened from $10M for balance)
- Ironwood: defense sum >= 17 (unchanged, already feasible)

| Team | Threshold | Rate |
|------|-----------|------|
| Apex City Aces | >= 78 | **80%** |
| Harlow Vipers | >= 73 + 1st pick | **74%** |
| Eastgate Titans | 67-78/SF-PF | **80%** |
| Ironwood Foxes | defense sum >= 17 | **74%** |
| Cascade Wolves | >= $22M shed | **76%** |
| Granite Bay Bulls | cap >= $11M/shed >= $18M/loss <= 10 | **76%** |

**Result**: All 6 in [0.70, 0.85]. Cross-goal spread = 6pp. PASS.

## Final Calibrated Thresholds

| Team | Goal | Threshold |
|------|------|-----------|
| Apex City Aces | Acquire one elite player | talent_rating >= 78 |
| Harlow Vipers | Trade star for package | player >= 73 + 1st-round pick |
| Eastgate Titans | Acquire role player | rated 67-78, SF/PF, 2+ yrs, <= $13M AAV |
| Ironwood Foxes | Acquire defensive players | 2 players with summed defense >= 17 |
| Cascade Wolves | Rebuild (picks + salary shed) | >= 2 first-round picks + shed >= $22M |
| Granite Bay Bulls | Create cap flexibility | cap room >= $11M, shed >= $18M AAV, rating loss <= 10 |

## Final Achievement Rates (50 seeds)

| Team | Achieved | Total | Rate |
|------|----------|-------|------|
| Apex City Aces | 40 | 50 | 80% |
| Harlow Vipers | 37 | 50 | 74% |
| Eastgate Titans | 40 | 50 | 80% |
| Ironwood Foxes | 37 | 50 | 74% |
| Cascade Wolves | 38 | 50 | 76% |
| Granite Bay Bulls | 38 | 50 | 76% |

- Min rate: 74% (Harlow Vipers, Ironwood Foxes)
- Max rate: 80% (Apex City Aces, Eastgate Titans)
- Cross-goal spread: 6pp
- All rates in [0.70, 0.85]: YES
- Cross-balance (spread <= 10pp): YES

## Locked Hash

SHA-256 of `trade_deadline_bench/teams_config.yaml`:
```
5b72788efcc44c083965a077aea6431d07ef24f9e5a0c13a1b35985af3ba56f7
```

Any future modification to goal specifications constitutes a new benchmark version.

## Key Findings

1. **Franchise-lock rule is the critical variable**: The generic "lock top-N"
   rule locked 82% of elite players, making talent-acquisition goals infeasible.
   Goal-aware locking (Path C) restores liquidity while preserving team identity.

2. **YAML-as-source-of-truth is essential**: Without it, the SHA-256 hash is
   decorative. After the refactor, modifying any threshold in YAML produces a
   measurable change in calibration rates (verified by regression test).

3. **Beta(2,5) produces ~5 elite (>=88) players league-wide**: This matches spec
   Section 5.1 (~6 players). With goal-aware locks, ~1.8-2.0 are tradeable,
   which is sufficient for 70-85% feasibility at threshold >= 78.

4. **Cross-goal coupling**: All 6 teams trade in the same market simultaneously.
   Salary-based goals (Cascade, GB) are less coupled than talent-acquisition
   goals (Apex, Harlow, Eastgate) because salary supply is more abundant.

5. **Random elite clustering**: Distributing elite players randomly (instead of
   round-robin) creates natural variance in availability, producing realistic
   [0.70, 0.85] rates rather than binary 0/100%.
