# Remaining timing-suite protocol

This protocol supplies the five production gates that are not fully documented: tick phase order, priority-dependent simultaneous KO, melee impact timing, ranged projectile timing, and magic projectile timing.

Record at least 20 agreeing repetitions for every case and retain a raw RuneLite log plus video reference. Test both player-priority assignments for simultaneous lethal hits. Test every distance used by a production policy separately for melee, rapid shortbow projectiles, and each enabled magic projectile family.

The JSON input to `python -m pure_solver validate-timing-experiment` contains:

- `experiment_id`, `game_version`, and `evidence_manifest`;
- `tick_pipeline_samples`, each an ordered list of observed phase labels;
- `same_tick_ko_samples` with `priority`, `outcome`, and `evidence_ref`;
- `impact_samples` with `kind`, `distance_tiles`, `attack_tick`, `impact_tick`, and `evidence_ref`.

Any disagreement raises `MechanicConflictError`; insufficient repetition raises `DataUnavailableError`. Successful validation produces **experimental** mechanic documents. A separate dated review must change their status to verified before the production ruleset accepts them.

