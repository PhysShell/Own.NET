#!/usr/bin/env python3
"""Syscall + process-inheritance probe: attempt one syscall from the seccomp
denylist, at a chosen depth in a fork tree, and report whether it was denied.

Usage: syscall_probe.py <syscall> <depth>
  syscall: ptrace | mount | setns
  depth:   self | child | grandchild | compiler_tree

`ptrace` is the load-bearing case for isolating seccomp's effect: an
unprivileged process may `PTRACE_TRACEME`-attach `ptrace()` on itself with NO
capability required (that's how strace/gdb work unprivileged), so a bare
unconfined run of this probe SUCCEEDS. If sandboy denies it, that denial is
attributable to seccomp specifically, not to an ambient kernel-privilege
check the probe would have hit anyway. `mount`/`setns` normally require
CAP_SYS_ADMIN, so an unprivileged unconfined run is ALSO denied by the kernel
— run_gate.py runs an unsandboxed baseline for every syscall and classifies
the result as "isolates seccomp" vs "privilege-equivalent, ambiguous" by
diffing against that baseline; this script only reports what happened here.

depth=compiler_tree simulates a compiler-driver-like tree: parent spawns a
harmless sibling first (stands in for e.g. cc1), then a second sibling that
performs the probe (stands in for e.g. collect2) — proving tree position and
process count don't matter to confinement.
"""
import ctypes
import os
import sys

libc = ctypes.CDLL(None, use_errno=True)

PTRACE_TRACEME = 0


def attempt(syscall):
    ctypes.set_errno(0)
    if syscall == "ptrace":
        rc = libc.ptrace(ctypes.c_long(PTRACE_TRACEME), 0, 0, 0)
    elif syscall == "mount":
        rc = libc.mount(b"none", b"/nonexistent-sandboy-probe-target", b"tmpfs", 0, None)
    elif syscall == "setns":
        # fd -1 is intentionally invalid: with an unconditional seccomp deny
        # rule, EPERM must arrive before the fd is ever validated, so an
        # invalid fd is fine — we want the denial, not a working setns.
        rc = libc.setns(-1, 0)
    else:
        print(f"RESULT=ERROR detail=unknown syscall {syscall!r}", flush=True)
        sys.exit(2)

    if rc == -1:
        e = ctypes.get_errno()
        print(f"RESULT=DENIED detail=errno={e} ({os.strerror(e)})", flush=True)
    else:
        print("RESULT=ALLOWED detail=syscall returned 0", flush=True)


def main():
    syscall, depth = sys.argv[1], sys.argv[2]

    if depth == "self":
        attempt(syscall)
    elif depth == "child":
        pid = os.fork()
        if pid == 0:
            attempt(syscall)
            os._exit(0)
        os.waitpid(pid, 0)
    elif depth == "grandchild":
        pid = os.fork()
        if pid == 0:
            gpid = os.fork()
            if gpid == 0:
                attempt(syscall)
                os._exit(0)
            os.waitpid(gpid, 0)
            os._exit(0)
        os.waitpid(pid, 0)
    elif depth == "compiler_tree":
        pid_a = os.fork()
        if pid_a == 0:
            os._exit(0)  # sibling A: harmless, stands in for e.g. cc1
        pid_b = os.fork()
        if pid_b == 0:
            attempt(syscall)  # sibling B: stands in for e.g. collect2
            os._exit(0)
        os.waitpid(pid_a, 0)
        os.waitpid(pid_b, 0)
    else:
        print(f"RESULT=ERROR detail=unknown depth {depth!r}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
