//! In-memory gear-matrix CSV with column lookup by name.  Rows keep their
//! original string fields so downstream manifests can echo them verbatim.

use std::collections::HashMap;
use std::path::Path;

use anyhow::{anyhow, bail, Context, Result};

use crate::items::BONUS_COLUMNS;

pub const ITEM_SLOTS: [&str; 8] = ["head", "neck", "body", "legs", "hands", "weapon", "ammo", "shield"];
pub const ACCOUNT_COLUMNS: [&str; 7] = [
    "account_attack",
    "account_strength",
    "account_ranged",
    "account_magic",
    "account_prayer",
    "account_defence",
    "account_hitpoints",
];
pub const BAND_SKILLS: [&str; 5] = ["attack", "strength", "ranged", "magic", "prayer"];

/// `_BAND_COLUMNS`: `{skill}_min, {skill}_max` for each band skill, in order.
pub fn band_columns() -> Vec<String> {
    BAND_SKILLS.iter().flat_map(|skill| [format!("{skill}_min"), format!("{skill}_max")]).collect()
}

pub fn required_columns() -> Vec<String> {
    let mut columns = vec!["profile_id".to_owned()];
    columns.extend(ACCOUNT_COLUMNS.iter().map(|c| c.to_string()));
    columns.extend(band_columns());
    columns.extend(ITEM_SLOTS.iter().map(|slot| format!("{slot}_id")));
    columns.extend(ITEM_SLOTS.iter().map(|slot| format!("{slot}_name")));
    columns.extend(BONUS_COLUMNS.iter().map(|c| c.to_string()));
    columns.extend(
        [
            "weapon_type",
            "weapon_attack_speed",
            "weapon_attack_range",
            "weapon_attack_styles",
            "two_handed",
        ]
        .map(str::to_owned),
    );
    columns
}

pub struct MatrixTable {
    pub headers: Vec<String>,
    index: HashMap<String, usize>,
    pub rows: Vec<csv::StringRecord>,
}

impl MatrixTable {
    pub fn read(path: &Path, required: &[String]) -> Result<MatrixTable> {
        let mut reader = csv::Reader::from_path(path).with_context(|| format!("cannot read {}", path.display()))?;
        let headers: Vec<String> = reader.headers()?.iter().map(str::to_owned).collect();
        let index: HashMap<String, usize> = headers.iter().enumerate().map(|(i, h)| (h.clone(), i)).collect();
        let mut missing: Vec<&str> = required.iter().filter(|c| !index.contains_key(*c)).map(String::as_str).collect();
        if !missing.is_empty() {
            missing.sort_unstable();
            bail!("Gear matrix is missing required columns: {}", missing.join(", "));
        }
        let rows = reader.records().collect::<Result<Vec<_>, _>>()?;
        if rows.is_empty() {
            bail!("Gear matrix contains no candidates");
        }
        Ok(MatrixTable { headers, index, rows })
    }

    pub fn column(&self, name: &str) -> Result<usize> {
        self.index.get(name).copied().ok_or_else(|| anyhow!("Gear matrix has no column {name:?}"))
    }

    pub fn get<'r>(&self, row: &'r csv::StringRecord, name: &str) -> Result<&'r str> {
        Ok(row.get(self.column(name)?).unwrap_or(""))
    }

    /// `_integer(value, field)`: required integer field.
    pub fn int(&self, row: &csv::StringRecord, name: &str) -> Result<i64> {
        let value = self.get(row, name)?;
        if value.is_empty() {
            bail!("Gear matrix row is missing integer field {name:?}");
        }
        value.parse().map_err(|_| anyhow!("Gear matrix field {name:?} must be an integer"))
    }

    /// `_integer(value, field, default=...)`: empty cells fall back to `default`.
    pub fn int_or(&self, row: &csv::StringRecord, name: &str, default: i64) -> Result<i64> {
        let value = self.get(row, name)?;
        if value.is_empty() {
            return Ok(default);
        }
        value.parse().map_err(|_| anyhow!("Gear matrix field {name:?} must be an integer"))
    }

    pub fn optional_int(&self, row: &csv::StringRecord, name: &str) -> Result<Option<i64>> {
        let value = self.get(row, name)?;
        if value.is_empty() {
            return Ok(None);
        }
        Ok(Some(value.parse().map_err(|_| anyhow!("Gear matrix field {name:?} must be an integer"))?))
    }

    pub fn boolean(&self, row: &csv::StringRecord, name: &str) -> Result<bool> {
        match self.get(row, name)?.trim().to_ascii_lowercase().as_str() {
            "true" => Ok(true),
            "false" => Ok(false),
            _ => bail!("Gear matrix field {name:?} must be True or False"),
        }
    }

    /// Sorted, non-empty style ids from the `;`-joined column.
    pub fn styles(&self, row: &csv::StringRecord) -> Result<Vec<String>> {
        let mut styles: Vec<String> = self
            .get(row, "weapon_attack_styles")?
            .split(';')
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .collect();
        styles.sort();
        Ok(styles)
    }
}
