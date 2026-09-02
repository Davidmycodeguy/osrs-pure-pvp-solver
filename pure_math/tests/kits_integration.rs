//! Stage 5 on a 30-row fixture: header, counts, determinism, and the
//! baseline-equals-Stage-4 invariant.

use std::collections::HashMap;
use std::path::PathBuf;

use pure_math::combat::CombatKernel;
use pure_math::items::load_items;
use pure_math::kits::output::{write_kits_csv, KIT_FIELDS};
use pure_math::kits::scores::rank_kits;
use pure_math::kits::KitConfig;
use pure_math::mechanics::MechanicRegistry;
use pure_math::ranking::scores::rank_survivor_manifest;
use pure_math::ranking::{RankedCandidate, RankingConfig};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn ruleset() -> PathBuf {
    root().join("../rulesets/osrs-f2p-v1")
}

fn manifest() -> PathBuf {
    root().join("tests/fixtures/kits/resolved-survivors-sample.csv")
}

fn screen_report() -> PathBuf {
    root().join("tests/fixtures/kits/resolved-screen-sample.json")
}

#[test]
fn fixture_run_is_deterministic_and_baselines_match_stage4() {
    let mechanics = MechanicRegistry::load(&ruleset().join("mechanics.json")).unwrap();
    let items = load_items(&ruleset().join("items.json")).unwrap();
    let kernel = CombatKernel::new(&mechanics).unwrap();
    let config = KitConfig {
        panel_size: 8,
        strength_potions: 0,
        magic: false,
        ..KitConfig::default()
    };
    let report = rank_kits(&manifest(), "fixture", &screen_report(), "fixture-report", &kernel, &items, &config).unwrap();
    assert_eq!(report.candidates.len(), 30);
    assert!(report.kits.len() > 30, "at least one survivor has a KO option");
    assert_eq!(report.kits.iter().filter(|k| k.is_baseline()).count(), 30);
    assert_eq!(report.rankings.len(), report.kits.len());

    let out_dir = std::env::temp_dir().join("pure_math_kits_integration");
    std::fs::create_dir_all(&out_dir).unwrap();
    let first = out_dir.join("kits-1.csv");
    let second = out_dir.join("kits-2.csv");
    write_kits_csv(&report, &first).unwrap();
    let again = rank_kits(&manifest(), "fixture", &screen_report(), "fixture-report", &kernel, &items, &config).unwrap();
    write_kits_csv(&again, &second).unwrap();
    let bytes_first = std::fs::read(&first).unwrap();
    assert_eq!(bytes_first, std::fs::read(&second).unwrap(), "two runs must be byte-identical");
    let header = String::from_utf8(bytes_first.split(|b| *b == b'\n').next().unwrap().to_vec()).unwrap();
    assert_eq!(header.trim_end(), KIT_FIELDS.join(","));
    assert!(bytes_first.windows(2).any(|w| w == b"\r\n"), "CRLF line endings");

    // Baseline kits must reproduce Stage 4's race numbers for the same candidate and panel size.
    let stage4 = rank_survivor_manifest(
        &manifest(),
        "fixture",
        &kernel,
        &RankingConfig {
            panel_size: 8,
            ..RankingConfig::default()
        },
    )
    .unwrap();
    let stage4_by_id: HashMap<&str, &RankedCandidate> = stage4.rankings.iter().map(|r| (stage4.candidates[r.index].candidate_id.as_str(), r)).collect();
    for ranked in report.rankings.iter().filter(|r| report.kits[r.index].is_baseline()) {
        let candidate = &report.candidates[report.kits[ranked.index].primary];
        let expected = stage4_by_id[candidate.candidate_id.as_str()];
        for (a, b) in ranked.race_scenarios.iter().zip(&expected.race_scenarios) {
            assert_eq!(a.eat_penalty, b.eat_penalty);
            assert_eq!(a.worst_margin_fish, b.worst_margin_fish, "{}", candidate.candidate_id);
            assert_eq!(a.tenth_percentile_margin_fish, b.tenth_percentile_margin_fish);
            assert_eq!(a.mean_margin_fish, b.mean_margin_fish);
            assert_eq!(a.win_fraction, b.win_fraction);
        }
        let ko = &report.ko_metrics[ranked.index];
        assert!(ko.stack_mean.is_zero());
        assert_eq!(
            ko.switch_by_window, candidate.ko_by_window,
            "baseline switch cadence equals Stage 3 cadence for {}",
            candidate.candidate_id
        );
    }

    // One carried Strength potion costs a slot everywhere and never lowers kill pressure.
    let potted = rank_kits(
        &manifest(),
        "fixture",
        &screen_report(),
        "fixture-report",
        &kernel,
        &items,
        &KitConfig {
            panel_size: 8,
            strength_potions: 1,
            magic: false,
            ..KitConfig::default()
        },
    )
    .unwrap();
    assert_eq!(potted.kits.len(), report.kits.len());
    for (a, b) in potted.kits.iter().zip(&report.kits) {
        assert_eq!(a.kit_id, b.kit_id);
        assert_eq!(a.food_slots, b.food_slots - 1);
    }
    for (a, b) in potted.ko_metrics.iter().zip(&report.ko_metrics) {
        assert!(a.pressure >= b.pressure);
    }

    // Magic adds a runes variant of a kit only when the spell out-hits the primary; runes cost food.
    let magic = rank_kits(
        &manifest(),
        "fixture",
        &screen_report(),
        "fixture-report",
        &kernel,
        &items,
        &KitConfig {
            panel_size: 8,
            strength_potions: 0,
            magic: true,
            ..KitConfig::default()
        },
    )
    .unwrap();
    assert!(magic.kits.len() >= report.kits.len());
    let casters = magic.kits.iter().filter(|k| k.spell.is_some()).count();
    assert!(casters > 0, "the fixture has accounts with enough Magic for an out-hitting spell");
    for kit in magic.kits.iter().filter(|k| k.spell.is_some()) {
        let spell = kit.spell.as_ref().unwrap();
        assert!(spell.style.max_hit > magic.candidates[kit.primary].max_hit);
        assert!(spell.rune_slots >= 1 && kit.food_slots <= 28 - spell.rune_slots);
        assert_eq!(spell.style.cooldown_ticks, 5);
    }
}
