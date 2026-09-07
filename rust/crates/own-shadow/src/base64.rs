//! Canonical base64, for the artifact's raw-input attestation (owner decision
//! B-2).
//!
//! The reference's half is `base64.b64encode` / `b64decode(..., validate=True)`
//! plus a re-encode check. This is the port's, and it is written here rather
//! than pulled in for one reason the `sha2` decision (D-3) does **not** cover:
//! base64 is a page of table lookups with no cryptographic content, so a
//! dependency would buy no audited implementation — only a version to pin.
//! `sha2` earned its place because hand-rolling SHA-256 under
//! `arithmetic_side_effects = deny` would have traded an audited algorithm for
//! a page of justified suppressions; that argument does not transfer to an
//! alphabet.
//!
//! ## Canonical, and why the decoder is strict
//!
//! The rule is one sentence and both sides implement *that sentence*:
//!
//! > an encoding is canonical iff re-encoding the bytes it decodes to
//! > reproduces it.
//!
//! It matters because the artifact uses the encoding as an **attestation**. If
//! two spellings decoded to the same bytes — `YQ==` and `YR==` both decode to
//! `b"a"`, since the last character's discarded bits are ignored by a lenient
//! decoder — then two different artifacts would attest one input, and "the
//! bytes this engine consumed" would have more than one written form. A
//! decoder that repaired its input would let that through silently, so this one
//! refuses: the standard alphabet only, padding only at the end, a length that
//! is a multiple of four, and discarded bits that are zero.
//!
//! No whitespace is skipped, deliberately. MIME base64 tolerates line breaks;
//! an attestation must not, or a re-wrapped blob would be a second spelling.

/// Encode to the standard alphabet with padding and no line breaks.
#[must_use]
pub fn encode(raw: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let symbol = |six: u32| -> char {
        // `ALPHABET` is indexed by a value masked to 6 bits, so the lookup
        // cannot be out of range; `get` keeps it out of the panicking path all
        // the same, because this crate denies `indexing_slicing`.
        char::from(*ALPHABET.get(six as usize & 0x3f).unwrap_or(&b'A'))
    };
    let mut out = String::new();
    let mut chunk: Vec<u8> = Vec::with_capacity(3);
    for byte in raw {
        chunk.push(*byte);
        if chunk.len() == 3 {
            let (a, b, c) = (
                u32::from(*chunk.first().unwrap_or(&0)),
                u32::from(*chunk.get(1).unwrap_or(&0)),
                u32::from(*chunk.get(2).unwrap_or(&0)),
            );
            let acc = a.wrapping_shl(16) | b.wrapping_shl(8) | c;
            out.push(symbol(acc.wrapping_shr(18)));
            out.push(symbol(acc.wrapping_shr(12)));
            out.push(symbol(acc.wrapping_shr(6)));
            out.push(symbol(acc));
            chunk.clear();
        }
    }
    match chunk.len() {
        1 => {
            let a = u32::from(*chunk.first().unwrap_or(&0));
            let acc = a.wrapping_shl(16);
            out.push(symbol(acc.wrapping_shr(18)));
            out.push(symbol(acc.wrapping_shr(12)));
            out.push('=');
            out.push('=');
        }
        2 => {
            let (a, b) = (
                u32::from(*chunk.first().unwrap_or(&0)),
                u32::from(*chunk.get(1).unwrap_or(&0)),
            );
            let acc = a.wrapping_shl(16) | b.wrapping_shl(8);
            out.push(symbol(acc.wrapping_shr(18)));
            out.push(symbol(acc.wrapping_shr(12)));
            out.push(symbol(acc.wrapping_shr(6)));
            out.push('=');
        }
        _ => {}
    }
    out
}

const fn sextet(b: u8) -> Option<u32> {
    match b {
        b'A'..=b'Z' => Some((b as u32).wrapping_sub(b'A' as u32)),
        b'a'..=b'z' => Some((b as u32).wrapping_sub(b'a' as u32).wrapping_add(26)),
        b'0'..=b'9' => Some((b as u32).wrapping_sub(b'0' as u32).wrapping_add(52)),
        b'+' => Some(62),
        b'/' => Some(63),
        _ => None,
    }
}

/// Decode canonical base64, or say why it is not canonical.
///
/// # Errors
/// A character outside the alphabet, a length that is not a multiple of four,
/// padding anywhere but at the end, more than two pad characters, or a final
/// group whose discarded bits are non-zero. Every one of those is a *second
/// spelling* of some byte sequence, which is what an attestation may not have.
pub fn decode(encoded: &str) -> Result<Vec<u8>, String> {
    let bytes = encoded.as_bytes();
    if bytes.len() % 4 != 0 {
        return Err(format!(
            "input.raw.base64 is not valid base64: its length ({}) is not a multiple of four",
            bytes.len()
        ));
    }
    let padding = bytes.iter().rev().take_while(|b| **b == b'=').count();
    if padding > 2 {
        return Err(
            "input.raw.base64 is not valid base64: more than two padding characters".to_owned(),
        );
    }
    let body = bytes.len().saturating_sub(padding);
    let mut acc: u32 = 0;
    let mut nbits: u32 = 0;
    let mut out: Vec<u8> = Vec::new();
    for (i, b) in bytes.iter().enumerate() {
        if i >= body {
            break; // the padding run, already counted
        }
        let Some(six) = sextet(*b) else {
            return Err(format!(
                "input.raw.base64 is not valid base64: byte {i} is {:?}, which is not in the \
                 standard alphabet (no whitespace is skipped — a re-wrapped blob would be a \
                 second spelling of one input)",
                char::from(*b)
            ));
        };
        acc = acc.wrapping_shl(6) | six;
        nbits = nbits.wrapping_add(6);
        if nbits >= 8 {
            nbits = nbits.wrapping_sub(8);
            out.push(u8::try_from(acc.wrapping_shr(nbits) & 0xff).unwrap_or(0));
        }
    }
    // The bits left in `acc` belong to no byte. A lenient decoder discards
    // them; this one requires them to be zero, because a non-zero remainder is
    // exactly how `YR==` becomes a second spelling of `YQ==`.
    let mask = 1u32.wrapping_shl(nbits).wrapping_sub(1);
    if acc & mask != 0 {
        return Err(
            "input.raw.base64 is not canonical base64: the final group carries non-zero bits \
             that decode to nothing, so more than one spelling would attest the same input"
                .to_owned(),
        );
    }
    if encode(&out) != encoded {
        return Err(
            "input.raw.base64 is not canonical base64: re-encoding the bytes it decodes to does \
             not reproduce it, so more than one spelling would attest the same input"
                .to_owned(),
        );
    }
    Ok(out)
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::{decode, encode};

    /// RFC 4648 §10's own vectors, plus the three padding shapes. The reference
    /// is `CPython`'s `base64`, and these are the values both agree on.
    #[test]
    fn the_rfc_vectors_round_trip() {
        for (raw, encoded) in [
            (&b""[..], ""),
            (&b"f"[..], "Zg=="),
            (&b"fo"[..], "Zm8="),
            (&b"foo"[..], "Zm9v"),
            (&b"foob"[..], "Zm9vYg=="),
            (&b"fooba"[..], "Zm9vYmE="),
            (&b"foobar"[..], "Zm9vYmFy"),
        ] {
            assert_eq!(encode(raw), encoded, "encoding {raw:?}");
            assert_eq!(decode(encoded).as_deref(), Ok(raw), "decoding {encoded:?}");
        }
    }

    /// Every byte value survives, which a 6-bit alphabet makes easy to get
    /// subtly wrong at the high end.
    #[test]
    fn every_byte_value_round_trips() {
        let raw: Vec<u8> = (0..=255u8).collect();
        assert_eq!(decode(&encode(&raw)), Ok(raw));
    }

    /// The refusals, one per way a second spelling could exist. Without these
    /// the decoder could quietly become lenient and every positive check above
    /// would still pass.
    #[test]
    fn a_non_canonical_encoding_is_refused() {
        for (label, encoded, needle) in [
            ("non-zero discarded bits", "YR==", "not canonical base64"),
            (
                "a character outside the alphabet",
                "Zm9-",
                "not in the standard alphabet",
            ),
            (
                "embedded whitespace",
                "Zm9v Zm9",
                "not in the standard alphabet",
            ),
            (
                "a length that is not a multiple of four",
                "Zm9",
                "multiple of four",
            ),
            (
                "more padding than a group can carry",
                "Zm9v====",
                "more than two padding",
            ),
            // A `=` that is not part of the trailing run is not padding at all,
            // and the message says so rather than inventing a "misplaced
            // padding" class: the alphabet check is the mechanism, and the
            // #259 cp1 taxonomy lesson is that a failure is classified by its
            // mechanism, never by what it looks like.
            (
                "padding in the middle",
                "Z=9v",
                "not in the standard alphabet",
            ),
        ] {
            let out = decode(encoded);
            assert!(
                out.as_ref().err().is_some_and(|e| e.contains(needle)),
                "{label}: {encoded:?} was not refused naming {needle:?}, got {out:?}"
            );
        }
        // `YQ==` is the canonical spelling of the bytes `YR==` decodes to, and
        // it is accepted — the refusal above is about the spelling, not the
        // content.
        assert_eq!(decode("YQ==").as_deref(), Ok(&b"a"[..]));
    }
}
