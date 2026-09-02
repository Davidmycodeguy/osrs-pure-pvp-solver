//! Combat kernel shared by the gear screen and the ranker: style resolution
//! (attack rolls, max hits, cooldowns), defence rolls, hit chance and exact
//! damage distributions.  Formula-backed values are evaluated from the pinned
//! `mechanics.json` ASTs exactly as `pure_solver.resolved_gear_screen` does.

use std::collections::BTreeMap;

use anyhow::{anyhow, bail, Result};

use crate::formula::Variables;
use crate::mechanics::MechanicRegistry;
use crate::prayers::{best_melee_prayers, best_ranged_prayer, multiplier_of};
use crate::rational::Rational;

pub const DEFENCE_TYPES: [&str; 4] = ["stab", "slash", "crush", "ranged"];

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct StyleBonuses {
    pub attack: i64,
    pub strength: i64,
    pub defence: i64,
    pub range: i64,
}

/// `combat_style.f2p_bonuses`, keyed by style family (`accurate`, `rapid`, ...).
#[derive(Clone, Debug)]
pub struct StyleTable {
    families: BTreeMap<String, StyleBonuses>,
}

impl StyleTable {
    pub fn load(mechanics: &MechanicRegistry) -> Result<StyleTable> {
        let mut families = BTreeMap::new();
        for (family, entry) in mechanics.table("combat_style.f2p_bonuses")? {
            let entry = entry
                .as_object()
                .ok_or_else(|| anyhow!("combat_style.f2p_bonuses.{family} must be a mapping"))?;
            let field = |name: &str| entry.get(name).and_then(serde_json::Value::as_i64).unwrap_or(0);
            families.insert(
                family.clone(),
                StyleBonuses {
                    attack: field("attack"),
                    strength: field("strength"),
                    defence: field("defence"),
                    range: field("range"),
                },
            );
        }
        Ok(StyleTable { families })
    }

    pub fn family(&self, family: &str) -> Result<StyleBonuses> {
        self.families
            .get(family)
            .copied()
            .ok_or_else(|| anyhow!("Missing verified combat-style family {family:?}"))
    }

    /// `family, damage_type` from a style id such as `aggressive_slash`.
    pub fn parts(style_id: &str) -> Result<(&str, &str)> {
        let (family, damage_type) = style_id
            .split_once('_')
            .ok_or_else(|| anyhow!("Unsupported matrix attack style {style_id:?}"))?;
        if !DEFENCE_TYPES.contains(&damage_type) {
            bail!("Unsupported matrix attack style {style_id:?}");
        }
        Ok((family, damage_type))
    }

    /// Largest defensive style bonus among a weapon's styles (defence-roll representative).
    pub fn max_defence_bonus<'a>(&self, styles: impl Iterator<Item = &'a str>) -> Result<i64> {
        let mut best: Option<i64> = None;
        for style in styles {
            let (family, _) = StyleTable::parts(style)?;
            let bonus = self.family(family)?.defence;
            best = Some(best.map_or(bonus, |b| b.max(bonus)));
        }
        best.ok_or_else(|| anyhow!("Gear matrix weapon has no verified attack styles"))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedStyle {
    pub style_id: String,
    pub damage_type: String,
    pub attack_roll: i64,
    pub max_hit: i64,
    pub potted_max_hit: i64,
    pub cooldown_ticks: i64,
    pub maximum_range: i64,
    pub defence_style_bonus: i64,
}

/// Row inputs needed to resolve a weapon's styles for one exact account.
#[derive(Clone, Debug)]
pub struct StyleInputs {
    pub attack: i64,
    pub strength: i64,
    pub ranged: i64,
    pub prayer: i64,
    pub base_speed: i64,
    pub base_range: i64,
    /// Sorted, non-empty style ids.
    pub style_ids: Vec<String>,
    /// `attack_stab`, `attack_slash`, `attack_crush`, `attack_ranged` in DEFENCE_TYPES order.
    pub attack_bonus: [i64; 4],
    pub melee_strength: i64,
    pub ranged_strength: i64,
}

impl StyleInputs {
    fn bonus(&self, damage_type: &str) -> i64 {
        let index = DEFENCE_TYPES.iter().position(|d| *d == damage_type).expect("validated damage type");
        self.attack_bonus[index]
    }
}

fn vars(pairs: Vec<(&str, Rational)>) -> Variables {
    pairs.into_iter().map(|(k, v)| (k.to_owned(), v)).collect()
}

fn int(value: i64) -> Rational {
    Rational::int(value as i128)
}

pub struct CombatKernel<'a> {
    pub mechanics: &'a MechanicRegistry,
    pub styles: StyleTable,
    pub zero_to_one: bool,
}

impl<'a> CombatKernel<'a> {
    pub fn new(mechanics: &'a MechanicRegistry) -> Result<CombatKernel<'a>> {
        let zero_to_one = mechanics
            .require("damage.player_successful_zero_to_one")?
            .value
            .as_bool()
            .ok_or_else(|| anyhow!("damage.player_successful_zero_to_one must be a boolean"))?;
        Ok(CombatKernel {
            mechanics,
            styles: StyleTable::load(mechanics)?,
            zero_to_one,
        })
    }

    /// `player.defence_roll(player.effective_defence(...))` with no boost or prayer.
    pub fn defence_roll(&self, defence_level: i64, defence_bonus: i64, style_bonus: i64) -> Result<i64> {
        let effective = self.mechanics.evaluate(
            "player.effective_defence",
            &vars(vec![
                ("defence_level", int(defence_level)),
                ("defence_boost", int(0)),
                ("prayer_multiplier", Rational::one()),
                ("style_bonus", int(style_bonus)),
            ]),
        )?;
        self.mechanics.evaluate_int(
            "player.defence_roll",
            &vars(vec![("effective_defence", effective), ("defence_bonus", int(defence_bonus))]),
        )
    }

    /// `melee.accuracy` (also used for ranged): hit chance of an attack roll against a defence roll.
    pub fn accuracy(&self, attack_roll: i64, defence_roll: i64) -> Result<Rational> {
        self.mechanics.evaluate(
            "melee.accuracy",
            &vars(vec![("attack_roll", int(attack_roll)), ("defence_roll", int(defence_roll))]),
        )
    }

    pub fn resolve_styles(&self, inputs: &StyleInputs) -> Result<Vec<ResolvedStyle>> {
        let (melee_attack_prayer, melee_strength_prayer) = best_melee_prayers(self.mechanics, inputs.prayer)?;
        let ranged_prayer = multiplier_of(&best_ranged_prayer(self.mechanics, inputs.prayer)?);
        let (attack_multiplier, strength_multiplier) = (multiplier_of(&melee_attack_prayer), multiplier_of(&melee_strength_prayer));
        let strength_boost = self
            .mechanics
            .evaluate_int("strength_potion.boost", &vars(vec![("base_strength", int(inputs.strength))]))?;
        let mut resolved = Vec::with_capacity(inputs.style_ids.len());
        for style_id in &inputs.style_ids {
            let (family, damage_type) = StyleTable::parts(style_id)?;
            let style = self.styles.family(family)?;
            let (attack_roll, max_hit, potted_max_hit, cooldown) = if damage_type == "ranged" {
                let effective = |style_bonus: i64| {
                    vars(vec![
                        ("ranged_level", int(inputs.ranged)),
                        ("ranged_boost", int(0)),
                        ("prayer_multiplier", ranged_prayer.clone()),
                        ("style_bonus", int(style_bonus)),
                        ("void_multiplier", Rational::one()),
                    ])
                };
                let effective_attack = self.mechanics.evaluate("ranged.effective_attack", &effective(style.attack))?;
                let effective_strength = self.mechanics.evaluate("ranged.effective_strength", &effective(style.strength))?;
                let attack_roll = self.mechanics.evaluate_int(
                    "ranged.attack_roll",
                    &vars(vec![
                        ("effective_ranged_attack", effective_attack),
                        ("ranged_attack_bonus", int(inputs.bonus("ranged"))),
                        ("gear_multiplier", Rational::one()),
                    ]),
                )?;
                let max_hit = self.mechanics.evaluate_int(
                    "ranged.max_hit",
                    &vars(vec![
                        ("effective_ranged_strength", effective_strength),
                        ("ranged_strength_bonus", int(inputs.ranged_strength)),
                        ("gear_multiplier", Rational::one()),
                    ]),
                )?;
                let cooldown = if family == "rapid" {
                    self.mechanics
                        .evaluate_int("ranged.rapid_attack_cooldown", &vars(vec![("base_attack_speed", int(inputs.base_speed))]))?
                } else {
                    inputs.base_speed
                };
                (attack_roll, max_hit, max_hit, cooldown)
            } else {
                let effective_attack = self.mechanics.evaluate(
                    "melee.effective_attack",
                    &vars(vec![
                        ("attack_level", int(inputs.attack)),
                        ("attack_boost", int(0)),
                        ("prayer_multiplier", attack_multiplier.clone()),
                        ("style_bonus", int(style.attack)),
                    ]),
                )?;
                let strength_vars = |boost: i64| {
                    vars(vec![
                        ("strength_level", int(inputs.strength)),
                        ("strength_boost", int(boost)),
                        ("prayer_multiplier", strength_multiplier.clone()),
                        ("style_bonus", int(style.strength)),
                    ])
                };
                let effective_strength = self.mechanics.evaluate("melee.effective_strength", &strength_vars(0))?;
                let potted_strength = self.mechanics.evaluate("melee.effective_strength", &strength_vars(strength_boost))?;
                let attack_roll = self.mechanics.evaluate_int(
                    "melee.attack_roll",
                    &vars(vec![("effective_attack", effective_attack), ("attack_bonus", int(inputs.bonus(damage_type)))]),
                )?;
                let max_hit_of = |effective: Rational| {
                    self.mechanics.evaluate_int(
                        "melee.max_hit",
                        &vars(vec![("effective_strength", effective), ("melee_strength_bonus", int(inputs.melee_strength))]),
                    )
                };
                (attack_roll, max_hit_of(effective_strength)?, max_hit_of(potted_strength)?, inputs.base_speed)
            };
            resolved.push(ResolvedStyle {
                style_id: style_id.clone(),
                damage_type: damage_type.to_owned(),
                attack_roll,
                max_hit,
                potted_max_hit,
                cooldown_ticks: cooldown,
                maximum_range: inputs.base_range + style.range,
                defence_style_bonus: style.defence,
            });
        }
        if resolved.is_empty() {
            bail!("Gear matrix weapon has no resolved styles");
        }
        Ok(resolved)
    }
}

/// Exact probability mass over damage values (port of `evaluation.DamageDistribution`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DamageDistribution {
    pub probability: BTreeMap<i64, Rational>,
}

impl DamageDistribution {
    pub fn certain(damage: i64) -> DamageDistribution {
        DamageDistribution {
            probability: BTreeMap::from([(damage, Rational::one())]),
        }
    }

    /// Uniform 0..=max_hit on success; a successful 0 becomes 1 when configured.
    pub fn from_success_chance(hit_chance: &Rational, max_hit: i64, zero_becomes_one: bool) -> DamageDistribution {
        let mut probability: BTreeMap<i64, Rational> = BTreeMap::new();
        probability.insert(0, &Rational::one() - hit_chance);
        if max_hit == 0 {
            return DamageDistribution {
                probability: probability.into_iter().filter(|(_, c)| !c.is_zero()).collect(),
            };
        }
        let each = hit_chance / Rational::int(max_hit as i128 + 1);
        for damage in 0..=max_hit {
            let resolved = if zero_becomes_one && damage == 0 { 1 } else { damage };
            let entry = probability.entry(resolved).or_insert_with(Rational::zero);
            *entry = &*entry + &each;
        }
        DamageDistribution {
            probability: probability.into_iter().filter(|(_, c)| !c.is_zero()).collect(),
        }
    }

    pub fn expected_damage(&self) -> Rational {
        self.probability
            .iter()
            .fold(Rational::zero(), |acc, (damage, chance)| acc + Rational::int(*damage as i128) * chance)
    }

    pub fn convolve(&self, other: &DamageDistribution) -> DamageDistribution {
        let mut probability: BTreeMap<i64, Rational> = BTreeMap::new();
        for (left, left_chance) in &self.probability {
            for (right, right_chance) in &other.probability {
                let entry = probability.entry(left + right).or_insert_with(Rational::zero);
                *entry = &*entry + left_chance * right_chance;
            }
        }
        DamageDistribution { probability }
    }

    /// Sum of mass at or above `threshold`.
    pub fn at_least(&self, threshold: i64) -> Rational {
        self.probability.range(threshold..).fold(Rational::zero(), |acc, (_, chance)| acc + chance)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_roll_becomes_one_when_configured() {
        let distribution = DamageDistribution::from_success_chance(&Rational::new(1, 2), 2, true);
        assert_eq!(
            distribution.probability,
            BTreeMap::from([(0, Rational::new(1, 2)), (1, Rational::new(1, 3)), (2, Rational::new(1, 6))])
        );
        assert_eq!(distribution.expected_damage(), Rational::new(2, 3));
    }

    #[test]
    fn zero_max_hit_only_misses() {
        let distribution = DamageDistribution::from_success_chance(&Rational::new(1, 2), 0, true);
        assert_eq!(distribution.probability, BTreeMap::from([(0, Rational::new(1, 2))]));
    }
}
