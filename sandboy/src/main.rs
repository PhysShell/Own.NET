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

fn main() {
    // Exit codes, distinguished by error *origin* rather than message text:
    //   2 = config/usage error (bad args, unreadable/invalid policy);
    //   1 = runtime/confinement error (Landlock/seccomp/fd/exec).
    let (policy_path, argv) = parse_args().unwrap_or_else(|e| {
        eprintln!("sandboy: {e:#}");
        std::process::exit(2);
    });
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

fn confine_and_exec(policy: &Policy, argv: &[String]) -> Result<()> {
    let (prog, prog_args) = argv.split_first().expect("argv non-empty (checked in main)");

    // 1. no_new_privs — required to install a seccomp filter unprivileged.
    set_no_new_privs()?;

    // 2. Landlock: filesystem + TCP-port scope. Best-effort so an older kernel
    //    degrades (and reports) instead of hard-failing.
    apply_landlock(policy)?;

    // 3. seccomp denylist: strip dangerous syscalls, allow the rest.
    apply_seccomp(policy)?;

    // 4. Close inherited descriptors. Landlock/seccomp do NOT revoke
    //    already-open fds, so any descriptor the launcher leaked (an open file,
    //    a live socket) would pass straight into the untrusted command and
    //    bypass the FS/port allowlists. Mark every fd > 2 close-on-exec so it
    //    vanishes at execve; stdio (0,1,2) is kept.
    close_inherited_fds()?;

    // 5. Hand off. execve replaces us; the confinements persist into it.
    //    `exec()` only returns on failure.
    let err = Command::new(prog).args(prog_args).exec();
    Err(err).with_context(|| format!("exec {prog}"))
}

fn parse_args() -> Result<(String, Vec<String>)> {
    let mut it = std::env::args().skip(1);
    match it.next().as_deref() {
        Some("run") => {}
        _ => bail!("usage: sandboy run --policy <file.toml> -- <cmd> [args...]"),
    }
    let mut policy_path = None;
    let mut argv = Vec::new();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--policy" => policy_path = Some(it.next().ok_or_else(|| anyhow!("--policy needs a value"))?),
            "--" => {
                argv.extend(it.by_ref());
                break;
            }
            other => bail!("unexpected arg {other:?} (did you forget `--` before the command?)"),
        }
    }
    Ok((
        policy_path.ok_or_else(|| anyhow!("--policy is required"))?,
        argv,
    ))
}

fn apply_landlock(policy: &Policy) -> Result<()> {
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

    let status = ruleset.restrict_self().context("landlock restrict_self")?;
    match status.ruleset {
        RulesetStatus::FullyEnforced => {}
        RulesetStatus::PartiallyEnforced => {
            eprintln!("sandboy: warning: Landlock only PARTIALLY enforced (kernel too old for some access rights)");
        }
        RulesetStatus::NotEnforced => {
            bail!("Landlock NOT enforced — kernel lacks Landlock (need >=5.13, >=6.7 for TCP). Refusing to run unconfined.");
        }
    }
    Ok(())
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
            eprintln!("sandboy: warning: skipping missing path {}: {e}", path.display());
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
        SeccompAction::Allow,                     // mismatch: everything not listed
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
        bail!("prctl(PR_SET_NO_NEW_PRIVS) failed: {}", std::io::Error::last_os_error());
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
        libc::close_range(3, libc::c_uint::MAX, libc::CLOSE_RANGE_CLOEXEC as libc::c_int)
    };
    if rc != 0 {
        bail!("close_range(CLOEXEC) failed: {}", std::io::Error::last_os_error());
    }
    Ok(())
}
