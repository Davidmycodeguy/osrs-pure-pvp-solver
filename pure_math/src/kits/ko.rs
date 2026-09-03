//! Exact stack (arrow + KO hit) and switch-cadence KO tables, built from a
//! shared cache of per-style damage distributions and their convolution
//! powers.  Baseline kits reproduce Stage 3's `cadence_ko_probabilities`.
//!
//! Convolutions run on a dense integer form (one shared denominator, `u128`
//! mass) whenever nothing overflows, and fall back to the exact big-fraction
//! form otherwise.  Both paths yield the same normalised fractions.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};

use anyhow::{anyhow, bail, Context, Result};
use num_bigint::BigInt;
use num_integer::Integer;
use num_traits::{One, ToPrimitive};
use rayon::prelude::*;
use serde_json::Value;

use super::{Kit, KitKo, KitKoTables, FINISH_THRESHOLDS, MELEE_DAMAGE_TYPES, PROGRESS_EVERY, STACK_STYLE_FAMILY, STACK_WEAPON_TYPE};
use crate::combat::{CombatKernel, DamageDistribution, StyleTable};
use crate::ranking::{RankingCandidate, RankingStyle, DAMAGE_TYPES, DEFENCE_STATES, HP_THRESHOLDS, WINDOWS};
use crate::rational::Rational;

pub type RepresentativeRolls = BTreeMap<String, BTreeMap<String, i64>>;

/// `representative_defence_rolls` from a Stage 3 screen report.
pub fn load_representative_rolls(path: &Path) -> Result<RepresentativeRolls> {
    let text = std::fs::read_to_string(path).with_context(|| format!("cannot read screen report {}", path.display()))?;
    let document: Value = serde_json::from_str(&text).with_context(|| format!("invalid JSON in screen report {}", path.display()))?;
    let rolls = document
        .get("representative_defence_rolls")
        .ok_or_else(|| anyhow!("screen report {} has no representative_defence_rolls", path.display()))?;
    let parsed: RepresentativeRolls =
        serde_json::from_value(rolls.clone()).context("representative_defence_rolls must map label -> damage type -> integer roll")?;
    for label in DEFENCE_STATES {
        let by_type = parsed
            .get(label)
            .ok_or_else(|| anyhow!("representative_defence_rolls is missing the {label:?} state"))?;
        for damage_type in DAMAGE_TYPES {
            if !by_type.contains_key(damage_type) {
                bail!("representative_defence_rolls[{label:?}] is missing {damage_type:?}");
            }
        }
    }
    Ok(parsed)
}

/// KO-weapon attacks landing inside `window` when the primary fires at tick 0 and its cooldown carries over.
pub fn ko_attacks_in_window(window: i64, primary_cooldown: i64, ko_cooldown: i64) -> i64 {
    if primary_cooldown >= window {
        0
    } else {
        1 + (window - 1 - primary_cooldown) / ko_cooldown
    }
}

/// The rapid shortbow style that opens a range->melee stack, if the primary has one.
pub fn stack_style(candidate: &RankingCandidate) -> Option<&RankingStyle> {
    if candidate.weapon_type != STACK_WEAPON_TYPE {
        return None;
    }
    candidate
        .styles
        .iter()
        .find(|s| StyleTable::parts(&s.style_id).map(|(family, _)| family == STACK_STYLE_FAMILY).unwrap_or(false))
}

/// Everything a style's damage distribution depends on.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct StyleKey {
    pub damage_type: String,
    pub attack_roll: i64,
    pub max_hit: i64,
    pub cooldown_ticks: i64,
}

impl StyleKey {
    pub fn of(style: &RankingStyle) -> StyleKey {
        StyleKey {
            damage_type: style.damage_type.clone(),
            attack_roll: style.attack_roll,
            max_hit: style.max_hit,
            cooldown_ticks: style.cooldown_ticks,
        }
    }

    /// Melee styles use the Strength-potion max hit when a potion is carried; ranged and magic are unaffected.
    pub fn for_kit(style: &RankingStyle, potted: bool) -> StyleKey {
        let mut key = StyleKey::of(style);
        if potted && MELEE_DAMAGE_TYPES.contains(&style.damage_type.as_str()) {
            key.max_hit = style.potted_max_hit;
        }
        key
    }
}

/// A probability mass that can be convolved and summed from a threshold.
trait Mass: Sized {
    fn convolve(&self, other: &Self) -> Option<Self>;
    fn at_least(&self, hp: i64) -> Option<Rational>;
    /// E[max(damage - threshold, 0)].
    fn overshoot(&self, threshold: i64) -> Option<Rational>;
}

impl Mass for DamageDistribution {
    fn convolve(&self, other: &Self) -> Option<Self> {
        Some(DamageDistribution::convolve(self, other))
    }

    fn at_least(&self, hp: i64) -> Option<Rational> {
        Some(DamageDistribution::at_least(self, hp))
    }

    fn overshoot(&self, threshold: i64) -> Option<Rational> {
        Some(
            self.probability
                .range(threshold + 1..)
                .fold(Rational::zero(), |acc, (damage, chance)| acc + Rational::from(damage - threshold) * chance),
        )
    }
}

/// Integer mass per damage value over one shared denominator; exact while nothing overflows `u128`.
#[derive(Clone, Debug)]
struct Dense {
    mass: Vec<u128>,
    denominator: u128,
}

impl Dense {
    fn from_distribution(distribution: &DamageDistribution) -> Option<Dense> {
        let mut lcm = BigInt::one();
        for chance in distribution.probability.values() {
            lcm = lcm.lcm(chance.denominator());
        }
        let denominator = lcm.to_u128()?;
        let max = distribution.probability.keys().max().copied().unwrap_or(0);
        let mut mass = vec![0u128; usize::try_from(max).ok()? + 1];
        for (damage, chance) in &distribution.probability {
            let scaled = chance.numerator() * (&lcm / chance.denominator());
            mass[usize::try_from(*damage).ok()?] = scaled.to_u128()?;
        }
        Some(Dense { mass, denominator })
    }
}

impl Mass for Dense {
    fn convolve(&self, other: &Self) -> Option<Self> {
        let denominator = self.denominator.checked_mul(other.denominator)?;
        let mut mass = vec![0u128; self.mass.len() + other.mass.len() - 1];
        for (i, a) in self.mass.iter().enumerate().filter(|(_, a)| **a != 0) {
            for (j, b) in other.mass.iter().enumerate() {
                mass[i + j] = mass[i + j].checked_add(a.checked_mul(*b)?)?;
            }
        }
        Some(Dense { mass, denominator })
    }

    fn at_least(&self, hp: i64) -> Option<Rational> {
        let start = usize::try_from(hp.max(0)).ok()?.min(self.mass.len());
        let mut total: u128 = 0;
        for value in &self.mass[start..] {
            total = total.checked_add(*value)?;
        }
        Some(Rational::from_bigints(BigInt::from(total), BigInt::from(self.denominator)))
    }

    fn overshoot(&self, threshold: i64) -> Option<Rational> {
        let start = usize::try_from(threshold.max(0) + 1).ok()?.min(self.mass.len());
        let mut total: u128 = 0;
        for (damage, value) in self.mass.iter().enumerate().skip(start) {
            let over = u128::try_from(damage as i64 - threshold).ok()?;
            total = total.checked_add(value.checked_mul(over)?)?;
        }
        Some(Rational::from_bigints(BigInt::from(total), BigInt::from(self.denominator)))
    }
}

fn max_window() -> i64 {
    *WINDOWS.iter().max().expect("windows")
}

/// `exact[label][n]` = `n` hits of one style against that defence state (`n = 0` is no damage);
/// `dense` mirrors it in integer form when every power fits.
struct StylePowers {
    exact: Vec<Vec<DamageDistribution>>,
    dense: Option<Vec<Vec<Dense>>>,
}

impl StylePowers {
    fn build(kernel: &CombatKernel<'_>, key: &StyleKey, rolls: &RepresentativeRolls) -> Result<StylePowers> {
        let max_power = 1 + (max_window() - 1) / key.cooldown_ticks;
        let exact = DEFENCE_STATES
            .iter()
            .map(|label| {
                let chance = kernel.accuracy(key.attack_roll, rolls[*label][&key.damage_type])?;
                let single = DamageDistribution::from_success_chance(&chance, key.max_hit, kernel.zero_to_one);
                let mut list = vec![DamageDistribution::certain(0)];
                for n in 1..=max_power as usize {
                    let next = list[n - 1].convolve(&single);
                    list.push(next);
                }
                Ok(list)
            })
            .collect::<Result<Vec<_>>>()?;
        let dense = exact
            .iter()
            .map(|list| list.iter().map(Dense::from_distribution).collect::<Option<Vec<_>>>())
            .collect::<Option<Vec<_>>>();
        Ok(StylePowers { exact, dense })
    }
}

/// Shared per-style distributions for every primary and KO style in the run.
pub struct PmfCache {
    styles: HashMap<StyleKey, StylePowers>,
    /// HP healed by one food item; the kill-pressure threshold.
    heal_per_eat: i64,
    /// Whether melee styles are keyed on their potted max hit.
    potted: bool,
}

impl PmfCache {
    pub fn build(
        kernel: &CombatKernel<'_>,
        rolls: &RepresentativeRolls,
        candidates: &[RankingCandidate],
        kits: &[Kit],
        heal_per_eat: i64,
        potted: bool,
    ) -> Result<PmfCache> {
        let mut keys: HashSet<StyleKey> = HashSet::new();
        for candidate in candidates {
            keys.extend(candidate.styles.iter().map(|s| StyleKey::for_kit(s, potted)));
        }
        for ko in kits.iter().filter_map(|kit| kit.ko.as_ref()) {
            keys.extend(ko.styles.iter().map(|s| StyleKey::for_kit(s, potted)));
        }
        for spell in kits.iter().filter_map(|kit| kit.spell.as_ref()) {
            keys.insert(StyleKey::of(&spell.style));
        }
        let keys: Vec<StyleKey> = keys.into_iter().collect();
        let styles = keys
            .into_par_iter()
            .map(|key| StylePowers::build(kernel, &key, rolls).map(|powers| (key, powers)))
            .collect::<Result<HashMap<_, _>>>()?;
        Ok(PmfCache { styles, heal_per_eat, potted })
    }

    pub fn len(&self) -> usize {
        self.styles.len()
    }

    pub fn is_empty(&self) -> bool {
        self.styles.is_empty()
    }

    fn exact(&self, key: &StyleKey, label: usize, attacks: i64) -> Option<&DamageDistribution> {
        Some(&self.styles[key].exact[label][attacks as usize])
    }

    fn dense(&self, key: &StyleKey, label: usize, attacks: i64) -> Option<&Dense> {
        self.styles[key].dense.as_ref().map(|by_label| &by_label[label][attacks as usize])
    }
}

fn zeros() -> [Rational; 6] {
    std::array::from_fn(|_| Rational::zero())
}

fn best_by_threshold<P: Mass>(best: &mut [Rational; 6], total: &P) -> Option<()> {
    for (slot, hp) in HP_THRESHOLDS.iter().enumerate() {
        let value = total.at_least(*hp)?;
        if value > best[slot] {
            best[slot] = value;
        }
    }
    Some(())
}

/// Kill pressure of the best unanswerable burst against one defence state.
struct BurstRow {
    pressure: Rational,
    bite: Rational,
    finish: [Rational; 3],
}

/// Per defence state: stack row, one switch row per window, and the burst row.
struct KitRows {
    stack: Vec<[Rational; 6]>,
    switch: Vec<Vec<[Rational; 6]>>,
    burst: Vec<BurstRow>,
    max_burst: i64,
}

/// Highest damage one unanswerable burst can deal for these keys.
fn max_burst(keys: &KitKeys) -> i64 {
    let burst = match &keys.rapid {
        Some(rapid) => rapid.max_hit + keys.ko.iter().map(|k| k.max_hit).max().unwrap_or(0),
        None => keys.primary.iter().chain(&keys.ko).map(|k| k.max_hit).max().unwrap_or(0),
    };
    burst.max(keys.spell.as_ref().map_or(0, |s| s.max_hit))
}

/// The burst that can land inside one eat lock: the arrow + KO stack when the kit can stack,
/// otherwise the single hardest hit.  Candidates are compared by pressure, then finish odds.
fn burst_row<'a, P: Mass + Clone + 'a>(power: &impl Fn(&StyleKey, usize, i64) -> Option<&'a P>, keys: &KitKeys, label: usize, heal: i64) -> Option<BurstRow> {
    let mut candidates: Vec<P> = Vec::new();
    if let Some(rapid) = &keys.rapid {
        let arrow = power(rapid, label, 1)?;
        for key in &keys.ko {
            candidates.push(arrow.convolve(power(key, label, 1)?)?);
        }
        if let Some(spell) = &keys.spell {
            candidates.push(power(spell, label, 1)?.clone());
        }
    } else {
        for key in keys.primary.iter().chain(&keys.ko) {
            candidates.push(power(key, label, 1)?.clone());
        }
    }
    let mut best: Option<BurstRow> = None;
    for candidate in &candidates {
        let row = BurstRow {
            pressure: candidate.at_least(heal + 1)?,
            bite: candidate.overshoot(heal)?,
            finish: [
                candidate.at_least(FINISH_THRESHOLDS[0])?,
                candidate.at_least(FINISH_THRESHOLDS[1])?,
                candidate.at_least(FINISH_THRESHOLDS[2])?,
            ],
        };
        let better = match &best {
            None => true,
            Some(current) => {
                (&row.pressure, &row.finish[2], &row.finish[1], &row.finish[0])
                    > (&current.pressure, &current.finish[2], &current.finish[1], &current.finish[0])
            }
        };
        if better {
            best = Some(row);
        }
    }
    best.or(Some(BurstRow {
        pressure: Rational::zero(),
        bite: Rational::zero(),
        finish: std::array::from_fn(|_| Rational::zero()),
    }))
}

struct KitKeys {
    primary: Vec<StyleKey>,
    ko: Vec<StyleKey>,
    rapid: Option<StyleKey>,
    /// Carried spell: an extra opener and a single-hit burst candidate.
    spell: Option<StyleKey>,
}

fn kit_keys(candidate: &RankingCandidate, kit: &Kit, potted: bool) -> KitKeys {
    let primary: Vec<StyleKey> = candidate.styles.iter().map(|s| StyleKey::for_kit(s, potted)).collect();
    let ko: Vec<StyleKey> = kit
        .ko
        .as_ref()
        .map_or_else(Vec::new, |k| k.styles.iter().map(|s| StyleKey::for_kit(s, potted)).collect());
    let rapid = stack_style(candidate).map(|s| StyleKey::for_kit(s, potted)).filter(|_| !ko.is_empty());
    let spell = kit.spell.as_ref().map(|choice| StyleKey::of(&choice.style));
    let mut primary = primary;
    if let Some(key) = &spell {
        primary.push(key.clone());
    }
    KitKeys { primary, ko, rapid, spell }
}

fn switch_rows<'a, P: Mass + 'a>(
    power: &impl Fn(&StyleKey, usize, i64) -> Option<&'a P>,
    label: usize,
    primary: &StyleKey,
    ko: &[StyleKey],
    rows: &mut [[Rational; 6]],
) -> Option<()> {
    let single = power(primary, label, 1)?;
    for (slot, window) in WINDOWS.iter().enumerate() {
        best_by_threshold(&mut rows[slot], power(primary, label, 1 + (window - 1) / primary.cooldown_ticks)?)?;
    }
    for key in ko {
        let mut memo: Vec<(i64, P)> = Vec::new();
        for (slot, window) in WINDOWS.iter().enumerate() {
            let attacks = ko_attacks_in_window(*window, primary.cooldown_ticks, key.cooldown_ticks);
            if attacks == 0 {
                continue;
            }
            if !memo.iter().any(|(n, _)| *n == attacks) {
                memo.push((attacks, single.convolve(power(key, label, attacks)?)?));
            }
            let total = &memo.iter().find(|(n, _)| *n == attacks).expect("memoised").1;
            best_by_threshold(&mut rows[slot], total)?;
        }
    }
    Some(())
}

fn rows_with<'a, P: Mass + Clone + 'a>(power: &impl Fn(&StyleKey, usize, i64) -> Option<&'a P>, keys: &KitKeys, heal: i64) -> Option<KitRows> {
    let mut rows = KitRows {
        stack: (0..DEFENCE_STATES.len()).map(|_| zeros()).collect(),
        switch: (0..DEFENCE_STATES.len()).map(|_| WINDOWS.iter().map(|_| zeros()).collect()).collect(),
        burst: Vec::with_capacity(DEFENCE_STATES.len()),
        max_burst: max_burst(keys),
    };
    for label in 0..DEFENCE_STATES.len() {
        rows.burst.push(burst_row(power, keys, label, heal)?);
        if let Some(rapid) = &keys.rapid {
            let arrow = power(rapid, label, 1)?;
            for key in &keys.ko {
                best_by_threshold(&mut rows.stack[label], &arrow.convolve(power(key, label, 1)?)?)?;
            }
        }
        for key in &keys.primary {
            switch_rows(power, label, key, &keys.ko, &mut rows.switch[label])?;
        }
    }
    Some(rows)
}

fn kit_rows(cache: &PmfCache, candidate: &RankingCandidate, kit: &Kit) -> KitRows {
    let keys = kit_keys(candidate, kit, cache.potted);
    rows_with(&|key, label, n| cache.dense(key, label, n), &keys, cache.heal_per_eat)
        .or_else(|| rows_with(&|key, label, n| cache.exact(key, label, n), &keys, cache.heal_per_eat))
        .expect("the exact big-fraction path never fails")
}

fn summary(rows: &KitRows) -> KitKo {
    let labels = Rational::from(DEFENCE_STATES.len() as i64);
    let cells = Rational::from((DEFENCE_STATES.len() * HP_THRESHOLDS.len()) as i64);
    let stack_by_hp: [Rational; 6] = std::array::from_fn(|slot| {
        let total = rows.stack.iter().fold(Rational::zero(), |acc, row| acc + &row[slot]);
        total / &labels
    });
    let stack_mean = Rational::mean(&stack_by_hp);
    let switch_by_window: [Rational; 4] = std::array::from_fn(|window| {
        let total = rows
            .switch
            .iter()
            .flat_map(|by_window| by_window[window].iter())
            .fold(Rational::zero(), |acc, v| acc + v);
        total / &cells
    });
    let mean_over_labels = |value: &dyn Fn(&BurstRow) -> &Rational| rows.burst.iter().fold(Rational::zero(), |acc, row| acc + value(row)) / &labels;
    let pressure = mean_over_labels(&|row| &row.pressure);
    let bite = mean_over_labels(&|row| &row.bite);
    let finish: [Rational; 3] = std::array::from_fn(|slot| mean_over_labels(&|row| &row.finish[slot]));
    KitKo {
        stack_by_hp,
        stack_mean,
        switch_by_window,
        pressure,
        bite,
        finish,
        max_burst: rows.max_burst,
    }
}

/// Scoring reductions only (what every kit keeps in memory).
pub fn kit_ko(cache: &PmfCache, candidate: &RankingCandidate, kit: &Kit) -> KitKo {
    summary(&kit_rows(cache, candidate, kit))
}

/// Full `label:hp` and `label:window:hp` tables plus the reductions (report preview only).
pub fn kit_ko_tables(cache: &PmfCache, candidate: &RankingCandidate, kit: &Kit) -> KitKoTables {
    let rows = kit_rows(cache, candidate, kit);
    let mut stack = BTreeMap::new();
    let mut switch = BTreeMap::new();
    for (label_index, label) in DEFENCE_STATES.iter().enumerate() {
        for (slot, hp) in HP_THRESHOLDS.iter().enumerate() {
            stack.insert(format!("{label}:{hp}"), rows.stack[label_index][slot].clone());
            for (window_slot, window) in WINDOWS.iter().enumerate() {
                switch.insert(format!("{label}:{window}:{hp}"), rows.switch[label_index][window_slot][slot].clone());
            }
        }
    }
    KitKoTables {
        stack,
        switch,
        summary: summary(&rows),
    }
}

pub fn all_kit_ko(cache: &PmfCache, candidates: &[RankingCandidate], kits: &[Kit]) -> Vec<KitKo> {
    let done = AtomicUsize::new(0);
    kits.par_iter()
        .map(|kit| {
            let result = kit_ko(cache, &candidates[kit.primary], kit);
            let count = done.fetch_add(1, Ordering::Relaxed) + 1;
            if count.is_multiple_of(PROGRESS_EVERY) {
                eprintln!("[expand-ko-kits] ko tables {count}/{}", kits.len());
            }
            result
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kits::testing::{candidate, ruleset};
    use crate::kits::KoLoadout;

    fn rolls() -> RepresentativeRolls {
        DEFENCE_STATES
            .iter()
            .map(|label| {
                (
                    label.to_string(),
                    DAMAGE_TYPES.iter().chain(["magic"].iter()).map(|d| (d.to_string(), 1000)).collect(),
                )
            })
            .collect()
    }

    fn style(id: &str, damage_type: &str, attack_roll: i64, max_hit: i64, cooldown: i64) -> RankingStyle {
        RankingStyle {
            style_id: id.into(),
            damage_type: damage_type.into(),
            attack_roll,
            max_hit,
            potted_max_hit: max_hit,
            cooldown_ticks: cooldown,
            maximum_range: 1,
        }
    }

    fn ko(styles: Vec<RankingStyle>) -> KoLoadout {
        KoLoadout {
            weapon_id: 1319,
            weapon_name: "Rune 2h sword".into(),
            two_handed: true,
            neck_id: None,
            neck_name: None,
            switch_slots: 1,
            styles,
        }
    }

    fn cache_for(primary: &RankingCandidate, kit: &Kit) -> PmfCache {
        let (mechanics, _) = ruleset();
        let kernel = CombatKernel::new(&mechanics).unwrap();
        PmfCache::build(&kernel, &rolls(), std::slice::from_ref(primary), std::slice::from_ref(kit), 14, false).unwrap()
    }

    fn tables(primary: &RankingCandidate, kit: &Kit) -> KitKoTables {
        kit_ko_tables(&cache_for(primary, kit), primary, kit)
    }

    #[test]
    fn ko_attacks_in_window_follow_carried_cooldown() {
        assert_eq!(ko_attacks_in_window(8, 3, 7), 1);
        assert_eq!(ko_attacks_in_window(8, 3, 4), 2);
        assert_eq!(ko_attacks_in_window(4, 4, 7), 0);
        assert_eq!(ko_attacks_in_window(12, 3, 4), 3);
    }

    #[test]
    fn stack_matches_enumerated_two_hit_distribution() {
        // Attack roll 1000 vs defence 1000 -> accuracy = 1000 / (2 * 1001) for both hits.
        let (mut primary, _) = candidate(&[]);
        primary.weapon_type = "shortbow".into();
        primary.styles = vec![style("rapid_ranged", "ranged", 1000, 2, 3)];
        let kit = Kit {
            kit_id: "k".into(),
            primary: 0,
            ko: Some(ko(vec![style("aggressive_slash", "slash", 1000, 3, 7)])),
            spell: None,
            food_slots: 27,
        };
        let result = tables(&primary, &kit);
        let p = Rational::new(1000, 2002);
        let miss = Rational::one() - &p;
        // Arrow: miss->0, hit-> uniform over {0,1,2} with 0 becoming 1: P(1)=2p/3, P(2)=p/3.
        // 2H:    miss->0, hit-> {0,1,2,3} with 0->1:             P(1)=2p/4, P(2)=p/4, P(3)=p/4.
        let a = [miss.clone(), &p * Rational::new(2, 3), &p * Rational::new(1, 3)];
        let b = [miss.clone(), &p * Rational::new(2, 4), &p * Rational::new(1, 4), &p * Rational::new(1, 4)];
        let mut joint = vec![Rational::zero(); 6];
        for (i, pa) in a.iter().enumerate() {
            for (j, pb) in b.iter().enumerate() {
                joint[i + j] = &joint[i + j] + pa * pb;
            }
        }
        let at_least = |hp: usize| joint[hp..].iter().fold(Rational::zero(), |acc, v| acc + v);
        assert_eq!(result.stack["medium:5"], at_least(5));
        assert_eq!(result.stack["low:5"], at_least(5));
        assert_eq!(result.stack["high:10"], Rational::zero());
        assert_eq!(result.summary.stack_by_hp[0], at_least(5));
        assert_eq!(result.summary.stack_mean, Rational::mean(&result.summary.stack_by_hp));
    }

    #[test]
    fn no_stack_for_a_longbow_or_a_baseline_kit() {
        let (mut primary, _) = candidate(&[]);
        primary.weapon_type = "longbow".into();
        primary.styles = vec![style("rapid_ranged", "ranged", 1000, 2, 5)];
        let kit = Kit {
            kit_id: "k".into(),
            primary: 0,
            ko: Some(ko(vec![style("aggressive_slash", "slash", 1000, 3, 7)])),
            spell: None,
            food_slots: 27,
        };
        assert!(tables(&primary, &kit).stack.values().all(|v| v.is_zero()));
        primary.weapon_type = "shortbow".into();
        let baseline = Kit {
            kit_id: "b".into(),
            primary: 0,
            ko: None,
            spell: None,
            food_slots: 28,
        };
        assert!(tables(&primary, &baseline).summary.stack_mean.is_zero());
    }

    #[test]
    fn switch_table_never_drops_below_the_no_switch_table_and_baseline_matches_stage3_reduction() {
        let (mechanics, _) = ruleset();
        let kernel = CombatKernel::new(&mechanics).unwrap();
        let (mut primary, _) = candidate(&[]);
        primary.styles = vec![style("aggressive_slash", "slash", 3000, 8, 4)];
        let baseline = Kit {
            kit_id: "b".into(),
            primary: 0,
            ko: None,
            spell: None,
            food_slots: 28,
        };
        let base = tables(&primary, &baseline);
        assert!(base.stack.values().all(|v| v.is_zero()));
        // Stage 3 reduction: mean over 3 labels x 6 thresholds of max over styles of P(n hits >= hp).
        let chance = kernel.accuracy(3000, 1000).unwrap();
        let pmf = DamageDistribution::from_success_chance(&chance, 8, kernel.zero_to_one);
        for (slot, window) in WINDOWS.iter().enumerate() {
            let n = 1 + (window - 1) / 4;
            let mut total = DamageDistribution::certain(0);
            for _ in 0..n {
                total = total.convolve(&pmf);
            }
            let values: Vec<Rational> = HP_THRESHOLDS.iter().map(|hp| total.at_least(*hp)).collect();
            assert_eq!(base.summary.switch_by_window[slot], Rational::mean(&values), "window {window}");
        }
        let switched = Kit {
            kit_id: "k".into(),
            primary: 0,
            ko: Some(ko(vec![style("aggressive_slash", "slash", 3500, 14, 7)])),
            spell: None,
            food_slots: 27,
        };
        let with = tables(&primary, &switched);
        for (key, value) in &base.switch {
            assert!(with.switch[key] >= *value, "{key}");
        }
        assert!(
            with.switch["medium:8:15"] > base.switch["medium:8:15"],
            "scim then 2H inside 8 ticks beats scim alone"
        );
    }

    #[test]
    fn dense_and_exact_paths_agree() {
        let (mut primary, _) = candidate(&[]);
        primary.weapon_type = "shortbow".into();
        primary.styles = vec![style("rapid_ranged", "ranged", 9973, 12, 3), style("accurate_ranged", "ranged", 11000, 12, 4)];
        let kit = Kit {
            kit_id: "k".into(),
            primary: 0,
            ko: Some(ko(vec![
                style("aggressive_slash", "slash", 8191, 19, 7),
                style("aggressive_crush", "crush", 7777, 19, 4),
            ])),
            spell: None,
            food_slots: 27,
        };
        let cache = cache_for(&primary, &kit);
        let keys = kit_keys(&primary, &kit, false);
        assert!(cache.styles.values().all(|s| s.dense.is_some()), "realistic rolls fit the dense path");
        let dense = rows_with(&|key, label, n| cache.dense(key, label, n), &keys, 14).unwrap();
        let exact = rows_with(&|key, label, n| cache.exact(key, label, n), &keys, 14).unwrap();
        assert_eq!(dense.stack, exact.stack);
        assert_eq!(dense.switch, exact.switch);
        for (d, e) in dense.burst.iter().zip(&exact.burst) {
            assert_eq!(d.pressure, e.pressure);
            assert_eq!(d.bite, e.bite);
            assert_eq!(d.finish, e.finish);
        }
        assert!(dense.stack.iter().flatten().any(|v| !v.is_zero()));
    }

    #[test]
    fn kill_pressure_is_the_stack_beating_one_heal() {
        // Arrow max 12 and hammer max 14 at roll 1000 vs 1000; pressure = P(arrow + hammer > 14).
        let (mut primary, _) = candidate(&[]);
        primary.weapon_type = "shortbow".into();
        primary.styles = vec![style("rapid_ranged", "ranged", 1000, 12, 3)];
        let kit = Kit {
            kit_id: "k".into(),
            primary: 0,
            ko: Some(ko(vec![style("aggressive_slash", "slash", 1000, 14, 7)])),
            spell: None,
            food_slots: 27,
        };
        let full = tables(&primary, &kit);
        assert_eq!(
            full.summary.pressure,
            Rational::mean(&DEFENCE_STATES.iter().map(|l| full.stack[&format!("{l}:15")].clone()).collect::<Vec<_>>())
        );
        assert_eq!(full.summary.finish[1], full.summary.pressure, "finish at 15 equals beating a 14 heal");
        assert!(full.summary.bite > Rational::zero());
        assert!(full.summary.finish[0] > full.summary.finish[1] && full.summary.finish[1] > full.summary.finish[2]);
        // A melee primary with no stack uses its single hardest hit: a 14 max hit can never beat 14.
        let (mut melee, _) = candidate(&[]);
        melee.styles = vec![style("aggressive_slash", "slash", 3000, 10, 4)];
        let melee_kit = Kit {
            kit_id: "m".into(),
            primary: 0,
            ko: Some(ko(vec![style("aggressive_slash", "slash", 3000, 14, 7)])),
            spell: None,
            food_slots: 27,
        };
        let melee_full = tables(&melee, &melee_kit);
        assert!(melee_full.summary.pressure.is_zero());
        assert!(melee_full.summary.finish[0] > Rational::zero(), "but it can still finish someone at 10 HP");
    }

    #[test]
    fn summary_equals_table_reductions() {
        let (mut primary, _) = candidate(&[]);
        primary.weapon_type = "shortbow".into();
        primary.styles = vec![style("rapid_ranged", "ranged", 2000, 6, 3), style("accurate_ranged", "ranged", 2400, 6, 4)];
        let kit = Kit {
            kit_id: "k".into(),
            primary: 0,
            ko: Some(ko(vec![
                style("aggressive_slash", "slash", 3500, 14, 7),
                style("aggressive_crush", "crush", 3000, 14, 7),
            ])),
            spell: None,
            food_slots: 27,
        };
        let cache = cache_for(&primary, &kit);
        assert_eq!(cache.len(), 4);
        let fast = kit_ko(&cache, &primary, &kit);
        let full = kit_ko_tables(&cache, &primary, &kit);
        assert_eq!(fast, full.summary);
        let manual_stack_5 = Rational::mean(&DEFENCE_STATES.iter().map(|l| full.stack[&format!("{l}:5")].clone()).collect::<Vec<_>>());
        assert_eq!(fast.stack_by_hp[0], manual_stack_5);
        let switch = &full.switch;
        let cells: Vec<Rational> = DEFENCE_STATES
            .iter()
            .flat_map(|l| HP_THRESHOLDS.iter().map(move |hp| switch[&format!("{l}:8:{hp}")].clone()))
            .collect();
        assert_eq!(fast.switch_by_window[2], Rational::mean(&cells));
    }

    #[test]
    fn a_strength_potion_raises_melee_burst_but_not_ranged() {
        let (mechanics, _) = ruleset();
        let kernel = CombatKernel::new(&mechanics).unwrap();
        let (mut primary, _) = candidate(&[]);
        primary.weapon_type = "shortbow".into();
        primary.styles = vec![style("rapid_ranged", "ranged", 3000, 8, 3)];
        let mut hammer = style("aggressive_crush", "crush", 3000, 14, 6);
        hammer.potted_max_hit = 16;
        let kit = Kit {
            kit_id: "k".into(),
            primary: 0,
            ko: Some(ko(vec![hammer])),
            spell: None,
            food_slots: 26,
        };
        let plain = PmfCache::build(&kernel, &rolls(), std::slice::from_ref(&primary), std::slice::from_ref(&kit), 14, false).unwrap();
        let potted = PmfCache::build(&kernel, &rolls(), std::slice::from_ref(&primary), std::slice::from_ref(&kit), 14, true).unwrap();
        let without = kit_ko(&plain, &primary, &kit);
        let with = kit_ko(&potted, &primary, &kit);
        assert!(with.pressure > without.pressure, "potted hammer beats a fish more often");
        assert_eq!(without.max_burst, 8 + 14, "arrow max + hammer max");
        assert_eq!(with.max_burst, 8 + 16, "potted hammer max when a potion is carried");
        assert!(with.stack_by_hp[3] > without.stack_by_hp[3], "arrow + potted hammer reaches 20 more often");
        // The arrow alone is unaffected: a ranged-only kit is identical either way.
        let bow_only = Kit {
            kit_id: "b".into(),
            primary: 0,
            ko: None,
            spell: None,
            food_slots: 27,
        };
        let a = PmfCache::build(&kernel, &rolls(), std::slice::from_ref(&primary), std::slice::from_ref(&bow_only), 14, false).unwrap();
        let b = PmfCache::build(&kernel, &rolls(), std::slice::from_ref(&primary), std::slice::from_ref(&bow_only), 14, true).unwrap();
        assert_eq!(kit_ko(&a, &primary, &bow_only), kit_ko(&b, &primary, &bow_only));
    }

    #[test]
    fn max_burst_is_arrow_plus_ko_for_stack_kits_and_hardest_hit_otherwise() {
        let (mut primary, _) = candidate(&[]);
        primary.weapon_type = "shortbow".into();
        primary.styles = vec![style("rapid_ranged", "ranged", 3000, 7, 3)];
        let kit = Kit {
            kit_id: "k".into(),
            primary: 0,
            ko: Some(ko(vec![style("aggressive_crush", "crush", 3000, 14, 6)])),
            spell: None,
            food_slots: 27,
        };
        assert_eq!(tables(&primary, &kit).summary.max_burst, 21);
        let (mut melee, _) = candidate(&[]);
        melee.styles = vec![style("aggressive_slash", "slash", 3000, 10, 4)];
        let melee_kit = Kit {
            kit_id: "m".into(),
            primary: 0,
            ko: Some(ko(vec![style("aggressive_slash", "slash", 3000, 14, 7)])),
            spell: None,
            food_slots: 27,
        };
        assert_eq!(tables(&melee, &melee_kit).summary.max_burst, 14);
        let baseline = Kit {
            kit_id: "b".into(),
            primary: 0,
            ko: None,
            spell: None,
            food_slots: 28,
        };
        assert_eq!(tables(&primary, &baseline).summary.max_burst, 7);
    }

    #[test]
    fn a_carried_spell_is_a_burst_candidate_and_lowers_nothing() {
        use crate::kits::magic::SpellChoice;
        let (mut primary, _) = candidate(&[]);
        primary.weapon_type = "shortbow".into();
        primary.styles = vec![style("rapid_ranged", "ranged", 3000, 7, 3)];
        let spell = SpellChoice {
            name: "Fire Bolt".into(),
            style: style("spell:fire_bolt", "magic", 2256, 12, 5),
            rune_slots: 3,
        };
        let bow_only = Kit {
            kit_id: "b".into(),
            primary: 0,
            ko: None,
            spell: None,
            food_slots: 28,
        };
        let with_runes = Kit {
            kit_id: "r".into(),
            primary: 0,
            ko: None,
            spell: Some(spell),
            food_slots: 25,
        };
        let plain = tables(&primary, &bow_only).summary;
        let caster = tables(&primary, &with_runes).summary;
        assert_eq!(plain.max_burst, 7);
        assert_eq!(caster.max_burst, 12, "the spell is the hardest single hit");
        assert!(
            caster.finish[0] > plain.finish[0],
            "a 12-max spell finishes a 10 HP target more often than a 7-max arrow"
        );
        assert!(caster.pressure >= plain.pressure);
        assert!(caster.switch_by_window[3] >= plain.switch_by_window[3]);
    }

    #[test]
    fn representative_rolls_load_from_a_screen_report() {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../outputs/cb30-rust/resolved-screen-cb30.json");
        if !std::path::Path::new(path).exists() {
            eprintln!("skipping representative_rolls_load_from_a_screen_report: {path} not present (run the pipeline to generate it)");
            return;
        }
        let rolls = load_representative_rolls(std::path::Path::new(path)).unwrap();
        assert_eq!(rolls["medium"]["slash"], 1092);
    }
}
