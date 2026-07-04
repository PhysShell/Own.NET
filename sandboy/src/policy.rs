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
}

impl Policy {
    pub fn load(path: &str) -> anyhow::Result<Self> {
        let text = std::fs::read_to_string(path)?;
        Ok(toml::from_str(&text)?)
    }

    /// Resolve the effective denylist to raw syscall numbers for this arch.
    /// Unknown names are skipped with a warning (a name may not exist on every
    /// arch), so a typo weakens the filter loudly rather than failing the run.
    pub fn seccomp_deny_numbers(&self) -> Vec<i64> {
        let names: Vec<&str> = match &self.seccomp_deny {
            Some(v) => v.iter().map(String::as_str).collect(),
            None => DEFAULT_DENY.to_vec(),
        };
        names
            .iter()
            .filter_map(|n| match syscall_number(n) {
                Some(nr) => Some(nr),
                None => {
                    eprintln!("sandboy: warning: unknown syscall in denylist: {n} (skipped)");
                    None
                }
            })
            .collect()
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
