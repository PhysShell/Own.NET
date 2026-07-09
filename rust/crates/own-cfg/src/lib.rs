//! `own-cfg` — `OwnLang` AST → CFG lowering: the port of
//! `ownlang/{cfg,cfg_json,buffers}.py` (P-022 migration step 3).
//!
//! The crate consumes the [`own_syntax`] AST and produces, per function, a
//! control-flow graph ([`Cfg`]) plus the flow-insensitive resolver diagnostics.
//! Its one **frozen contract** is the canonical CFG-JSON seam
//! ([`canonical_json`] / [`module_cfg_json`]): the differential oracle
//! byte-compares it against `python -m ownlang cfg --format json` over the whole
//! corpus. Python wins on any divergence — the port introduces no behaviour
//! change.
//!
//! **Diagnostics carry code + line only.** The CFG-JSON seam this step is gated
//! on does *not* include diagnostic text — the human message is a verdict-layer
//! contract, pinned later by the SARIF oracle once `own-diagnostics`/`own-analysis`
//! land. Emitting the code + line here is enough to (a) drive every
//! instruction-emission decision Python makes and (b) be cross-checked against
//! Python's build-time diagnostics per the migration ratchet, without importing
//! ~200 lines of message-formatting that this step's oracle cannot see. Per the
//! P-022 DAG, `own-cfg` depends on `own-syntax` (and may depend on the `own-ir`
//! span leaf) only — never on analysis or diagnostics.

pub mod buffers;
pub mod builder;
pub mod ir;
pub mod json;

use own_syntax::ast::Module;

pub use buffers::{validate_policies, BufferInfo, BufferMode, Policies, Policy};
pub use builder::{
    build_cfg, collect_kinds, collect_policies, collect_resource_names, collect_signatures,
};
pub use ir::{Block, BlockId, Cfg, Instr, Kind, Signature, SymId, Symbol};
pub use json::{canonical_json, module_cfg_value, python_dumps, CFG_JSON_VERSION};

/// A flow-insensitive resolver diagnostic — its code and 1-based source line.
///
/// The human message is deliberately absent (see the crate docs): this step's
/// oracle compares the CFG-JSON seam, which does not carry diagnostic text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diag {
    pub code: &'static str,
    pub line: u32,
}

impl Diag {
    pub(crate) const fn new(code: &'static str, line: u32) -> Self {
        Self { code, line }
    }
}

/// Lower every function in a module, mirroring the `cmd_cfg` driver.
///
/// Collects the resource names / signatures / policies / kinds once, then
/// [`build_cfg`]s each function. Returns the per-function CFGs and the
/// concatenated build-time diagnostics (the `cfg` surface does not run
/// `validate_policies`).
#[must_use]
pub fn build_module(module: &Module) -> (Vec<Cfg>, Vec<Diag>) {
    let resource_names = collect_resource_names(module);
    let signatures = collect_signatures(module);
    let policies = collect_policies(module);
    let kinds = collect_kinds(module);

    let mut cfgs = Vec::with_capacity(module.functions.len());
    let mut diags = Vec::new();
    for f in &module.functions {
        let (cfg, d) = build_cfg(f, &resource_names, &signatures, &policies, &kinds);
        cfgs.push(cfg);
        diags.extend(d);
    }
    (cfgs, diags)
}

/// The canonical CFG-JSON document for a whole module — the exact string
/// `python -m ownlang cfg --format json` prints.
#[must_use]
pub fn module_cfg_json(module: &Module) -> String {
    let (cfgs, _) = build_module(module);
    canonical_json(&cfgs)
}

#[cfg(test)]
#[allow(clippy::expect_used)] // test-only unwraps on known-good fixtures
mod tests {
    use super::{build_module, module_cfg_json, CFG_JSON_VERSION};
    use own_syntax::parse;
    use serde_json::Value;

    const CLEAN: &str = "module M\n\
        resource Conn { acquire open release close }\n\
        fn f() {\n  let c = acquire Conn(1);\n  release c;\n}\n";

    #[test]
    fn lowers_a_clean_program_without_diagnostics() {
        let module = parse(CLEAN).expect("clean source parses");
        let (cfgs, diags) = build_module(&module);
        assert_eq!(cfgs.len(), 1, "one function");
        assert!(
            diags.is_empty(),
            "a clean program has no resolver diagnostics"
        );
        let cfg = cfgs.first().expect("one cfg");
        assert_eq!(cfg.fn_name, "f");
        assert!(!cfg.has_return_type);
        // entry block, acquire then release, one owned symbol.
        assert_eq!(cfg.symbols.len(), 1);
        assert_eq!(cfg.symbols.first().expect("sym").name, "c");
    }

    #[test]
    fn canonical_json_is_a_valid_versioned_document() {
        let module = parse(CLEAN).expect("clean source parses");
        let text = module_cfg_json(&module);
        let doc: Value = serde_json::from_str(&text).expect("emits valid JSON");
        assert_eq!(
            doc.get("ownlang_cfg_version"),
            Some(&Value::from(CFG_JSON_VERSION))
        );
        assert!(doc
            .get("functions")
            .and_then(Value::as_array)
            .is_some_and(|a| a.len() == 1));
    }

    #[test]
    fn undefined_name_is_own030() {
        let module = parse("module M\nfn f() {\n  use nope;\n}\n").expect("parses");
        let (_cfgs, diags) = build_module(&module);
        assert_eq!(diags.len(), 1);
        let d = diags.first().expect("one diag");
        assert_eq!(d.code, "OWN030");
        assert_eq!(d.line, 3);
    }
}
