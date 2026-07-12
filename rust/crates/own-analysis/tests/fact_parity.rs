//! Fact-level differential parity for the effect (EFF001) and DI (DI001–005)
//! analyses — the Rust side of the Python-authored oracle
//! (`tests/fixtures/di_eff_fact_parity.json`, regenerate:
//! `python tests/test_di_eff_fact_parity.py --write`).
//!
//! These families have no `.own` surface; Python is the reference. This test
//! deserializes the frozen fact inputs, runs the ported analyses, and asserts the
//! exact ordered `(path, line, code)` verdict list — with **zero Python**. On any
//! divergence it prints the case name and both lists.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_analysis::di::{self, Lifetime, Service};
use own_analysis::effect::{Binding, Effect};
use serde_json::Value;

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/di_eff_fact_parity.json"
);

fn strs(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array).map_or_else(Vec::new, |a| {
        a.iter()
            .filter_map(|x| x.as_str().map(str::to_owned))
            .collect()
    })
}

fn u32_of(v: Option<&Value>) -> u32 {
    v.and_then(Value::as_u64)
        .and_then(|n| u32::try_from(n).ok())
        .unwrap_or(0)
}

fn sites(v: Option<&Value>) -> Vec<(String, String, u32)> {
    v.and_then(Value::as_array).map_or_else(Vec::new, |a| {
        a.iter()
            .filter_map(|t| {
                let t = t.as_array()?;
                Some((
                    t.first()?.as_str()?.to_owned(),
                    t.get(1)?.as_str()?.to_owned(),
                    u32::try_from(t.get(2)?.as_u64()?).ok()?,
                ))
            })
            .collect()
    })
}

fn effect_from(v: &Value) -> Effect {
    let bindings = v
        .get("bindings")
        .and_then(Value::as_array)
        .map_or_else(Vec::new, |a| {
            a.iter()
                .map(|b| Binding {
                    name: b
                        .get("name")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_owned(),
                    init: b
                        .get("init")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_owned(),
                    refs: strs(b.get("refs")),
                    line: u32_of(b.get("line")),
                })
                .collect()
        });
    Effect {
        component: v
            .get("component")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_owned(),
        deps: strs(v.get("deps")),
        io: v.get("io").and_then(Value::as_bool).unwrap_or(false),
        bindings,
        file: v
            .get("file")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_owned(),
        line: u32_of(v.get("line")),
    }
}

fn service_from(v: &Value) -> Service {
    let lifetime = v
        .get("lifetime")
        .and_then(Value::as_str)
        .and_then(Lifetime::parse);
    Service {
        name: v
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_owned(),
        lifetime,
        deps: strs(v.get("deps")),
        disposable: v
            .get("disposable")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        file: v
            .get("file")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_owned(),
        line: u32_of(v.get("line")),
        weak_deps: strs(v.get("weak_deps")),
        root_resolves: strs(v.get("root_resolves")),
        root_resolve_sites: sites(v.get("root_resolve_sites")),
        scope_cached: strs(v.get("scope_cached")),
        scope_cache_sites: sites(v.get("scope_cache_sites")),
    }
}

fn expected(case: &Value) -> Vec<(String, u32, String)> {
    case.get("expected")
        .and_then(Value::as_array)
        .expect("'expected'")
        .iter()
        .map(|row| {
            let row = row.as_array().expect("[file, line, code]");
            (
                row.first()
                    .and_then(Value::as_str)
                    .expect("file")
                    .to_owned(),
                u32_of(row.get(1)),
                row.get(2).and_then(Value::as_str).expect("code").to_owned(),
            )
        })
        .collect()
}

fn load() -> Value {
    let raw = std::fs::read_to_string(FIXTURE)
        .expect("fixture missing — regenerate: python tests/test_di_eff_fact_parity.py --write");
    serde_json::from_str(&raw).expect("di_eff_fact_parity.json parses")
}

#[test]
fn effect_fact_parity() {
    let root = load();
    let cases = root
        .get("effect_cases")
        .and_then(Value::as_array)
        .expect("'effect_cases'");
    let mut failures = Vec::new();
    for case in cases {
        let name = case.get("name").and_then(Value::as_str).expect("name");
        let effects: Vec<Effect> = case
            .get("effects")
            .and_then(Value::as_array)
            .expect("effects")
            .iter()
            .map(effect_from)
            .collect();
        let got: Vec<(String, u32, String)> = own_analysis::effect_verdicts(&effects)
            .into_iter()
            .map(|(f, l, c)| (f, l, c.to_owned()))
            .collect();
        let want = expected(case);
        if got != want {
            failures.push(format!(
                "effect case {name}:\n    python={want:?}\n    rust  ={got:?}"
            ));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
    assert!(cases.len() >= 8, "expected the full effect corpus");
}

#[test]
fn di_fact_parity() {
    let root = load();
    let cases = root
        .get("di_cases")
        .and_then(Value::as_array)
        .expect("'di_cases'");
    let mut failures = Vec::new();
    for case in cases {
        let name = case.get("name").and_then(Value::as_str).expect("name");
        let services: Vec<Service> = case
            .get("services")
            .and_then(Value::as_array)
            .expect("services")
            .iter()
            .map(service_from)
            .collect();
        let got: Vec<(String, u32, String)> = di::di_verdicts(&services)
            .into_iter()
            .map(|(f, l, c)| (f, l, c.to_owned()))
            .collect();
        let want = expected(case);
        if got != want {
            failures.push(format!(
                "DI case {name}:\n    python={want:?}\n    rust  ={got:?}"
            ));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
    assert!(cases.len() >= 13, "expected the full DI corpus");
}
