//! Golden test: every formula mechanic must evaluate exactly as the Python
//! reference did when `golden/generate_formula_golden.py` produced the fixture.

use std::collections::HashMap;
use std::path::PathBuf;

use pure_math::formula::{evaluate, Variables};
use pure_math::rational::Rational;
use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
struct Encoded {
    numerator: i128,
    denominator: i128,
}

#[derive(Deserialize)]
struct Case {
    mechanic_id: String,
    variables: HashMap<String, Encoded>,
    result: Option<Encoded>,
    error: Option<String>,
}

#[derive(Deserialize)]
struct Fixture {
    cases: Vec<Case>,
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
}

fn load_mechanics() -> HashMap<String, Value> {
    let path = repo_root().join("rulesets").join("osrs-f2p-v1").join("mechanics.json");
    let document: Value = serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
    document["mechanics"]
        .as_array()
        .unwrap()
        .iter()
        .map(|m| (m["mechanic_id"].as_str().unwrap().to_owned(), m["value"].clone()))
        .collect()
}

#[test]
fn formula_evaluator_matches_python_reference() {
    let fixture_path = repo_root().join("pure_math").join("tests").join("fixtures").join("formula-golden.json");
    let fixture: Fixture = serde_json::from_str(&std::fs::read_to_string(&fixture_path).unwrap()).unwrap();
    let mechanics = load_mechanics();
    assert!(fixture.cases.len() >= 600, "fixture unexpectedly small: {}", fixture.cases.len());

    let mut checked = 0;
    for case in &fixture.cases {
        let formula = &mechanics[&case.mechanic_id];
        let variables: Variables = case
            .variables
            .iter()
            .map(|(k, v)| (k.clone(), Rational::new(v.numerator, v.denominator)))
            .collect();
        let outcome = evaluate(formula, &variables);
        match (&case.result, &case.error) {
            (Some(expected), _) => {
                let actual = outcome.unwrap_or_else(|e| panic!("{}: unexpected error {e}", case.mechanic_id));
                assert_eq!(
                    actual,
                    Rational::new(expected.numerator, expected.denominator),
                    "{} diverged for {:?}",
                    case.mechanic_id,
                    case.variables.iter().map(|(k, v)| (k.as_str(), v.numerator, v.denominator)).collect::<Vec<_>>()
                );
            }
            (None, Some(_)) => assert!(outcome.is_err(), "{} should have failed", case.mechanic_id),
            (None, None) => panic!("malformed case for {}", case.mechanic_id),
        }
        checked += 1;
    }
    assert_eq!(checked, fixture.cases.len());
}
