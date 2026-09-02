//! Strict per-account item dominance (port of `pure_solver.dominance`).
//! Only items with identical mechanic signatures may prune each other.

use std::collections::{BTreeSet, HashMap, HashSet};

use crate::accounts::AccountState;
use crate::items::{is_item_legal, EquipmentItem};

const MINIMISE_BONUSES: [&str; 1] = ["weight"];

type Signature<'a> = (
    &'a str,
    Option<&'a str>,
    bool,
    BTreeSet<&'a str>,
    BTreeSet<i64>,
    BTreeSet<&'a str>,
    BTreeSet<&'a str>,
);

fn mechanic_signature(item: &EquipmentItem) -> Signature<'_> {
    (
        item.slot.as_str(),
        item.weapon_type.as_deref(),
        item.two_handed,
        item.attack_styles.iter().map(String::as_str).collect(),
        item.ammo_ids.iter().copied().collect(),
        item.spell_ids.iter().map(String::as_str).collect(),
        item.mechanic_flags.iter().map(String::as_str).collect(),
    )
}

fn bonus_comparison(dominator: &EquipmentItem, candidate: &EquipmentItem) -> (bool, bool) {
    let keys: HashSet<&str> = dominator.bonuses.keys().chain(candidate.bonuses.keys()).map(String::as_str).collect();
    let (mut weakly, mut strictly) = (true, false);
    for key in keys {
        let (left, right) = (dominator.bonus(key), candidate.bonus(key));
        if MINIMISE_BONUSES.contains(&key) {
            weakly &= left <= right;
            strictly |= left < right;
        } else {
            weakly &= left >= right;
            strictly |= left > right;
        }
    }
    (weakly, strictly)
}

/// Whether `dominator` may safely remove `candidate` for this account.
pub fn dominates_for_account(
    dominator: &EquipmentItem,
    candidate: &EquipmentItem,
    account: AccountState,
    ammo_compatibility: &HashMap<i64, BTreeSet<i64>>,
) -> bool {
    if dominator.item_id == candidate.item_id || !is_item_legal(dominator, account) || !is_item_legal(candidate, account) {
        return false;
    }
    if mechanic_signature(dominator) != mechanic_signature(candidate) {
        return false;
    }
    if dominator.slot == "ammo" {
        let empty = BTreeSet::new();
        let left = ammo_compatibility.get(&dominator.item_id).unwrap_or(&empty);
        let right = ammo_compatibility.get(&candidate.item_id).unwrap_or(&empty);
        if left != right {
            return false;
        }
    }
    let (weakly, mut strictly) = bonus_comparison(dominator, candidate);
    if !weakly {
        return false;
    }
    match (candidate.attack_speed, dominator.attack_speed) {
        (Some(c), Some(d)) => {
            if d > c {
                return false;
            }
            strictly |= d < c;
        }
        (None, None) => {}
        _ => return false,
    }
    match (candidate.attack_range, dominator.attack_range) {
        (Some(c), Some(d)) => {
            if d < c {
                return false;
            }
            strictly |= d > c;
        }
        (None, None) => {}
        _ => return false,
    }
    if !strictly {
        return dominator.item_id < candidate.item_id;
    }
    true
}

/// Legal items for the account with dominated ones removed, sorted by item id.
pub fn prune_dominated_items(account: AccountState, items: &[EquipmentItem]) -> Vec<&EquipmentItem> {
    let mut legal: Vec<&EquipmentItem> = items.iter().filter(|item| is_item_legal(item, account)).collect();
    legal.sort_by_key(|item| item.item_id);
    let mut ammo_compatibility: HashMap<i64, BTreeSet<i64>> = HashMap::new();
    for weapon in &legal {
        for &ammo_id in &weapon.ammo_ids {
            ammo_compatibility.entry(ammo_id).or_default().insert(weapon.item_id);
        }
    }
    legal
        .iter()
        .copied()
        .filter(|candidate| !legal.iter().any(|item| dominates_for_account(item, candidate, account, &ammo_compatibility)))
        .collect()
}
