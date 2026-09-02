//! Experience table and standard-F2P Hitpoints reachability
//! (port of the parts of `pure_solver.experience` used by the ranking path).
//!
//! Ordinary F2P combat training grants 4 XP per damage to the trained skill and
//! 4/3 XP per damage to Hitpoints; Magic is excluded because it trains without HP.

use anyhow::Result;

use crate::mechanics::MechanicRegistry;
use crate::rational::Rational;

pub const MAX_LEVEL: i64 = 99;
pub const STARTING_HITPOINTS: i64 = 10;
const MAX_XP: i64 = 200_000_000;

/// XP required for `level`, following the wiki formula floor-by-floor like the Python reference.
pub fn xp_for_level(level: i64, mechanics: &MechanicRegistry) -> Result<i64> {
    mechanics.require("experience.level_threshold")?;
    anyhow::ensure!((1..=MAX_LEVEL).contains(&level), "XP level must be between 1 and 99");
    Ok(xp_table()[level as usize])
}

fn xp_table() -> &'static [i64; 100] {
    static TABLE: std::sync::OnceLock<[i64; 100]> = std::sync::OnceLock::new();
    TABLE.get_or_init(|| {
        let mut table = [0i64; 100];
        let mut points = 0i64;
        for level in 1..=MAX_LEVEL {
            table[level as usize] = points.div_euclid(4);
            let current = level as f64;
            points += (current + 300.0 * 2f64.powf(current / 7.0)).floor() as i64;
        }
        table
    })
}

pub fn level_for_xp(xp: Rational, mechanics: &MechanicRegistry) -> Result<i64> {
    mechanics.require("experience.level_threshold")?;
    anyhow::ensure!(!xp.is_negative(), "XP cannot be negative");
    for level in (1..=MAX_LEVEL).rev() {
        if xp >= Rational::int(xp_table()[level as usize] as i128) {
            return Ok(level);
        }
    }
    Ok(1)
}

fn ceil_div(numerator: i64, denominator: i64) -> i64 {
    -((-numerator).div_euclid(denominator))
}

fn damage_range_for_level(level: i64, mechanics: &MechanicRegistry) -> Result<(i64, i64)> {
    let minimum_xp = xp_for_level(level, mechanics)?;
    let maximum_xp = if level < MAX_LEVEL { xp_for_level(level + 1, mechanics)? - 1 } else { MAX_XP };
    Ok((ceil_div(minimum_xp, 4), maximum_xp.div_euclid(4)))
}

/// Total damage interval implied by Attack/Strength/Ranged trained through normal combat.
pub fn standard_f2p_damage_range(attack: i64, strength: i64, ranged: i64, mechanics: &MechanicRegistry) -> Result<(i64, i64)> {
    standard_f2p_damage_range_with_defence(attack, strength, ranged, DEFENCE_UNTRAINED, mechanics)
}

/// A pure that never trained Defence sits at exactly 0 Defence XP, so level 1 adds no damage.
pub const DEFENCE_UNTRAINED: i64 = 1;

/// Same, with Defence trained on the defensive style (4 XP per damage, like Attack/Strength).
pub fn standard_f2p_damage_range_with_defence(attack: i64, strength: i64, ranged: i64, defence: i64, mechanics: &MechanicRegistry) -> Result<(i64, i64)> {
    let mut ranges = vec![
        damage_range_for_level(attack, mechanics)?,
        damage_range_for_level(strength, mechanics)?,
        damage_range_for_level(ranged, mechanics)?,
    ];
    if defence > DEFENCE_UNTRAINED {
        ranges.push(damage_range_for_level(defence, mechanics)?);
    }
    Ok((ranges.iter().map(|r| r.0).sum(), ranges.iter().map(|r| r.1).sum()))
}

/// Whether the damage interval for these offensive levels overlaps the HP level's XP interval.
pub fn standard_f2p_hitpoints_achievable_with_defence(
    attack: i64,
    strength: i64,
    ranged: i64,
    defence: i64,
    hitpoints: i64,
    mechanics: &MechanicRegistry,
) -> Result<bool> {
    if hitpoints < STARTING_HITPOINTS {
        return Ok(false);
    }
    let (damage_min, damage_max) = standard_f2p_damage_range_with_defence(attack, strength, ranged, defence, mechanics)?;
    let starting_xp = xp_for_level(STARTING_HITPOINTS, mechanics)?;
    let hp_min = xp_for_level(hitpoints, mechanics)?;
    let hp_max = if hitpoints < MAX_LEVEL {
        xp_for_level(hitpoints + 1, mechanics)? - 1
    } else {
        MAX_XP
    };
    let hp_damage_min = ceil_div(3 * (hp_min - starting_xp), 4).max(0);
    let hp_damage_max = (3 * (hp_max - starting_xp)).div_euclid(4).max(0);
    Ok(damage_min.max(hp_damage_min) <= damage_max.min(hp_damage_max))
}

/// HP levels (within 10..=99) reachable by ordinary combat training of these offensive levels.
pub fn standard_f2p_hitpoints_levels_with_defence(attack: i64, strength: i64, ranged: i64, defence: i64, mechanics: &MechanicRegistry) -> Result<Vec<i64>> {
    let (damage_min, damage_max) = standard_f2p_damage_range_with_defence(attack, strength, ranged, defence, mechanics)?;
    let starting_xp = Rational::int(xp_for_level(STARTING_HITPOINTS, mechanics)? as i128);
    let lowest = level_for_xp(&starting_xp + Rational::new(4 * damage_min as i128, 3), mechanics)?;
    let highest = level_for_xp(&starting_xp + Rational::new(4 * damage_max as i128, 3), mechanics)?;
    let mut levels = Vec::new();
    for hitpoints in lowest.max(STARTING_HITPOINTS)..=highest.min(MAX_LEVEL) {
        if standard_f2p_hitpoints_achievable_with_defence(attack, strength, ranged, defence, hitpoints, mechanics)? {
            levels.push(hitpoints);
        }
    }
    Ok(levels)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xp_table_has_the_well_known_anchors() {
        let table = xp_table();
        assert_eq!(table[1], 0);
        assert_eq!(table[2], 83);
        assert_eq!(table[10], 1_154);
        assert_eq!(table[50], 101_333);
        assert_eq!(table[99], 13_034_431);
    }

    #[test]
    fn ceil_div_rounds_toward_positive_infinity() {
        assert_eq!(ceil_div(7, 4), 2);
        assert_eq!(ceil_div(8, 4), 2);
        assert_eq!(ceil_div(-7, 4), -1);
    }
    #[test]
    fn trained_defence_raises_the_hitpoints_floor() {
        let mechanics = crate::mechanics::MechanicRegistry::load(std::path::Path::new(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../rulesets/osrs-f2p-v1/mechanics.json"
        )))
        .unwrap();
        let pure = standard_f2p_damage_range_with_defence(40, 50, 40, 1, &mechanics).unwrap();
        let untrained = standard_f2p_damage_range(40, 50, 40, &mechanics).unwrap();
        assert_eq!(pure, untrained, "Defence 1 means no Defence XP, matching the original pure model");
        let tank = standard_f2p_damage_range_with_defence(40, 50, 40, 40, &mechanics).unwrap();
        assert!(tank.0 > pure.0 && tank.1 > pure.1, "training Defence deals damage that feeds Hitpoints");
        let floor_pure = standard_f2p_hitpoints_levels_with_defence(40, 50, 40, 1, &mechanics).unwrap()[0];
        let floor_tank = standard_f2p_hitpoints_levels_with_defence(40, 50, 40, 40, &mechanics).unwrap()[0];
        assert!(floor_tank > floor_pure);
    }
}
