//! Reactive-effect stability analysis (EFF001, the effect storm) — an exact port
//! of `ownlang/effects.py`.
//!
//! A deterministic property of the **render-scope binding graph**: a `useEffect`
//! that performs IO and depends on a name whose identity changes every render (a
//! fresh object/array/`new` literal, directly or via a derivation chain) re-fires
//! every render — a request storm. The stability lattice `STABLE < UNKNOWN <
//! UNSTABLE` is computed to a fixpoint over binding references with a cycle guard.
//!
//! This is a **fact-driven** analysis: the `OwnIR` bridge (own-bridge, step 6)
//! feeds [`Effect`]/[`Binding`] facts; there is no `.own` surface. This module
//! ports the algorithm and pins it with unit tests; its end-to-end diagnostic
//! parity lands with the bridge. `#[allow(clippy::panic)]`-free; `(line, code)`
//! is the parity contract (EFF001 anchors at the effect's call line).

use std::collections::{BTreeMap, BTreeSet};

use own_diagnostics::{title, Diagnostic};

/// The stability lattice (join = worst case): `Stable < Unknown < Unstable`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Stability {
    Stable,
    Unknown,
    Unstable,
}

impl Stability {
    const fn rank(self) -> u8 {
        match self {
            Self::Stable => 0,
            Self::Unknown => 1,
            Self::Unstable => 2,
        }
    }
}

/// One render-scope binding: `name` bound to an initialiser of kind `init`, which
/// may reference other binding names (`refs`). Mirrors `effects.Binding`.
#[derive(Debug, Clone)]
pub struct Binding {
    pub name: String,
    pub init: String,
    pub refs: Vec<String>,
    pub line: u32,
}

/// One `useEffect`, mirroring `effects.Effect`.
///
/// The deps it declares, whether its body does IO, and the render-scope bindings
/// visible to it. `file`/`line` are the effect's call site — the finding's
/// primary `(path, line)`.
#[derive(Debug, Clone)]
pub struct Effect {
    pub component: String,
    pub deps: Vec<String>,
    pub io: bool,
    pub bindings: Vec<Binding>,
    pub file: String,
    pub line: u32,
}

/// An EFF001 finding: the effect whose IO re-fires and the unstable dependency.
///
/// `origin` is the upstream binding whose fresh identity is the root cause;
/// `file`/`line` are the verdict's primary `(path, line)` — the effect call site.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectStorm {
    pub component: String,
    pub dep: String,
    pub origin: String,
    pub file: String,
    pub line: u32,
}

fn kind_stability(init: &str) -> Option<Stability> {
    match init {
        "object" | "array" | "new" => Some(Stability::Unstable),
        "memo" | "callback" | "ref" | "prop" | "state" | "primitive" | "import" | "fn"
        | "param" => Some(Stability::Stable),
        // "ident"/"spread"/"ternary"/"derive" join over refs; handled by the caller.
        _ => None,
    }
}

fn is_derived(init: &str) -> bool {
    matches!(init, "ident" | "spread" | "ternary" | "derive")
}

/// A plain identifier or member chain (`tenantId`, `props.id`) — referentially
/// stable when it has no render-scope binding. Port of the `_IDENT` regex
/// `^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$`.
fn is_ident_chain(s: &str) -> bool {
    if s.is_empty() {
        return false;
    }
    let seg_ok = |seg: &str| {
        let mut chars = seg.chars();
        match chars.next() {
            Some(c) if c == '_' || c == '$' || c.is_ascii_alphabetic() => {}
            _ => return false,
        }
        chars.all(|c| c == '_' || c == '$' || c.is_ascii_alphanumeric())
    };
    s.split('.').all(seg_ok)
}

/// Stability of each binding name, resolved to a fixpoint with memoization and a
/// cycle guard, recording the upstream `origin` of an unstable name. Port of
/// `effects._Lattice`.
struct Lattice<'a> {
    by_name: BTreeMap<&'a str, &'a Binding>,
    stab: BTreeMap<String, Stability>,
    origin: BTreeMap<String, String>,
}

impl<'a> Lattice<'a> {
    fn new(bindings: &'a [Binding]) -> Self {
        Self {
            by_name: bindings.iter().map(|b| (b.name.as_str(), b)).collect(),
            stab: BTreeMap::new(),
            origin: BTreeMap::new(),
        }
    }

    fn stability(&mut self, name: &str) -> Stability {
        self.resolve(name, &BTreeSet::new()).0
    }

    fn origin_of(&self, name: &str) -> String {
        self.origin
            .get(name)
            .cloned()
            .unwrap_or_else(|| name.to_owned())
    }

    fn resolve(&mut self, name: &str, on_stack: &BTreeSet<String>) -> (Stability, String) {
        if let Some(s) = self.stab.get(name) {
            return (*s, self.origin_of(name));
        }
        let Some(b) = self.by_name.get(name).copied() else {
            // No render-scope binding: an identifier/member chain is referentially
            // stable; anything else (a literal/ctor/call) stays conservative.
            let stab = if is_ident_chain(name) {
                Stability::Stable
            } else {
                Stability::Unknown
            };
            return (stab, name.to_owned());
        };
        if on_stack.contains(name) {
            // an identity cycle (a = b; b = a): cannot prove unstable — stay safe.
            return (Stability::Unknown, name.to_owned());
        }
        let mut next_stack = on_stack.clone();
        next_stack.insert(name.to_owned());
        let (stab, origin) = self.classify(b, &next_stack);
        self.stab.insert(name.to_owned(), stab);
        self.origin.insert(name.to_owned(), origin.clone());
        (stab, origin)
    }

    fn classify(&mut self, b: &Binding, on_stack: &BTreeSet<String>) -> (Stability, String) {
        if let Some(s) = kind_stability(&b.init) {
            return (s, b.name.clone());
        }
        if is_derived(&b.init) {
            if b.refs.is_empty() {
                return (Stability::Unknown, b.name.clone());
            }
            let mut worst = Stability::Stable;
            let mut worst_origin = b.name.clone();
            for r in &b.refs {
                let (s, o) = self.resolve(r, on_stack);
                if s.rank() > worst.rank() {
                    worst = s;
                    worst_origin = o;
                }
            }
            return (worst, worst_origin);
        }
        // "call" or any unrecognised kind: opaque identity -> conservative.
        (Stability::Unknown, b.name.clone())
    }
}

/// Every EFF001 effect storm: an IO effect with a provably `Unstable` dependency
/// (the first one). Deterministic, sorted by `(line, dep)`. Port of
/// `find_effect_storms`.
#[must_use]
pub fn find_effect_storms(effects: &[Effect]) -> Vec<EffectStorm> {
    let mut out: Vec<EffectStorm> = Vec::new();
    for e in effects {
        if !e.io {
            continue;
        }
        let mut lat = Lattice::new(&e.bindings);
        for dep in &e.deps {
            if lat.stability(dep) != Stability::Unstable {
                continue;
            }
            out.push(EffectStorm {
                component: e.component.clone(),
                dep: dep.clone(),
                origin: lat.origin_of(dep),
                file: e.file.clone(),
                line: e.line,
            });
            break; // one finding per effect
        }
    }
    // Python sorts by (file, line, dep) — file is verdict identity, not metadata.
    out.sort_by(|a, b| {
        a.file
            .cmp(&b.file)
            .then_with(|| a.line.cmp(&b.line))
            .then_with(|| a.dep.cmp(&b.dep))
    });
    out
}

/// The EFF001 verdicts as `(path, line, code)` — the #214 comparison surface.
/// `path` is the effect's file (a fact-set can span files), so it is part of the
/// verdict identity, not presentation.
#[must_use]
pub fn effect_verdicts(effects: &[Effect]) -> Vec<(String, u32, &'static str)> {
    find_effect_storms(effects)
        .into_iter()
        .map(|s| (s.file, s.line, "EFF001"))
        .collect()
}

/// Project the effect storms to `(line, EFF001)` diagnostics — the #214 verdict
/// surface (the bridge does final anchoring/evidence at step 6).
#[must_use]
pub fn effect_diagnostics(effects: &[Effect]) -> Vec<Diagnostic> {
    let mut out = Vec::new();
    for storm in find_effect_storms(effects) {
        let msg = title("EFF001").unwrap_or("EFF001");
        if let Ok(d) = Diagnostic::new("EFF001", msg, storm.line) {
            out.push(d);
        }
    }
    out
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]
mod tests {
    use super::{find_effect_storms, Binding, Effect};

    fn binding(name: &str, init: &str, refs: &[&str]) -> Binding {
        Binding {
            name: name.to_owned(),
            init: init.to_owned(),
            refs: refs.iter().map(|s| (*s).to_owned()).collect(),
            line: 1,
        }
    }

    fn effect(deps: &[&str], io: bool, bindings: Vec<Binding>) -> Effect {
        Effect {
            component: "C".to_owned(),
            deps: deps.iter().map(|s| (*s).to_owned()).collect(),
            io,
            bindings,
            file: "C.tsx".to_owned(),
            line: 10,
        }
    }

    #[test]
    fn fresh_object_dep_with_io_is_a_storm() {
        let e = effect(&["opts"], true, vec![binding("opts", "object", &[])]);
        let storms = find_effect_storms(&[e]);
        assert_eq!(storms.len(), 1);
        assert_eq!(storms[0].dep, "opts");
        assert_eq!(storms[0].line, 10);
    }

    #[test]
    fn memoised_dep_is_clean() {
        let e = effect(&["opts"], true, vec![binding("opts", "memo", &[])]);
        assert!(find_effect_storms(&[e]).is_empty());
    }

    #[test]
    fn no_io_never_fires() {
        let e = effect(&["opts"], false, vec![binding("opts", "object", &[])]);
        assert!(find_effect_storms(&[e]).is_empty());
    }

    #[test]
    fn instability_propagates_through_a_derivation_chain() {
        // a = {..}(unstable); b = a; c = b — c is unstable, origin a.
        let e = effect(
            &["c"],
            true,
            vec![
                binding("a", "object", &[]),
                binding("b", "ident", &["a"]),
                binding("c", "ident", &["b"]),
            ],
        );
        let storms = find_effect_storms(&[e]);
        assert_eq!(storms.len(), 1);
        assert_eq!(storms[0].dep, "c");
        assert_eq!(storms[0].origin, "a");
    }

    #[test]
    fn opaque_call_is_unknown_not_a_storm() {
        // a call return has unknown identity — conservative, no false positive.
        let e = effect(&["x"], true, vec![binding("x", "call", &[])]);
        assert!(find_effect_storms(&[e]).is_empty());
    }

    #[test]
    fn plain_identifier_dep_without_binding_is_stable() {
        let e = effect(&["props.id"], true, vec![]);
        assert!(find_effect_storms(&[e]).is_empty());
    }

    #[test]
    fn identity_cycle_stays_safe() {
        // a = b; b = a (both ident derivations) — cannot prove unstable.
        let e = effect(
            &["a"],
            true,
            vec![binding("a", "ident", &["b"]), binding("b", "ident", &["a"])],
        );
        assert!(find_effect_storms(&[e]).is_empty());
    }
}
