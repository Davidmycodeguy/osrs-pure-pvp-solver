//! CSV/JSON readers and writers shared by the pipeline stages.  Output shapes
//! match the Python originals byte-for-byte so downstream consumers are unchanged.

use std::path::Path;

use anyhow::{anyhow, Context, Result};

use crate::account_frontier::from_levels_with_defence;
use crate::accounts::{AccountState, LEVEL_FIELDS};
use crate::mechanics::MechanicRegistry;

pub fn ensure_parent(path: &Path) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).with_context(|| format!("cannot create {}", parent.display()))?;
    }
    Ok(())
}

/// Python's `csv.writer` default dialect: comma separated, CRLF line endings, minimal quoting.
pub fn csv_writer(path: &Path) -> Result<csv::Writer<std::fs::File>> {
    ensure_parent(path)?;
    let file = std::fs::File::create(path).with_context(|| format!("cannot write {}", path.display()))?;
    Ok(csv::WriterBuilder::new().terminator(csv::Terminator::CRLF).from_writer(file))
}

pub fn write_account_csv(accounts: &[AccountState], mechanics: &MechanicRegistry, path: &Path) -> Result<()> {
    let mut writer = csv_writer(path)?;
    let mut header: Vec<&str> = LEVEL_FIELDS.to_vec();
    header.extend(["defence", "combat_level"]);
    writer.write_record(&header)?;
    for account in accounts {
        let mut row: Vec<String> = account.levels().iter().map(i64::to_string).collect();
        row.push(account.defence().to_string());
        row.push(account.combat_level(mechanics)?.to_string());
        writer.write_record(&row)?;
    }
    writer.flush()?;
    Ok(())
}

pub fn read_account_csv(path: &Path) -> Result<Vec<AccountState>> {
    let mut reader = csv::Reader::from_path(path).with_context(|| format!("cannot read {}", path.display()))?;
    let headers = reader.headers()?.clone();
    let indices: Vec<usize> = LEVEL_FIELDS
        .iter()
        .map(|field| {
            headers
                .iter()
                .position(|h| h == *field)
                .ok_or_else(|| anyhow!("Account frontier CSV is missing column {field}"))
        })
        .collect::<Result<_>>()?;
    let defence_index = headers.iter().position(|h| h == "defence");
    let mut accounts = Vec::new();
    for record in reader.records() {
        let record = record?;
        let mut levels = [0i64; 6];
        for (slot, &index) in indices.iter().enumerate() {
            levels[slot] = record[index].parse().with_context(|| format!("non-integer level {:?}", &record[index]))?;
        }
        let defence = match defence_index {
            Some(index) => record[index].parse().with_context(|| format!("non-integer defence {:?}", &record[index]))?,
            None => crate::accounts::DEFENCE_LEVEL,
        };
        accounts.push(from_levels_with_defence(levels, defence));
    }
    Ok(accounts)
}

/// Python text-mode `write_text`: `\n` becomes the platform line ending (CRLF on Windows).
pub fn write_text(path: &Path, text: &str) -> Result<()> {
    ensure_parent(path)?;
    let body = if cfg!(windows) { text.replace('\n', "\r\n") } else { text.to_owned() };
    std::fs::write(path, body).with_context(|| format!("cannot write {}", path.display()))
}

pub fn write_json(path: &Path, value: &serde_json::Value) -> Result<()> {
    write_text(path, &format!("{}\n", crate::canonical::pretty_sorted_json(value)))
}
