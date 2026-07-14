//! Confinement policy for one wrapped command.
//!
//! Loaded from TOML. The filesystem/port allowlists are per-step (the worktree,
//! the toolchain dirs, port 443/22). The seccomp denylist has a curated default
//! and can be overridden by name.

use std::path::PathBuf;

use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct Policy {
    /// Read+execute paths — binaries, shared libs, source to read.
    #[serde(default)]
    pub fs_ro: Vec<PathBuf>,
    /// Read+write+execute paths — the worktree, tmp, output dirs.
    #[serde(default)]
    pub fs_rw: Vec<PathBuf>,
    /// Allowed TCP connect ports (e.g. 443 https, 22 ssh). Empty = no TCP out.
    #[serde(default)]
    pub tcp_connect: Vec<u16>,
    /// Allowed TCP bind ports. Empty = no listening sockets.
    #[serde(default)]
    pub tcp_bind: Vec<u16>,
    /// Override the default seccomp denylist by syscall name. When absent, the
    /// curated `DEFAULT_DENY` below is used.
    #[serde(default)]
    pub seccomp_deny: Option<Vec<String>>,
    /// Environment variable NAMES passed through from the launcher's own
    /// environment to the wrapped command. Every other variable is cleared
    /// before exec. Default (empty): the wrapped command gets no inherited
    /// environment at all — deny-all is the safe default for an untrusted
    /// command, since the launcher's environment is where CI credentials
    /// (`GITHUB_TOKEN`, cloud/package-registry secrets, `SSH_AUTH_SOCK`, …)
    /// live. Allowlist by name, not by stripping a denylist of known-bad ones.
    #[serde(default)]
    pub env_allow: Vec<String>,
}

impl Policy {
    pub fn load(path: &str) -> anyhow::Result<Self> {
        let text = std::fs::read_to_string(path)?;
        Ok(toml::from_str(&text)?)
    }

    /// Resolve the effective denylist to raw syscall numbers for this arch.
    ///
    /// An **explicit** `seccomp_deny` from the policy author is authoritative:
    /// an unresolved name (typo, or unsupported on this arch) is a **hard
    /// error** — silently dropping it would weaken the filter the author asked
    /// for, and a wrapped step's stderr is easy to lose in a gate/CI context.
    /// The curated `DEFAULT_DENY` keeps best-effort skip-with-warn, since
    /// cross-arch portability is its stated reason.
    pub fn seccomp_deny_numbers(&self) -> anyhow::Result<Vec<i64>> {
        match &self.seccomp_deny {
            Some(names) => names
                .iter()
                .map(|n| {
                    syscall_number(n)
                        .ok_or_else(|| anyhow::anyhow!("unknown syscall in seccomp_deny: {n}"))
                })
                .collect(),
            None => Ok(DEFAULT_DENY
                .iter()
                .filter_map(|n| match syscall_number(n) {
                    Some(nr) => Some(nr),
                    None => {
                        eprintln!("sandboy: warning: default-deny syscall unknown on this arch: {n} (skipped)");
                        None
                    }
                })
                .collect()),
        }
    }
}

/// Curated starting denylist: syscalls a normal build/analysis toolchain never
/// needs, but which are prime host-kernel attack surface. NOT exhaustive — a
/// deny of the obviously-dangerous, chosen to keep broad freedom for real tools.
/// (Argument-level filtering, e.g. clone/CLONE_NEWUSER, is a later refinement.)
const DEFAULT_DENY: &[&str] = &[
    "ptrace",
    "process_vm_readv",
    "process_vm_writev",
    "mount",
    "umount2",
    "pivot_root",
    "chroot",
    "kexec_load",
    "kexec_file_load",
    "bpf",
    "add_key",
    "keyctl",
    "request_key",
    "init_module",
    "finit_module",
    "delete_module",
    "perf_event_open",
    "ioperm",
    "iopl",
    "swapon",
    "swapoff",
    "reboot",
    "setns",
    "quotactl",
];

/// Name -> raw syscall number on the current arch, via libc's `SYS_*` constants.
/// Extend as the denylist grows.
fn syscall_number(name: &str) -> Option<i64> {
    let nr = match name {
        "ptrace" => libc::SYS_ptrace,
        "process_vm_readv" => libc::SYS_process_vm_readv,
        "process_vm_writev" => libc::SYS_process_vm_writev,
        "mount" => libc::SYS_mount,
        "umount2" => libc::SYS_umount2,
        "pivot_root" => libc::SYS_pivot_root,
        "chroot" => libc::SYS_chroot,
        "kexec_load" => libc::SYS_kexec_load,
        "kexec_file_load" => libc::SYS_kexec_file_load,
        "bpf" => libc::SYS_bpf,
        "add_key" => libc::SYS_add_key,
        "keyctl" => libc::SYS_keyctl,
        "request_key" => libc::SYS_request_key,
        "init_module" => libc::SYS_init_module,
        "finit_module" => libc::SYS_finit_module,
        "delete_module" => libc::SYS_delete_module,
        "perf_event_open" => libc::SYS_perf_event_open,
        "ioperm" => libc::SYS_ioperm,
        "iopl" => libc::SYS_iopl,
        "swapon" => libc::SYS_swapon,
        "swapoff" => libc::SYS_swapoff,
        "reboot" => libc::SYS_reboot,
        "setns" => libc::SYS_setns,
        "quotactl" => libc::SYS_quotactl,
        _ => return None,
    };
    Some(nr as i64)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `env_allow` deny-all-by-default: an older policy file written before
    /// this field existed must still parse, with `env_allow` defaulting to
    /// empty — i.e. the wrapped command gets NO inherited environment, not
    /// "whatever it used to get" (there was no env handling before, so this
    /// is the conservative direction: adding the field can only narrow what
    /// a pre-existing policy grants, never widen it).
    #[test]
    fn env_allow_defaults_to_empty_when_absent() {
        let toml = r#"
            fs_ro = ["/usr"]
            fs_rw = ["/tmp"]
        "#;
        let policy: Policy = toml::from_str(toml).unwrap();
        assert!(policy.env_allow.is_empty());
    }

    #[test]
    fn env_allow_parses_explicit_names() {
        let toml = r#"
            fs_ro = ["/usr"]
            fs_rw = ["/tmp"]
            env_allow = ["PATH", "HOME"]
        "#;
        let policy: Policy = toml::from_str(toml).unwrap();
        assert_eq!(
            policy.env_allow,
            vec!["PATH".to_string(), "HOME".to_string()]
        );
    }

    #[test]
    fn seccomp_deny_default_is_nonempty_and_includes_ptrace() {
        let toml = r#"
            fs_ro = ["/usr"]
            fs_rw = ["/tmp"]
        "#;
        let policy: Policy = toml::from_str(toml).unwrap();
        let numbers = policy.seccomp_deny_numbers().unwrap();
        assert!(!numbers.is_empty());
        assert!(numbers.contains(&{ libc::SYS_ptrace }));
    }

    #[test]
    fn seccomp_deny_explicit_unknown_name_is_a_hard_error() {
        let toml = r#"
            fs_ro = ["/usr"]
            fs_rw = ["/tmp"]
            seccomp_deny = ["not_a_real_syscall_name"]
        "#;
        let policy: Policy = toml::from_str(toml).unwrap();
        assert!(policy.seccomp_deny_numbers().is_err());
    }
}
