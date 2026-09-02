//! F2P combat spells as extra attack options for Stage 5 kits.
//!
//! Spells come from the verified `magic.f2p.spells` table (base max hit,
//! 5-tick cast, level requirement, rune cost).  They are cast bare-handed
//! because the item catalog holds no staves, so every rune type costs one
//! inventory slot.  The opponent's magic defence roll uses the standard
//! 70% Magic / 30% Defence rule, which has no verified mechanic id in the
//! ruleset; it is reported as `magic.defence_roll_unverified`.

use std::collections::BTreeMap;

use anyhow::{anyhow, Context, Result};

use super::SourceColumns;
use crate::formula::Variables;
use crate::mechanics::MechanicRegistry;
use crate::prayers::{best_magic_prayer, multiplier_of};
use crate::ranking::{RankingCandidate, RankingStyle, DEFENCE_STATES};
use crate::rational::Rational;

pub const MAGIC_DAMAGE_TYPE: &str = "magic";
pub const SPELL_STYLE_PREFIX: &str = "spell:";
/// Maximum range of a combat spell in tiles.
pub const SPELL_RANGE: i64 = 10;
const NON_DAMAGING_SPELLS: [&str; 2] = ["bind", "snare"];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Spell {
    pub id: String,
    pub name: String,
    pub base_max_hit: i64,
    pub magic_level: i64,
    pub cooldown_ticks: i64,
    /// Distinct rune types, each one inventory slot when cast without a staff.
    pub rune_slots: i64,
}

/// The damaging F2P spells, sorted by base max hit descending then id.
pub struct SpellBook {
    pub spells: Vec<Spell>,
}

impl SpellBook {
    pub fn load(mechanics: &MechanicRegistry) -> Result<SpellBook> {
        let table = mechanics.table("magic.f2p.spells")?;
        let mut spells = Vec::new();
        for (id, entry) in table {
            let int = |key: &str| -> Result<i64> {
                entry
                    .get(key)
                    .and_then(|v| v.as_i64())
                    .ok_or_else(|| anyhow!("spell {id} has no integer {key}"))
            };
            let base_max_hit = int("base_max_hit")?;
            // Bind and Snare are holds, not damage, whatever the table's nominal max hit says.
            if base_max_hit <= 0 || NON_DAMAGING_SPELLS.contains(&id.as_str()) {
                continue;
            }
            if entry.get("status").and_then(|v| v.as_str()) != Some("verified") {
                continue;
            }
            let runes = entry
                .get("rune_cost")
                .and_then(|v| v.as_object())
                .ok_or_else(|| anyhow!("spell {id} has no rune_cost"))?;
            spells.push(Spell {
                id: id.clone(),
                name: entry.get("name").and_then(|v| v.as_str()).unwrap_or(id).to_owned(),
                base_max_hit,
                magic_level: int("magic_level")?,
                cooldown_ticks: int("attack_speed_ticks")?,
                rune_slots: runes.len() as i64,
            });
        }
        spells.sort_by(|a, b| b.base_max_hit.cmp(&a.base_max_hit).then_with(|| a.id.cmp(&b.id)));
        if spells.is_empty() {
            return Err(anyhow!("magic.f2p.spells has no damaging verified spells"));
        }
        Ok(SpellBook { spells })
    }

    /// The hardest-hitting spell this Magic level can cast.
    pub fn best_castable(&self, magic_level: i64) -> Option<&Spell> {
        self.spells.iter().find(|spell| spell.magic_level <= magic_level)
    }
}

/// A spell carried as a kit option.
#[derive(Clone, Debug)]
pub struct SpellChoice {
    pub name: String,
    pub style: RankingStyle,
    pub rune_slots: i64,
}

fn vars(pairs: Vec<(&str, Rational)>) -> Variables {
    pairs.into_iter().map(|(k, v)| (k.to_owned(), v)).collect()
}

/// Inputs a spell style depends on, read from the survivor row.
#[derive(Clone, Copy, Debug)]
pub struct CasterInputs {
    pub magic_level: i64,
    pub prayer_level: i64,
    pub magic_attack_bonus: i64,
    pub magic_damage_percent: i64,
}

impl CasterInputs {
    pub fn of(candidate: &RankingCandidate, columns: &SourceColumns) -> Result<CasterInputs> {
        Ok(CasterInputs {
            magic_level: candidate.levels[3],
            prayer_level: candidate.levels[4],
            magic_attack_bonus: candidate.magic_attack_bonus,
            magic_damage_percent: columns.int(candidate, "magic_damage")?,
        })
    }
}

/// Resolve one spell into a ranking style: `magic.effective_attack` → `magic.attack_roll`, `magic.max_hit`.
/// No boost and no style bonus (bare-handed cast); the best available F2P magic prayer is assumed on.
pub fn spell_style(mechanics: &MechanicRegistry, caster: CasterInputs, spell: &Spell) -> Result<RankingStyle> {
    let prayer = multiplier_of(&best_magic_prayer(mechanics, caster.prayer_level)?);
    let effective = mechanics.evaluate(
        "magic.effective_attack",
        &vars(vec![
            ("magic_level", Rational::from(caster.magic_level)),
            ("magic_boost", Rational::zero()),
            ("prayer_multiplier", prayer),
            ("style_bonus", Rational::zero()),
        ]),
    )?;
    let attack_roll = mechanics
        .evaluate_int(
            "magic.attack_roll",
            &vars(vec![
                ("effective_magic_attack", effective),
                ("magic_attack_bonus", Rational::from(caster.magic_attack_bonus)),
            ]),
        )
        .context("magic.attack_roll")?;
    let max_hit = mechanics
        .evaluate_int(
            "magic.max_hit",
            &vars(vec![
                ("spell_base_max_hit", Rational::from(spell.base_max_hit)),
                ("magic_damage_percent", Rational::from(caster.magic_damage_percent)),
            ]),
        )
        .context("magic.max_hit")?;
    Ok(RankingStyle {
        style_id: format!("{SPELL_STYLE_PREFIX}{}", spell.id),
        damage_type: MAGIC_DAMAGE_TYPE.to_owned(),
        attack_roll,
        max_hit,
        potted_max_hit: max_hit,
        cooldown_ticks: spell.cooldown_ticks,
        maximum_range: SPELL_RANGE,
    })
}

/// The best spell this survivor can cast, as a kit option, if any.
pub fn best_spell(mechanics: &MechanicRegistry, book: &SpellBook, candidate: &RankingCandidate, columns: &SourceColumns) -> Result<Option<SpellChoice>> {
    let caster = CasterInputs::of(candidate, columns)?;
    let Some(spell) = book.best_castable(caster.magic_level) else {
        return Ok(None);
    };
    Ok(Some(SpellChoice {
        name: spell.name.clone(),
        style: spell_style(mechanics, caster, spell)?,
        rune_slots: spell.rune_slots,
    }))
}

/// Standard magic defence: floor(0.7 × (Magic + 8)) + floor(0.3 × (Defence + 8)), times (magic defence bonus + 64).
/// Not a verified ruleset mechanic; reported as `magic.defence_roll_unverified`.
pub fn magic_defence_roll(magic_level: i64, defence_level: i64, magic_defence_bonus: i64) -> i64 {
    let magic_part = (7 * (magic_level + 8)) / 10;
    let defence_part = (3 * (defence_level + 8)) / 10;
    (magic_part + defence_part) * (magic_defence_bonus + 64)
}

pub fn candidate_magic_defence_roll(candidate: &RankingCandidate) -> i64 {
    magic_defence_roll(candidate.levels[3], candidate.levels[5], candidate.magic_defence_bonus)
}

/// Stage 3's quantile rule: element at floor((n-1) × numerator / denominator) of the sorted values.
fn quantile(sorted: &[i64], numerator: usize, denominator: usize) -> i64 {
    sorted[((sorted.len() - 1) * numerator) / denominator]
}

/// Low / medium / high representative magic defence rolls over the survivor population.
pub fn representative_magic_rolls(candidates: &[RankingCandidate]) -> Result<BTreeMap<String, i64>> {
    if candidates.is_empty() {
        return Err(anyhow!("no candidates for representative magic defence rolls"));
    }
    let mut rolls: Vec<i64> = candidates.iter().map(candidate_magic_defence_roll).collect();
    rolls.sort_unstable();
    let fractions = [("low", 1usize, 10usize), ("medium", 1, 2), ("high", 9, 10)];
    let mut out = BTreeMap::new();
    for (label, numerator, denominator) in fractions {
        debug_assert!(DEFENCE_STATES.contains(&label));
        out.insert(label.to_owned(), quantile(&rolls, numerator, denominator));
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kits::testing::{candidate, ruleset};

    #[test]
    fn spellbook_loads_damaging_verified_spells_in_max_hit_order() {
        let (mechanics, _) = ruleset();
        let book = SpellBook::load(&mechanics).unwrap();
        assert_eq!(book.spells[0].id, "fire_blast");
        assert_eq!(book.spells[0].base_max_hit, 16);
        assert!(book.spells.iter().all(|s| s.base_max_hit > 0 && s.cooldown_ticks == 5));
        assert!(book.spells.iter().all(|s| s.id != "bind" && s.id != "snare"), "non-damaging spells are skipped");
        assert_eq!(book.best_castable(40).map(|s| s.id.as_str()), Some("fire_bolt"), "41 is needed for wind blast");
        assert_eq!(book.best_castable(41).map(|s| s.id.as_str()), Some("wind_blast"));
        assert_eq!(book.best_castable(0), None);
        let fire_bolt = book.spells.iter().find(|s| s.id == "fire_bolt").unwrap();
        assert_eq!(fire_bolt.rune_slots, 3, "air, chaos, fire");
    }

    #[test]
    fn spell_style_matches_hand_computation() {
        // Magic 40, Prayer 1 (no magic prayer), magic attack bonus -17:
        // effective = floor(40 * 1) + 0 + 8 = 48; attack roll = 48 * (-17 + 64) = 2256; fire bolt max 12.
        let (mechanics, _) = ruleset();
        let book = SpellBook::load(&mechanics).unwrap();
        let caster = CasterInputs {
            magic_level: 40,
            prayer_level: 1,
            magic_attack_bonus: -17,
            magic_damage_percent: 0,
        };
        let style = spell_style(&mechanics, caster, book.best_castable(40).unwrap()).unwrap();
        assert_eq!(style.style_id, "spell:fire_bolt");
        assert_eq!(style.damage_type, "magic");
        assert_eq!(style.attack_roll, 2256);
        assert_eq!(style.max_hit, 12);
        assert_eq!(style.cooldown_ticks, 5);
    }

    #[test]
    fn magic_defence_roll_uses_seventy_thirty_split() {
        // Magic 1, Defence 1, bonus 0: floor(0.7*9)=6 + floor(0.3*9)=2 -> 8 * 64 = 512.
        assert_eq!(magic_defence_roll(1, 1, 0), 512);
        // Magic 40, Defence 1, bonus -17: floor(0.7*48)=33 + 2 -> 35 * 47 = 1645.
        assert_eq!(magic_defence_roll(40, 1, -17), 1645);
    }

    #[test]
    fn best_spell_reads_the_survivor_row() {
        let (mechanics, _) = ruleset();
        let book = SpellBook::load(&mechanics).unwrap();
        let (mut primary, columns) = candidate(&[("magic_damage", "0")]);
        primary.levels[3] = 35;
        primary.magic_attack_bonus = -17;
        let choice = best_spell(&mechanics, &book, &primary, &columns).unwrap().unwrap();
        assert_eq!(choice.name, "Fire Bolt");
        assert_eq!(choice.rune_slots, 3);
        assert_eq!(choice.style.max_hit, 12);
        primary.levels[3] = 1;
        assert_eq!(
            best_spell(&mechanics, &book, &primary, &columns).unwrap().map(|c| c.name),
            Some("Wind Strike".to_owned())
        );
    }

    #[test]
    fn representative_magic_rolls_follow_the_stage3_quantile_rule() {
        let (base, _) = candidate(&[]);
        let population: Vec<RankingCandidate> = (0..10)
            .map(|i| {
                let mut c = base.clone();
                c.levels[3] = 1 + i * 5;
                c
            })
            .collect();
        let rolls = representative_magic_rolls(&population).unwrap();
        let mut sorted: Vec<i64> = population.iter().map(candidate_magic_defence_roll).collect();
        sorted.sort_unstable();
        assert_eq!(rolls["low"], sorted[0]);
        assert_eq!(rolls["medium"], sorted[4]);
        assert_eq!(rolls["high"], sorted[8]);
    }
}
