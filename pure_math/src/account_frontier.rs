//! Exact combat-level account profiles at one or more Defence levels (1-Defence pures by default)
//! (port of `pure_solver.account_frontier`).

use std::collections::{BTreeMap, HashMap};

use anyhow::{bail, Result};

use crate::accounts::{dominant, AccountState, DEFENCE_LEVEL, PINNED_COMBAT_FORMULA};
use crate::experience::{standard_f2p_hitpoints_levels_with_defence, MAX_LEVEL, STARTING_HITPOINTS};
use crate::mechanics::MechanicRegistry;
use crate::prayers::relevant_prayer_levels;

const HP_PRAYER_WEIGHT: i64 = 40;
const DOMINANT_WEIGHT: i64 = 52;
const COMBAT_DENOMINATOR: i64 = 160;

#[derive(Clone, Debug)]
pub struct AccountFrontier {
    pub combat_level: i64,
    pub defence_levels: Vec<i64>,
    pub prayer_levels: Vec<i64>,
    pub raw_count: usize,
    pub full_frontier: Vec<AccountState>,
    pub ranking_frontier: Vec<AccountState>,
}

fn require_pinned_formula(mechanics: &MechanicRegistry) -> Result<()> {
    let mechanic = mechanics.require("combat_level")?;
    if mechanic.formula_version != PINNED_COMBAT_FORMULA {
        bail!(
            "Account frontier requires combat formula {PINNED_COMBAT_FORMULA:?}, got {:?}",
            mechanic.formula_version
        );
    }
    Ok(())
}

/// Verified prayer breakpoints lifted to the odd level that costs the same combat.
pub fn prayer_level_choices(mechanics: &MechanicRegistry) -> Result<Vec<i64>> {
    let lifted: std::collections::BTreeSet<i64> = relevant_prayer_levels(mechanics, true, true)?
        .into_iter()
        .map(|level| if level % 2 == 1 { level } else { (level + 1).min(MAX_LEVEL) })
        .collect();
    Ok(lifted.into_iter().collect())
}

fn combat_numerator(defence: i64, hitpoints: i64, prayer: i64, dominant_term: i64) -> i64 {
    HP_PRAYER_WEIGHT * (defence + hitpoints + prayer.div_euclid(2)) + DOMINANT_WEIGHT * dominant_term
}

/// Highest Magic level keeping the combat level exact, or None if unreachable.
pub fn maximum_magic_for_combat(attack: i64, strength: i64, ranged: i64, prayer: i64, hitpoints: i64, combat_level: i64) -> Option<i64> {
    maximum_magic_for_combat_with_defence(attack, strength, ranged, prayer, hitpoints, DEFENCE_LEVEL, combat_level)
}

#[allow(clippy::too_many_arguments)]
pub fn maximum_magic_for_combat_with_defence(
    attack: i64,
    strength: i64,
    ranged: i64,
    prayer: i64,
    hitpoints: i64,
    defence: i64,
    combat_level: i64,
) -> Option<i64> {
    let low = COMBAT_DENOMINATOR * combat_level;
    let high = COMBAT_DENOMINATOR * (combat_level + 1) - 1;
    let mut best = None;
    for magic in 1..=MAX_LEVEL {
        let numerator = combat_numerator(defence, hitpoints, prayer, dominant(attack, strength, ranged, magic));
        if numerator > high {
            break;
        }
        if numerator >= low {
            best = Some(magic);
        }
    }
    best
}

fn melee_ranged_triples(combat_level: i64, defence: i64) -> Vec<(i64, i64, i64)> {
    let high = COMBAT_DENOMINATOR * (combat_level + 1) - 1;
    let floor_cost = HP_PRAYER_WEIGHT * (defence + STARTING_HITPOINTS);
    let mut triples = Vec::new();
    for attack in 1..=MAX_LEVEL {
        for strength in 1..=MAX_LEVEL {
            if DOMINANT_WEIGHT * (attack + strength) + floor_cost > high {
                break;
            }
            for ranged in 1..=MAX_LEVEL {
                if DOMINANT_WEIGHT * dominant(attack, strength, ranged, 1) + floor_cost > high {
                    break;
                }
                triples.push((attack, strength, ranged));
            }
        }
    }
    triples
}

/// Every Magic-max-filled account at exactly `combat_level`, over every listed Defence level
/// (defensive-style training feeds the Hitpoints floor), each re-verified against the formula.
pub fn enumerate_exact_combat_accounts_with_defence(
    mechanics: &MechanicRegistry,
    combat_level: i64,
    prayer_levels: &[i64],
    defence_levels: &[i64],
) -> Result<Vec<AccountState>> {
    require_pinned_formula(mechanics)?;
    let mut accounts = Vec::new();
    for &defence in defence_levels {
        for (attack, strength, ranged) in melee_ranged_triples(combat_level, defence) {
            let hitpoints_levels = standard_f2p_hitpoints_levels_with_defence(attack, strength, ranged, defence, mechanics)?;
            for &prayer in prayer_levels {
                for &hitpoints in &hitpoints_levels {
                    let Some(magic) = maximum_magic_for_combat_with_defence(attack, strength, ranged, prayer, hitpoints, defence, combat_level) else {
                        continue;
                    };
                    let account = AccountState::with_defence(attack, strength, ranged, magic, prayer, hitpoints, defence)?;
                    if account.combat_level(mechanics)? != combat_level {
                        bail!("Compiled combat arithmetic disagrees with the verified combat-level formula");
                    }
                    accounts.push(account);
                }
            }
        }
    }
    Ok(accounts)
}

/// Pareto dimensions: attack, strength, ranged, prayer, hitpoints, defence (index 6).
const COMPARED: [usize; 6] = [0, 1, 2, 4, 5, 6];

/// Drop accounts another account matches or beats in every compared skill.
/// Magic is a group key when it counts (it is always max-filled), otherwise ignored.
pub fn pareto_frontier(accounts: &[AccountState], ignore_magic: bool) -> Vec<AccountState> {
    let grouping: &[usize] = if ignore_magic { &[] } else { &[3] };
    // Every compared dimension except Hitpoints (index 5) keys the cheap highest-HP pre-pass.
    let key_indices: Vec<usize> = (0..7).filter(|i| *i != 5 && (COMPARED.contains(i) || grouping.contains(i))).collect();
    let mut groups: BTreeMap<Vec<i64>, Vec<[i64; 7]>> = BTreeMap::new();
    for levels in highest_hitpoints_only(accounts, &key_indices) {
        groups.entry(grouping.iter().map(|&i| levels[i]).collect()).or_default().push(levels);
    }
    let mut survivors: Vec<AccountState> = groups.into_values().flat_map(group_frontier).collect();
    survivors.sort_by_key(|a| a.levels());
    survivors
}

/// Cheap pre-pass: with every other level equal, only the highest HP can survive.
fn highest_hitpoints_only(accounts: &[AccountState], key_indices: &[usize]) -> Vec<[i64; 7]> {
    let mut best: HashMap<Vec<i64>, [i64; 7]> = HashMap::new();
    for account in accounts {
        let levels = levels_with_defence(*account);
        let key: Vec<i64> = key_indices.iter().map(|&i| levels[i]).collect();
        match best.get(&key) {
            Some(current) if current[5] >= levels[5] => {}
            _ => {
                best.insert(key, levels);
            }
        }
    }
    best.into_values().collect()
}

fn levels_with_defence(account: AccountState) -> [i64; 7] {
    let l = account.levels();
    [l[0], l[1], l[2], l[3], l[4], l[5], account.defence]
}

fn group_frontier(mut members: Vec<[i64; 7]>) -> Vec<AccountState> {
    // Descending compared-sum; stable so equal sums keep their arrival order like Python's sort.
    members.sort_by_key(|levels| -COMPARED.iter().map(|&i| levels[i]).sum::<i64>());
    let mut kept: Vec<[i64; 7]> = Vec::new();
    for levels in members {
        if kept.iter().any(|other| COMPARED.iter().all(|&i| other[i] >= levels[i])) {
            continue;
        }
        kept.push(levels);
    }
    kept.into_iter()
        .map(|levels| from_levels_with_defence([levels[0], levels[1], levels[2], levels[3], levels[4], levels[5]], levels[6]))
        .collect()
}

pub fn from_levels(levels: [i64; 6]) -> AccountState {
    from_levels_with_defence(levels, DEFENCE_LEVEL)
}

pub fn from_levels_with_defence(levels: [i64; 6], defence: i64) -> AccountState {
    AccountState {
        attack: levels[0],
        strength: levels[1],
        ranged: levels[2],
        magic: levels[3],
        prayer: levels[4],
        hitpoints: levels[5],
        defence,
    }
}

/// `1-40`, `1,5,10`, or a mix; deduplicated and sorted.
pub fn parse_defence_levels(text: &str) -> Result<Vec<i64>> {
    let mut levels: Vec<i64> = Vec::new();
    for part in text.split([',', ' ']).filter(|p| !p.is_empty()) {
        let (low, high) = match part.split_once('-') {
            Some((a, b)) => (a.trim().parse::<i64>(), b.trim().parse::<i64>()),
            None => (part.trim().parse::<i64>(), part.trim().parse::<i64>()),
        };
        let (Ok(low), Ok(high)) = (low, high) else {
            bail!("--defence-levels: {part:?} is not a level or a range like 1-40")
        };
        if low < 1 || high > MAX_LEVEL || low > high {
            bail!("--defence-levels: {part:?} must stay within 1..=99 and ascend");
        }
        levels.extend(low..=high);
    }
    levels.sort_unstable();
    levels.dedup();
    if levels.is_empty() {
        bail!("--defence-levels must name at least one level");
    }
    Ok(levels)
}

/// Pareto is taken within each Defence level and the frontiers are concatenated: an exact
/// combat level leaves no slack for a lower-Defence account to be dominated by a higher one
/// in every other skill, and per-level frontiers keep the quadratic dominance pass tractable.
pub fn build_account_frontier_with_defence(mechanics: &MechanicRegistry, combat_level: i64, defence_levels: &[i64]) -> Result<AccountFrontier> {
    let prayer_levels = prayer_level_choices(mechanics)?;
    let mut raw_count = 0usize;
    let mut full_frontier = Vec::new();
    let mut ranking_frontier = Vec::new();
    for &defence in defence_levels {
        let raw = enumerate_exact_combat_accounts_with_defence(mechanics, combat_level, &prayer_levels, &[defence])?;
        raw_count += raw.len();
        full_frontier.extend(pareto_frontier(&raw, false));
        ranking_frontier.extend(pareto_frontier(&raw, true));
    }
    if raw_count == 0 {
        bail!("No account with Defence in {defence_levels:?} reaches combat level {combat_level} exactly");
    }
    full_frontier.sort_by_key(|a| (a.levels(), a.defence));
    ranking_frontier.sort_by_key(|a| (a.levels(), a.defence));
    Ok(AccountFrontier {
        combat_level,
        defence_levels: defence_levels.to_vec(),
        prayer_levels,
        raw_count,
        full_frontier,
        ranking_frontier,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maximum_magic_keeps_combat_exact() {
        assert_eq!(maximum_magic_for_combat(35, 35, 9, 1, 31, 30), Some(47));
        assert_eq!(maximum_magic_for_combat(30, 20, 30, 1, 28, 30), Some(49));
    }

    #[test]
    fn pareto_frontier_drops_dominated_accounts() {
        let weaker = from_levels([30, 30, 1, 40, 1, 30]);
        let stronger_hp = from_levels([30, 30, 1, 40, 1, 31]);
        let stronger_prayer = from_levels([30, 30, 1, 40, 5, 30]);
        let more_magic = from_levels([30, 30, 1, 42, 1, 30]);
        let accounts = [weaker, stronger_hp, stronger_prayer, more_magic];
        let with_magic = pareto_frontier(&accounts, false);
        assert!(!with_magic.contains(&weaker));
        assert!(with_magic.contains(&more_magic));
        let without_magic = pareto_frontier(&accounts, true);
        assert_eq!(without_magic, vec![stronger_hp, stronger_prayer]);
    }

    #[test]
    fn defence_is_a_pareto_dimension_and_costs_combat_level() {
        let pure = from_levels_with_defence([30, 30, 1, 40, 1, 30], 1);
        let tank = from_levels_with_defence([30, 30, 1, 40, 1, 30], 20);
        let frontier = pareto_frontier(&[pure, tank], true);
        assert_eq!(frontier, vec![tank], "more Defence with everything else equal dominates");
        // Defence 5 pushes the same account from combat 30 to 31, so max Magic must drop to compensate.
        assert_eq!(maximum_magic_for_combat_with_defence(35, 35, 9, 1, 31, 1, 30), Some(47));
        assert!(maximum_magic_for_combat_with_defence(35, 35, 9, 1, 31, 5, 30).is_none());
    }

    #[test]
    fn defence_levels_parse_ranges_and_lists() {
        assert_eq!(parse_defence_levels("1-5").unwrap(), vec![1, 2, 3, 4, 5]);
        assert_eq!(parse_defence_levels("40,1,10-12").unwrap(), vec![1, 10, 11, 12, 40]);
        assert!(parse_defence_levels("0-3").is_err());
        assert!(parse_defence_levels("x").is_err());
    }
}
