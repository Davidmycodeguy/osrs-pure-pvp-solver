//! Streams a resolved survivor manifest into `RankingCandidate`s, validating
//! every field the way `survivor_ranking._parse_candidate` does.

use std::collections::{HashMap, HashSet};
use std::path::Path;

use anyhow::{anyhow, bail, Context, Result};
use num_bigint::BigInt;
use rayon::prelude::*;
use serde_json::Value;

use super::output::RANKED_FIELDS;
use super::{RankingCandidate, RankingStyle, CADENCE_SCOPE, DAMAGE_TYPES, DEFENCE_STATES, EQUIPMENT_NAME_COLUMNS, HP_THRESHOLDS, WINDOWS};
use crate::combat::CombatKernel;
use crate::matrix_table::ACCOUNT_COLUMNS;
use crate::rational::Rational;

const OMITTED_SOURCE_BLOBS: [&str; 2] = ["best_expected_damage_per_tick_json", "cadence_ko_probabilities_json"];
const PARSE_CHUNK: usize = 2_000;

fn required_columns() -> Vec<&'static str> {
    let mut columns = vec![
        "candidate_id",
        "resolved_signature",
        "resolved_styles_json",
        "best_expected_damage_per_tick_json",
        "cadence_ko_probabilities_json",
        "cadence_ko_scope",
        "profile_id",
        "attack_magic",
        "defence_stab",
        "defence_slash",
        "defence_crush",
        "defence_magic",
        "defence_ranged",
        "prayer",
        "weapon_type",
        "weapon_name",
        "weapon_slot",
        "two_handed",
    ];
    columns.extend(ACCOUNT_COLUMNS);
    columns.extend(EQUIPMENT_NAME_COLUMNS);
    columns
}

pub struct LoadedManifest {
    pub candidates: Vec<RankingCandidate>,
    pub source_fields: Vec<String>,
}

struct Header {
    index: HashMap<String, usize>,
    source_indices: Vec<usize>,
    source_fields: Vec<String>,
}

impl Header {
    fn new(fields: &csv::StringRecord) -> Result<Header> {
        let names: Vec<String> = fields.iter().map(str::to_owned).collect();
        let index: HashMap<String, usize> = names.iter().enumerate().map(|(i, n)| (n.clone(), i)).collect();
        let mut missing: Vec<&str> = required_columns().into_iter().filter(|c| !index.contains_key(*c)).collect();
        if !missing.is_empty() {
            missing.sort_unstable();
            bail!("Resolved survivor manifest is missing required columns: {}", missing.join(", "));
        }
        let (source_indices, source_fields): (Vec<usize>, Vec<String>) = names
            .iter()
            .enumerate()
            .filter(|(_, name)| !RANKED_FIELDS.contains(&name.as_str()) && !OMITTED_SOURCE_BLOBS.contains(&name.as_str()))
            .map(|(i, name)| (i, name.clone()))
            .unzip();
        Ok(Header {
            index,
            source_indices,
            source_fields,
        })
    }
}

struct Row<'a> {
    header: &'a Header,
    record: &'a csv::StringRecord,
    candidate_id: String,
}

impl Row<'_> {
    fn get(&self, column: &str) -> &str {
        self.header.index.get(column).and_then(|i| self.record.get(*i)).unwrap_or("")
    }

    fn int(&self, column: &str) -> Result<i64> {
        self.get(column)
            .trim()
            .parse()
            .map_err(|_| anyhow!("Candidate {:?} has invalid integer column {column:?}", self.candidate_id))
    }

    fn boolean(&self, column: &str) -> Result<bool> {
        match self.get(column).trim().to_ascii_lowercase().as_str() {
            "1" | "true" | "yes" => Ok(true),
            "0" | "false" | "no" => Ok(false),
            _ => bail!("Candidate {:?} has invalid boolean column {column:?}", self.candidate_id),
        }
    }

    fn json(&self, column: &str) -> Result<Value> {
        serde_json::from_str(self.get(column)).map_err(|_| anyhow!("Candidate {:?} has invalid JSON column {column:?}", self.candidate_id))
    }
}

fn json_integer(value: &Value, context: &str) -> Result<i64> {
    match value {
        Value::Number(number) => number.as_i64().ok_or_else(|| anyhow!("{context} must be an integer")),
        _ => bail!("{context} must be an integer"),
    }
}

/// Arbitrary-precision integer (KO denominators exceed 64 bits).
fn big_integer(value: &Value, context: &str) -> Result<BigInt> {
    let Value::Number(number) = value else {
        bail!("{context} has non-integer numerator or denominator")
    };
    let text = number.to_string();
    if text.contains(['.', 'e', 'E']) {
        bail!("{context} has non-integer numerator or denominator");
    }
    text.parse().map_err(|_| anyhow!("{context} has non-integer numerator or denominator"))
}

pub fn parse_fraction(value: Option<&Value>, context: &str, probability: bool) -> Result<Rational> {
    let map = value
        .and_then(Value::as_object)
        .ok_or_else(|| anyhow!("{context} must contain exactly numerator and denominator"))?;
    if map.len() != 2 || !map.contains_key("numerator") || !map.contains_key("denominator") {
        bail!("{context} must contain exactly numerator and denominator");
    }
    let numerator = big_integer(&map["numerator"], context)?;
    let denominator = big_integer(&map["denominator"], context)?;
    if denominator <= BigInt::from(0) {
        bail!("{context} denominator must be positive");
    }
    let result = Rational::from_bigints(numerator, denominator);
    if probability && (result.is_negative() || result > Rational::one()) {
        bail!("{context} must be a probability");
    }
    Ok(result)
}

fn parse_styles(value: &Value, candidate_id: &str) -> Result<Vec<RankingStyle>> {
    let items = match value {
        Value::Array(items) if !items.is_empty() => items,
        _ => bail!("Candidate {candidate_id:?} resolved styles must be a non-empty list"),
    };
    let required = [
        "style_id",
        "damage_type",
        "attack_roll",
        "max_hit",
        "potted_max_hit",
        "cooldown_ticks",
        "maximum_range",
    ];
    let mut styles = Vec::with_capacity(items.len());
    for (index, item) in items.iter().enumerate() {
        let context = format!("Candidate {candidate_id:?} resolved style {index}");
        let map = item
            .as_object()
            .filter(|m| required.iter().all(|k| m.contains_key(*k)))
            .ok_or_else(|| anyhow!("{context} is missing required fields"))?;
        let text = |key: &str| map[key].as_str().filter(|s| !s.is_empty()).map(str::to_owned);
        let (Some(style_id), Some(damage_type)) = (text("style_id"), text("damage_type")) else {
            bail!("{context} has invalid style_id or damage_type");
        };
        let field = |key: &str| json_integer(&map[key], &format!("{context} {key}"));
        let style = RankingStyle {
            style_id,
            damage_type,
            attack_roll: field("attack_roll")?,
            max_hit: field("max_hit")?,
            potted_max_hit: field("potted_max_hit")?,
            cooldown_ticks: field("cooldown_ticks")?,
            maximum_range: field("maximum_range")?,
        };
        if !DAMAGE_TYPES.contains(&style.damage_type.as_str()) {
            bail!("Candidate {candidate_id:?} has unsupported damage type {:?}", style.damage_type);
        }
        if style.attack_roll < 0 || style.max_hit < 0 || style.potted_max_hit < 0 || style.cooldown_ticks <= 0 || style.maximum_range <= 0 {
            bail!("Candidate {candidate_id:?} has invalid resolved style values");
        }
        styles.push(style);
    }
    let unique: HashSet<&str> = styles.iter().map(|s| s.style_id.as_str()).collect();
    if unique.len() != styles.len() {
        bail!("Candidate {candidate_id:?} has duplicate resolved style IDs");
    }
    styles.sort_by(|a, b| a.style_id.cmp(&b.style_id));
    Ok(styles)
}

fn parse_sustained(row: &Row<'_>) -> Result<[Rational; 3]> {
    let document = row.json("best_expected_damage_per_tick_json")?;
    let map = document
        .as_object()
        .ok_or_else(|| anyhow!("Candidate {:?} DPT document must be an object", row.candidate_id))?;
    let mut values = Vec::with_capacity(3);
    for state in DEFENCE_STATES {
        let value = parse_fraction(map.get(state), &format!("{} DPT {state}", row.candidate_id), false)?;
        if value.is_negative() {
            bail!("Candidate {:?} has negative expected damage", row.candidate_id);
        }
        values.push(value);
    }
    Ok(values.try_into().expect("three defence states"))
}

fn parse_ko_by_window(row: &Row<'_>) -> Result<[Rational; 4]> {
    let document = row.json("cadence_ko_probabilities_json")?;
    let map = document
        .as_object()
        .ok_or_else(|| anyhow!("Candidate {:?} KO document must be an object", row.candidate_id))?;
    let mut means = Vec::with_capacity(4);
    for window in WINDOWS {
        let mut values = Vec::with_capacity(DEFENCE_STATES.len() * HP_THRESHOLDS.len());
        for state in DEFENCE_STATES {
            for hp in HP_THRESHOLDS {
                let key = format!("{state}:{window}:{hp}");
                values.push(parse_fraction(map.get(&key), &format!("{} KO {key}", row.candidate_id), true)?);
            }
        }
        means.push(Rational::mean(&values));
    }
    Ok(means.try_into().expect("four windows"))
}

fn defence_rolls(kernel: &CombatKernel<'_>, row: &Row<'_>, styles: &[RankingStyle]) -> Result<[i64; 4]> {
    // Best available defensive style, matching the representative-defence screen.
    let style_bonus = kernel.styles.max_defence_bonus(styles.iter().map(|s| s.style_id.as_str()))?;
    let defence_level = row.int("account_defence")?;
    let mut rolls = [0i64; 4];
    for (slot, damage_type) in DAMAGE_TYPES.iter().enumerate() {
        rolls[slot] = kernel.defence_roll(defence_level, row.int(&format!("defence_{damage_type}"))?, style_bonus)?;
    }
    Ok(rolls)
}

fn parse_candidate(kernel: &CombatKernel<'_>, header: &Header, record: &csv::StringRecord) -> Result<RankingCandidate> {
    let candidate_id = header.index.get("candidate_id").and_then(|i| record.get(*i)).unwrap_or("").trim().to_owned();
    if candidate_id.is_empty() {
        bail!("Resolved survivor row has no candidate_id");
    }
    let row = Row { header, record, candidate_id };
    let styles = parse_styles(&row.json("resolved_styles_json")?, &row.candidate_id)?;
    let sustained_dpt = parse_sustained(&row)?;
    let ko_by_window = parse_ko_by_window(&row)?;
    let mut levels = [0i64; 7];
    for (slot, column) in ACCOUNT_COLUMNS.iter().enumerate() {
        levels[slot] = row.int(column)?;
    }
    if levels.iter().any(|level| *level < 1) {
        bail!("Candidate {:?} has a level below 1", row.candidate_id);
    }
    let equipment_names: [String; 8] = EQUIPMENT_NAME_COLUMNS.map(|column| row.get(column).to_owned());
    let cadence_scope = row.get("cadence_ko_scope");
    if cadence_scope != CADENCE_SCOPE {
        bail!("Candidate {:?} has unsupported cadence KO scope {cadence_scope:?}", row.candidate_id);
    }
    let defence_rolls = defence_rolls(kernel, &row, &styles)?;
    let mut damage_types: Vec<String> = styles.iter().map(|s| s.damage_type.clone()).collect();
    damage_types.sort();
    damage_types.dedup();
    let source_values = header.source_indices.iter().map(|i| record.get(*i).unwrap_or("").to_owned()).collect();
    Ok(RankingCandidate {
        resolved_signature: row.get("resolved_signature").to_owned(),
        profile_id: row.int("profile_id")?,
        magic_attack_bonus: row.int("attack_magic")?,
        magic_defence_bonus: row.int("defence_magic")?,
        prayer_bonus: row.int("prayer")?,
        weapon_type: row.get("weapon_type").to_owned(),
        weapon_name: row.get("weapon_name").to_owned(),
        weapon_slot: row.get("weapon_slot").to_owned(),
        two_handed: row.boolean("two_handed")?,
        sustain_average: Rational::mean(&sustained_dpt),
        sustain_worst: sustained_dpt.iter().min().cloned().expect("three states"),
        physical_defence_average: Rational::mean(&defence_rolls.map(Rational::from)),
        max_hit: styles.iter().map(|s| s.max_hit).max().expect("non-empty styles"),
        maximum_attack_roll: styles.iter().map(|s| s.attack_roll).max().expect("non-empty styles"),
        potted_max_hit: styles.iter().map(|s| s.potted_max_hit).max().expect("non-empty styles"),
        maximum_range: styles.iter().map(|s| s.maximum_range).max().expect("non-empty styles"),
        damage_types,
        candidate_id: row.candidate_id,
        levels,
        styles,
        sustained_dpt,
        ko_by_window,
        defence_rolls,
        equipment_names,
        source_values,
    })
}

/// Load, validate and sort (by candidate id) every survivor row.
pub fn load_ranking_candidates(path: &Path, kernel: &CombatKernel<'_>) -> Result<LoadedManifest> {
    let mut reader = csv::Reader::from_path(path).with_context(|| format!("cannot read {}", path.display()))?;
    let header = Header::new(reader.headers()?)?;
    let mut candidates: Vec<RankingCandidate> = Vec::new();
    let mut chunk: Vec<csv::StringRecord> = Vec::with_capacity(PARSE_CHUNK);
    let flush = |chunk: &mut Vec<csv::StringRecord>, candidates: &mut Vec<RankingCandidate>| -> Result<()> {
        let parsed: Vec<RankingCandidate> = chunk.par_iter().map(|record| parse_candidate(kernel, &header, record)).collect::<Result<_>>()?;
        candidates.extend(parsed);
        chunk.clear();
        Ok(())
    };
    for record in reader.records() {
        chunk.push(record?);
        if chunk.len() >= PARSE_CHUNK {
            flush(&mut chunk, &mut candidates)?;
        }
    }
    flush(&mut chunk, &mut candidates)?;
    if candidates.is_empty() {
        bail!("Resolved survivor manifest contains no candidates");
    }
    candidates.sort_by(|a, b| a.candidate_id.cmp(&b.candidate_id));
    if candidates.windows(2).any(|pair| pair[0].candidate_id == pair[1].candidate_id) {
        let duplicate = candidates
            .windows(2)
            .find(|pair| pair[0].candidate_id == pair[1].candidate_id)
            .expect("duplicate present");
        bail!("Resolved survivor manifest contains duplicate candidate {}", duplicate[0].candidate_id);
    }
    Ok(LoadedManifest {
        candidates,
        source_fields: header.source_fields,
    })
}
