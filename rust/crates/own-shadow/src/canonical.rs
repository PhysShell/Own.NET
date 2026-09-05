//! The canonical document identity: the byte form and the digest over it.
//!
//! One job — to **name an input**, so that "both engines saw the same
//! document" is a checked fact rather than an assumption about which file was
//! passed where. The rule is frozen in `ownlang/repro.py`'s docstring and
//! restated in [`crate::json`]: it is taken over the *parsed* document (so
//! whitespace, key order and a parser-resolved duplicate key are insignificant
//! text formatting), over a closed value domain, with keys sorted by code
//! point and no insignificant whitespace.
//!
//! Unlike the Python side, this side cannot fail: the domain is enforced by
//! [`crate::json::Json`] at parse time, so every value that exists here is
//! canonicalizable.

use std::fmt::Write as _;

use sha2::{Digest, Sha256};

use crate::json::Json;

/// The digest algorithm, named in the artifact so that changing it is a
/// visible contract change rather than a silent reinterpretation of the same
/// hex string.
pub const CANONICAL_ALGORITHM: &str = "sha256";

/// A document's canonical identity: what the artifact's `input.canonical`
/// carries, and what verification recomputes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CanonicalHash {
    pub algorithm: &'static str,
    /// Lowercase hex.
    pub digest: String,
    /// The length of the canonical byte form, carried beside the digest so a
    /// mismatch says *which* of the two disagrees.
    pub bytes: usize,
}

/// The canonical byte form of a parsed document.
#[must_use]
pub fn canonical_bytes(value: &Json) -> Vec<u8> {
    value.to_canonical().into_bytes()
}

/// The canonical identity of a parsed document.
#[must_use]
pub fn canonical_hash(value: &Json) -> CanonicalHash {
    let raw = canonical_bytes(value);
    let mut hasher = Sha256::new();
    hasher.update(&raw);
    let mut digest = String::with_capacity(64);
    for byte in hasher.finalize() {
        // `write!` into a String is infallible; the Result is discarded rather
        // than unwrapped so the crate keeps its no-panic surface.
        let _ = write!(digest, "{byte:02x}");
    }
    CanonicalHash {
        algorithm: CANONICAL_ALGORITHM,
        digest,
        bytes: raw.len(),
    }
}
