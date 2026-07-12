//! DI lifetime analysis (DI001–DI005, captive dependency) — an exact port of
//! `ownlang/di.py`.
//!
//! A deterministic property of the DI **registration graph** (who is registered
//! with which lifetime, and who they depend on), not the acquire/release model:
//!
//! * **DI001** singleton → scoped (directly or via transients): captive;
//! * **DI002** singleton weakly captures a scoped service (`WeakReference<T>`);
//! * **DI003** singleton captures a transient `IDisposable`;
//! * **DI004** singleton hand-resolves a transient `IDisposable` from its root
//!   provider (`GetService`/`GetRequiredService` — service-locator);
//! * **DI005** singleton caches a scope-resolved scoped service into a field.
//!
//! **Fact-driven**: the `OwnIR` bridge (own-bridge, step 6) feeds [`Service`]
//! facts; there is no `.own` surface. This module ports the algorithms and pins
//! them with unit tests; end-to-end diagnostic parity lands with the bridge.
//! `(line, code)` is the parity contract (DI findings anchor at the registration
//! line here; the bridge does final call-site anchoring/evidence at step 6).

use std::collections::{BTreeMap, BTreeSet};

use own_diagnostics::{title, Diagnostic};

/// A service lifetime. Unknown strings parse to `None` (ignored, like Python's
/// membership checks against the three known lifetimes).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Lifetime {
    Singleton,
    Scoped,
    Transient,
}

impl Lifetime {
    /// Parse a registration lifetime; unknown → `None`.
    #[must_use]
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "singleton" => Some(Self::Singleton),
            "scoped" => Some(Self::Scoped),
            "transient" => Some(Self::Transient),
            _ => None,
        }
    }
}

/// One DI registration.
///
/// Mirrors the control-flow-relevant fields of `di.Service`; presentation-only
/// metadata (ctor/site tuples, used for evidence text) is omitted — evidence and
/// SARIF are a later step, out of #214.
/// A `(type, file, line)` call/store site (a `root_resolve` or `scope_cache`
/// site), the DI004/DI005 primary anchor.
pub type SiteTriple = (String, String, u32);

#[derive(Debug, Clone)]
pub struct Service {
    pub name: String,
    pub lifetime: Option<Lifetime>,
    pub deps: Vec<String>,
    pub disposable: bool,
    /// The **registration** site — the DI001/002/003 primary `(path, line)` and
    /// the DI004/DI005 fallback when the call/store site is unknown.
    pub file: String,
    pub line: u32,
    /// Services injected via `WeakReference<T>` (DI002).
    pub weak_deps: Vec<String>,
    /// Types hand-resolved from an injected root `IServiceProvider` (DI004).
    pub root_resolves: Vec<String>,
    /// `(type, file, line)` of each `root_resolves` call site — the DI004 primary.
    pub root_resolve_sites: Vec<SiteTriple>,
    /// Types resolved from a self-created scope and cached into a field (DI005).
    pub scope_cached: Vec<String>,
    /// `(type, file, line)` of each `scope_cached` field store — the DI005 primary.
    pub scope_cache_sites: Vec<SiteTriple>,
}

impl Service {
    /// A minimal service with a name + lifetime + registration `(file, line)`.
    #[must_use]
    pub fn new(name: &str, lifetime: Lifetime, file: &str, line: u32) -> Self {
        Self {
            name: name.to_owned(),
            lifetime: Some(lifetime),
            deps: Vec::new(),
            disposable: false,
            file: file.to_owned(),
            line,
            weak_deps: Vec::new(),
            root_resolves: Vec::new(),
            root_resolve_sites: Vec::new(),
            scope_cached: Vec::new(),
            scope_cache_sites: Vec::new(),
        }
    }
}

/// A DI finding, carrying the **primary** verdict anchor `(file, line, code)`.
///
/// The registration site for DI001/002/003, the resolve call site for DI004, the
/// field-store site for DI005 (each with the registration fallback Python uses).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DiFinding {
    pub code: &'static str,
    pub singleton: String,
    pub subject: String,
    pub path: Vec<String>,
    pub file: String,
    pub line: u32,
}

fn by_name(services: &[Service]) -> BTreeMap<&str, &Service> {
    services.iter().map(|s| (s.name.as_str(), s)).collect()
}

fn sort_findings(f: &mut [DiFinding]) {
    // Python sorts each finder's output by (file, line, singleton, captured).
    f.sort_by(|a, b| {
        a.file
            .cmp(&b.file)
            .then_with(|| a.line.cmp(&b.line))
            .then_with(|| a.singleton.cmp(&b.singleton))
            .then_with(|| a.subject.cmp(&b.subject))
    });
}

/// The DI004/DI005 primary anchor: the call/store `site` for the entry `type`
/// when its line ≥ 1, else the registration `(file, line)` fallback (Python's
/// `_di004_primary` / `_di005_primary`).
fn primary_from_site(
    sites: &[SiteTriple],
    entry: &str,
    reg_file: &str,
    reg_line: u32,
) -> (String, u32) {
    for (ty, f, ln) in sites {
        if ty == entry && *ln >= 1 {
            return (f.clone(), *ln);
        }
    }
    (reg_file.to_owned(), reg_line)
}

fn is_singleton(s: &Service) -> bool {
    s.lifetime == Some(Lifetime::Singleton)
}

/// DI001 — every scoped service a singleton reaches through its (transitive,
/// transient-followed) strong dependency chain.
#[must_use]
pub fn find_captive_dependencies(services: &[Service]) -> Vec<DiFinding> {
    let map = by_name(services);
    let mut findings = Vec::new();
    for s in services.iter().filter(|s| is_singleton(s)) {
        let mut reported: BTreeSet<String> = BTreeSet::new();
        let mut visited: BTreeSet<String> = BTreeSet::new();
        let mut stack: Vec<(String, Vec<String>)> = vec![(s.name.clone(), vec![s.name.clone()])];
        while let Some((cur, path)) = stack.pop() {
            let Some(node) = map.get(cur.as_str()) else {
                continue;
            };
            for dep in &node.deps {
                let Some(dnode) = map.get(dep.as_str()) else {
                    continue;
                };
                let mut npath = path.clone();
                npath.push(dep.clone());
                match dnode.lifetime {
                    Some(Lifetime::Scoped) => {
                        if reported.insert(dep.clone()) {
                            findings.push(DiFinding {
                                code: "DI001",
                                singleton: s.name.clone(),
                                subject: dep.clone(),
                                path: npath,
                                file: s.file.clone(),
                                line: s.line,
                            });
                        }
                        // the violating edge is found; don't recurse past it.
                    }
                    Some(Lifetime::Transient) if visited.insert(dep.clone()) => {
                        stack.push((dep.clone(), npath));
                    }
                    _ => {}
                }
            }
        }
    }
    sort_findings(&mut findings);
    findings
}

/// DI002 — every scoped service a singleton reaches via a `WeakReference<T>`
/// entry edge, following strong transient edges thereafter.
#[must_use]
pub fn find_weak_captive_dependencies(services: &[Service]) -> Vec<DiFinding> {
    let map = by_name(services);
    let mut findings = Vec::new();
    for s in services.iter().filter(|s| is_singleton(s)) {
        let mut reported: BTreeSet<String> = BTreeSet::new();
        let mut visited: BTreeSet<String> = BTreeSet::new();
        let mut stack: Vec<(String, Vec<String>)> = s
            .weak_deps
            .iter()
            .map(|dep| (dep.clone(), vec![s.name.clone(), dep.clone()]))
            .collect();
        while let Some((cur, path)) = stack.pop() {
            let Some(cnode) = map.get(cur.as_str()) else {
                continue;
            };
            match cnode.lifetime {
                Some(Lifetime::Scoped) => {
                    if reported.insert(cur.clone()) {
                        findings.push(DiFinding {
                            code: "DI002",
                            singleton: s.name.clone(),
                            subject: cur.clone(),
                            path,
                            file: s.file.clone(),
                            line: s.line,
                        });
                    }
                }
                Some(Lifetime::Transient) if visited.insert(cur.clone()) => {
                    for d in &cnode.deps {
                        let mut npath = path.clone();
                        npath.push(d.clone());
                        stack.push((d.clone(), npath));
                    }
                }
                _ => {}
            }
        }
    }
    sort_findings(&mut findings);
    findings
}

/// DI003 — every transient `IDisposable` captured by a singleton (held to app
/// shutdown), following the transient chain.
#[must_use]
pub fn find_captured_transient_disposables(services: &[Service]) -> Vec<DiFinding> {
    let map = by_name(services);
    let mut findings = Vec::new();
    for s in services.iter().filter(|s| is_singleton(s)) {
        let mut reported: BTreeSet<String> = BTreeSet::new();
        let mut visited: BTreeSet<String> = BTreeSet::new();
        let mut stack: Vec<(String, Vec<String>)> = vec![(s.name.clone(), vec![s.name.clone()])];
        while let Some((cur, path)) = stack.pop() {
            let Some(node) = map.get(cur.as_str()) else {
                continue;
            };
            for dep in &node.deps {
                let Some(dnode) = map.get(dep.as_str()) else {
                    continue;
                };
                if dnode.lifetime != Some(Lifetime::Transient) {
                    continue; // scoped -> DI001; singleton -> its own pass
                }
                let mut npath = path.clone();
                npath.push(dep.clone());
                if dnode.disposable && reported.insert(dep.clone()) {
                    findings.push(DiFinding {
                        code: "DI003",
                        singleton: s.name.clone(),
                        subject: dep.clone(),
                        path: npath.clone(),
                        file: s.file.clone(),
                        line: s.line,
                    });
                }
                if visited.insert(dep.clone()) {
                    stack.push((dep.clone(), npath));
                }
            }
        }
    }
    sort_findings(&mut findings);
    findings
}

/// DI004 — every transient `IDisposable` a singleton hand-resolves from its root
/// provider, following the transient subtree the root builds.
#[must_use]
pub fn find_explicit_root_resolutions(services: &[Service]) -> Vec<DiFinding> {
    let map = by_name(services);
    let mut findings = Vec::new();
    for s in services.iter().filter(|s| is_singleton(s)) {
        let mut reported: BTreeSet<String> = BTreeSet::new();
        let mut visited: BTreeSet<String> = BTreeSet::new();
        let mut stack: Vec<(String, Vec<String>)> = s
            .root_resolves
            .iter()
            .map(|t| (t.clone(), vec![s.name.clone(), t.clone()]))
            .collect();
        while let Some((cur, path)) = stack.pop() {
            let Some(node) = map.get(cur.as_str()) else {
                continue;
            };
            if node.lifetime != Some(Lifetime::Transient) {
                continue; // only transients are root-built/tracked (scoped is DI001's)
            }
            if node.disposable && reported.insert(cur.clone()) {
                // DI004 anchors at the root-resolution call site of the ENTRY type
                // (path[1]), even when the disposable is dragged in transitively;
                // registration is the fallback when the site is unknown.
                let entry = path.get(1).map_or("", String::as_str);
                let (pf, pl) = primary_from_site(&s.root_resolve_sites, entry, &s.file, s.line);
                findings.push(DiFinding {
                    code: "DI004",
                    singleton: s.name.clone(),
                    subject: cur.clone(),
                    path: path.clone(),
                    file: pf,
                    line: pl,
                });
            }
            if visited.insert(cur.clone()) {
                for dep in &node.deps {
                    let mut npath = path.clone();
                    npath.push(dep.clone());
                    stack.push((dep.clone(), npath));
                }
            }
        }
    }
    sort_findings(&mut findings);
    findings
}

/// DI005 — every scoped service a singleton reaches by caching, into a field, a
/// value resolved from a scope it creates (through transients).
#[must_use]
pub fn find_scope_cached_captives(services: &[Service]) -> Vec<DiFinding> {
    let map = by_name(services);
    let mut findings = Vec::new();
    for s in services.iter().filter(|s| is_singleton(s)) {
        let mut reported: BTreeSet<String> = BTreeSet::new();
        for entry in &s.scope_cached {
            if reported.contains(entry) {
                continue;
            }
            let mut visited: BTreeSet<String> = BTreeSet::new();
            let mut stack: Vec<(String, Vec<String>)> =
                vec![(entry.clone(), vec![s.name.clone(), entry.clone()])];
            while let Some((cur, path)) = stack.pop() {
                let Some(node) = map.get(cur.as_str()) else {
                    continue;
                };
                match node.lifetime {
                    Some(Lifetime::Scoped) => {
                        reported.insert(entry.clone());
                        // DI005 anchors at the field-store site of the cached ENTRY
                        // (registration fallback when unknown).
                        let (pf, pl) =
                            primary_from_site(&s.scope_cache_sites, entry, &s.file, s.line);
                        findings.push(DiFinding {
                            code: "DI005",
                            singleton: s.name.clone(),
                            subject: cur.clone(),
                            path,
                            file: pf,
                            line: pl,
                        });
                        break; // first scoped reached — one finding per cached entry
                    }
                    Some(Lifetime::Transient) if visited.insert(cur.clone()) => {
                        for dep in &node.deps {
                            let mut npath = path.clone();
                            npath.push(dep.clone());
                            stack.push((dep.clone(), npath));
                        }
                    }
                    _ => {}
                }
            }
        }
    }
    sort_findings(&mut findings);
    findings
}

/// All DI findings, combined in the bridge's append order (DI001, DI003, DI002,
/// DI004, DI005) — used by [`di_verdicts`] before the final `(file, line, code)`
/// sort. Mirrors `ownir._di_findings`.
#[must_use]
pub fn all_di_findings(services: &[Service]) -> Vec<DiFinding> {
    let mut findings = find_captive_dependencies(services);
    findings.extend(find_captured_transient_disposables(services));
    findings.extend(find_weak_captive_dependencies(services));
    findings.extend(find_explicit_root_resolutions(services));
    findings.extend(find_scope_cached_captives(services));
    findings
}

/// The DI verdicts as `(path, line, code)`, sorted by `(file, line, code)`.
///
/// The #214 comparison surface. `path` is the finding's primary file
/// (registration / resolve site / cache site), part of the verdict identity.
#[must_use]
pub fn di_verdicts(services: &[Service]) -> Vec<(String, u32, &'static str)> {
    let mut out: Vec<(String, u32, &'static str)> = all_di_findings(services)
        .into_iter()
        .map(|f| (f.file, f.line, f.code))
        .collect();
    out.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then_with(|| a.1.cmp(&b.1))
            .then_with(|| a.2.cmp(b.2))
    });
    out
}

/// Project the DI verdicts to `own-diagnostics` values (code + line).
///
/// Kept for the eventual bridge integration; `(path, line, code)` parity uses
/// [`di_verdicts`] since `Diagnostic` does not carry the path.
#[must_use]
pub fn check_di(services: &[Service]) -> Vec<Diagnostic> {
    let mut out = Vec::new();
    for (_file, line, code) in di_verdicts(services) {
        let msg = title(code).unwrap_or(code);
        if let Ok(d) = Diagnostic::new(code, msg, line) {
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
    use super::{
        find_captive_dependencies, find_captured_transient_disposables,
        find_explicit_root_resolutions, find_scope_cached_captives, find_weak_captive_dependencies,
        Lifetime, Service,
    };

    fn svc(name: &str, lt: Lifetime, deps: &[&str]) -> Service {
        let mut s = Service::new(name, lt, "reg.cs", 1);
        s.deps = deps.iter().map(|d| (*d).to_owned()).collect();
        s
    }

    #[test]
    fn di001_direct_singleton_to_scoped() {
        let services = vec![
            svc("App", Lifetime::Singleton, &["Db"]),
            svc("Db", Lifetime::Scoped, &[]),
        ];
        let f = find_captive_dependencies(&services);
        assert_eq!(f.len(), 1);
        assert_eq!((f[0].code, f[0].subject.as_str()), ("DI001", "Db"));
    }

    #[test]
    fn di001_through_a_transient() {
        // singleton -> transient -> scoped is captive (the transient is
        // singleton-lived and drags the scoped along).
        let services = vec![
            svc("App", Lifetime::Singleton, &["Mid"]),
            svc("Mid", Lifetime::Transient, &["Db"]),
            svc("Db", Lifetime::Scoped, &[]),
        ];
        let f = find_captive_dependencies(&services);
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].subject, "Db");
    }

    #[test]
    fn di001_not_followed_through_an_inner_singleton() {
        // singleton -> singleton -> scoped: the INNER singleton is the captor,
        // reported on its own pass — the outer does not double-report.
        let services = vec![
            svc("A", Lifetime::Singleton, &["B"]),
            svc("B", Lifetime::Singleton, &["Db"]),
            svc("Db", Lifetime::Scoped, &[]),
        ];
        let f = find_captive_dependencies(&services);
        // Only B -> Db is reported (once), not A -> ... -> Db.
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].singleton, "B");
    }

    #[test]
    fn di002_weak_scoped_capture() {
        let mut app = Service::new("App", Lifetime::Singleton, "reg.cs", 1);
        app.weak_deps = vec!["Db".to_owned()];
        let services = vec![app, svc("Db", Lifetime::Scoped, &[])];
        let f = find_weak_captive_dependencies(&services);
        assert_eq!(f.len(), 1);
        assert_eq!((f[0].code, f[0].subject.as_str()), ("DI002", "Db"));
    }

    #[test]
    fn di003_transient_disposable_capture() {
        let mut disp = svc("Conn", Lifetime::Transient, &[]);
        disp.disposable = true;
        let services = vec![svc("App", Lifetime::Singleton, &["Conn"]), disp];
        let f = find_captured_transient_disposables(&services);
        assert_eq!(f.len(), 1);
        assert_eq!((f[0].code, f[0].subject.as_str()), ("DI003", "Conn"));
    }

    #[test]
    fn di004_root_resolved_transient_disposable() {
        let mut app = Service::new("App", Lifetime::Singleton, "reg.cs", 1);
        app.root_resolves = vec!["Conn".to_owned()];
        let mut disp = svc("Conn", Lifetime::Transient, &[]);
        disp.disposable = true;
        let services = vec![app, disp];
        let f = find_explicit_root_resolutions(&services);
        assert_eq!(f.len(), 1);
        assert_eq!((f[0].code, f[0].subject.as_str()), ("DI004", "Conn"));
    }

    #[test]
    fn di005_scope_cached_scoped_service() {
        let mut app = Service::new("App", Lifetime::Singleton, "reg.cs", 1);
        app.scope_cached = vec!["Db".to_owned()];
        let services = vec![app, svc("Db", Lifetime::Scoped, &[])];
        let f = find_scope_cached_captives(&services);
        assert_eq!(f.len(), 1);
        assert_eq!((f[0].code, f[0].subject.as_str()), ("DI005", "Db"));
    }

    #[test]
    fn no_captive_when_all_singleton() {
        let services = vec![
            svc("A", Lifetime::Singleton, &["B"]),
            svc("B", Lifetime::Singleton, &[]),
        ];
        assert!(find_captive_dependencies(&services).is_empty());
    }
}
