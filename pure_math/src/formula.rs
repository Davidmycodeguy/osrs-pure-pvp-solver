//! Port of `pure_solver.formula`: evaluates the small exact JSON formula AST
//! stored in `mechanics.json`.  Formulae stay data; this module only walks them.

use std::collections::HashMap;

use anyhow::{anyhow, bail, Result};
use serde_json::Value;

use crate::rational::Rational;

pub type Variables = HashMap<String, Rational>;

/// Mirrors `formula._number`: only exact integers, booleans, and
/// `{"numerator": n, "denominator": d}` objects are accepted as literals.
fn number(value: &Value) -> Result<Rational> {
    match value {
        Value::Bool(flag) => Ok(Rational::int(*flag as i128)),
        Value::Number(n) => n
            .as_i64()
            .map(|v| Rational::int(v as i128))
            .ok_or_else(|| anyhow!("Formula contains a non-exact numeric literal: {value}")),
        Value::Object(map) if map.len() == 2 && map.contains_key("numerator") && map.contains_key("denominator") => {
            let numerator = map["numerator"].as_i64().ok_or_else(|| anyhow!("numerator must be an integer"))?;
            let denominator = map["denominator"].as_i64().ok_or_else(|| anyhow!("denominator must be an integer"))?;
            if denominator == 0 {
                bail!("Formula literal has a zero denominator");
            }
            Ok(Rational::new(numerator as i128, denominator as i128))
        }
        _ => Err(anyhow!("Formula contains a non-exact numeric literal: {value}")),
    }
}

fn args_of(expression: &Value) -> &[Value] {
    expression.get("args").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
}

fn expect_arity(op: &str, args: &[Rational], arity: usize) -> Result<()> {
    if args.len() != arity {
        bail!("{op} requires exactly {arity} arguments");
    }
    Ok(())
}

/// Evaluate a formula node against named inputs, exactly as the Python evaluator does.
pub fn evaluate(expression: &Value, variables: &Variables) -> Result<Rational> {
    if let Value::Number(_) = expression {
        return number(expression);
    }
    let Value::Object(_) = expression else {
        bail!("Formula node must be an object or exact integer");
    };
    let op = expression.get("op").and_then(Value::as_str).unwrap_or("");
    match op {
        "const" => return number(expression.get("value").ok_or_else(|| anyhow!("const requires value"))?),
        "ref" => {
            let name = expression.get("name").map(|n| n.as_str().map(str::to_owned).unwrap_or_else(|| n.to_string()));
            let name = name.ok_or_else(|| anyhow!("ref requires name"))?;
            return variables
                .get(&name)
                .cloned()
                .ok_or_else(|| anyhow!("Formula references missing input {name:?}"));
        }
        "if" => {
            let raw = args_of(expression);
            if raw.len() != 3 {
                bail!("if requires condition, true branch, and false branch");
            }
            let branch = if !evaluate(&raw[0], variables)?.is_zero() { &raw[1] } else { &raw[2] };
            return evaluate(branch, variables);
        }
        _ => {}
    }
    let args: Vec<Rational> = args_of(expression).iter().map(|a| evaluate(a, variables)).collect::<Result<_>>()?;
    match op {
        "add" => Ok(args.iter().fold(Rational::zero(), |acc, v| &acc + v)),
        "sub" => {
            expect_arity(op, &args, 2)?;
            Ok(&args[0] - &args[1])
        }
        "mul" => Ok(args.iter().fold(Rational::one(), |acc, v| &acc * v)),
        "div" => {
            if args.len() != 2 || args[1].is_zero() {
                bail!("div requires two arguments and non-zero divisor");
            }
            Ok(&args[0] / &args[1])
        }
        "floor" => {
            expect_arity(op, &args, 1)?;
            Ok(args[0].floor())
        }
        "max" => args.iter().max().cloned().ok_or_else(|| anyhow!("max requires at least one argument")),
        "min" => args.iter().min().cloned().ok_or_else(|| anyhow!("min requires at least one argument")),
        "gt" | "gte" | "lt" | "lte" | "eq" => {
            expect_arity(op, &args, 2)?;
            let (a, b) = (&args[0], &args[1]);
            let truth = match op {
                "gt" => a > b,
                "gte" => a >= b,
                "lt" => a < b,
                "lte" => a <= b,
                _ => a == b,
            };
            Ok(Rational::int(truth as i128))
        }
        _ => Err(anyhow!("Unsupported formula operation {op:?}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn vars(pairs: &[(&str, i128)]) -> Variables {
        pairs.iter().map(|(k, v)| (k.to_string(), Rational::int(*v))).collect()
    }

    #[test]
    fn combat_level_floor_order_is_preserved() {
        // floor((40*(def+hp+floor(prayer/2)) + 52*max(att+str, floor(1.5*rng), floor(1.5*mag))) / 160)
        let formula = json!({"op": "floor", "args": [{"op": "div", "args": [
            {"op": "add", "args": [
                {"op": "mul", "args": [40, {"op": "add", "args": [
                    {"op": "ref", "name": "defence"}, {"op": "ref", "name": "hitpoints"},
                    {"op": "floor", "args": [{"op": "div", "args": [{"op": "ref", "name": "prayer"}, 2]}]}]}]},
                {"op": "mul", "args": [52, {"op": "max", "args": [
                    {"op": "add", "args": [{"op": "ref", "name": "attack"}, {"op": "ref", "name": "strength"}]},
                    {"op": "floor", "args": [{"op": "mul", "args": [{"op": "const", "value": {"numerator": 3, "denominator": 2}}, {"op": "ref", "name": "ranged"}]}]},
                    {"op": "floor", "args": [{"op": "mul", "args": [{"op": "const", "value": {"numerator": 3, "denominator": 2}}, {"op": "ref", "name": "magic"}]}]}]}]}]},
            160]}]});
        let level = evaluate(
            &formula,
            &vars(&[
                ("attack", 35),
                ("strength", 35),
                ("ranged", 9),
                ("magic", 47),
                ("prayer", 1),
                ("defence", 1),
                ("hitpoints", 31),
            ]),
        )
        .unwrap();
        assert_eq!(level, Rational::int(30));
    }

    #[test]
    fn rejects_float_literals_and_missing_refs() {
        assert!(evaluate(&json!(1.5), &Variables::new()).is_err());
        assert!(evaluate(&json!({"op": "ref", "name": "x"}), &Variables::new()).is_err());
        assert!(evaluate(&json!({"op": "div", "args": [1, 0]}), &Variables::new()).is_err());
    }

    #[test]
    fn if_and_comparisons_return_integers() {
        let formula = json!({"op": "if", "args": [{"op": "gt", "args": [{"op": "ref", "name": "a"}, 3]}, 10, 20]});
        assert_eq!(evaluate(&formula, &vars(&[("a", 4)])).unwrap(), Rational::int(10));
        assert_eq!(evaluate(&formula, &vars(&[("a", 3)])).unwrap(), Rational::int(20));
    }
}
