//! Notional attrition race (`survivor_ranking._race_margin` / `_race_scenarios`):
//! closed-form v3 approximation with equal notional inventories for every row.

use rayon::prelude::*;

use super::{quantile, RaceScenario, RankingCandidate};
use crate::rational::Rational;

fn int(value: i64) -> Rational {
    Rational::from(value)
}

/// Compiled accuracy times expected successful damage, per tick.
pub fn style_dpt(attack_roll: i64, defence_roll: i64, max_hit: i64, cooldown_ticks: i64, successful_zero_to_one: bool) -> Rational {
    let accuracy = if attack_roll > defence_roll {
        Rational::one() - Rational::new(defence_roll as i128 + 2, 2 * (attack_roll as i128 + 1))
    } else {
        Rational::new(attack_roll as i128, 2 * (defence_roll as i128 + 1))
    };
    let expected_success = if max_hit == 0 {
        Rational::zero()
    } else if successful_zero_to_one {
        Rational::new(max_hit as i128, 2) + Rational::new(1, max_hit as i128 + 1)
    } else {
        Rational::new(max_hit as i128, 2)
    };
    accuracy * expected_success / int(cooldown_ticks)
}

pub fn best_dpt(attacker: &RankingCandidate, defender: &RankingCandidate, successful_zero_to_one: bool) -> Rational {
    attacker
        .styles
        .iter()
        .map(|style| {
            style_dpt(
                style.attack_roll,
                defender.defence_roll_for(&style.damage_type),
                style.max_hit,
                style.cooldown_ticks,
                successful_zero_to_one,
            )
        })
        .max()
        .expect("non-empty styles")
}

pub struct RaceInputs {
    pub eat_penalty: i64,
    pub food_slots: i64,
    pub heal_per_eat: i64,
}

/// Signed margin in heal units with each side's own food count.
#[allow(clippy::too_many_arguments)]
pub fn race_margin_with_food(
    candidate_hp: i64,
    opponent_hp: i64,
    outgoing: &Rational,
    incoming: &Rational,
    candidate_food: i64,
    opponent_food: i64,
    heal_per_eat: i64,
    eat_penalty: i64,
) -> Rational {
    let heal = int(heal_per_eat);
    let penalty = int(eat_penalty);
    if outgoing.is_zero() && incoming.is_zero() {
        return Rational::zero();
    }
    if outgoing.is_zero() {
        return -((int(candidate_hp) + int(candidate_food) * &heal) / &heal);
    }
    if incoming.is_zero() {
        return (int(opponent_hp) + int(opponent_food) * &heal) / &heal;
    }
    // v3 closed-form attrition: uptime shrinks as incoming damage forces eats.
    let candidate_uptime = &heal / (&heal + &penalty * incoming);
    let opponent_uptime = &heal / (&heal + &penalty * outgoing);
    let candidate_effective = outgoing * candidate_uptime;
    let opponent_effective = incoming * opponent_uptime;
    let candidate_ttk = (int(opponent_hp) + int(opponent_food) * &heal) / &candidate_effective;
    let opponent_ttk = (int(candidate_hp) + int(candidate_food) * &heal) / &opponent_effective;
    if candidate_ttk == opponent_ttk {
        Rational::zero()
    } else if candidate_ttk < opponent_ttk {
        (opponent_ttk - candidate_ttk) * opponent_effective / heal
    } else {
        -((candidate_ttk - opponent_ttk) * candidate_effective / heal)
    }
}

/// Signed margin in heal units; `outgoing`/`incoming` are the best DPT each way.
pub fn race_margin(candidate: &RankingCandidate, opponent: &RankingCandidate, outgoing: &Rational, incoming: &Rational, inputs: &RaceInputs) -> Rational {
    race_margin_with_food(
        candidate.hitpoints(),
        opponent.hitpoints(),
        outgoing,
        incoming,
        inputs.food_slots,
        inputs.food_slots,
        inputs.heal_per_eat,
        inputs.eat_penalty,
    )
}

/// Worst / p10 / mean / win fraction of one scenario's margins.
pub fn summarise_margins(eat_penalty: i64, margins: &[Rational]) -> RaceScenario {
    let wins = margins.iter().filter(|m| !m.is_zero() && !m.is_negative()).count();
    RaceScenario {
        eat_penalty,
        opponent_count: margins.len(),
        worst_margin_fish: margins.iter().min().cloned().expect("non-empty margins"),
        tenth_percentile_margin_fish: quantile(margins, 1, 10),
        mean_margin_fish: Rational::mean(margins),
        win_fraction: Rational::new(wins as i128, margins.len() as i128),
    }
}

pub struct RaceConfig<'a> {
    pub panel: &'a [usize],
    pub self_matchup_reserve: Option<usize>,
    pub eat_penalties: &'a [i64],
    pub food_slots: i64,
    pub heal_per_eat: i64,
    pub successful_zero_to_one: bool,
}

pub fn opponents_for(index: usize, config: &RaceConfig<'_>) -> Vec<usize> {
    let mut opponents: Vec<usize> = config.panel.iter().copied().filter(|&o| o != index).collect();
    // Panel rows swap their mirror for one deterministic ranking-only reserve so
    // every real candidate faces the same number of distinct opponents.
    if opponents.len() < config.panel.len() {
        if let Some(reserve) = config.self_matchup_reserve.filter(|&r| r != index) {
            opponents.push(reserve);
        }
    }
    if opponents.is_empty() {
        // The one-row case has no distinct opponent; its mirror is the neutral comparison.
        opponents.push(index);
    }
    opponents
}

fn scenarios_for(candidates: &[RankingCandidate], index: usize, config: &RaceConfig<'_>) -> Vec<RaceScenario> {
    let candidate = &candidates[index];
    let opponents = opponents_for(index, config);
    let flows: Vec<(Rational, Rational)> = opponents
        .iter()
        .map(|&o| {
            (
                best_dpt(candidate, &candidates[o], config.successful_zero_to_one),
                best_dpt(&candidates[o], candidate, config.successful_zero_to_one),
            )
        })
        .collect();
    config
        .eat_penalties
        .iter()
        .map(|&eat_penalty| {
            let inputs = RaceInputs {
                eat_penalty,
                food_slots: config.food_slots,
                heal_per_eat: config.heal_per_eat,
            };
            let margins: Vec<Rational> = opponents
                .iter()
                .zip(&flows)
                .map(|(&o, (outgoing, incoming))| race_margin(candidate, &candidates[o], outgoing, incoming, &inputs))
                .collect();
            summarise_margins(eat_penalty, &margins)
        })
        .collect()
}

pub fn race_scenarios(candidates: &[RankingCandidate], config: &RaceConfig<'_>) -> Vec<Vec<RaceScenario>> {
    (0..candidates.len())
        .into_par_iter()
        .map(|index| scenarios_for(candidates, index, config))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::style_dpt;
    use crate::rational::Rational;

    #[test]
    fn style_dpt_matches_closed_form() {
        // attack 100 > defence 50: accuracy = 1 - 52/202 = 75/101; expected = 4 + 1/9 = 37/9; /4 ticks.
        let expected = Rational::new(75, 101) * Rational::new(37, 9) / Rational::int(4);
        assert_eq!(style_dpt(100, 50, 8, 4, true), expected);
        // attack 40 <= defence 50: accuracy = 40/102.
        assert_eq!(style_dpt(40, 50, 8, 4, true), Rational::new(40, 102) * Rational::new(37, 9) / Rational::int(4));
        assert!(style_dpt(40, 50, 0, 4, true).is_zero());
    }
}
