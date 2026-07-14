//! sandboy — wrap-the-child confinement for one untrusted command.
//!
//! The Sandboy MVP (Layer 2 of docs/notes/sandboy-isolation-adr.md): fork is
//! implicit — we confine THIS process, then `execve` the target, and both
//! Landlock and seccomp survive the exec. So
//!
//!     sandboy run --policy step.toml -- bash -lc '<a .007/gate.toml step>'
//!
//! runs that step with:
//!   * filesystem access scoped to an allowlist of paths (Landlock);
//!   * TCP connect/bind scoped to an allowlist of ports (Landlock ABI v4);
//!   * a seccomp denylist stripping the clearly-dangerous syscalls
//!     (ptrace, mount, bpf, kexec, …) to shrink host-kernel attack surface,
//!   * while keeping *broad freedom* for everything a normal toolchain needs.
//!
//! This is the least-privilege-per-command layer. It shares the host kernel
//! (no VM), so it is NOT host-escape resistance on its own — that is Layer 1
//! (Firecracker), added when an untrusted target repo enters scope. Host-level
//! egress by address (CIDR/domain) is Layer 3 (netns + proxy); Landlock only
//! scopes ports, which is called out below and in the README.

mod policy;

use std::os::unix::process::CommandExt;
use std::process::Command;

use anyhow::{anyhow, bail, Context, Result};
use landlock::{
    Access, AccessFs, AccessNet, NetPort, PathBeneath, PathFd, Ruleset, RulesetAttr,
    RulesetCreatedAttr, RulesetStatus, ABI,
};

use policy::Policy;

enum Mode {
    Run {
        policy_path: String,
        argv: Vec<String>,
    },
    Probe,
}

fn main() {
    // Exit codes, distinguished by error *origin* rather than message text:
    //   2 = config/usage error (bad args, unreadable/invalid policy);
    //   1 = runtime/confinement error (Landlock/seccomp/fd/exec).
    let mode = parse_args().unwrap_or_else(|e| {
        eprintln!("sandboy: {e:#}");
        std::process::exit(2);
    });
    match mode {
        Mode::Probe => {
            // `probe` is diagnostic-only: it reports what this host can
            // enforce and always exits 0 (finding "not enforced" is not a
            // probe *failure* — a caller decides pass/fail from the JSON).
            let report = probe_capabilities();
            println!("{}", report_to_json(&report));
        }
        Mode::Run { policy_path, argv } => {
            let policy = Policy::load(&policy_path)
                .with_context(|| format!("loading policy {policy_path}"))
                .unwrap_or_else(|e| {
                    eprintln!("sandboy: {e:#}");
                    std::process::exit(2);
                });
            if argv.is_empty() {
                eprintln!("sandboy: no command after `--`");
                std::process::exit(2);
            }
            if let Err(e) = confine_and_exec(&policy, &argv) {
                eprintln!("sandboy: {e:#}");
                std::process::exit(1);
            }
        }
    }
}

fn confine_and_exec(policy: &Policy, argv: &[String]) -> Result<()> {
    let (prog, prog_args) = argv
        .split_first()
        .expect("argv non-empty (checked in main)");

    // 1. no_new_privs — required to install a seccomp filter unprivileged.
    set_no_new_privs()?;

    // 2. Landlock: filesystem + TCP-port scope. Best-effort so an older kernel
    //    degrades (and reports) instead of hard-failing.
    let status = landlock_status(policy)?;
    report_landlock_status(status)?;

    // 3. seccomp denylist: strip dangerous syscalls, allow the rest.
    apply_seccomp(policy)?;

    // 4. Close inherited descriptors. Landlock/seccomp do NOT revoke
    //    already-open fds, so any descriptor the launcher leaked (an open file,
    //    a live socket) would pass straight into the untrusted command and
    //    bypass the FS/port allowlists. Mark every fd > 2 close-on-exec so it
    //    vanishes at execve; stdio (0,1,2) is kept.
    close_inherited_fds()?;

    // 5. Environment: clear everything, then pass through only the names the
    //    policy explicitly allowlists. Done last, right before exec, so
    //    nothing above (which never touches child env) can reintroduce a
    //    variable. Default (no env_allow) = the wrapped command inherits
    //    NOTHING — the launcher's environment is exactly where CI/agent
    //    credentials live.
    let mut cmd = Command::new(prog);
    cmd.args(prog_args);
    cmd.env_clear();
    for name in &policy.env_allow {
        if let Ok(val) = std::env::var(name) {
            cmd.env(name, val);
        }
    }

    // 6. Hand off. execve replaces us; the confinements persist into it.
    //    `exec()` only returns on failure.
    let err = cmd.exec();
    Err(err).with_context(|| format!("exec {prog}"))
}

fn parse_args() -> Result<Mode> {
    let mut it = std::env::args().skip(1);
    match it.next().as_deref() {
        Some("probe") => {
            if let Some(extra) = it.next() {
                bail!("unexpected arg {extra:?} (`probe` takes no arguments)");
            }
            return Ok(Mode::Probe);
        }
        Some("run") => {}
        _ => bail!(
            "usage: sandboy run --policy <file.toml> -- <cmd> [args...]\n   or: sandboy probe"
        ),
    }
    let mut policy_path = None;
    let mut argv = Vec::new();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--policy" => {
                policy_path = Some(it.next().ok_or_else(|| anyhow!("--policy needs a value"))?)
            }
            "--" => {
                argv.extend(it.by_ref());
                break;
            }
            other => bail!("unexpected arg {other:?} (did you forget `--` before the command?)"),
        }
    }
    Ok(Mode::Run {
        policy_path: policy_path.ok_or_else(|| anyhow!("--policy is required"))?,
        argv,
    })
}

/// Build the same ruleset `run` would (given `policy`) and restrict_self it,
/// returning the enforcement status without deciding pass/fail — `run` bails
/// on `NotEnforced`, `probe` just reports it. This is the single code path
/// both go through, so probe output can't drift from real enforcement.
fn landlock_status(policy: &Policy) -> Result<RulesetStatus> {
    // ABI::V4 adds TCP bind/connect scoping (kernel 6.7+). Best-effort compat
    // means: on an older kernel, unsupported bits are dropped, not fatal.
    let abi = ABI::V4;
    let mut ruleset = Ruleset::default()
        .handle_access(AccessFs::from_all(abi))?
        .handle_access(AccessNet::BindTcp | AccessNet::ConnectTcp)?
        .create()?;

    // Read+execute paths (binaries, libs, source to analyze).
    for p in &policy.fs_ro {
        ruleset = add_fs(ruleset, p, AccessFs::from_read(abi))
            .with_context(|| format!("fs_ro {}", p.display()))?;
    }
    // Read+write+execute paths (the worktree, tmp, output dirs).
    for p in &policy.fs_rw {
        ruleset = add_fs(ruleset, p, AccessFs::from_all(abi))
            .with_context(|| format!("fs_rw {}", p.display()))?;
    }
    // TCP port allowlists. Landlock scopes *ports*, not addresses — host-level
    // egress by CIDR/domain is Layer 3 (see README).
    for &port in &policy.tcp_connect {
        ruleset = ruleset.add_rule(NetPort::new(port, AccessNet::ConnectTcp))?;
    }
    for &port in &policy.tcp_bind {
        ruleset = ruleset.add_rule(NetPort::new(port, AccessNet::BindTcp))?;
    }

    Ok(ruleset
        .restrict_self()
        .context("landlock restrict_self")?
        .ruleset)
}

fn report_landlock_status(status: RulesetStatus) -> Result<()> {
    match status {
        RulesetStatus::FullyEnforced => Ok(()),
        RulesetStatus::PartiallyEnforced => {
            eprintln!("sandboy: warning: Landlock only PARTIALLY enforced (kernel too old for some access rights)");
            Ok(())
        }
        RulesetStatus::NotEnforced => {
            bail!("Landlock NOT enforced — kernel lacks Landlock (need >=5.13, >=6.7 for TCP). Refusing to run unconfined.");
        }
    }
}

/// A path that doesn't exist would make the whole ruleset fail; skip-with-warn
/// keeps a policy portable across hosts that lack e.g. /opt.
fn add_fs(
    ruleset: landlock::RulesetCreated,
    path: &std::path::Path,
    access: landlock::BitFlags<AccessFs>,
) -> Result<landlock::RulesetCreated> {
    match PathFd::new(path) {
        Ok(fd) => Ok(ruleset.add_rule(PathBeneath::new(fd, access))?),
        Err(e) => {
            eprintln!(
                "sandboy: warning: skipping missing path {}: {e}",
                path.display()
            );
            Ok(ruleset)
        }
    }
}

fn apply_seccomp(policy: &Policy) -> Result<()> {
    use seccompiler::{apply_filter, BpfProgram, SeccompAction, SeccompFilter};
    use std::collections::BTreeMap;

    // Denylist model: default = Allow (broad freedom), listed syscalls = EPERM.
    // An empty rule vec means "match unconditionally".
    let mut rules: BTreeMap<i64, Vec<seccompiler::SeccompRule>> = BTreeMap::new();
    for nr in policy.seccomp_deny_numbers()? {
        rules.insert(nr, vec![]);
    }

    let filter = SeccompFilter::new(
        rules,
        SeccompAction::Allow, // mismatch: everything not listed
        SeccompAction::Errno(libc::EPERM as u32), // match: the dangerous ones
        std::env::consts::ARCH
            .try_into()
            .map_err(|e| anyhow!("seccomp target arch: {e:?}"))?,
    )
    .context("building seccomp filter")?;

    let program: BpfProgram = filter.try_into().context("compiling seccomp bpf")?;
    apply_filter(&program).context("installing seccomp filter")?;
    Ok(())
}

/// Audited `unsafe` #1: a single prctl to set no_new_privs, without which an
/// unprivileged seccomp install is rejected. Sandboy is the syscall-boundary
/// crate, so — unlike the analyzer core (`unsafe_code = forbid`) — it permits
/// narrowly-scoped, audited unsafe at exactly these seams. Nothing user-derived
/// touches this call.
fn set_no_new_privs() -> Result<()> {
    // SAFETY: PR_SET_NO_NEW_PRIVS takes fixed constant args, has no memory
    // effects, and only ever tightens privileges. Return value checked below.
    let rc = unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) };
    if rc != 0 {
        bail!(
            "prctl(PR_SET_NO_NEW_PRIVS) failed: {}",
            std::io::Error::last_os_error()
        );
    }
    Ok(())
}

/// Audited `unsafe` #2: mark every descriptor above stdio close-on-exec, in one
/// `close_range` syscall (Linux 5.11+, below our Landlock floor of 5.13). This
/// closes the inherited-fd hole around Landlock (which scopes new opens by path,
/// not descriptors already handed to us).
fn close_inherited_fds() -> Result<()> {
    // SAFETY: close_range with CLOSE_RANGE_CLOEXEC only sets FD_CLOEXEC on the
    // [3, u32::MAX] descriptor range; fixed flag, no memory effects. rc checked.
    let rc = unsafe {
        libc::close_range(
            3,
            libc::c_uint::MAX,
            libc::CLOSE_RANGE_CLOEXEC as libc::c_int,
        )
    };
    if rc != 0 {
        bail!(
            "close_range(CLOEXEC) failed: {}",
            std::io::Error::last_os_error()
        );
    }
    Ok(())
}

/// One field of the `probe` report: what was checked, and how it turned out.
/// `ok` is `None` when the check itself couldn't be performed (not a failure
/// of the *mechanism*, e.g. `/proc` unreadable).
struct Field {
    name: &'static str,
    value: Json,
}

enum Json {
    Bool(bool),
    Int(i64),
    Str(String),
    Null,
}

/// Host capability report used by the Sandboy S0 feasibility gate
/// (`sandboy-host-capabilities.json`). This is the SAME enforcement code
/// `run` uses (`landlock_status`, `apply_seccomp`), applied to a synthetic
/// default policy, so the report can't drift from what a real `run` would
/// actually do on this host. `probe` restricts itself the same way `run`
/// does — safe here because probe only ever writes to already-open stdout
/// and then exits, neither of which any policy denies.
fn probe_capabilities() -> Vec<Field> {
    let mut f = Vec::new();
    f.push(Field {
        name: "sandboy_version",
        value: Json::Str(env!("CARGO_PKG_VERSION").to_string()),
    });
    f.push(Field {
        name: "arch",
        value: Json::Str(std::env::consts::ARCH.to_string()),
    });
    f.push(Field {
        name: "kernel_release",
        value: json_opt_str(kernel_release()),
    });
    f.push(Field {
        name: "euid",
        value: Json::Int(unsafe { libc::geteuid() } as i64),
    });
    f.push(Field {
        name: "egid",
        value: Json::Int(unsafe { libc::getegid() } as i64),
    });

    let (kernel_abi, kernel_abi_note) = raw_landlock_kernel_abi();
    f.push(Field {
        name: "landlock_kernel_abi_version",
        value: json_opt_int(kernel_abi),
    });
    f.push(Field {
        name: "landlock_kernel_abi_note",
        value: Json::Str(kernel_abi_note),
    });
    f.push(Field {
        name: "landlock_compiled_abi",
        value: Json::Str("V4".to_string()),
    });

    let no_new_privs_ok = set_no_new_privs().is_ok();
    f.push(Field {
        name: "no_new_privs_supported",
        value: Json::Bool(no_new_privs_ok),
    });

    // A wide-open default policy (no fs_ro/fs_rw/ports/env_allow, curated
    // seccomp DEFAULT_DENY): the same shape `run` would enforce for a step
    // that declares nothing. Reports what THIS host does with it, not what an
    // idealized one would.
    let probe_policy = Policy {
        fs_ro: Vec::new(),
        fs_rw: Vec::new(),
        tcp_connect: Vec::new(),
        tcp_bind: Vec::new(),
        seccomp_deny: None,
        env_allow: Vec::new(),
    };

    let landlock = landlock_status(&probe_policy);
    let (landlock_ok, landlock_str) = match &landlock {
        Ok(RulesetStatus::FullyEnforced) => (true, "fully_enforced".to_string()),
        Ok(RulesetStatus::PartiallyEnforced) => (false, "partially_enforced".to_string()),
        Ok(RulesetStatus::NotEnforced) => (false, "not_enforced".to_string()),
        Err(e) => (false, format!("error: {e:#}")),
    };
    f.push(Field {
        name: "landlock_ruleset_status",
        value: Json::Str(landlock_str),
    });
    f.push(Field {
        name: "landlock_fully_enforced",
        value: Json::Bool(landlock_ok),
    });

    let deny_numbers = probe_policy.seccomp_deny_numbers().unwrap_or_default();
    f.push(Field {
        name: "seccomp_default_deny_count",
        value: Json::Int(deny_numbers.len() as i64),
    });
    let seccomp_ok = apply_seccomp(&probe_policy).is_ok();
    f.push(Field {
        name: "seccomp_installed",
        value: Json::Bool(seccomp_ok),
    });

    let close_range_ok = close_inherited_fds().is_ok();
    f.push(Field {
        name: "close_range_supported",
        value: Json::Bool(close_range_ok),
    });

    f.push(Field {
        name: "dockerenv_present",
        value: Json::Bool(std::path::Path::new("/.dockerenv").exists()),
    });
    f.push(Field {
        name: "cgroup_summary",
        value: json_opt_str(cgroup_summary()),
    });

    f
}

fn json_opt_str(v: Option<String>) -> Json {
    match v {
        Some(s) => Json::Str(s),
        None => Json::Null,
    }
}

fn json_opt_int(v: Option<i64>) -> Json {
    match v {
        Some(n) => Json::Int(n),
        None => Json::Null,
    }
}

fn kernel_release() -> Option<String> {
    std::fs::read_to_string("/proc/sys/kernel/osrelease")
        .ok()
        .map(|s| s.trim().to_string())
}

/// First line of `/proc/self/cgroup`, a cheap container/VM signal (empty on a
/// bare VM, non-empty and container-shaped under most container runtimes).
/// Best-effort only — never a security decision, just probe context.
fn cgroup_summary() -> Option<String> {
    std::fs::read_to_string("/proc/self/cgroup")
        .ok()
        .and_then(|s| s.lines().next().map(str::to_string))
}

/// Audited `unsafe` #3: the raw `landlock_create_ruleset(NULL, 0,
/// LANDLOCK_CREATE_RULESET_VERSION)` probe syscall — the kernel-documented way
/// to ask "which Landlock ABI does this kernel implement", independent of
/// what the `landlock` crate itself understands. Read-only query, no ruleset
/// is created, no process state changes; this crate's public API deliberately
/// hides this (to stop callers building ABI-inconsistent rulesets — see
/// `landlock::compat`), but a diagnostic probe is exactly the sanctioned use.
fn raw_landlock_kernel_abi() -> (Option<i64>, String) {
    // SAFETY: null attr pointer + size 0 + the VERSION query flag is the
    // documented no-op probe form (Linux landlock(7)); it creates no ruleset
    // and touches no caller memory. Return value and errno both checked.
    let v = unsafe {
        libc::syscall(
            libc::SYS_landlock_create_ruleset,
            std::ptr::null::<u8>(),
            0usize,
            1u32,
        )
    };
    if v < 0 {
        let note = match std::io::Error::last_os_error().raw_os_error() {
            Some(libc::EOPNOTSUPP) => {
                "not_enabled (kernel built with Landlock but disabled, e.g. boot param)".to_string()
            }
            Some(libc::ENOSYS) => "not_implemented (kernel not built with Landlock)".to_string(),
            other => format!("errno {other:?}"),
        };
        (None, note)
    } else {
        (Some(v), "ok".to_string())
    }
}

fn report_to_json(fields: &[Field]) -> String {
    let mut out = String::from("{\n");
    for (i, f) in fields.iter().enumerate() {
        out.push_str("  \"");
        out.push_str(f.name);
        out.push_str("\": ");
        match &f.value {
            Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Json::Int(n) => out.push_str(&n.to_string()),
            Json::Null => out.push_str("null"),
            Json::Str(s) => {
                out.push('"');
                for c in s.chars() {
                    match c {
                        '"' => out.push_str("\\\""),
                        '\\' => out.push_str("\\\\"),
                        '\n' => out.push_str("\\n"),
                        c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
                        c => out.push(c),
                    }
                }
                out.push('"');
            }
        }
        if i + 1 < fields.len() {
            out.push(',');
        }
        out.push('\n');
    }
    out.push('}');
    out
}
