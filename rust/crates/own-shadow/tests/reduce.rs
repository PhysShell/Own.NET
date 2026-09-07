//! The first-divergence reduction's acceptance contract (P-022 step 7a
//! checkpoint 4, #260):
//!
//! ```text
//! <case>.trace.json → own_shadow::reduce_traces  ≡  <case>.reduction.json
//! ```
//!
//! byte-for-byte, with **zero Python** — and, more importantly than the
//! goldens, the reducer is shown to *work*:
//!
//! * **silent on unchanged data** — a reducer that reports on agreement is
//!   worse than none;
//! * **naming, on a synthetic divergence** — one controlled change introduced
//!   into a copy of a real Layer 2 output, and the reducer must name the layer,
//!   the step address and the **minimal** path inside it, not the whole step.
//!   A reducer that has never reported is a reducer nobody has seen work.
//!
//! The scope is `lowered` + `summaries`. The `verdicts` layer is **refused, not
//! skipped**, and the refusal is asserted here: comparing final diagnostics is
//! #260's acceptance, blocked by #259, and "not compared" must never be
//! readable as "compared and agreed".

#![allow(clippy::panic, clippy::expect_used, clippy::unwrap_used)]

use std::collections::BTreeSet;

use own_shadow::{
    judge, parse, reduce_traces, Json, ACCEPTANCE_DECLARED, ACCEPTANCE_UNEXPLAINED, BOUNDARY_OD1,
    BOUNDARY_POLICY, KIND_CHANGED, KIND_LEFT_ONLY, KIND_MISSING_LAYER, KIND_ORDERING_ONLY,
    KIND_PROJECTION, KIND_RIGHT_ONLY, KIND_STATUS, LAYER_ORDER, REDUCTION_SCOPE, REDUCTION_VERSION,
};

const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../tests/fixtures");

fn read(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|e| panic!("cannot read {path}: {e}"))
}

fn artifact_names() -> BTreeSet<String> {
    let manifest =
        parse(&read(&format!("{FIXTURES}/repro/manifest.json"))).expect("repro manifest parses");
    manifest
        .get("artifacts")
        .and_then(Json::as_array)
        .expect("manifest carries an 'artifacts' ledger")
        .iter()
        .filter_map(|e| e.get("name").and_then(Json::as_str))
        .map(str::to_owned)
        .collect()
}

fn traces_of(case: &str) -> Json {
    parse(&read(&format!("{FIXTURES}/repro/{case}.trace.json"))).expect("trace golden parses")
}

#[test]
fn every_reduction_golden_is_reproduced_byte_for_byte() {
    for case in artifact_names() {
        let ours = reduce_traces(&traces_of(&case));
        assert_eq!(
            ours,
            reduce_traces(&traces_of(&case)),
            "{case}: the reduction is not deterministic"
        );
        assert_eq!(
            ours.get("reduction_version").and_then(Json::as_i64),
            Some(REDUCTION_VERSION),
            "{case}: reduction surface version"
        );
        let mut rendered = ours.to_pretty();
        rendered.push('\n');
        assert_eq!(
            rendered,
            read(&format!("{FIXTURES}/repro/{case}.reduction.json")),
            "{case}: this side's reduction differs from the committed one — the two \
             implementations of the comparison disagree, which is a finding about the REDUCER"
        );
    }
}

/// The pin, in its POSITIVE form (owner decision D-4).
///
/// It used to assert the verdict layer was OUT of scope, and the assertion was
/// right at the time: comparing final diagnostics is #260's acceptance, and
/// infrastructure that would quietly do it on request becomes an unearned
/// shadow-mode claim the first time somebody widens a constant. The owner took
/// the decision, so the same test now asserts the other side of it — and that
/// the scope is the layer ORDER rather than a third copy of the list that could
/// drift from it.
#[test]
fn the_reduction_scope_is_the_layer_order_and_nothing_is_excluded() {
    assert_eq!(
        REDUCTION_SCOPE, LAYER_ORDER,
        "REDUCTION_SCOPE is not LAYER_ORDER — D-4 says the scope IS the layer order, because a \
         third copy of one list is the one that drifts"
    );
    assert!(
        REDUCTION_SCOPE.contains(&"verdicts"),
        "the verdict layer is not in scope — owner decision D-4 put it there"
    );
    for case in artifact_names() {
        let reduction = reduce_traces(&traces_of(&case));
        assert_eq!(
            reduction.get("out_of_scope").and_then(Json::as_array),
            Some(&[][..]),
            "{case}: the reduction records a layer as out of scope. Every layer is walked now; \
             the member stays and is EMPTY, so 'nothing is excluded' stays distinguishable from \
             'the field went away'"
        );
    }
}

/// Owner decision D-5, driven through the production judgement.
///
/// Every rule the policy states needs a case that breaks exactly it, because
/// the design is a set of *refusals to explain* — and a rule that only ever
/// says "yes" is a rule no mutation can disturb.
#[test]
fn the_boundary_policy_explains_exactly_what_it_names() {
    // 1. The policy IS the three OD-1 typed-door entries, exactly. Not a
    //    superset, not a subset — widening it is an owner decision.
    assert_eq!(
        BOUNDARY_POLICY,
        [
            ("lowered", KIND_STATUS, BOUNDARY_OD1),
            ("summaries", KIND_STATUS, BOUNDARY_OD1),
            ("verdicts", KIND_STATUS, BOUNDARY_OD1),
        ],
        "the frozen boundary policy changed — widening it is an owner decision, not a patch"
    );

    let od1 = boundary(BOUNDARY_OD1, "typed door: whatever it said");
    let other_detail = boundary(BOUNDARY_OD1, "an entirely different wording");
    let wrong_class = boundary("OD-9", "typed door: whatever it said");

    // 2. The door refuses every layer, so each layer's status observation is
    //    explained by it.
    for layer in LAYER_ORDER {
        assert_eq!(
            judge(layer, KIND_STATUS, Some(&od1)).0,
            ACCEPTANCE_DECLARED,
            "OD-1 on a {layer} status observation is not explained"
        );
    }

    // 3. A known class on the WRONG KIND explains nothing. This is what the
    //    (layer, kind, class) shape exists for: a class is not a token that
    //    excuses whatever it is pinned to.
    for kind in [KIND_CHANGED, KIND_MISSING_LAYER, KIND_PROJECTION] {
        assert_eq!(
            judge("verdicts", kind, Some(&od1)).0,
            ACCEPTANCE_UNEXPLAINED,
            "OD-1 attached to a {kind} observation was allowed to explain it"
        );
    }
    // A content observation keeps no boundary at all — the policy is not
    // consulted for one, and carrying the class would invite a later reader to
    // treat it as an explanation.
    assert_eq!(
        judge("verdicts", KIND_CHANGED, Some(&od1)).1,
        Json::Null,
        "a content observation kept a boundary"
    );

    // 4. A known class on a layer the policy does not name explains nothing.
    assert_eq!(
        judge("renders", KIND_STATUS, Some(&od1)).0,
        ACCEPTANCE_UNEXPLAINED,
        "OD-1 explained a status observation on a layer the policy does not name"
    );

    // 5. `detail` never participates: the same class with different prose is
    //    still explained, and a different class with the SAME prose is not.
    assert_eq!(
        judge("verdicts", KIND_STATUS, Some(&other_detail)).0,
        ACCEPTANCE_DECLARED,
        "the judgement depends on the boundary's prose"
    );
    assert_eq!(
        judge("verdicts", KIND_STATUS, Some(&wrong_class)).0,
        ACCEPTANCE_UNEXPLAINED,
        "an unknown class wearing OD-1's detail was accepted — the policy matched on text"
    );

    // 6. A refusal with no declaration is unexplained, not unknown. Silence is
    //    the one thing a policy may not accept.
    for undeclared in [
        None,
        Some(Json::Object(Vec::new())),
        Some(Json::Object(vec![(
            "detail".to_owned(),
            Json::Str("no class at all".to_owned()),
        )])),
    ] {
        assert_eq!(
            judge("verdicts", KIND_STATUS, undeclared.as_ref()).0,
            ACCEPTANCE_UNEXPLAINED,
            "a status observation with no declared class was explained anyway"
        );
    }
}

fn boundary(class: &str, detail: &str) -> Json {
    Json::Object(vec![
        ("class".to_owned(), Json::Str(class.to_owned())),
        ("detail".to_owned(), Json::Str(detail.to_owned())),
    ])
}

/// Owner decision D-7, driven adversarially and cross-engine.
///
/// The BR-V8 address `file:line:column:code` is a PAIRING address, not object
/// identity, and a duplicate address takes a `~<n>` suffix that is **part of
/// the address**. So two findings that share an address and swap their messages
/// between the engines are two `changed` observations at `.message`, one per
/// ordinal — never `ordering-only`, which would say the engines put the same
/// things in a different sequence and licence a reader to shrug.
///
/// Built synthetically because no corpus document reaches it: the two engines
/// agree on every finding, so the permutation has to be introduced on purpose.
/// That is the point — a rule the corpus cannot exercise is a rule a mutation
/// walks straight through.
#[test]
fn a_duplicate_address_permutation_is_changed_on_both_ordinals() {
    const ADDRESS: &str = "A.cs:1:1:OWN001";
    let finding = |message: &str| -> Json {
        Json::Object(vec![
            ("file".to_owned(), Json::Str("A.cs".to_owned())),
            ("line".to_owned(), Json::Int(1)),
            ("column".to_owned(), Json::Int(1)),
            ("code".to_owned(), Json::Str("OWN001".to_owned())),
            ("message".to_owned(), Json::Str(message.to_owned())),
        ])
    };
    let side = |first: &str, second: &str| -> Json {
        Json::Object(vec![
            ("layer".to_owned(), Json::Str("verdicts".to_owned())),
            ("status".to_owned(), Json::Str("produced".to_owned())),
            (
                "projection".to_owned(),
                Json::Object(vec![("kind".to_owned(), Json::Str("full".to_owned()))]),
            ),
            ("order".to_owned(), Json::Str("significant".to_owned())),
            (
                "steps".to_owned(),
                Json::Array(vec![
                    Json::Object(vec![
                        ("id".to_owned(), Json::Str(format!("findings[{ADDRESS}]"))),
                        ("value".to_owned(), finding(first)),
                    ]),
                    Json::Object(vec![
                        ("id".to_owned(), Json::Str(format!("findings[{ADDRESS}~1]"))),
                        ("value".to_owned(), finding(second)),
                    ]),
                ]),
            ),
        ])
    };

    let base = traces_of("canonical_key_order");
    let messages = [("X", "Y"), ("Y", "X")];
    let forged = forge_layers(&base, "verdicts", |i, _layer| {
        let (a, b) = messages.get(i).copied().unwrap_or(("X", "Y"));
        side(a, b)
    });
    let result = reduce_traces(&forged);
    let by_kind = result
        .get("classification")
        .and_then(|c| c.get("by_kind"))
        .expect("by_kind");
    assert_eq!(
        by_kind.get(KIND_ORDERING_ONLY).and_then(Json::as_i64),
        Some(0),
        "a duplicate-address permutation was reported as ORDERING-ONLY — the `~<n>` ordinal is \
         part of the address, so this is two findings whose values differ, not the same \
         findings in another sequence"
    );
    let changed: Vec<&Json> = result
        .get("observations")
        .and_then(Json::as_array)
        .expect("observations")
        .iter()
        .filter(|o| {
            o.get("layer").and_then(Json::as_str) == Some("verdicts")
                && o.get("kind").and_then(Json::as_str) == Some(KIND_CHANGED)
        })
        .collect();
    let steps: Vec<Option<&str>> = changed
        .iter()
        .map(|o| o.get("step").and_then(Json::as_str))
        .collect();
    assert_eq!(
        steps,
        vec![
            Some(format!("findings[{ADDRESS}]").as_str()),
            Some(format!("findings[{ADDRESS}~1]").as_str()),
        ],
        "expected one `changed` per ordinal, in address order"
    );
    for observation in &changed {
        assert_eq!(
            observation.get("path").and_then(Json::as_str),
            Some(".message"),
            "the pairing address holds, so the difference is a VALUE at that address"
        );
        assert_eq!(
            observation.get("acceptance").and_then(Json::as_str),
            Some(ACCEPTANCE_UNEXPLAINED),
            "a content difference on the verdict layer must be unexplained (D-5)"
        );
    }
    assert_eq!(
        result.get("outcome").and_then(Json::as_str),
        Some("diverged")
    );
}

/// Rebuild `traces` with `f` applied to the right engine's lowered layer.
fn forge(traces: &Json, f: impl Fn(&[Json]) -> Vec<Json>) -> Json {
    let Json::Object(top) = traces else {
        panic!("traces is not an object")
    };
    Json::Object(
        top.iter()
            .map(|(k, v)| {
                if k != "traces" {
                    return (k.clone(), v.clone());
                }
                let list = v.as_array().expect("traces array");
                let rebuilt: Vec<Json> = list
                    .iter()
                    .enumerate()
                    .map(|(i, trace)| {
                        if i != 1 {
                            return trace.clone();
                        }
                        let Json::Object(fields) = trace else {
                            return trace.clone();
                        };
                        Json::Object(
                            fields
                                .iter()
                                .map(|(tk, tv)| {
                                    if tk != "layers" {
                                        return (tk.clone(), tv.clone());
                                    }
                                    let layers: Vec<Json> = tv
                                        .as_array()
                                        .expect("layers")
                                        .iter()
                                        .map(|layer| {
                                            if layer.get("layer").and_then(Json::as_str)
                                                != Some("lowered")
                                            {
                                                return layer.clone();
                                            }
                                            let Json::Object(lf) = layer else {
                                                return layer.clone();
                                            };
                                            Json::Object(
                                                lf.iter()
                                                    .map(|(lk, lv)| {
                                                        if lk != "steps" {
                                                            return (lk.clone(), lv.clone());
                                                        }
                                                        (
                                                            lk.clone(),
                                                            Json::Array(f(lv
                                                                .as_array()
                                                                .expect("steps"))),
                                                        )
                                                    })
                                                    .collect(),
                                            )
                                        })
                                        .collect();
                                    (tk.clone(), Json::Array(layers))
                                })
                                .collect(),
                        )
                    })
                    .collect();
                (k.clone(), Json::Array(rebuilt))
            })
            .collect(),
    )
}

fn first(reduction: &Json) -> &Json {
    reduction.get("first").expect("first")
}

// Five controls, each a distinct classification with its own forged input.
#[allow(clippy::too_many_lines)]
#[test]
fn the_reducer_is_silent_on_unchanged_data_and_names_a_synthetic_divergence() {
    // `canonical_key_order` is the control case because its lowered layer
    // carries real flow statements with `line` fields — `di` is DI-only and has
    // no line-bearing step, which is how the changed-field control below first
    // read as a no-op here while the reference's half (which ADDED the key)
    // passed on the wrong thing. The two halves disagreeing is what surfaced it.
    let case = "canonical_key_order";
    assert!(
        artifact_names().contains(case),
        "the control case '{case}' is not a committed artifact"
    );
    let base = traces_of(case);

    // 0. Silence.
    let quiet = reduce_traces(&base);
    assert_eq!(
        quiet.get("outcome").and_then(Json::as_str),
        Some("identical"),
        "the reducer reports a divergence on unchanged data: {:#?}",
        first(&quiet)
    );
    assert_eq!(
        first(&quiet),
        &Json::Null,
        "a silent reduction names nothing"
    );

    let steps_of = |traces: &Json| -> Vec<Json> {
        traces
            .get("traces")
            .and_then(Json::as_array)
            .and_then(|t| t.get(1))
            .and_then(|t| t.get("layers"))
            .and_then(Json::as_array)
            .and_then(<[Json]>::first)
            .and_then(|l| l.get("steps"))
            .and_then(Json::as_array)
            .expect("the right engine's lowered steps")
            .to_vec()
    };
    let base_steps = steps_of(&base);
    let last_id = base_steps
        .last()
        .and_then(|s| s.get("id"))
        .and_then(Json::as_str)
        .expect("a last step")
        .to_owned();
    // The changed-field control must change an EXISTING field.
    let changed_id = base_steps
        .iter()
        .find(|s| s.get("value").is_some_and(|v| v.has("line")))
        .and_then(|s| s.get("id"))
        .and_then(Json::as_str)
        .expect("a lowered step carrying a `line` to change")
        .to_owned();

    let check = |label: &str, forged: &Json, kind: &str, step: Option<&str>, path: Option<&str>| {
        let reduction = reduce_traces(forged);
        assert_eq!(
            reduction.get("outcome").and_then(Json::as_str),
            Some("diverged"),
            "the reducer is SILENT on {label}"
        );
        let f = first(&reduction);
        assert_eq!(
            f.get("kind").and_then(Json::as_str),
            Some(kind),
            "{label}: wrong classification"
        );
        assert_eq!(
            f.get("layer").and_then(Json::as_str),
            Some("lowered"),
            "{label}: wrong layer"
        );
        if let Some(step) = step {
            assert_eq!(
                f.get("step").and_then(Json::as_str),
                Some(step),
                "{label}: wrong step"
            );
        }
        if let Some(path) = path {
            assert_eq!(
                f.get("path").and_then(Json::as_str),
                Some(path),
                "{label}: the difference must be MINIMAL — the field, not the whole step"
            );
        }
    };

    // 1. ONE controlled change, deep inside a step's value.
    let changed = forge(&base, |steps| {
        steps
            .iter()
            .map(|s| {
                if s.get("id").and_then(Json::as_str) != Some(changed_id.as_str()) {
                    return s.clone();
                }
                let Json::Object(fields) = s else {
                    return s.clone();
                };
                Json::Object(
                    fields
                        .iter()
                        .map(|(k, v)| {
                            if k != "value" {
                                return (k.clone(), v.clone());
                            }
                            let Json::Object(value) = v else {
                                return (k.clone(), v.clone());
                            };
                            let mut value = value.clone();
                            for entry in &mut value {
                                if entry.0 == "line" {
                                    entry.1 = Json::Int(999_001);
                                }
                            }
                            (k.clone(), Json::Object(value))
                        })
                        .collect(),
                )
            })
            .collect()
    });
    check(
        "one changed field",
        &changed,
        KIND_CHANGED,
        Some(&changed_id),
        Some(".line"),
    );

    // 2. A step only the reference has.
    let dropped = forge(&base, |steps| {
        steps
            .get(..steps.len().saturating_sub(1))
            .unwrap_or_default()
            .to_vec()
    });
    check(
        "a step only the reference has",
        &dropped,
        KIND_LEFT_ONLY,
        Some(&last_id),
        None,
    );

    // 3. A step only the port has.
    let added = forge(&base, |steps| {
        let mut out = steps.to_vec();
        out.push(Json::Object(vec![
            (
                "id".to_owned(),
                Json::Str("handles[synthetic|X.cs|1|E|H]".to_owned()),
            ),
            ("value".to_owned(), Json::Object(Vec::new())),
        ]));
        out
    });
    check(
        "a step only the port has",
        &added,
        KIND_RIGHT_ONLY,
        Some("handles[synthetic|X.cs|1|E|H]"),
        None,
    );

    // 4. The same steps in a different sequence — the difference this layer's
    //    declared `significant` order exists to keep visible.
    let swapped = forge(&base, |steps| {
        let mut out = steps.to_vec();
        out.swap(0, 1);
        out
    });
    check(
        "the same steps in a different order",
        &swapped,
        KIND_ORDERING_ONLY,
        None,
        None,
    );
}

/// Rebuild `traces` with `f` applied to BOTH engines' lowered layers.
fn forge_layers(traces: &Json, name: &str, f: impl Fn(usize, &Json) -> Json) -> Json {
    let Json::Object(top) = traces else {
        panic!("traces is not an object")
    };
    Json::Object(
        top.iter()
            .map(|(k, v)| {
                if k != "traces" {
                    return (k.clone(), v.clone());
                }
                let rebuilt: Vec<Json> = v
                    .as_array()
                    .expect("traces array")
                    .iter()
                    .enumerate()
                    .map(|(side, trace)| {
                        let Json::Object(fields) = trace else {
                            return trace.clone();
                        };
                        Json::Object(
                            fields
                                .iter()
                                .map(|(tk, tv)| {
                                    if tk != "layers" {
                                        return (tk.clone(), tv.clone());
                                    }
                                    let layers: Vec<Json> = tv
                                        .as_array()
                                        .expect("layers")
                                        .iter()
                                        .map(|layer| {
                                            if layer.get("layer").and_then(Json::as_str)
                                                == Some(name)
                                            {
                                                f(side, layer)
                                            } else {
                                                layer.clone()
                                            }
                                        })
                                        .collect();
                                    (tk.clone(), Json::Array(layers))
                                })
                                .collect(),
                        )
                    })
                    .collect();
                (k.clone(), Json::Array(rebuilt))
            })
            .collect(),
    )
}

/// Two engines that BOTH refused a layer agree, however differently they
/// phrased it and however their projections were declared.
///
/// Neither is reachable from the committed corpus — both refusals there carry
/// the same projection — so the rule is driven synthetically at the only level
/// that reaches it. Without this, the short-circuit that states the rule is
/// code no mutation can disturb, and a reducer that grew a refusal-text diff
/// would manufacture a divergence out of message vocabulary.
#[test]
fn two_engines_that_both_refused_a_layer_agree() {
    let base = traces_of("canonical_key_order");
    let forged = forge_layers(&base, "lowered", |side, layer| {
        let (error, projection) = if side == 0 {
            (
                "the reference's own wording",
                Json::Object(vec![("kind".to_owned(), Json::Str("full".to_owned()))]),
            )
        } else {
            (
                "the port's own wording",
                Json::Object(vec![
                    ("kind".to_owned(), Json::Str("partial".to_owned())),
                    (
                        "members".to_owned(),
                        Json::Array(vec![Json::Str("x".to_owned())]),
                    ),
                    (
                        "reason".to_owned(),
                        Json::Str("declared elsewhere".to_owned()),
                    ),
                ]),
            )
        };
        let Json::Object(fields) = layer else {
            panic!("layer is not an object")
        };
        let mut out: Vec<(String, Json)> = fields
            .iter()
            .filter(|(k, _)| !matches!(k.as_str(), "status" | "steps" | "projection" | "error"))
            .cloned()
            .collect();
        out.push(("status".to_owned(), Json::Str("refused".to_owned())));
        out.push(("projection".to_owned(), projection));
        out.push(("error".to_owned(), Json::Str(error.to_owned())));
        out.push(("steps".to_owned(), Json::Array(Vec::new())));
        Json::Object(out)
    });
    let reduction = reduce_traces(&forged);
    assert_eq!(
        reduction.get("outcome").and_then(Json::as_str),
        Some("identical"),
        "two engines that both REFUSED a layer are reported as diverging: {:#?}",
        reduction.get("first")
    );
}

/// Object key ORDER is a difference. Nothing in the corpus exercises it any
/// more — the MOS capture was fixed to carry its surface's own order — so it
/// needs a synthetic control or the rule is untested.
#[test]
fn the_same_fields_in_a_different_key_order_are_a_difference() {
    let base = traces_of("canonical_key_order");
    let forged = forge_layers(&base, "lowered", |side, layer| {
        if side != 1 {
            return layer.clone();
        }
        let Json::Object(fields) = layer else {
            panic!("layer is not an object")
        };
        let mut reversed_one = false;
        Json::Object(
            fields
                .iter()
                .map(|(k, v)| {
                    if k != "steps" {
                        return (k.clone(), v.clone());
                    }
                    let steps: Vec<Json> = v
                        .as_array()
                        .expect("steps")
                        .iter()
                        .map(|step| {
                            let Some(Json::Object(value)) = step.get("value") else {
                                return step.clone();
                            };
                            if reversed_one || value.len() < 2 {
                                return step.clone();
                            }
                            reversed_one = true;
                            let mut flipped = value.clone();
                            flipped.reverse();
                            let Json::Object(sf) = step else {
                                return step.clone();
                            };
                            Json::Object(
                                sf.iter()
                                    .map(|(sk, sv)| {
                                        if sk == "value" {
                                            (sk.clone(), Json::Object(flipped.clone()))
                                        } else {
                                            (sk.clone(), sv.clone())
                                        }
                                    })
                                    .collect(),
                            )
                        })
                        .collect();
                    (k.clone(), Json::Array(steps))
                })
                .collect(),
        )
    });
    let reduction = reduce_traces(&forged);
    assert_eq!(
        reduction.get("outcome").and_then(Json::as_str),
        Some("diverged"),
        "the same fields in a different key ORDER are reported as agreement; the surfaces fix \
         their field order byte-exactly, so a port emitting them in the wrong order is a real \
         defect"
    );
    let first = reduction.get("first").expect("first");
    assert_eq!(
        first.get("kind").and_then(Json::as_str),
        Some(KIND_CHANGED),
        "a key-order difference must be a content difference"
    );
    assert_eq!(
        first.get("path").and_then(Json::as_str),
        Some("[keys]"),
        "the reader should not have to diff two identical-looking objects"
    );
}
