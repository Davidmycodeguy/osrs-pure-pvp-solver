//! Attrition race per kit: best DPT over both loadouts, the kit's own food,
//! opponents unchanged from Stage 4's single-weapon panel.

use rayon::prelude::*;

use super::{Kit, PROGRESS_EVERY};
use crate::ranking::race::{best_dpt, opponents_for, race_margin_with_food, style_dpt, summarise_margins, RaceConfig};
use crate::ranking::{RaceScenario, RankingCandidate};
use crate::rational::Rational;

/// Best DPT across the primary, KO and spell styles versus this opponent's defence rolls
/// (`opponent_magic_roll` is the opponent's magic defence roll for a carried spell).
pub fn kit_outgoing(candidate: &RankingCandidate, kit: &Kit, opponent: &RankingCandidate, opponent_magic_roll: i64, zero_to_one: bool) -> Rational {
    let mut best = best_dpt(candidate, opponent, zero_to_one);
    if let Some(ko) = &kit.ko {
        best = ko
            .styles
            .iter()
            .map(|s| {
                style_dpt(
                    s.attack_roll,
                    opponent.defence_roll_for(&s.damage_type),
                    s.max_hit,
                    s.cooldown_ticks,
                    zero_to_one,
                )
            })
            .fold(best, Rational::max);
    }
    if let Some(spell) = &kit.spell {
        let s = &spell.style;
        best = best.max(style_dpt(s.attack_roll, opponent_magic_roll, s.max_hit, s.cooldown_ticks, zero_to_one));
    }
    best
}

fn scenarios_for(candidates: &[RankingCandidate], magic_rolls: &[i64], kit: &Kit, config: &RaceConfig<'_>) -> Vec<RaceScenario> {
    let candidate = &candidates[kit.primary];
    let opponents = opponents_for(kit.primary, config);
    let flows: Vec<(Rational, Rational)> = opponents
        .iter()
        .map(|&o| {
            (
                kit_outgoing(candidate, kit, &candidates[o], magic_rolls[o], config.successful_zero_to_one),
                best_dpt(&candidates[o], candidate, config.successful_zero_to_one),
            )
        })
        .collect();
    config
        .eat_penalties
        .iter()
        .map(|&eat_penalty| {
            let margins: Vec<Rational> = opponents
                .iter()
                .zip(&flows)
                .map(|(&o, (outgoing, incoming))| {
                    race_margin_with_food(
                        candidate.hitpoints(),
                        candidates[o].hitpoints(),
                        outgoing,
                        incoming,
                        kit.food_slots,
                        config.food_slots,
                        config.heal_per_eat,
                        eat_penalty,
                    )
                })
                .collect();
            summarise_margins(eat_penalty, &margins)
        })
        .collect()
}

/// `config.food_slots` is the opponent's (full inventory) food; each kit uses its own `food_slots`.
pub fn kit_race_scenarios(candidates: &[RankingCandidate], magic_rolls: &[i64], kits: &[Kit], config: &RaceConfig<'_>) -> Vec<Vec<RaceScenario>> {
    let done = std::sync::atomic::AtomicUsize::new(0);
    kits.par_iter()
        .map(|kit| {
            let result = scenarios_for(candidates, magic_rolls, kit, config);
            let count = done.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
            if count.is_multiple_of(PROGRESS_EVERY) {
                eprintln!("[expand-ko-kits] races {count}/{}", kits.len());
            }
            result
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kits::testing::candidate;
    use crate::kits::KoLoadout;
    use crate::ranking::race::race_scenarios;
    use crate::ranking::RankingStyle;

    fn style(damage_type: &str, attack_roll: i64, max_hit: i64, cooldown: i64) -> RankingStyle {
        RankingStyle {
            style_id: format!("aggressive_{damage_type}"),
            damage_type: damage_type.into(),
            attack_roll,
            max_hit,
            potted_max_hit: max_hit,
            cooldown_ticks: cooldown,
            maximum_range: 1,
        }
    }

    fn population() -> Vec<RankingCandidate> {
        let (a, _) = candidate(&[]);
        let mut b = a.clone();
        b.candidate_id = "test-candidate-b".into();
        b.styles = vec![style("crush", 2500, 9, 5)];
        b.defence_rolls = [900, 1200, 800, 1000];
        let mut c = a.clone();
        c.candidate_id = "test-candidate-c".into();
        c.styles = vec![style("ranged", 2800, 6, 3)];
        vec![a, b, c]
    }

    fn config(panel: &[usize]) -> RaceConfig<'_> {
        RaceConfig {
            panel,
            self_matchup_reserve: None,
            eat_penalties: &[3, 0],
            food_slots: 28,
            heal_per_eat: 14,
            successful_zero_to_one: true,
        }
    }

    #[test]
    fn baseline_kits_reproduce_stage4_race_scenarios() {
        let candidates = population();
        let panel = vec![0usize, 1, 2];
        let config = config(&panel);
        let kits: Vec<Kit> = (0..3)
            .map(|i| Kit {
                kit_id: format!("k{i}"),
                primary: i,
                ko: None,
                spell: None,
                food_slots: 28,
            })
            .collect();
        let expected = race_scenarios(&candidates, &config);
        let actual = kit_race_scenarios(&candidates, &[512, 512, 512], &kits, &config);
        for (kit, stage4) in actual.iter().zip(&expected) {
            for (a, b) in kit.iter().zip(stage4) {
                assert_eq!(a.eat_penalty, b.eat_penalty);
                assert_eq!(a.worst_margin_fish, b.worst_margin_fish);
                assert_eq!(a.tenth_percentile_margin_fish, b.tenth_percentile_margin_fish);
                assert_eq!(a.mean_margin_fish, b.mean_margin_fish);
                assert_eq!(a.win_fraction, b.win_fraction);
            }
        }
    }

    #[test]
    fn ko_weapon_raises_outgoing_only_where_it_out_damages_the_primary() {
        let candidates = population();
        let ko = KoLoadout {
            weapon_id: 1319,
            weapon_name: "Rune 2h sword".into(),
            two_handed: true,
            neck_id: None,
            neck_name: None,
            switch_slots: 1,
            styles: vec![style("slash", 3500, 14, 7)],
        };
        let kit = Kit {
            kit_id: "k".into(),
            primary: 0,
            ko: Some(ko),
            spell: None,
            food_slots: 27,
        };
        let baseline = Kit {
            kit_id: "b".into(),
            primary: 0,
            ko: None,
            spell: None,
            food_slots: 28,
        };
        let with = kit_outgoing(&candidates[0], &kit, &candidates[1], 512, true);
        let without = kit_outgoing(&candidates[0], &baseline, &candidates[1], 512, true);
        assert!(with >= without);
        assert_eq!(without, best_dpt(&candidates[0], &candidates[1], true));
    }

    #[test]
    fn fewer_food_slots_lower_the_margin() {
        let candidates = population();
        let panel = vec![0usize, 1, 2];
        let config = config(&panel);
        let full = Kit {
            kit_id: "f".into(),
            primary: 0,
            ko: None,
            spell: None,
            food_slots: 28,
        };
        let short = Kit {
            kit_id: "s".into(),
            primary: 0,
            ko: None,
            spell: None,
            food_slots: 26,
        };
        let scenarios = kit_race_scenarios(&candidates, &[512, 512, 512], &[full, short], &config);
        assert!(scenarios[1][0].mean_margin_fish < scenarios[0][0].mean_margin_fish);
    }

    #[test]
    fn a_carried_spell_raises_outgoing_against_weak_magic_defence() {
        use crate::kits::magic::SpellChoice;
        let candidates = population();
        let spell = SpellChoice {
            name: "Fire Bolt".into(),
            style: style("magic", 2256, 12, 5),
            rune_slots: 3,
        };
        let caster = Kit {
            kit_id: "c".into(),
            primary: 0,
            ko: None,
            spell: Some(spell),
            food_slots: 25,
        };
        let baseline = Kit {
            kit_id: "b".into(),
            primary: 0,
            ko: None,
            spell: None,
            food_slots: 28,
        };
        let weak = kit_outgoing(&candidates[0], &caster, &candidates[1], 512, true);
        let plain = kit_outgoing(&candidates[0], &baseline, &candidates[1], 512, true);
        assert!(weak > plain, "a 12-max spell at 5 ticks out-damages an 8-max scimitar against a 512 magic roll");
        let strong = kit_outgoing(&candidates[0], &caster, &candidates[1], 50_000, true);
        assert_eq!(strong, plain, "against a huge magic defence the spell is not chosen");
    }
}
