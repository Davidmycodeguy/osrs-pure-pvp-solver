//! `export-account-gear-matrix <ruleset> <accounts.csv> [--kit-mode=offence_pareto] [--keep-defensive=false] [--completed-quests=..] [--csv-output=..]`

use std::path::Path;

use anyhow::Result;
use serde_json::json;

use crate::cli::Args;
use crate::gear_matrix::{GearRow, EMPTY_NAME, MATRIX_ARMOUR_SLOTS, MATRIX_SKILLS};
use crate::io::{csv_writer, read_account_csv};
use crate::items::{load_items, EquipmentItem, BONUS_COLUMNS, REQUIREMENT_COLUMNS};

pub fn gear_matrix_header() -> Vec<String> {
    let mut header = vec!["profile_id".to_owned()];
    for skill in MATRIX_SKILLS {
        header.push(format!("{skill}_min"));
        header.push(format!("{skill}_max"));
    }
    header.extend(["defence", "hitpoints"].map(str::to_owned));
    header.extend(
        MATRIX_SKILLS
            .iter()
            .chain(["defence", "hitpoints"].iter())
            .map(|skill| format!("account_{skill}")),
    );
    for slot in MATRIX_ARMOUR_SLOTS.iter().chain(["weapon"].iter()) {
        header.push(format!("{slot}_id"));
        header.push(format!("{slot}_name"));
    }
    header.push("weapon_slot".to_owned());
    header.extend(["ammo_id", "ammo_name", "shield_id", "shield_name"].map(str::to_owned));
    header.extend(REQUIREMENT_COLUMNS.iter().map(|skill| format!("req_{skill}")));
    header.extend(BONUS_COLUMNS.iter().map(|b| b.to_string()));
    header.extend(
        [
            "weapon_type",
            "weapon_attack_speed",
            "weapon_attack_range",
            "weapon_attack_styles",
            "two_handed",
        ]
        .map(str::to_owned),
    );
    header
}

fn slot_columns(item: Option<&EquipmentItem>) -> [String; 2] {
    match item {
        Some(item) => [item.item_id.to_string(), item.name.clone()],
        None => [String::new(), EMPTY_NAME.to_owned()],
    }
}

fn optional(value: Option<i64>) -> String {
    value.map(|v| v.to_string()).unwrap_or_default()
}

/// Python `bool` rendering used by the original CSV writer.
pub fn python_bool(value: bool) -> &'static str {
    if value {
        "True"
    } else {
        "False"
    }
}

pub fn gear_matrix_record(row: &GearRow<'_>) -> Vec<String> {
    let account = row.account;
    let exact = [account.attack, account.strength, account.ranged, account.magic, account.prayer];
    let mut record = vec![row.profile_id.to_string()];
    for level in exact {
        record.push(level.to_string());
        record.push(level.to_string());
    }
    record.push("1".to_owned());
    record.push(account.hitpoints.to_string());
    record.extend(exact.iter().map(i64::to_string));
    record.push(account.defence().to_string());
    record.push(account.hitpoints.to_string());
    for item in row.armour.iter() {
        record.extend(slot_columns(*item));
    }
    record.extend(slot_columns(Some(row.weapon)));
    record.push(row.weapon.slot.clone());
    record.extend(slot_columns(row.ammo));
    record.extend(slot_columns(row.shield));
    let requirements = row.aggregate_requirements();
    record.extend(
        REQUIREMENT_COLUMNS
            .iter()
            .map(|skill| requirements.get(*skill).copied().unwrap_or(0).to_string()),
    );
    let bonuses = row.aggregate_bonuses();
    record.extend(BONUS_COLUMNS.iter().map(|bonus| bonuses[bonus].to_string()));
    record.push(row.weapon.weapon_type.clone().unwrap_or_default());
    record.push(optional(row.weapon.attack_speed));
    record.push(optional(row.weapon.attack_range));
    record.push(row.weapon.attack_styles.join(";"));
    record.push(python_bool(row.weapon.two_handed).to_owned());
    record
}

pub fn write_gear_matrix_csv(rows: &[GearRow<'_>], path: &Path) -> Result<()> {
    let mut writer = csv_writer(path)?;
    writer.write_record(gear_matrix_header())?;
    for row in rows {
        writer.write_record(gear_matrix_record(row))?;
    }
    writer.flush()?;
    Ok(())
}

pub fn run(args: &Args) -> Result<()> {
    let ruleset = args.path(1, "ruleset")?;
    let accounts_path = args.path(2, "accounts")?;
    let kit_mode = args.flag("kit-mode").unwrap_or("offence_pareto");
    let csv_output = args.flag_path("csv-output", "outputs/cb30/gear-matrix.csv");
    let keep_defensive = match args.flag("keep-defensive").unwrap_or("false") {
        "true" | "1" | "yes" => true,
        "false" | "0" | "no" => false,
        other => anyhow::bail!("--keep-defensive must be true or false, got {other:?}"),
    };
    if let Some(quests) = args.flag("completed-quests") {
        crate::items::set_completed_quests(quests.split(';').map(str::to_owned))?;
    }
    let items = load_items(&ruleset.join("items.json"))?;
    let accounts = read_account_csv(&accounts_path)?;
    let (rows, signature_count) = crate::gear_matrix::build_account_gear_matrix_with(&accounts, &items, kit_mode, keep_defensive)?;
    write_gear_matrix_csv(&rows, &csv_output)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "accounts": accounts.len(),
            "combination_count": rows.len(),
            "csv_output": csv_output.display().to_string(),
            "kit_mode": kit_mode,
            "keep_defensive": keep_defensive,
            "completed_quests": crate::items::completed_quests().iter().cloned().collect::<Vec<_>>(),
            "unlock_signatures": signature_count,
        }))?
    );
    Ok(())
}
