//! F2P prayer tables (port of `pure_solver.prayers`).

use anyhow::{anyhow, Result};
use serde_json::Value;

use crate::mechanics::{fraction_value, int_value, MechanicRegistry};
use crate::rational::Rational;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PrayerBoost {
    pub prayer_id: String,
    pub level: i64,
    pub multiplier: Rational,
}

const OFFENSIVE_TABLES: [&str; 4] = [
    "prayer.f2p.attack_boosts",
    "prayer.f2p.strength_boosts",
    "prayer.f2p.ranged_boosts",
    "prayer.f2p.extra_ranged_boosts",
];

fn boost_table(mechanics: &MechanicRegistry, mechanic_id: &str) -> Result<Vec<PrayerBoost>> {
    let raw = mechanics.table(mechanic_id)?;
    let mut boosts = Vec::with_capacity(raw.len());
    for (prayer_id, entry) in raw {
        let entry = entry.as_object().ok_or_else(|| anyhow!("{mechanic_id} has an invalid prayer entry"))?;
        boosts.push(PrayerBoost {
            prayer_id: prayer_id.clone(),
            level: int_value(entry.get("level").unwrap_or(&Value::Null), &format!("{mechanic_id}.{prayer_id}.level"))?,
            multiplier: fraction_value(
                entry.get("multiplier").unwrap_or(&Value::Null),
                &format!("{mechanic_id}.{prayer_id}.multiplier"),
            )?,
        });
    }
    boosts.sort_by(|a, b| (a.level, &a.prayer_id).cmp(&(b.level, &b.prayer_id)));
    Ok(boosts)
}

fn combined_boost_table(mechanics: &MechanicRegistry, ids: &[&str]) -> Result<Vec<PrayerBoost>> {
    let mut boosts = Vec::new();
    for id in ids {
        boosts.extend(boost_table(mechanics, id)?);
    }
    boosts.sort_by(|a, b| (a.level, &a.prayer_id).cmp(&(b.level, &b.prayer_id)));
    Ok(boosts)
}

/// Prayer levels at which some F2P prayer of interest unlocks, always including level 1.
pub fn relevant_prayer_levels(mechanics: &MechanicRegistry, include_protection: bool, include_magic: bool) -> Result<Vec<i64>> {
    let mut levels = std::collections::BTreeSet::from([1i64]);
    for id in OFFENSIVE_TABLES {
        levels.extend(boost_table(mechanics, id)?.into_iter().map(|b| b.level));
    }
    if include_magic {
        levels.extend(boost_table(mechanics, "prayer.f2p.magic_boosts")?.into_iter().map(|b| b.level));
    }
    if include_protection {
        for (style, entry) in mechanics.table("prayer.pvp_protection")? {
            let entry = entry.as_object().ok_or_else(|| anyhow!("prayer.pvp_protection has an invalid style entry"))?;
            levels.insert(int_value(
                entry.get("level").unwrap_or(&Value::Null),
                &format!("prayer.pvp_protection.{style}.level"),
            )?);
        }
    }
    Ok(levels.into_iter().collect())
}

fn best_at_or_below(boosts: Vec<PrayerBoost>, prayer_level: i64) -> Option<PrayerBoost> {
    boosts.into_iter().rfind(|b| b.level <= prayer_level)
}

/// Best (attack, strength) melee prayer boosts available at `prayer_level`.
pub fn best_melee_prayers(mechanics: &MechanicRegistry, prayer_level: i64) -> Result<(Option<PrayerBoost>, Option<PrayerBoost>)> {
    Ok((
        best_at_or_below(boost_table(mechanics, "prayer.f2p.attack_boosts")?, prayer_level),
        best_at_or_below(boost_table(mechanics, "prayer.f2p.strength_boosts")?, prayer_level),
    ))
}

pub fn best_ranged_prayer(mechanics: &MechanicRegistry, prayer_level: i64) -> Result<Option<PrayerBoost>> {
    Ok(best_at_or_below(
        combined_boost_table(mechanics, &["prayer.f2p.ranged_boosts", "prayer.f2p.extra_ranged_boosts"])?,
        prayer_level,
    ))
}

pub fn best_magic_prayer(mechanics: &MechanicRegistry, prayer_level: i64) -> Result<Option<PrayerBoost>> {
    Ok(best_at_or_below(boost_table(mechanics, "prayer.f2p.magic_boosts")?, prayer_level))
}

pub fn multiplier_of(boost: &Option<PrayerBoost>) -> Rational {
    boost.as_ref().map(|b| b.multiplier.clone()).unwrap_or_else(Rational::one)
}
