//! Attach equipment to exact account profiles, caching gear by unlock signature
//! (port of `pure_solver.account_gear_matrix` + the row builder in `gear_matrix`).

use std::collections::{BTreeMap, HashMap};

use anyhow::{bail, Result};

use crate::accounts::AccountState;
use crate::dominance::prune_dominated_items;
use crate::items::{equipment_unlock_signature, EquipmentItem, BONUS_COLUMNS};

pub const MATRIX_ARMOUR_SLOTS: [&str; 5] = ["head", "neck", "body", "legs", "hands"];
pub const MATRIX_SKILLS: [&str; 5] = ["attack", "strength", "ranged", "magic", "prayer"];
pub const KIT_MODES: [&str; 2] = ["full", "offence_pareto"];
pub const EMPTY_NAME: &str = "EMPTY";
const MELEE_DAMAGE_TYPES: [&str; 3] = ["stab", "slash", "crush"];
const DEFENCE_BONUSES: [&str; 5] = ["defence_stab", "defence_slash", "defence_crush", "defence_ranged", "defence_magic"];
const OFFHAND_SHIELD_NAME: &str = "Mooleta";

/// One loadout row: five armour slots, a weapon, and derived ammo/shield.
#[derive(Clone, Debug)]
pub struct GearRow<'a> {
    pub profile_id: usize,
    pub account: AccountState,
    pub armour: [Option<&'a EquipmentItem>; 5],
    pub weapon: &'a EquipmentItem,
    pub ammo: Option<&'a EquipmentItem>,
    pub shield: Option<&'a EquipmentItem>,
}

impl<'a> GearRow<'a> {
    pub fn items(&self) -> impl Iterator<Item = &'a EquipmentItem> + '_ {
        self.armour
            .iter()
            .flatten()
            .copied()
            .chain(std::iter::once(self.weapon))
            .chain(self.ammo)
            .chain(self.shield)
    }

    pub fn aggregate_bonuses(&self) -> BTreeMap<&'static str, i64> {
        BONUS_COLUMNS
            .iter()
            .map(|name| (*name, self.items().map(|item| item.bonus(name)).sum()))
            .collect()
    }

    pub fn aggregate_requirements(&self) -> BTreeMap<String, i64> {
        let mut requirements: BTreeMap<String, i64> = BTreeMap::new();
        for item in self.items() {
            for (skill, level) in &item.requirements {
                let entry = requirements.entry(skill.clone()).or_insert(0);
                *entry = (*entry).max(*level);
            }
        }
        requirements
    }
}

/// One (armour, weapon, ammo, shield) loadout, weapon-major like the Python generator.
pub type LoadoutTuple<'a> = (
    [Option<&'a EquipmentItem>; 5],
    &'a EquipmentItem,
    Option<&'a EquipmentItem>,
    Option<&'a EquipmentItem>,
);

/// Weapon-keyed loadouts shared by every account with one unlock signature.
#[derive(Clone, Debug)]
pub struct SignatureGear<'a> {
    pub weapons: Vec<&'a EquipmentItem>,
    pub ammo_by_weapon: HashMap<i64, &'a EquipmentItem>,
    pub shield_by_weapon: HashMap<i64, &'a EquipmentItem>,
    /// (armour, weapon, ammo, shield) tuples, weapon-major like the Python generator.
    pub rows: Vec<LoadoutTuple<'a>>,
}

pub fn offence_bonus_names(weapon: &EquipmentItem) -> Vec<&'static str> {
    let types = weapon.damage_types();
    if types.contains("ranged") {
        return vec!["attack_ranged", "ranged_strength"];
    }
    let mut names: Vec<&'static str> = Vec::new();
    for (kind, name) in MELEE_DAMAGE_TYPES.iter().zip(["attack_stab", "attack_slash", "attack_crush"]) {
        if types.contains(kind) {
            names.push(name);
        }
    }
    names.push("melee_strength");
    names
}

fn offence_vector(item: &EquipmentItem, names: &[&str]) -> Vec<i64> {
    names.iter().map(|name| item.bonus(name)).collect()
}

fn defence_key(item: &EquipmentItem) -> (i64, i64) {
    (DEFENCE_BONUSES.iter().map(|name| item.bonus(name)).sum(), item.bonus("prayer"))
}

/// Items whose offence vector nobody matches-or-beats; ties resolved by defence then lowest id.
pub fn offence_pareto_items<'a>(items: &[&'a EquipmentItem], names: &[&str]) -> Vec<&'a EquipmentItem> {
    let mut order: Vec<Vec<i64>> = Vec::new();
    let mut best: HashMap<Vec<i64>, &EquipmentItem> = HashMap::new();
    for &item in items {
        let vector = offence_vector(item, names);
        match best.get(&vector) {
            Some(current) if (defence_key(item), -item.item_id) <= (defence_key(current), -current.item_id) => {}
            Some(_) => {
                best.insert(vector, item);
            }
            None => {
                order.push(vector.clone());
                best.insert(vector, item);
            }
        }
    }
    order
        .iter()
        .filter(|vector| {
            !order
                .iter()
                .any(|other| other != *vector && other.iter().zip(vector.iter()).all(|(o, v)| o >= v))
        })
        .map(|vector| best[vector])
        .collect()
}

pub fn best_compatible_ammo<'a>(weapon: &EquipmentItem, ammo: &[&'a EquipmentItem]) -> Option<&'a EquipmentItem> {
    ammo.iter()
        .copied()
        .filter(|item| weapon.ammo_ids.contains(&item.item_id))
        .max_by_key(|item| (item.bonus("ranged_strength"), item.bonus("attack_ranged"), -item.item_id))
}

fn cartesian<'a>(choices: &[Vec<&'a EquipmentItem>]) -> Vec<[Option<&'a EquipmentItem>; 5]> {
    let mut rows: Vec<[Option<&EquipmentItem>; 5]> = vec![[None; 5]];
    for (slot, options) in choices.iter().enumerate() {
        rows = rows
            .iter()
            .flat_map(|row| {
                options.iter().map(move |&item| {
                    let mut next = *row;
                    next[slot] = Some(item);
                    next
                })
            })
            .collect();
    }
    rows
}

/// Total defensive bonus, for picking the tankiest legal item in a slot.
fn total_defence(item: &EquipmentItem) -> i64 {
    DEFENCE_BONUSES.iter().map(|name| item.bonus(name)).sum()
}

/// The legal item with the highest total defence bonus (ties: lowest id), if any beats zero.
pub fn most_defensive<'a>(items: &[&'a EquipmentItem]) -> Option<&'a EquipmentItem> {
    items
        .iter()
        .copied()
        .filter(|item| total_defence(item) > 0)
        .min_by_key(|item| (-total_defence(item), item.item_id))
}

/// `keep_defensive` adds, per armour slot, the most defensive legal item alongside the offence
/// frontier, and offers the most defensive legal shield next to the offensive one, so tank
/// loadouts survive the offence pruning.  With `false` the original rows come back unchanged.
pub fn build_signature_gear_with<'a>(account: AccountState, items: &'a [EquipmentItem], kit_mode: &str, keep_defensive: bool) -> Result<SignatureGear<'a>> {
    if !KIT_MODES.contains(&kit_mode) {
        bail!("Unknown kit mode {kit_mode:?}; expected one of {KIT_MODES:?}");
    }
    let retained = prune_dominated_items(account, items);
    let slot_items = |slot: &str| -> Vec<&'a EquipmentItem> { retained.iter().copied().filter(|item| item.slot == slot).collect() };
    let weapons: Vec<&EquipmentItem> = slot_items("weapon").into_iter().chain(slot_items("2h")).collect();
    let ammo_options = slot_items("ammo");
    let shields = slot_items("shield");
    let offensive_shield = shields.iter().copied().find(|item| item.name == OFFHAND_SHIELD_NAME);
    let mut shield_options: Vec<Option<&EquipmentItem>> = vec![offensive_shield];
    if keep_defensive {
        if let Some(tank) = most_defensive(&shields) {
            if offensive_shield.is_none_or(|s| s.item_id != tank.item_id) {
                shield_options.push(Some(tank));
            }
        }
    }
    let armour_options: Vec<Vec<&EquipmentItem>> = MATRIX_ARMOUR_SLOTS.iter().map(|slot| slot_items(slot)).collect();

    let mut ammo_by_weapon = HashMap::new();
    let mut shield_by_weapon = HashMap::new();
    let mut rows = Vec::new();
    for &weapon in &weapons {
        if !weapon.ammo_ids.is_empty() {
            if let Some(ammo) = best_compatible_ammo(weapon, &ammo_options) {
                ammo_by_weapon.insert(weapon.item_id, ammo);
            }
        }
        if weapon.slot == "weapon" {
            if let Some(shield) = offensive_shield {
                shield_by_weapon.insert(weapon.item_id, shield);
            }
        }
        let choices: Vec<Vec<&EquipmentItem>> = if kit_mode == "full" {
            armour_options.clone()
        } else {
            let names = offence_bonus_names(weapon);
            armour_options.iter().map(|options| offence_pareto_items(options, &names)).collect()
        };
        let mut armour_rows = cartesian(&choices);
        if keep_defensive && kit_mode != "full" {
            // One extra loadout per weapon: the tankiest legal item in every slot (offence slots
            // keep their frontier pick when no defensive item exists), so tanks are representable
            // without multiplying the offence rows by every slot.
            let mut tank_row = [None; 5];
            for (slot, options) in armour_options.iter().enumerate() {
                tank_row[slot] = most_defensive(options).or_else(|| choices[slot].first().copied());
            }
            if tank_row.iter().any(Option::is_some) && !armour_rows.contains(&tank_row) {
                armour_rows.push(tank_row);
            }
        }
        let ammo = ammo_by_weapon.get(&weapon.item_id).copied();
        let weapon_shields: Vec<Option<&EquipmentItem>> = if weapon.slot == "weapon" { shield_options.clone() } else { vec![None] };
        for armour in armour_rows {
            for &shield_item in &weapon_shields {
                rows.push((armour, weapon, ammo, shield_item));
            }
        }
    }
    Ok(SignatureGear {
        weapons,
        ammo_by_weapon,
        shield_by_weapon,
        rows,
    })
}

/// Expand accounts into loadout rows (profile ids start at 1); returns rows and signature count.
pub fn build_account_gear_matrix_with<'a>(
    accounts: &[AccountState],
    items: &'a [EquipmentItem],
    kit_mode: &str,
    keep_defensive: bool,
) -> Result<(Vec<GearRow<'a>>, usize)> {
    let mut gear_by_signature: HashMap<Vec<i64>, SignatureGear<'a>> = HashMap::new();
    let mut rows = Vec::new();
    for (index, &account) in accounts.iter().enumerate() {
        let signature = equipment_unlock_signature(account, items);
        if !gear_by_signature.contains_key(&signature) {
            gear_by_signature.insert(signature.clone(), build_signature_gear_with(account, items, kit_mode, keep_defensive)?);
        }
        let gear = &gear_by_signature[&signature];
        rows.extend(gear.rows.iter().map(|(armour, weapon, ammo, shield)| GearRow {
            profile_id: index + 1,
            account,
            armour: *armour,
            weapon,
            ammo: *ammo,
            shield: *shield,
        }));
    }
    Ok((rows, gear_by_signature.len()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keep_defensive_adds_the_tankiest_legal_items_and_shield() {
        let dir = std::path::PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../rulesets/osrs-f2p-v1"));
        let items = crate::items::load_items(&dir.join("items.json")).unwrap();
        let tank = AccountState::with_defence(40, 40, 40, 1, 1, 40, 40).unwrap();
        let plain = build_signature_gear_with(tank, &items, "offence_pareto", false).unwrap();
        let kept = build_signature_gear_with(tank, &items, "offence_pareto", true).unwrap();
        assert!(kept.rows.len() > plain.rows.len());
        let names: std::collections::HashSet<String> = kept
            .rows
            .iter()
            .flat_map(|(armour, _, _, shield)| armour.iter().flatten().chain(shield.iter()).map(|i| i.name.clone()))
            .collect();
        assert!(names.contains("Rune full helm"), "{names:?}");
        assert!(names.contains("Rune kiteshield"), "{names:?}");
        assert!(names.contains("Mooleta"));
        let pure = AccountState::new(40, 40, 40, 1, 1, 40).unwrap();
        let pure_kept = build_signature_gear_with(pure, &items, "offence_pareto", true).unwrap();
        let wears_rune = pure_kept
            .rows
            .iter()
            .any(|(armour, _, _, _)| armour.iter().flatten().any(|i| i.name == "Rune full helm"));
        assert!(!wears_rune, "1 Defence cannot wear rune");
    }
}
