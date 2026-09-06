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
///
/// The remaining members carry the finding's **presentation**, which the
/// reference's `EffectStorm` owns rather than the bridge (`ownlang/effects.py`;
/// spec/Bridge.md BR-B1 — the analysis owns its verdict, message included):
/// `origin_kind` picks the kind phrase, `chain` supplies the `via …` clause, and
/// `decl_line` is where the unstable identity is minted — the second hop of the
/// bridge's two-step evidence slice (BR-V5).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectStorm {
    pub component: String,
    pub dep: String,
    pub origin: String,
    /// The `init` kind of the origin binding (`object`/`array`/`new`/…), or
    /// `"object"` when the origin has no binding — the reference's fallback.
    pub origin_kind: String,
    pub file: String,
    pub line: u32,
    /// The origin binding's declaration line — the fix site. Falls back to the
    /// effect's own line when the origin has no binding.
    pub decl_line: u32,
    /// The reference chain from the dependency to its origin. Renders as the
    /// `via …` clause only when it has more than one element.
    pub chain: Vec<String>,
}

impl EffectStorm {
    /// The phrase naming what the origin is (`_kind_phrase`).
    fn kind_phrase(&self) -> &'static str {
        match self.origin_kind.as_str() {
            "object" => "an object literal",
            "array" => "an array literal",
            "new" => "a freshly constructed object",
            _ => "a value with an unstable identity",
        }
    }

    /// The EFF001 human message, byte-for-byte the reference's
    /// `EffectStorm.message`. Owned here because the finder owns the verdict;
    /// the bridge copies it and never rewords it.
    #[must_use]
    pub fn message(&self) -> String {
        let phrase = self.kind_phrase();
        let root = if self.origin == self.dep {
            format!(
                "dependency '{}' is {phrase} created in render scope, so its identity \
                 changes on every render",
                self.dep
            )
        } else {
            let via = if self.chain.len() > 1 {
                format!(" (via {})", self.chain.join(" -> "))
            } else {
                String::new()
            };
            format!(
                "dependency '{}' derives from '{}', {phrase} created in render \
                 scope{via}, so its identity changes on every render",
                self.dep, self.origin
            )
        };
        format!(
            "effect re-runs on every render: {root}; the effect performs IO, which can \
             become a request storm — stabilise '{}' with useMemo/useCallback (or move \
             it out of render)",
            self.origin
        )
    }
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
    /// The reference chain that carried the instability, captor first — the
    /// `via a -> b -> c` clause of the EFF001 message (`_Lattice._path`).
    path: BTreeMap<String, Vec<String>>,
}

impl<'a> Lattice<'a> {
    fn new(bindings: &'a [Binding]) -> Self {
        Self {
            by_name: bindings.iter().map(|b| (b.name.as_str(), b)).collect(),
            stab: BTreeMap::new(),
            origin: BTreeMap::new(),
            path: BTreeMap::new(),
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

    fn path_of(&self, name: &str) -> Vec<String> {
        self.path
            .get(name)
            .cloned()
            .unwrap_or_else(|| vec![name.to_owned()])
    }

    fn resolve(
        &mut self,
        name: &str,
        on_stack: &BTreeSet<String>,
    ) -> (Stability, String, Vec<String>) {
        if let Some(s) = self.stab.get(name) {
            return (*s, self.origin_of(name), self.path_of(name));
        }
        let Some(b) = self.by_name.get(name).copied() else {
            // No render-scope binding: an identifier/member chain is referentially
            // stable; anything else (a literal/ctor/call) stays conservative.
            let stab = if is_ident_chain(name) {
                Stability::Stable
            } else {
                Stability::Unknown
            };
            return (stab, name.to_owned(), vec![name.to_owned()]);
        };
        if on_stack.contains(name) {
            // an identity cycle (a = b; b = a): cannot prove unstable — stay safe.
            return (Stability::Unknown, name.to_owned(), vec![name.to_owned()]);
        }
        let mut next_stack = on_stack.clone();
        next_stack.insert(name.to_owned());
        let (stab, origin, path) = self.classify(b, &next_stack);
        self.stab.insert(name.to_owned(), stab);
        self.origin.insert(name.to_owned(), origin.clone());
        self.path.insert(name.to_owned(), path.clone());
        (stab, origin, path)
    }

    fn classify(
        &mut self,
        b: &Binding,
        on_stack: &BTreeSet<String>,
    ) -> (Stability, String, Vec<String>) {
        if let Some(s) = kind_stability(&b.init) {
            return (s, b.name.clone(), vec![b.name.clone()]);
        }
        if is_derived(&b.init) {
            if b.refs.is_empty() {
                return (Stability::Unknown, b.name.clone(), vec![b.name.clone()]);
            }
            let mut worst = Stability::Stable;
            let mut worst_origin = b.name.clone();
            let mut worst_path = vec![b.name.clone()];
            for r in &b.refs {
                let (s, o, p) = self.resolve(r, on_stack);
                if s.rank() > worst.rank() {
                    worst = s;
                    worst_origin = o;
                    worst_path = std::iter::once(b.name.clone()).chain(p).collect();
                }
            }
            return (worst, worst_origin, worst_path);
        }
        // "call" or any unrecognised kind: opaque identity -> conservative.
        (Stability::Unknown, b.name.clone(), vec![b.name.clone()])
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
            let origin = lat.origin_of(dep);
            let binding = e.bindings.iter().find(|b| b.name == origin);
            out.push(EffectStorm {
                component: e.component.clone(),
                dep: dep.clone(),
                // `decl.get(origin, e.line)` and `b.init if b else "object"`:
                // an origin with no binding of its own takes the effect's own
                // line and the object phrasing.
                origin_kind: binding.map_or("object", |b| b.init.as_str()).to_owned(),
                decl_line: binding.map_or(e.line, |b| b.line),
                chain: lat.path_of(dep),
                origin,
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
