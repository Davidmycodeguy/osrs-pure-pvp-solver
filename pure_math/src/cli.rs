//! Minimal `--flag=value` / `--flag value` argument parsing for the subcommands.

use std::collections::HashMap;
use std::path::PathBuf;

use anyhow::{anyhow, Result};

#[derive(Debug, Default)]
pub struct Args {
    positional: Vec<String>,
    flags: HashMap<String, String>,
}

impl Args {
    pub fn parse(raw: &[String]) -> Result<Args> {
        let mut args = Args::default();
        let mut index = 0;
        while index < raw.len() {
            let token = &raw[index];
            if let Some(flag) = token.strip_prefix("--") {
                if let Some((key, value)) = flag.split_once('=') {
                    args.flags.insert(key.to_owned(), value.to_owned());
                } else {
                    let value = raw.get(index + 1).ok_or_else(|| anyhow!("--{flag} needs a value"))?;
                    args.flags.insert(flag.to_owned(), value.clone());
                    index += 1;
                }
            } else {
                args.positional.push(token.clone());
            }
            index += 1;
        }
        Ok(args)
    }

    pub fn positional(&self, index: usize, name: &str) -> Result<&str> {
        self.positional
            .get(index)
            .map(String::as_str)
            .ok_or_else(|| anyhow!("missing required argument <{name}>"))
    }

    pub fn path(&self, index: usize, name: &str) -> Result<PathBuf> {
        Ok(PathBuf::from(self.positional(index, name)?))
    }

    pub fn flag(&self, name: &str) -> Option<&str> {
        self.flags.get(name).map(String::as_str)
    }

    pub fn flag_path(&self, name: &str, default: &str) -> PathBuf {
        PathBuf::from(self.flag(name).unwrap_or(default))
    }

    pub fn flag_int(&self, name: &str, default: i64) -> Result<i64> {
        match self.flag(name) {
            None => Ok(default),
            Some(value) => value.parse().map_err(|_| anyhow!("--{name} must be an integer, got {value:?}")),
        }
    }
}
