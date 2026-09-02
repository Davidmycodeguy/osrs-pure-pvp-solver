//! Rebuilds a survivor's armour from the item catalog, checks the row's
//! bonus columns are plain item sums, and derives the KO loadout inputs.

use std::collections::HashMap;

use anyhow::{anyhow, bail, Result};

use super::SourceColumns;
use crate::accounts::AccountState;
use crate::combat::{ResolvedStyle, StyleInputs};
use crate::items::EquipmentItem;
use crate::ranking::{RankingCandidate, RankingStyle, DAMAGE_TYPES};

pub const ARMOUR_SLOTS: [&str; 5] = ["head", "neck", "body", "legs", "hands"];

/// The offence bonuses `CombatKernel::resolve_styles` reads.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct OffenceBonuses {
    pub attack: [i64; 4],
    pub melee_strength: i64,
    pub ranged_strength: i64,
}

impl OffenceBonuses {
    pub fn of(item: &EquipmentItem) -> OffenceBonuses {
        let mut attack = [0i64; 4];
        for (slot, damage_type) in DAMAGE_TYPES.iter().enumerate() {
            attack[slot] = item.bonus(&format!("attack_{damage_type}"));
        }
        OffenceBonuses {
            attack,
            melee_strength: item.bonus("melee_strength"),
            ranged_strength: item.bonus("ranged_strength"),
        }
    }

    pub fn minus(self, other: OffenceBonuses) -> OffenceBonuses {
        let mut attack = self.attack;
        for (slot, value) in other.attack.iter().enumerate() {
            attack[slot] -= value;
        }
        OffenceBonuses {
            attack,
            melee_strength: self.melee_strength - other.melee_strength,
            ranged_strength: self.ranged_strength - other.ranged_strength,
        }
    }

    pub fn plus(self, other: OffenceBonuses) -> OffenceBonuses {
        let mut attack = self.attack;
        for (slot, value) in other.attack.iter().enumerate() {
            attack[slot] += value;
        }
        OffenceBonuses {
            attack,
            melee_strength: self.melee_strength + other.melee_strength,
            ranged_strength: self.ranged_strength + other.ranged_strength,
        }
    }

    pub fn of_row(columns: &SourceColumns, candidate: &RankingCandidate) -> Result<OffenceBonuses> {
        let mut attack = [0i64; 4];
        for (slot, damage_type) in DAMAGE_TYPES.iter().enumerate() {
            attack[slot] = columns.int(candidate, &format!("attack_{damage_type}"))?;
        }
        Ok(OffenceBonuses {
            attack,
            melee_strength: columns.int(candidate, "melee_strength")?,
            ranged_strength: columns.int(candidate, "ranged_strength")?,
        })
    }
}

#[derive(Debug)]
pub struct PrimaryGear<'a> {
    pub account: AccountState,
    pub weapon: &'a EquipmentItem,
    pub shield: Option<&'a EquipmentItem>,
    pub ammo: Option<&'a EquipmentItem>,
    /// The worn amulet (already inside `armour`); the KO loadout may swap it.
    pub neck: &'a EquipmentItem,
    /// Sum of the five armour items only.
    pub armour: OffenceBonuses,
}

/// Looks up every equipped item and fails if the row's bonus columns are not their sum.
pub fn primary_gear<'a>(candidate: &RankingCandidate, columns: &SourceColumns, items_by_id: &HashMap<i64, &'a EquipmentItem>) -> Result<PrimaryGear<'a>> {
    let item = |id: i64| -> Result<&'a EquipmentItem> {
        items_by_id
            .get(&id)
            .copied()
            .ok_or_else(|| anyhow!("Candidate {} references item {id} absent from the ruleset", candidate.candidate_id))
    };
    let mut armour = OffenceBonuses::default();
    for slot in ARMOUR_SLOTS {
        armour = armour.plus(OffenceBonuses::of(item(columns.int(candidate, &format!("{slot}_id"))?)?));
    }
    let weapon = item(columns.int(candidate, "weapon_id")?)?;
    let neck = item(columns.int(candidate, "neck_id")?)?;
    let shield = columns.optional_int(candidate, "shield_id")?.map(item).transpose()?;
    let ammo = columns.optional_int(candidate, "ammo_id")?.map(item).transpose()?;
    let mut total = armour.plus(OffenceBonuses::of(weapon));
    for extra in [shield, ammo].into_iter().flatten() {
        total = total.plus(OffenceBonuses::of(extra));
    }
    let row = OffenceBonuses::of_row(columns, candidate)?;
    if total != row {
        bail!(
            "Candidate {} bonus columns {row:?} are not the sum of its equipped items {total:?}",
            candidate.candidate_id
        );
    }
    let levels = candidate.levels;
    let account = AccountState::with_defence(levels[0], levels[1], levels[2], levels[3], levels[4], levels[6], levels[5])?;
    Ok(PrimaryGear {
        account,
        weapon,
        shield,
        ammo,
        neck,
        armour,
    })
}

/// `kits.py inventory_slots`: items in one loadout but not the other, worse direction. Ammo is excluded.
pub fn switch_slots(primary_weapon: &EquipmentItem, primary_shield: Option<&EquipmentItem>, ko_weapon: &EquipmentItem, neck_switch: bool) -> i64 {
    let primary: Vec<i64> = [Some(primary_weapon), primary_shield].into_iter().flatten().map(|i| i.item_id).collect();
    let ko_shield = primary_shield.filter(|_| !ko_weapon.two_handed);
    let ko: Vec<i64> = [Some(ko_weapon), ko_shield].into_iter().flatten().map(|i| i.item_id).collect();
    let only_in = |a: &[i64], b: &[i64]| a.iter().filter(|id| !b.contains(id)).count() as i64;
    only_in(&ko, &primary).max(only_in(&primary, &ko)) + i64::from(neck_switch)
}

/// Armour + KO weapon + ammo, plus the shield only when the KO weapon is one-handed.
pub fn ko_style_inputs(gear: &PrimaryGear<'_>, ko_weapon: &EquipmentItem) -> Result<StyleInputs> {
    ko_style_inputs_with_neck(gear, ko_weapon, None)
}

/// As `ko_style_inputs`, with the worn amulet replaced by `neck` when given.
pub fn ko_style_inputs_with_neck(gear: &PrimaryGear<'_>, ko_weapon: &EquipmentItem, neck: Option<&EquipmentItem>) -> Result<StyleInputs> {
    let mut bonuses = gear.armour.plus(OffenceBonuses::of(ko_weapon));
    if let Some(alternative) = neck {
        bonuses = bonuses.minus(OffenceBonuses::of(gear.neck)).plus(OffenceBonuses::of(alternative));
    }
    if let Some(shield) = gear.shield.filter(|_| !ko_weapon.two_handed) {
        bonuses = bonuses.plus(OffenceBonuses::of(shield));
    }
    if let Some(ammo) = gear.ammo {
        bonuses = bonuses.plus(OffenceBonuses::of(ammo));
    }
    let mut style_ids = ko_weapon.attack_styles.clone();
    style_ids.sort();
    if style_ids.is_empty() {
        bail!("KO weapon {} ({}) has no verified attack styles", ko_weapon.name, ko_weapon.item_id);
    }
    Ok(StyleInputs {
        attack: gear.account.attack,
        strength: gear.account.strength,
        ranged: gear.account.ranged,
        prayer: gear.account.prayer,
        base_speed: ko_weapon
            .attack_speed
            .ok_or_else(|| anyhow!("KO weapon {} has no attack speed", ko_weapon.name))?,
        base_range: ko_weapon
            .attack_range
            .ok_or_else(|| anyhow!("KO weapon {} has no attack range", ko_weapon.name))?,
        style_ids,
        attack_bonus: bonuses.attack,
        melee_strength: bonuses.melee_strength,
        ranged_strength: bonuses.ranged_strength,
    })
}

pub fn ranking_styles(styles: &[ResolvedStyle]) -> Vec<RankingStyle> {
    styles
        .iter()
        .map(|s| RankingStyle {
            style_id: s.style_id.clone(),
            damage_type: s.damage_type.clone(),
            attack_roll: s.attack_roll,
            max_hit: s.max_hit,
            potted_max_hit: s.potted_max_hit,
            cooldown_ticks: s.cooldown_ticks,
            maximum_range: s.maximum_range,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kits::testing::{candidate, ruleset};

    const MAPLE_SHORTBOW: i64 = 853;
    const ADAMANT_ARROW: i64 = 890;
    const RUNE_2H: i64 = 1319;
    const RUNE_SCIMITAR: i64 = 1333;
    const RUNE_MACE: i64 = 1432;
    const MOOLETA: i64 = 33101;
    const AMULET_OF_POWER: i64 = 1731;
    const AMULET_OF_STRENGTH: i64 = 1725;

    fn by_id(items: &[EquipmentItem]) -> HashMap<i64, &EquipmentItem> {
        items.iter().map(|i| (i.item_id, i)).collect()
    }

    #[test]
    fn switch_slots_follow_the_kit_rule() {
        let (_, items) = ruleset();
        let ids = by_id(&items);
        assert_eq!(switch_slots(ids[&MAPLE_SHORTBOW], None, ids[&RUNE_2H], false), 1, "bow -> 2H");
        assert_eq!(
            switch_slots(ids[&RUNE_SCIMITAR], Some(ids[&MOOLETA]), ids[&RUNE_2H], false),
            2,
            "scim+shield -> 2H"
        );
        assert_eq!(
            switch_slots(ids[&RUNE_SCIMITAR], Some(ids[&MOOLETA]), ids[&RUNE_MACE], false),
            1,
            "scim+shield -> mace keeps shield"
        );
        assert_eq!(switch_slots(ids[&RUNE_SCIMITAR], None, ids[&RUNE_2H], false), 1, "scim no shield -> 2H");
        assert_eq!(switch_slots(ids[&MAPLE_SHORTBOW], None, ids[&RUNE_2H], true), 2, "bow -> 2H + amulet switch");
    }

    #[test]
    fn primary_gear_rejects_bonus_columns_that_are_not_item_sums() {
        let (_, items) = ruleset();
        let ids = by_id(&items);
        // Valid armour ids with deliberately wrong (all zero) bonus columns.
        let source = [
            ("head_id", "579"),
            ("neck_id", "1478"),
            ("body_id", "577"),
            ("legs_id", "542"),
            ("hands_id", "1063"),
            ("weapon_id", "1333"),
            ("shield_id", ""),
            ("ammo_id", ""),
            ("attack_stab", "0"),
            ("attack_slash", "0"),
            ("attack_crush", "0"),
            ("attack_ranged", "0"),
            ("melee_strength", "0"),
            ("ranged_strength", "0"),
        ];
        let (candidate, columns) = candidate(&source);
        let error = primary_gear(&candidate, &columns, &ids).unwrap_err().to_string();
        assert!(error.contains("test-candidate"), "{error}");
        assert!(error.contains("not the sum"), "{error}");
    }

    #[test]
    fn ko_style_inputs_drop_the_shield_for_a_two_handed_ko_weapon() {
        let (_, items) = ruleset();
        let ids = by_id(&items);
        let armour = OffenceBonuses {
            attack: [1, 2, 3, 4],
            melee_strength: 5,
            ranged_strength: 0,
        };
        let account = AccountState::new(40, 31, 30, 1, 1, 30).unwrap();
        let gear = PrimaryGear {
            account,
            weapon: ids[&RUNE_SCIMITAR],
            shield: Some(ids[&MOOLETA]),
            ammo: Some(ids[&ADAMANT_ARROW]),
            neck: ids[&AMULET_OF_POWER],
            armour,
        };
        let two_handed = ko_style_inputs(&gear, ids[&RUNE_2H]).unwrap();
        let rune_2h = OffenceBonuses::of(ids[&RUNE_2H]);
        assert_eq!(
            two_handed.attack_bonus,
            [1 + rune_2h.attack[0], 2 + rune_2h.attack[1], 3 + rune_2h.attack[2], 4 + rune_2h.attack[3]]
        );
        assert_eq!(two_handed.melee_strength, 5 + rune_2h.melee_strength);
        assert_eq!(
            two_handed.ranged_strength,
            OffenceBonuses::of(ids[&ADAMANT_ARROW]).ranged_strength,
            "ammo stays equipped"
        );
        assert_eq!(two_handed.base_speed, 7);
        assert_eq!(
            two_handed.style_ids,
            vec!["accurate_slash", "aggressive_crush", "aggressive_slash", "defensive_slash"]
        );
        let one_handed = ko_style_inputs(&gear, ids[&RUNE_MACE]).unwrap();
        let mooleta = OffenceBonuses::of(ids[&MOOLETA]);
        let mace = OffenceBonuses::of(ids[&RUNE_MACE]);
        assert_eq!(
            one_handed.melee_strength,
            5 + mace.melee_strength + mooleta.melee_strength,
            "one-handed KO keeps the shield"
        );
        // Amulet switch: power (+6 str) out, strength (+10 str) in.
        let swapped = ko_style_inputs_with_neck(&gear, ids[&RUNE_2H], Some(ids[&AMULET_OF_STRENGTH])).unwrap();
        assert_eq!(swapped.melee_strength, two_handed.melee_strength - 6 + 10);
        assert_eq!(swapped.attack_bonus[1], two_handed.attack_bonus[1] - 6, "loses the power amulet's slash attack");
    }
}
