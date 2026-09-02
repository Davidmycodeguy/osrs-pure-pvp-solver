//! Account skill profiles (port of `pure_solver.accounts.AccountState`).

use anyhow::{bail, Result};

use crate::formula::Variables;
use crate::mechanics::MechanicRegistry;
use crate::rational::Rational;

pub const PINNED_COMBAT_FORMULA: &str = "osrs-wiki-combat-level-15305725";
pub const LEVEL_FIELDS: [&str; 6] = ["attack", "strength", "ranged", "magic", "prayer", "hitpoints"];
pub const DEFENCE_LEVEL: i64 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct AccountState {
    pub attack: i64,
    pub strength: i64,
    pub ranged: i64,
    pub magic: i64,
    pub prayer: i64,
    pub hitpoints: i64,
    /// Defence level; `DEFENCE_LEVEL` (1) for the original pure search.
    pub defence: i64,
}

impl AccountState {
    /// A 1-Defence account (the original pure search).
    pub fn new(attack: i64, strength: i64, ranged: i64, magic: i64, prayer: i64, hitpoints: i64) -> Result<AccountState> {
        AccountState::with_defence(attack, strength, ranged, magic, prayer, hitpoints, DEFENCE_LEVEL)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn with_defence(attack: i64, strength: i64, ranged: i64, magic: i64, prayer: i64, hitpoints: i64, defence: i64) -> Result<AccountState> {
        let account = AccountState {
            attack,
            strength,
            ranged,
            magic,
            prayer,
            hitpoints,
            defence,
        };
        let mut invalid: Vec<&str> = LEVEL_FIELDS
            .iter()
            .zip(account.levels())
            .filter(|(_, level)| !(1..=99).contains(level))
            .map(|(name, _)| *name)
            .collect();
        if !(1..=99).contains(&defence) {
            invalid.push("defence");
        }
        if !invalid.is_empty() {
            bail!("Skill levels must be between 1 and 99: {}", invalid.join(", "));
        }
        Ok(account)
    }

    /// Levels in `LEVEL_FIELDS` order: attack, strength, ranged, magic, prayer, hitpoints.
    pub fn levels(self) -> [i64; 6] {
        [self.attack, self.strength, self.ranged, self.magic, self.prayer, self.hitpoints]
    }

    pub fn defence(self) -> i64 {
        self.defence
    }

    /// Exact compiled form of the pinned formula; falls back to the JSON AST otherwise.
    pub fn combat_level(self, mechanics: &MechanicRegistry) -> Result<i64> {
        let mechanic = mechanics.require("combat_level")?;
        if mechanic.formula_version == PINNED_COMBAT_FORMULA {
            return Ok(compiled_combat_level(self));
        }
        let variables: Variables = LEVEL_FIELDS
            .iter()
            .zip(self.levels())
            .map(|(name, level)| (name.to_string(), Rational::int(level as i128)))
            .chain(std::iter::once(("defence".to_string(), Rational::int(self.defence as i128))))
            .collect();
        mechanics.evaluate_int("combat_level", &variables)
    }
}

pub fn dominant(attack: i64, strength: i64, ranged: i64, magic: i64) -> i64 {
    (attack + strength).max((ranged * 3).div_euclid(2)).max((magic * 3).div_euclid(2))
}

fn compiled_combat_level(account: AccountState) -> i64 {
    let base = 40 * (account.defence + account.hitpoints + account.prayer.div_euclid(2));
    (base + 52 * dominant(account.attack, account.strength, account.ranged, account.magic)).div_euclid(160)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compiled_combat_level_matches_known_values() {
        assert_eq!(
            compiled_combat_level(AccountState {
                attack: 35,
                strength: 35,
                ranged: 9,
                magic: 47,
                prayer: 1,
                hitpoints: 31,
                defence: 1
            }),
            30
        );
        assert_eq!(
            compiled_combat_level(AccountState {
                attack: 35,
                strength: 35,
                ranged: 9,
                magic: 48,
                prayer: 1,
                hitpoints: 31,
                defence: 1
            }),
            31
        );
        assert_eq!(
            compiled_combat_level(AccountState {
                attack: 30,
                strength: 20,
                ranged: 30,
                magic: 1,
                prayer: 1,
                hitpoints: 29,
                defence: 1
            }),
            23
        );
        // Four Defence levels cost one combat level, like Hitpoints.
        assert_eq!(
            compiled_combat_level(AccountState {
                attack: 35,
                strength: 35,
                ranged: 9,
                magic: 47,
                prayer: 1,
                hitpoints: 31,
                defence: 5
            }),
            31
        );
        assert!(AccountState::with_defence(1, 1, 1, 1, 1, 10, 0).is_err());
    }

    #[test]
    fn rejects_out_of_range_levels() {
        assert!(AccountState::new(0, 1, 1, 1, 1, 10).is_err());
        assert!(AccountState::new(1, 1, 1, 1, 1, 100).is_err());
    }
}
