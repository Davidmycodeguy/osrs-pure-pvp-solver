//! Legal KO weapons per survivor and kit construction (baseline + switches).

use std::collections::HashMap;

use anyhow::{bail, Result};
use rayon::prelude::*;
use serde_json::json;

use super::loadout::{ko_style_inputs_with_neck, primary_gear, ranking_styles, switch_slots, OffenceBonuses, PrimaryGear};
use super::magic::{best_spell, SpellBook, SpellChoice};
use super::{Kit, KitConfig, KoLoadout, SourceColumns, MELEE_DAMAGE_TYPES};
use crate::accounts::AccountState;
use crate::canonical::canonical_hash;
use crate::combat::CombatKernel;
use crate::items::{is_item_legal, EquipmentItem};
use crate::ranking::{RankingCandidate, RankingStyle};

pub fn legal_ko_weapons(items: &[EquipmentItem], account: AccountState, primary_weapon_id: i64) -> Vec<&EquipmentItem> {
    let mut weapons: Vec<&EquipmentItem> = items
        .iter()
        .filter(|item| item.is_weapon() && item.item_id != primary_weapon_id && !item.attack_styles.is_empty())
        .filter(|item| item.damage_types().iter().all(|d| MELEE_DAMAGE_TYPES.contains(d)))
        .filter(|item| is_item_legal(item, account))
        .collect();
    weapons.sort_by_key(|item| item.item_id);
    weapons
}

pub fn kit_id(candidate_id: &str, ko_weapon_id: Option<i64>, ko_neck_id: Option<i64>, spell: Option<&str>) -> String {
    canonical_hash(&json!({ "candidate_id": candidate_id, "ko_weapon_id": ko_weapon_id, "ko_neck_id": ko_neck_id, "spell": spell }))
}

/// The legal amulet with the highest melee strength bonus, if it beats the worn one (ties: lowest id).
pub fn best_strength_neck<'a>(items: &'a [EquipmentItem], account: AccountState, worn: &EquipmentItem) -> Option<&'a EquipmentItem> {
    let mut necks: Vec<&EquipmentItem> = items.iter().filter(|item| item.slot == "neck" && is_item_legal(item, account)).collect();
    necks.sort_by_key(|item| (-item.bonus("melee_strength"), item.item_id));
    necks
        .first()
        .copied()
        .filter(|best| best.item_id != worn.item_id && best.bonus("melee_strength") > worn.bonus("melee_strength"))
}

/// Everything `resolve_styles` depends on for a KO loadout; identical keys share one resolution.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct StyleKey {
    levels: [i64; 4],
    bonuses: [i64; 6],
    weapon_id: i64,
    neck_id: Option<i64>,
}

fn style_key(gear: &PrimaryGear<'_>, weapon: &EquipmentItem, neck: Option<&EquipmentItem>, bonuses: OffenceBonuses) -> StyleKey {
    let account = gear.account;
    StyleKey {
        levels: [account.attack, account.strength, account.ranged, account.prayer],
        bonuses: [
            bonuses.attack[0],
            bonuses.attack[1],
            bonuses.attack[2],
            bonuses.attack[3],
            bonuses.melee_strength,
            bonuses.ranged_strength,
        ],
        weapon_id: weapon.item_id,
        neck_id: neck.map(|item| item.item_id),
    }
}

/// One candidate KO loadout: a weapon, optionally with an amulet swapped in.
struct KoOption<'a> {
    weapon: &'a EquipmentItem,
    neck: Option<&'a EquipmentItem>,
    key: StyleKey,
    /// Key of the same weapon without the amulet swap (the swap must out-hit it to be kept).
    base_key: StyleKey,
}

struct Pending<'a> {
    primary: usize,
    gear: PrimaryGear<'a>,
    options: Vec<KoOption<'a>>,
    /// Best castable spell that out-hits the primary weapon, if any.
    spell: Option<SpellChoice>,
}

fn pending<'a>(
    index: usize,
    candidate: &RankingCandidate,
    columns: &SourceColumns,
    items: &'a [EquipmentItem],
    items_by_id: &HashMap<i64, &'a EquipmentItem>,
    kernel: &CombatKernel<'_>,
    book: Option<&SpellBook>,
) -> Result<Pending<'a>> {
    let gear = primary_gear(candidate, columns, items_by_id)?;
    let spell = match book {
        Some(book) => best_spell(kernel.mechanics, book, candidate, columns)?.filter(|choice| choice.style.max_hit > candidate.max_hit),
        None => None,
    };
    let best_neck = best_strength_neck(items, gear.account, gear.neck);
    let mut options = Vec::new();
    for weapon in legal_ko_weapons(items, gear.account, gear.weapon.item_id) {
        let key_for = |neck: Option<&'a EquipmentItem>| -> Result<StyleKey> {
            let inputs = ko_style_inputs_with_neck(&gear, weapon, neck)?;
            let bonuses = OffenceBonuses {
                attack: inputs.attack_bonus,
                melee_strength: inputs.melee_strength,
                ranged_strength: inputs.ranged_strength,
            };
            Ok(style_key(&gear, weapon, neck, bonuses))
        };
        let base_key = key_for(None)?;
        options.push(KoOption {
            weapon,
            neck: None,
            key: base_key.clone(),
            base_key: base_key.clone(),
        });
        if let Some(neck) = best_neck {
            options.push(KoOption {
                weapon,
                neck: Some(neck),
                key: key_for(Some(neck))?,
                base_key,
            });
        }
    }
    Ok(Pending {
        primary: index,
        gear,
        options,
        spell,
    })
}

fn resolve_unique<'a>(kernel: &CombatKernel<'_>, pending: &[Pending<'a>]) -> Result<HashMap<StyleKey, Vec<RankingStyle>>> {
    let mut unique: HashMap<StyleKey, (usize, &'a EquipmentItem, Option<&'a EquipmentItem>)> = HashMap::new();
    for (index, item) in pending.iter().enumerate() {
        for option in &item.options {
            unique.entry(option.key.clone()).or_insert((index, option.weapon, option.neck));
        }
    }
    let keys: Vec<(StyleKey, usize, &EquipmentItem, Option<&EquipmentItem>)> = unique.into_iter().map(|(k, (i, w, n))| (k, i, w, n)).collect();
    keys.into_par_iter()
        .map(|(key, index, weapon, neck)| {
            let styles = kernel.resolve_styles(&ko_style_inputs_with_neck(&pending[index].gear, weapon, neck)?)?;
            Ok((key, ranking_styles(&styles)))
        })
        .collect()
}

fn kits_for(
    candidate: &RankingCandidate,
    item: &Pending<'_>,
    resolved: &HashMap<StyleKey, Vec<RankingStyle>>,
    inventory_slots: i64,
    potions: i64,
    max_ko_options: usize,
) -> Result<Vec<Kit>> {
    let free = inventory_slots - potions;
    if free < 0 {
        bail!("{potions} strength potions do not fit in {inventory_slots} inventory slots");
    }
    let mut kits = vec![Kit {
        kit_id: kit_id(&candidate.candidate_id, None, None, None),
        primary: item.primary,
        ko: None,
        spell: None,
        food_slots: free,
    }];
    // With a Strength potion carried the KO tables score potted hits, so the filters compare potted hits too;
    // otherwise a swap that only pays off potted (Amulet of strength at 52 Strength: 17 against 16) is dropped.
    let potted = potions > 0;
    let hit_of = |styles: &[RankingStyle]| styles.iter().map(|s| if potted { s.potted_max_hit } else { s.max_hit }).max().unwrap_or(0);
    let primary_hit = if potted { candidate.potted_max_hit } else { candidate.max_hit };
    for option in &item.options {
        let (weapon, neck) = (option.weapon, option.neck);
        let styles = &resolved[&option.key];
        if hit_of(styles) <= primary_hit {
            continue;
        }
        // An amulet swap must add max hit over the same weapon without it, or it is just a wasted slot.
        if neck.is_some() && hit_of(styles) <= hit_of(&resolved[&option.base_key]) {
            continue;
        }
        let slots = switch_slots(item.gear.weapon, item.gear.shield, weapon, neck.is_some());
        let food_slots = free - slots;
        if food_slots < 0 {
            bail!(
                "Candidate {} with KO weapon {} needs {slots} switch slots but only {free} inventory slots remain after potions",
                candidate.candidate_id,
                weapon.name
            );
        }
        kits.push(Kit {
            kit_id: kit_id(&candidate.candidate_id, Some(weapon.item_id), neck.map(|n| n.item_id), None),
            primary: item.primary,
            ko: Some(KoLoadout {
                weapon_id: weapon.item_id,
                weapon_name: weapon.name.clone(),
                two_handed: weapon.two_handed,
                neck_id: neck.map(|n| n.item_id),
                neck_name: neck.map(|n| n.name.clone()),
                styles: styles.clone(),
                switch_slots: slots,
            }),
            spell: None,
            food_slots,
        });
    }
    if max_ko_options > 0 && kits.len() > max_ko_options + 1 {
        // Baseline stays first; the switches are ranked by potted max hit, then attack roll, then id.
        let mut switches: Vec<Kit> = kits.drain(1..).collect();
        let strength = |kit: &Kit| {
            let ko = kit.ko.as_ref().expect("switch kit");
            let potted = ko.styles.iter().map(|s| s.potted_max_hit).max().unwrap_or(0);
            let roll = ko.styles.iter().map(|s| s.attack_roll).max().unwrap_or(0);
            (-potted, -roll, ko.weapon_id, ko.neck_id.unwrap_or(0))
        };
        switches.sort_by_key(strength);
        switches.truncate(max_ko_options);
        kits.extend(switches);
    }
    // Runes variant of every kit: the same loadout carrying the best out-hitting spell.
    if let Some(choice) = &item.spell {
        let mut with_runes = Vec::with_capacity(kits.len());
        for kit in &kits {
            let food_slots = kit.food_slots - choice.rune_slots;
            if food_slots < 0 {
                bail!(
                    "Candidate {} cannot carry {} rune types on top of its switches",
                    candidate.candidate_id,
                    choice.rune_slots
                );
            }
            let ko = kit.ko.as_ref();
            with_runes.push(Kit {
                kit_id: kit_id(&candidate.candidate_id, ko.map(|k| k.weapon_id), ko.and_then(|k| k.neck_id), Some(&choice.name)),
                primary: kit.primary,
                ko: kit.ko.clone(),
                spell: Some(choice.clone()),
                food_slots,
            });
        }
        kits.extend(with_runes);
    }
    Ok(kits)
}

/// Inventory and enumeration limits for [`enumerate_kits`], taken from [`KitConfig`].
#[derive(Clone, Copy, Debug)]
pub struct KitLimits {
    /// Total inventory slots; food gets whatever potions, switches and runes leave free.
    pub inventory_slots: i64,
    /// Strength potions carried, one slot each.
    pub strength_potions: i64,
    /// Keep at most this many KO loadouts per build (0 = all).
    pub max_ko_options: usize,
}

impl From<&KitConfig> for KitLimits {
    fn from(config: &KitConfig) -> KitLimits {
        KitLimits {
            inventory_slots: config.inventory_slots,
            strength_potions: config.strength_potions,
            max_ko_options: config.max_ko_options,
        }
    }
}

/// Baseline kit plus every out-hitting legal melee switch, per survivor, in candidate order.
pub fn enumerate_kits(
    candidates: &[RankingCandidate],
    columns: &SourceColumns,
    items: &[EquipmentItem],
    kernel: &CombatKernel<'_>,
    book: Option<&SpellBook>,
    limits: KitLimits,
) -> Result<Vec<Kit>> {
    if limits.inventory_slots < 0 {
        bail!("inventory_slots cannot be negative");
    }
    if limits.strength_potions < 0 {
        bail!("strength_potions cannot be negative");
    }
    let items_by_id: HashMap<i64, &EquipmentItem> = items.iter().map(|i| (i.item_id, i)).collect();
    let pending: Vec<Pending<'_>> = candidates
        .par_iter()
        .enumerate()
        .map(|(index, c)| pending(index, c, columns, items, &items_by_id, kernel, book))
        .collect::<Result<_>>()?;
    let resolved = resolve_unique(kernel, &pending)?;
    let per_candidate: Vec<Vec<Kit>> = pending
        .par_iter()
        .map(|item| {
            kits_for(
                &candidates[item.primary],
                item,
                &resolved,
                limits.inventory_slots,
                limits.strength_potions,
                limits.max_ko_options,
            )
        })
        .collect::<Result<_>>()?;
    Ok(per_candidate.into_iter().flatten().collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kits::testing::{candidate, ruleset};

    /// Full inventory, no potion, every KO option kept.
    const FULL_INVENTORY: KitLimits = KitLimits {
        inventory_slots: 28,
        strength_potions: 0,
        max_ko_options: 0,
    };

    /// Rune scimitar survivor row (plus any `extra` columns); bonus columns are the true item sums
    /// so the reconstruction check passes.
    fn scimitar_row(items: &[EquipmentItem], extra: &[(&str, &str)]) -> Vec<(String, String)> {
        scimitar_row_with_neck(items, 1478, extra)
    }

    /// `scimitar_row` with a chosen amulet in the neck slot.
    fn scimitar_row_with_neck(items: &[EquipmentItem], neck_id: i64, extra: &[(&str, &str)]) -> Vec<(String, String)> {
        let ids: HashMap<i64, &EquipmentItem> = items.iter().map(|i| (i.item_id, i)).collect();
        let armour_ids = [579i64, neck_id, 577, 542, 1063];
        let mut total = OffenceBonuses::of(ids[&1333]);
        for id in armour_ids {
            total = total.plus(OffenceBonuses::of(ids[&id]));
        }
        let text = |v: i64| v.to_string();
        let mut owned: Vec<(String, String)> = vec![
            ("head_id".into(), text(armour_ids[0])),
            ("neck_id".into(), text(armour_ids[1])),
            ("body_id".into(), text(armour_ids[2])),
            ("legs_id".into(), text(armour_ids[3])),
            ("hands_id".into(), text(armour_ids[4])),
            ("weapon_id".into(), "1333".into()),
            ("shield_id".into(), String::new()),
            ("ammo_id".into(), String::new()),
            ("attack_stab".into(), text(total.attack[0])),
            ("attack_slash".into(), text(total.attack[1])),
            ("attack_crush".into(), text(total.attack[2])),
            ("attack_ranged".into(), text(total.attack[3])),
            ("melee_strength".into(), text(total.melee_strength)),
            ("ranged_strength".into(), text(total.ranged_strength)),
        ];
        owned.extend(extra.iter().map(|(k, v)| (k.to_string(), v.to_string())));
        owned
    }

    #[test]
    fn legal_ko_weapons_are_melee_only_and_exclude_the_primary() {
        let (_, items) = ruleset();
        let account = AccountState::new(40, 31, 30, 1, 1, 30).unwrap();
        let weapons = legal_ko_weapons(&items, account, 1333);
        assert!(weapons.iter().all(|w| w.item_id != 1333), "primary excluded");
        assert!(
            weapons.iter().all(|w| w.damage_types().iter().all(|d| MELEE_DAMAGE_TYPES.contains(d))),
            "melee only"
        );
        assert!(weapons.iter().any(|w| w.item_id == 1319), "rune 2h is legal at 40 attack");
        assert!(weapons.windows(2).all(|p| p[0].item_id < p[1].item_id), "sorted by id");
        let low = AccountState::new(1, 31, 30, 1, 1, 30).unwrap();
        assert!(legal_ko_weapons(&items, low, 1333).iter().all(|w| w.item_id != 1319), "rune 2h needs 40 attack");
    }

    #[test]
    fn kit_ids_are_stable_and_distinct() {
        assert_eq!(kit_id("abc", None, None, None), kit_id("abc", None, None, None));
        assert_ne!(kit_id("abc", None, None, None), kit_id("abc", Some(1319), None, None));
        assert_ne!(kit_id("abc", Some(1319), None, None), kit_id("abc", Some(1319), Some(1725), None));
        assert_ne!(kit_id("abc", Some(1319), None, None), kit_id("abc", Some(1319), None, Some("Fire Bolt")));
        assert_eq!(kit_id("abc", None, None, None).len(), 64);
    }

    #[test]
    fn enumerate_kits_keeps_baseline_and_only_out_hitting_ko_weapons() {
        let (mechanics, items) = ruleset();
        let kernel = CombatKernel::new(&mechanics).unwrap();
        let owned = scimitar_row(&items, &[]);
        let source: Vec<(&str, &str)> = owned.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
        let (mut primary, columns) = candidate(&source);
        primary.max_hit = 8;
        primary.potted_max_hit = 8;
        let kits = enumerate_kits(std::slice::from_ref(&primary), &columns, &items, &kernel, None, FULL_INVENTORY).unwrap();
        assert!(kits[0].is_baseline() && kits[0].food_slots == 28);
        let potted = enumerate_kits(
            std::slice::from_ref(&primary),
            &columns,
            &items,
            &kernel,
            None,
            KitLimits {
                strength_potions: 1,
                ..FULL_INVENTORY
            },
        )
        .unwrap();
        assert_eq!(potted[0].food_slots, 27, "a potion costs one slot");
        let same = potted.iter().find(|k| k.kit_id == kits[1].kit_id).expect("the first switch kit exists potted too");
        assert_eq!(same.food_slots, kits[1].food_slots - 1);
        assert!(kits.len() > 1, "a 40-attack scimitar account has at least the rune 2h as a KO option");
        for kit in &kits[1..] {
            let ko = kit.ko.as_ref().unwrap();
            assert!(
                ko.styles.iter().map(|s| s.max_hit).max().unwrap() > 8,
                "{} must out-hit the primary",
                ko.weapon_name
            );
            assert_eq!(kit.food_slots, 28 - ko.switch_slots);
        }
        assert!(kits[1..]
            .windows(2)
            .all(|p| p[0].ko.as_ref().unwrap().weapon_id <= p[1].ko.as_ref().unwrap().weapon_id));
        // Amulet of accuracy is worn. At 31 Strength the +10 strength amulet lifts the Rune battleaxe from 8 to 9
        // (so only its amulet-switch variant out-hits the primary) but leaves the Rune 2h at 9 (so no variant).
        let variants = |weapon_id: i64| -> Vec<&Kit> { kits.iter().filter(|k| k.ko.as_ref().is_some_and(|ko| ko.weapon_id == weapon_id)).collect() };
        let battleaxe = variants(1373);
        assert_eq!(battleaxe.len(), 1, "plain battleaxe cannot out-hit the primary; the amulet-switch variant can");
        let swapped = battleaxe[0].ko.as_ref().unwrap();
        assert_eq!(swapped.neck_id, Some(1725));
        assert_eq!(swapped.neck_name.as_deref(), Some("Amulet of strength"));
        assert_eq!(swapped.switch_slots, 2, "weapon switch plus amulet switch");
        assert_eq!(swapped.styles.iter().map(|s| s.max_hit).max(), Some(9));
        let rune_2h = variants(1319);
        assert_eq!(rune_2h.len(), 1, "the swap does not raise the 2h max hit, so it is not a kit");
        assert_eq!(rune_2h[0].ko.as_ref().unwrap().neck_id, None);
        assert_ne!(battleaxe[0].kit_id, rune_2h[0].kit_id);
    }

    #[test]
    fn runes_variants_double_the_kits_when_a_spell_out_hits_the_primary() {
        let (mechanics, items) = ruleset();
        let kernel = CombatKernel::new(&mechanics).unwrap();
        let book = SpellBook::load(&mechanics).unwrap();
        let owned = scimitar_row(&items, &[("magic_damage", "0")]);
        let source: Vec<(&str, &str)> = owned.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
        let (mut primary, columns) = candidate(&source);
        primary.max_hit = 8;
        primary.levels[3] = 35; // Fire Bolt, max 12 > 8
        let without = enumerate_kits(std::slice::from_ref(&primary), &columns, &items, &kernel, None, FULL_INVENTORY).unwrap();
        let with = enumerate_kits(std::slice::from_ref(&primary), &columns, &items, &kernel, Some(&book), FULL_INVENTORY).unwrap();
        assert_eq!(with.len(), without.len() * 2, "every kit gets a runes variant");
        let runes: Vec<&Kit> = with.iter().filter(|k| k.spell.is_some()).collect();
        assert_eq!(runes.len(), without.len());
        for (plain, carried) in without.iter().zip(&runes) {
            assert_eq!(carried.food_slots, plain.food_slots - 3, "fire bolt needs air, chaos and fire runes");
            assert_eq!(carried.spell.as_ref().unwrap().name, "Fire Bolt");
            assert_ne!(carried.kit_id, plain.kit_id);
        }
        primary.levels[3] = 9; // Earth Strike max 6 does not out-hit the primary: no runes variants
        let low = enumerate_kits(std::slice::from_ref(&primary), &columns, &items, &kernel, Some(&book), FULL_INVENTORY).unwrap();
        assert_eq!(low.len(), without.len());
    }

    #[test]
    fn potion_aware_filters_keep_an_amulet_swap_that_only_pays_off_potted() {
        let (mechanics, items) = ruleset();
        let kernel = CombatKernel::new(&mechanics).unwrap();
        let owned = scimitar_row_with_neck(&items, 1731, &[]); // Amulet of power worn
        let source: Vec<(&str, &str)> = owned.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
        let (mut primary, columns) = candidate(&source);
        // Strength 50, Superhuman Strength: the Rune warhammer hits 14 unpotted with either amulet,
        // but 16 potted with Amulet of strength against 15 with Amulet of power.
        primary.levels[1] = 50;
        primary.levels[4] = 13;
        primary.max_hit = 8;
        primary.potted_max_hit = 8;
        let warhammers = |kits: &[Kit]| kits.iter().filter(|k| k.ko.as_ref().is_some_and(|ko| ko.weapon_id == 1347)).count();
        let unpotted = enumerate_kits(std::slice::from_ref(&primary), &columns, &items, &kernel, None, FULL_INVENTORY).unwrap();
        assert_eq!(warhammers(&unpotted), 1, "without a potion the swap adds nothing");
        let potted = enumerate_kits(
            std::slice::from_ref(&primary),
            &columns,
            &items,
            &kernel,
            None,
            KitLimits {
                strength_potions: 1,
                ..FULL_INVENTORY
            },
        )
        .unwrap();
        assert_eq!(warhammers(&potted), 2, "with a potion the swap lifts 15 to 16 and is a kit");
    }

    #[test]
    fn best_strength_neck_prefers_amulet_of_strength_over_power() {
        let (_, items) = ruleset();
        let ids: HashMap<i64, &EquipmentItem> = items.iter().map(|i| (i.item_id, i)).collect();
        let account = AccountState::new(40, 31, 30, 1, 1, 30).unwrap();
        assert_eq!(
            best_strength_neck(&items, account, ids[&1731]).map(|n| n.item_id),
            Some(1725),
            "power -> strength"
        );
        assert_eq!(best_strength_neck(&items, account, ids[&1725]), None, "already wearing the best");
    }
    #[test]
    fn max_ko_options_keeps_the_hardest_hitting_switches() {
        let (mechanics, items) = ruleset();
        let kernel = CombatKernel::new(&mechanics).unwrap();
        let owned = scimitar_row(&items, &[]);
        let source: Vec<(&str, &str)> = owned.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
        let (mut primary, columns) = candidate(&source);
        primary.max_hit = 8;
        let all = enumerate_kits(std::slice::from_ref(&primary), &columns, &items, &kernel, None, FULL_INVENTORY).unwrap();
        let capped = enumerate_kits(
            std::slice::from_ref(&primary),
            &columns,
            &items,
            &kernel,
            None,
            KitLimits {
                max_ko_options: 2,
                ..FULL_INVENTORY
            },
        )
        .unwrap();
        assert!(all.len() > 3);
        assert_eq!(capped.len(), 3, "baseline + 2 switches");
        assert!(capped[0].is_baseline());
        let best_all = all
            .iter()
            .filter_map(|k| k.ko.as_ref())
            .map(|k| k.styles.iter().map(|s| s.potted_max_hit).max().unwrap())
            .max()
            .unwrap();
        let best_capped = capped[1].ko.as_ref().unwrap().styles.iter().map(|s| s.potted_max_hit).max().unwrap();
        assert_eq!(best_all, best_capped);
    }
}
