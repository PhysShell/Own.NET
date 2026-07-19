//! The `to_module` port (red skeleton — the green commit fills it in).

use crate::BridgeError;
use own_ir::OwnIr;
use own_lowered::{LoweredDocument, LOWERED_VERSION};

pub(crate) fn lower(facts: &OwnIr) -> Result<LoweredDocument, BridgeError> {
    let _ = facts;
    Ok(LoweredDocument {
        lowered_version: LOWERED_VERSION,
        module: String::new(),
        resources: Vec::new(),
        externs: Vec::new(),
        lifetimes: Vec::new(),
        functions: Vec::new(),
        handles: Vec::new(),
    })
}
