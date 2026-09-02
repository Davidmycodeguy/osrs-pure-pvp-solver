//! Equipment records and per-account legality (port of `pure_solver.legality`).
//! Catalog verification (provenance, scope, duplicates) is the Python layer's job;
//! this loader only reads what the verified `items.json` snapshot contains.

use std::collections::BTreeMap;
use std::path::Path;

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;

use crate::accounts::AccountState;

pub const F2P_STANDARD_WORLD_SCOPE: &str = "f2p_standard_world";
pub const REQUIREMENT_COLUMNS: [&str; 7] = ["attack", "strength", "ranged", "magic", "prayer", "defence", "hitpoints"];
pub const BONUS_COLUMNS: [&str; 14] = [
    "attack_stab",
    "attack_slash",
    "attack_crush",
    "attack_magic",
    "attack_ranged",
    "defence_stab",
    "defence_slash",
    "defence_crush",
    "defence_magic",
    "defence_ranged",
    "melee_strength",
    "ranged_strength",
    "magic_damage",
    "prayer",
];

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
pub struct EquipmentItem {
    pub item_id: i64,
    pub name: String,
    pub free_to_play: bool,
    pub members: bool,
    pub obtainable: bool,
    pub slot: String,
    #[serde(default)]
    pub requirements: BTreeMap<String, i64>,
    #[serde(default)]
    pub bonuses: BTreeMap<String, i64>,
    #[serde(default)]
    pub quest_requirements: Vec<String>,
    #[serde(default)]
    pub two_handed: bool,
    #[serde(default)]
    pub weapon_type: Option<String>,
    #[serde(default)]
    pub attack_speed: Option<i64>,
    #[serde(default)]
    pub attack_range: Option<i64>,
    #[serde(default)]
    pub attack_styles: Vec<String>,
    #[serde(default)]
    pub ammo_ids: Vec<i64>,
    #[serde(default)]
    pub spell_ids: Vec<String>,
    #[serde(default)]
    pub mechanic_flags: Vec<String>,
    #[serde(default)]
    pub source_ids: Vec<String>,
    #[serde(default = "unverified")]
    pub status: String,
    #[serde(default = "unverified")]
    pub availability_scope: String,
}

fn unverified() -> String {
    "unverified".to_owned()
}

impl EquipmentItem {
    pub fn bonus(&self, name: &str) -> i64 {
        self.bonuses.get(name).copied().unwrap_or(0)
    }

    pub fn is_weapon(&self) -> bool {
        self.slot == "weapon" || self.slot == "2h"
    }

    /// Damage types named by this weapon's attack styles (`accurate_slash` -> `slash`).
    pub fn damage_types(&self) -> std::collections::BTreeSet<&str> {
        self.attack_styles.iter().map(|style| style.rsplit('_').next().unwrap_or(style)).collect()
    }
}

pub fn load_items(path: &Path) -> Result<Vec<EquipmentItem>> {
    let text = std::fs::read_to_string(path).with_context(|| format!("Missing required ruleset file: {}", path.display()))?;
    let mut items: Vec<EquipmentItem> = serde_json::from_str(&text).with_context(|| format!("Invalid JSON in ruleset file {}", path.display()))?;
    for item in &mut items {
        item.name = item.name.trim().to_owned();
        item.slot = item.slot.trim().to_owned();
        item.quest_requirements.sort();
        item.mechanic_flags.sort();
    }
    Ok(items)
}

fn account_level(account: AccountState, skill: &str) -> i64 {
    match skill {
        "attack" => account.attack,
        "strength" => account.strength,
        "ranged" => account.ranged,
        "magic" => account.magic,
        "prayer" => account.prayer,
        "hitpoints" => account.hitpoints,
        "defence" => account.defence(),
        _ => -1,
    }
}

static COMPLETED_QUESTS: std::sync::OnceLock<std::collections::BTreeSet<String>> = std::sync::OnceLock::new();

/// Quests assumed completed for legality (process-wide; set once by the CLI, empty by default).
pub fn set_completed_quests(quests: impl IntoIterator<Item = String>) -> Result<()> {
    let set: std::collections::BTreeSet<String> = quests.into_iter().map(|q| q.trim().to_owned()).filter(|q| !q.is_empty()).collect();
    COMPLETED_QUESTS
        .set(set)
        .map_err(|_| anyhow!("completed quests were already configured for this process"))
}

pub fn completed_quests() -> &'static std::collections::BTreeSet<String> {
    COMPLETED_QUESTS.get_or_init(std::collections::BTreeSet::new)
}

/// Mirrors `is_item_legal` with the default `LegalityContext` (no quests unless configured, verified items only).
pub fn is_item_legal(item: &EquipmentItem, account: AccountState) -> bool {
    item.status == "verified"
        && item.availability_scope == F2P_STANDARD_WORLD_SCOPE
        && !item.source_ids.is_empty()
        && item.free_to_play
        && !item.members
        && item.obtainable
        && item.requirements.iter().all(|(skill, required)| account_level(account, skill) >= *required)
        && item.quest_requirements.iter().all(|quest| completed_quests().contains(quest))
}

/// Sorted IDs of every item this account may equip; equal vectors share gear expansions.
pub fn equipment_unlock_signature(account: AccountState, items: &[EquipmentItem]) -> Vec<i64> {
    let mut ids: Vec<i64> = items.iter().filter(|item| is_item_legal(item, account)).map(|item| item.item_id).collect();
    ids.sort_unstable();
    ids
}
