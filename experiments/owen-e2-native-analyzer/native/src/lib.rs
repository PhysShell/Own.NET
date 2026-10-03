//! E2 spike: `owen_e2_check(facts) -> msbuild lines`, the SAME `check_facts` + `render_finding`
//! the `own-cli ownir --format msbuild` path runs. No semantics of its own.

use std::slice;

/// Check one OwnIR facts document and write the msbuild-rendered findings (UTF-8, one per
/// line) into `out`. Returns the number of bytes needed: when it exceeds `cap`, nothing usable
/// was written and the caller retries with a larger buffer. A negative value is a refusal
/// (the facts did not load or the core refused them).
///
/// # Safety
/// `facts` must point to `len` readable bytes and `out` to `cap` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn owen_e2_check(facts: *const u8, len: usize, out: *mut u8, cap: usize) -> isize {
    let bytes = unsafe { slice::from_raw_parts(facts, len) };
    let Ok(text) = std::str::from_utf8(bytes) else { return -1 };
    let Ok(doc) = own_ir::OwnIr::from_json(text) else { return -2 };
    let Ok(findings) = own_bridge::check_facts(&doc) else { return -3 };
    let mut rendered = String::new();
    for f in &findings {
        rendered.push_str(&own_bridge::render_finding(f, "msbuild", "warning"));
        rendered.push('\n');
    }
    let need = rendered.len();
    if need <= cap {
        unsafe { std::ptr::copy_nonoverlapping(rendered.as_ptr(), out, need) };
    }
    need as isize
}
