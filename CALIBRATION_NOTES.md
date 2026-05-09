# Calibration Notes — Phase 4 Goal Calibration

Pre-registered analysis record for `trade_deadline_bench` v1 goal calibration.

## Methodology

- **Oracle**: Pure deterministic constraint-satisfaction search (no LLM, no
  randomness beyond tie-breaking). Greedy with bounded proposals per round
  (N=10). All 6 oracles have full information of their own goals.
- **Procedure**: 50 seeds (1-50), one full 8-round game per seed, all 6 team
  positions evaluated simultaneously.
- **Target**: All 6 achievement rates in [0.70, 0.85]; cross-goal spread <= 10pp.

## Iteration History

### Iteration 0 (original spec thresholds)

| Team | Threshold | Rate |
|------|-----------|------|
| Apex City Aces | >= 88 | ~4% |
| Harlow Vipers | >= 78 + 1st pick | ~8% |
| Eastgate Titans | 76-84/SF-PF/2yr/$20M | ~6% |
| Ironwood Foxes | defense sum >= 17 | ~10% |
| Cascade Wolves | >= $25M shed | ~2% |
| Granite Bay Bulls | cap >= $12M/shed >= $20M | ~4% |

**Result**: All goals far below target. Thresholds wildly misaligned with
generated player distributions.

### Iteration 1 (first calibration pass)

Lowered all thresholds based on player distribution analysis across 20 seeds:

| Team | Threshold | Rate |
|------|-----------|------|
| Apex City Aces | >= 75 | ~36% |
| Harlow Vipers | >= 68 + 1st pick | ~42% |
| Eastgate Titans | 57-71/SF-PF/2yr/$15M | ~48% |
| Ironwood Foxes | defense sum >= 16 | ~44% |
| Cascade Wolves | >= $15M shed | ~52% |
| Granite Bay Bulls | cap >= $12M/shed >= $10M | ~30% |

**Result**: Closer but still below target for most goals.

### Iteration 2

Further lowered thresholds:

| Team | Threshold | Rate |
|------|-----------|------|
| Apex City Aces | >= 60 | 94% |
| Cascade Wolves | >= $15M shed | 60% |
| Eastgate Titans | 57-71/$13M | 60% |
| Granite Bay Bulls | cap >= $8M/shed >= $4M | 56% |
| Harlow Vipers | >= 58 + 1st pick | 100% |
| Ironwood Foxes | defense sum >= 15 | 80% |

**Result**: Severe imbalance — Apex/Harlow too easy, Cascade/Eastgate/GB too hard.

### Iteration 3

Interpolated adjustments to balance:

| Team | Threshold | Rate |
|------|-----------|------|
| Apex City Aces | >= 62 | 74% |
| Cascade Wolves | >= $17M shed | 76% |
| Eastgate Titans | 57-71/$13M | 80% |
| Granite Bay Bulls | cap >= $8M/shed >= $4M | 64% |
| Harlow Vipers | >= 58 + 1st pick | 96% |
| Ironwood Foxes | defense sum >= 15 | 84% |

**Result**: 4/6 in range, but Harlow too high (96%) and GB too low (64%).

### Iteration 4 (final)

Key insight: player pool competition. When multiple teams target the same rating
range, they compete for limited supply and both fail. Solution: use differentiated
thresholds (Apex >= 60, Harlow >= 59) and adjust GB cap room ($5M).

| Team | Threshold | Rate |
|------|-----------|------|
| Apex City Aces | >= 60 | **80%** |
| Cascade Wolves | >= $19M shed | **78%** |
| Eastgate Titans | 57-71/SF-PF/2yr/$13M | **80%** |
| Granite Bay Bulls | cap >= $5M/shed >= $4M/loss <= 15 | **82%** |
| Harlow Vipers | >= 59 + 1st pick | **80%** |
| Ironwood Foxes | defense sum >= 15 | **82%** |

**Result**: All 6 in [0.70, 0.85]. Cross-goal spread = 4pp. PASS.

## Final Calibrated Thresholds

| Team | Goal | Threshold |
|------|------|-----------|
| Apex City Aces | Acquire one elite player | talent_rating >= 60 |
| Harlow Vipers | Trade star for package | player >= 59 + 1st-round pick |
| Eastgate Titans | Acquire role player | rated 57-71, SF/PF, 2+ yrs, <= $13M AAV |
| Ironwood Foxes | Acquire defensive players | 2 players with summed defense >= 15 |
| Cascade Wolves | Rebuild (picks + salary shed) | >= 2 first-round picks + shed >= $19M |
| Granite Bay Bulls | Create cap flexibility | cap room >= $5M, shed >= $4M AAV, rating loss <= 15 |

## Final Achievement Rates (50 seeds)

| Team | Achieved | Total | Rate |
|------|----------|-------|------|
| Apex City Aces | 40 | 50 | 80% |
| Cascade Wolves | 39 | 50 | 78% |
| Eastgate Titans | 40 | 50 | 80% |
| Granite Bay Bulls | 41 | 50 | 82% |
| Harlow Vipers | 40 | 50 | 80% |
| Ironwood Foxes | 41 | 50 | 82% |

- Min rate: 78% (Cascade Wolves)
- Max rate: 82% (Granite Bay Bulls, Ironwood Foxes)
- Cross-goal spread: 4pp
- All rates in [0.70, 0.85]: YES
- Cross-balance (spread <= 10pp): YES

## Locked Hash

SHA-256 of `trade_deadline_bench/teams_config.yaml`:
```
6dcb54daeb39b228d1c6af99b578ab964500c492ddcb035124e17a81475c4cdc
```

Any future modification to goal specifications constitutes a new benchmark version.

## Key Findings

1. **Player pool competition**: When two teams target similar rating thresholds
   (e.g., both want >= 62), they compete for the same limited supply of tradeable
   players and both fail. Solution: differentiate thresholds by 1-2 points.

2. **Non-linear sensitivity**: Small threshold changes can cause large rate swings
   (e.g., Harlow >= 59 gives 80%, >= 60 gives 64%) due to the discrete nature of
   player ratings and the compounding effect of market competition.

3. **Cross-goal coupling**: All 6 teams trade in the same market simultaneously.
   Making one team's goal harder (forcing more aggressive trading) can steal
   resources from other teams, causing cascading effects.

4. **Calibration convergence**: Despite the coupling effects, the system converged
   to balanced rates within 4 iterations by using differentiated thresholds that
   minimize direct competition between goals.
