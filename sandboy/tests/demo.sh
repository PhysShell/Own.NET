#!/usr/bin/env bash
# Demonstrate the confinement: what a wrapped step CAN and CANNOT do.
# Run after `cargo build --release`. Needs a Linux kernel >= 5.13 (FS),
# ideally >= 6.7 (for the TCP-port scoping to be enforced too).
#
#   ./tests/demo.sh
#
# It builds a throwaway policy that allows RW only under $WORK and TCP only to
# 443, then shows four probes: two that should succeed, two that should be
# denied by Landlock/seccomp.

set -u
BIN=./target/release/sandboy
WORK=$(mktemp -d)
POL=$(mktemp)
trap 'rm -rf "$WORK" "$POL"' EXIT

cat >"$POL" <<EOF
fs_ro       = ["/usr", "/bin", "/lib", "/lib64", "/etc"]
fs_rw       = ["$WORK", "/tmp"]
tcp_connect = [443]
tcp_bind    = []
EOF

echo "policy: RW only under $WORK ; TCP only to :443"
echo

run() { echo "### $1"; shift; "$BIN" run --policy "$POL" -- "$@"; echo "  exit=$?"; echo; }

# (1) ALLOWED: write inside the worktree.
run "write inside worktree (expect OK)" \
    bash -lc "echo hello > '$WORK/ok.txt' && cat '$WORK/ok.txt'"

# (2) DENIED: write outside the allowlist (Landlock -> EACCES).
run "write to \$HOME outside allowlist (expect Permission denied)" \
    bash -lc "echo pwned > \$HOME/sandboy-should-not-exist.txt"

# (3) DENIED: ptrace another process (seccomp -> EPERM).
run "ptrace via strace (expect seccomp EPERM / Operation not permitted)" \
    bash -lc "strace -f true 2>&1 | head -1"

# (4) DENIED: TCP connect to a non-allowlisted port (Landlock -> EACCES),
#     shown against :80 which the policy does not allow.
run "curl http://example.com :80 (expect denied; :443 would be allowed)" \
    bash -lc "curl -sS --max-time 5 http://example.com >/dev/null; echo connected"

echo "Done. Probes 2-4 should have failed; 1 should have succeeded."
echo "If probe 2 SUCCEEDED, Landlock is not enforcing — check the kernel"
echo "(uname -r >= 5.13) and that sandboy printed no 'NOT enforced' warning."
