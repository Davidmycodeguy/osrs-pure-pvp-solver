//! Canonical JSON + SHA-256 identifiers (port of `pure_solver.canonical`).
//!
//! Python emits `json.dumps(value, separators=(",", ":"), sort_keys=True,
//! ensure_ascii=True)`; this module reproduces that byte stream so candidate
//! ids and signatures hash identically on both sides.

use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::rational::Rational;

/// A `fractions.Fraction` normalised the way `canonical.normalise` does it.
pub fn fraction_document(value: &Rational) -> Value {
    let mut map = serde_json::Map::new();
    map.insert("denominator".to_owned(), Value::String(value.denominator().to_string()));
    map.insert("numerator".to_owned(), Value::String(value.numerator().to_string()));
    Value::Object(map).into_bigint_marker()
}

/// Marker trick: big integers are carried as strings tagged with a private key
/// and unquoted when serialised, so arbitrary-precision numerators survive.
trait BigIntMarker {
    fn into_bigint_marker(self) -> Value;
}

const BIGINT_TAG: &str = "__pure_math_bigint__";

impl BigIntMarker for Value {
    fn into_bigint_marker(self) -> Value {
        match self {
            Value::Object(map) => {
                let mut tagged = serde_json::Map::new();
                for (key, value) in map {
                    let mut wrapper = serde_json::Map::new();
                    wrapper.insert(BIGINT_TAG.to_owned(), value);
                    tagged.insert(key, Value::Object(wrapper));
                }
                Value::Object(tagged)
            }
            other => other,
        }
    }
}

/// The one-key object `into_bigint_marker` wraps each big integer in; it prints as a bare number.
fn is_bigint_wrapper(map: &serde_json::Map<String, Value>) -> bool {
    map.len() == 1 && map.contains_key(BIGINT_TAG)
}

fn write_string(out: &mut String, text: &str) {
    out.push('"');
    for ch in text.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                let mut buffer = [0u16; 2];
                for unit in c.encode_utf16(&mut buffer) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write_value(out: &mut String, value: &Value) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(flag) => out.push_str(if *flag { "true" } else { "false" }),
        Value::Number(number) => out.push_str(&number.to_string()),
        Value::String(text) => write_string(out, text),
        Value::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_value(out, item);
            }
            out.push(']');
        }
        Value::Object(map) => {
            if map.len() == 1 {
                if let Some(Value::String(digits)) = map.get(BIGINT_TAG) {
                    out.push_str(digits);
                    return;
                }
            }
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (index, key) in keys.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_string(out, key);
                out.push(':');
                write_value(out, &map[*key]);
            }
            out.push('}');
        }
    }
}

/// Compact, key-sorted, ASCII-only JSON identical to Python's `canonical_json`.
pub fn canonical_json(value: &Value) -> String {
    let mut out = String::new();
    write_value(&mut out, value);
    out
}

pub fn canonical_hash(value: &Value) -> String {
    hex::encode(Sha256::digest(canonical_json(value).as_bytes()))
}

fn write_pretty(out: &mut String, value: &Value, depth: usize) {
    let indent = |out: &mut String, level: usize| {
        out.push('\n');
        for _ in 0..level {
            out.push_str("  ");
        }
    };
    match value {
        Value::Array(items) if !items.is_empty() => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                indent(out, depth + 1);
                write_pretty(out, item, depth + 1);
            }
            indent(out, depth);
            out.push(']');
        }
        Value::Object(map) if !(map.is_empty() || is_bigint_wrapper(map)) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (index, key) in keys.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                indent(out, depth + 1);
                write_string(out, key);
                out.push_str(": ");
                write_pretty(out, &map[*key], depth + 1);
            }
            indent(out, depth);
            out.push('}');
        }
        other => write_value(out, other),
    }
}

/// Python `json.dumps(obj, indent=2, sort_keys=True)` (no trailing newline).
pub fn pretty_sorted_json(value: &Value) -> String {
    let mut out = String::new();
    write_pretty(&mut out, value, 0);
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn matches_python_json_dumps_layout() {
        let value = json!({"b": [1, 2, {"z": null, "a": true}], "a": "x\"y", "c": "\u{e9}"});
        assert_eq!(
            canonical_json(&value),
            "{\"a\":\"x\\\"y\",\"b\":[1,2,{\"a\":true,\"z\":null}],\"c\":\"\\u00e9\"}"
        );
    }

    #[test]
    fn fraction_documents_unquote_big_integers() {
        let value = fraction_document(&Rational::new(3, 4));
        assert_eq!(canonical_json(&value), r#"{"denominator":4,"numerator":3}"#);
    }

    #[test]
    fn pretty_layout_matches_python_indent_two() {
        let value = json!({"b": [], "a": {"y": [1, {"k": "v"}], "x": {}}});
        assert_eq!(
            pretty_sorted_json(&value),
            "{\n  \"a\": {\n    \"x\": {},\n    \"y\": [\n      1,\n      {\n        \"k\": \"v\"\n      }\n    ]\n  },\n  \"b\": []\n}"
        );
    }

    #[test]
    fn sha256_hex_is_lowercase() {
        assert_eq!(canonical_hash(&json!({})), "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a");
    }
}
