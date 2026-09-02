//! Loader for `mechanics.json`.  Provenance/archive verification stays in the
//! Python data layer; here we only insist that a mechanic we use is marked
//! verified and conflict-free, exactly as `MechanicRegistry.require` does.

use std::collections::HashMap;
use std::path::Path;

use anyhow::{anyhow, bail, Context, Result};
use serde_json::Value;

use crate::formula::{evaluate, Variables};
use crate::rational::Rational;

#[derive(Clone, Debug)]
pub struct Mechanic {
    pub mechanic_id: String,
    pub status: String,
    pub value: Value,
    pub formula_version: String,
    pub conflicts: Vec<String>,
}

#[derive(Clone, Debug, Default)]
pub struct MechanicRegistry {
    mechanics: HashMap<String, Mechanic>,
}

impl MechanicRegistry {
    pub fn from_document(document: &Value) -> Result<MechanicRegistry> {
        let mut mechanics = HashMap::new();
        let entries = document
            .get("mechanics")
            .and_then(Value::as_array)
            .ok_or_else(|| anyhow!("mechanics.json has no mechanics array"))?;
        for item in entries {
            let mechanic_id = item["mechanic_id"].as_str().ok_or_else(|| anyhow!("mechanic without mechanic_id"))?.to_owned();
            if mechanics.contains_key(&mechanic_id) {
                bail!("Duplicate mechanic_id {mechanic_id:?} in mechanics document");
            }
            let conflicts = item
                .get("conflicts")
                .and_then(Value::as_array)
                .map(|c| c.iter().filter_map(Value::as_str).map(str::to_owned).collect())
                .unwrap_or_default();
            mechanics.insert(
                mechanic_id.clone(),
                Mechanic {
                    mechanic_id,
                    status: item.get("status").and_then(Value::as_str).unwrap_or("unverified").to_owned(),
                    value: item.get("value").cloned().unwrap_or(Value::Null),
                    formula_version: item.get("formula_version").and_then(Value::as_str).unwrap_or("unversioned").to_owned(),
                    conflicts,
                },
            );
        }
        Ok(MechanicRegistry { mechanics })
    }

    pub fn load(path: &Path) -> Result<MechanicRegistry> {
        let text = std::fs::read_to_string(path).with_context(|| format!("Missing required ruleset file: {}", path.display()))?;
        let document: Value = serde_json::from_str(&text).with_context(|| format!("Invalid JSON in ruleset file {}", path.display()))?;
        MechanicRegistry::from_document(&document)
    }

    pub fn require(&self, mechanic_id: &str) -> Result<&Mechanic> {
        let mechanic = self
            .mechanics
            .get(mechanic_id)
            .filter(|m| m.status == "verified")
            .ok_or_else(|| anyhow!("Mechanic {mechanic_id:?} is unavailable or not verified; simulation is invalid."))?;
        if !mechanic.conflicts.is_empty() {
            bail!("Mechanic {mechanic_id:?} has unresolved conflicts: {}", mechanic.conflicts.join(", "));
        }
        Ok(mechanic)
    }

    pub fn evaluate(&self, mechanic_id: &str, variables: &Variables) -> Result<Rational> {
        let mechanic = self.require(mechanic_id)?;
        if !mechanic.value.is_object() {
            bail!("Mechanic {mechanic_id:?} does not contain a formula AST");
        }
        evaluate(&mechanic.value, variables)
    }

    /// Integer result of a formula mechanic, truncated like the Python callers' `int(...)`.
    pub fn evaluate_int(&self, mechanic_id: &str, variables: &Variables) -> Result<i64> {
        Ok(self.evaluate(mechanic_id, variables)?.trunc_i64())
    }

    /// Table-valued mechanic (prayer boosts, style bonuses, ...), as raw JSON.
    pub fn table(&self, mechanic_id: &str) -> Result<&serde_json::Map<String, Value>> {
        let mechanic = self.require(mechanic_id)?;
        mechanic.value.as_object().ok_or_else(|| anyhow!("{mechanic_id} must be a mapping"))
    }
}

/// Decode an exact fraction literal (`int` or `{numerator, denominator}`) from table data.
pub fn fraction_value(value: &Value, label: &str) -> Result<Rational> {
    if let Some(v) = value.as_i64() {
        return Ok(Rational::int(v as i128));
    }
    let (Some(n), Some(d)) = (value.get("numerator").and_then(Value::as_i64), value.get("denominator").and_then(Value::as_i64)) else {
        bail!("{label} does not encode an exact fraction");
    };
    if d <= 0 {
        bail!("{label} does not encode an exact fraction");
    }
    Ok(Rational::new(n as i128, d as i128))
}

pub fn int_value(value: &Value, label: &str) -> Result<i64> {
    value.as_i64().ok_or_else(|| anyhow!("{label} is not an exact integer"))
}
