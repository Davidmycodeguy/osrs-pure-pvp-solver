# F2P range-to-melee timing experiment

This experiment supplies the unresolved timing evidence for the first production combat slice. It does not use wall-clock duration as a substitute for logical ticks.

## Fixed conditions

- Current dated OSRS game version and world number recorded.
- One attacker and one stationary 1×1 player target in F2P single combat.
- Maple shortbow on rapid with adamant arrows, then rune 2h sword.
- Separate sample sets at each tested cardinal/diagonal distance.
- No movement unless the distance-specific test explicitly requires it.
- No latency correction applied to the logical event observations.

## Capture requirements

Record RuneLite `GameTick`, menu input, projectile, animation, equipment-container, and hitsplat events. Histogram may record click/ping timing, but its estimated processing constants are metadata rather than server truth. Every sample must retain a video or raw-log reference.

For each repetition record:

```text
sample_id
distance_tiles
ranged_attack_tick
ranged_impact_tick
weapon_switch_tick
melee_attack_tick
melee_impact_tick
evidence_ref
```

At least 20 agreeing repetitions are required at each distance before the importer emits an experimental claim. Any disagreement produces `MechanicConflictError`; it is investigated rather than averaged away.

The output remains labelled `experimental`. Promotion into the production ruleset requires a dated review decision and golden stack-timing tests.

