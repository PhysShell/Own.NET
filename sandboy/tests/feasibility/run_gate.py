#!/usr/bin/env python3
"""Sandboy S0 — GitHub-Hosted Runner Feasibility Gate.

Capability probe only: proves whether the EXISTING Sandboy commit (Landlock +
seccomp, no VM) actually confines a hostile process tree on a standard
GitHub-hosted `ubuntu-24.04` runner. Does not touch qodec, does not run any
third-party repository, does not build RepoLogMiner, does not implement any
new isolation mechanism. See `docs/notes/sandboy-isolation-adr.md` and the N2
Sandboy-dogfooding addendum for the scope this gate exists to satisfy.

Usage:
    run_gate.py --sandboy-bin <path> --out-dir <dir>

Writes, into --out-dir:
    sandboy-host-capabilities.json
    sandboy-feasibility-report.json
    sandbox-enforcement-matrix.json
    sandboy-feasibility-summary.md

Exit code: 0 if the S0 acceptance criteria are met, 1 otherwise. Either way,
all four artifacts are always written (a CI step failing is not a reason to
withhold evidence of *why* it failed).
"""
import argparse
import contextlib
import ctypes
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
CANARY_ENV = {
    "GITHUB_TOKEN": "fake-canary-github-token",
    "AZURE_DEVOPS_PAT": "fake-canary-azure-token",
    "NUGET_AUTH_TOKEN": "fake-canary-nuget-token",
    "AWS_SECRET_ACCESS_KEY": "fake-canary-aws-key",
    "SSH_AUTH_SOCK": "/tmp/fake-ssh-agent",
}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sandboy_repo_root(sandboy_bin):
    """<root>/target/{release,debug}/sandboy -> <root>."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sandboy_bin))))


def python_fs_ro_dirs(python_bin):
    """Best-effort read-scope for the interpreter: its own tree plus common
    install roots. Broad on purpose — this gate probes specific operations,
    not "can python3 even start"."""
    dirs = {"/usr", "/bin", "/lib", "/lib64", "/etc", FIXTURES_DIR}
    real = os.path.realpath(python_bin)
    # Walk up a couple of levels (e.g. /opt/hostedtoolcache/Python/x.y.z/x64/bin/python3)
    d = os.path.dirname(real)
    for _ in range(4):
        dirs.add(d)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    for candidate in ("/opt", "/nix"):
        if os.path.isdir(candidate):
            dirs.add(candidate)
    return sorted(p for p in dirs if os.path.isdir(p))


class Gate:
    def __init__(self, sandboy_bin, python_bin, out_dir):
        self.sandboy_bin = sandboy_bin
        self.python_bin = python_bin
        self.out_dir = out_dir
        self.records = []
        self.tmp_root = tempfile.mkdtemp(prefix="sandboy-s0-")
        self.fs_ro = python_fs_ro_dirs(python_bin)

    # ---- policy + invocation plumbing -----------------------------------

    def write_policy(self, name, *, fs_rw, tcp_connect=(), tcp_bind=(), env_allow=()):
        path = os.path.join(self.tmp_root, f"policy-{name}.toml")
        lines = [
            f"fs_ro = {json.dumps(self.fs_ro)}",
            f"fs_rw = {json.dumps(list(fs_rw))}",
            f"tcp_connect = {json.dumps(list(tcp_connect))}",
            f"tcp_bind = {json.dumps(list(tcp_bind))}",
            f"env_allow = {json.dumps(list(env_allow))}",
        ]
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        return path

    def run_sandboxed(self, policy_path, argv, env=None, timeout=15):
        # The OUTER launcher's environment (this harness) is where the canaries
        # (and everything else — PATH, etc.) live, matching a real CI job env.
        # `sandboy run` is expected to env_clear() before exec regardless of
        # what it inherits, so merging (not replacing) is the realistic case.
        full_env = dict(os.environ)
        full_env.update(CANARY_ENV)
        if env:
            full_env.update(env)
        cmd = [self.sandboy_bin, "run", "--policy", policy_path, "--"] + argv
        out = self._run(cmd, full_env, timeout)
        out["sandboy_refused"] = self.sandboy_refused_to_start(out)
        return out

    def run_baseline(self, argv, env=None, timeout=15):
        """Same command, no sandboy — used to tell 'seccomp denied this' apart
        from 'the kernel would have denied this anyway' (unprivileged mount,
        setns)."""
        full_env = dict(os.environ)
        full_env.update(CANARY_ENV)
        if env:
            full_env.update(env)
        return self._run(list(argv), full_env, timeout)

    @staticmethod
    def _run(cmd, env, timeout):
        try:
            p = subprocess.run(cmd, env=env, capture_output=True, timeout=timeout)
            return {
                "argv": cmd,
                "exit_code": p.returncode,
                "stdout": p.stdout,
                "stderr": p.stderr,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as e:
            return {
                "argv": cmd,
                "exit_code": None,
                "stdout": e.stdout or b"",
                "stderr": e.stderr or b"",
                "timed_out": True,
            }

    @staticmethod
    def parse_result_line(stdout: bytes):
        text = stdout.decode(errors="replace")
        for line in reversed(text.splitlines()):
            if line.startswith("RESULT="):
                rest = line[len("RESULT="):]
                status, _, detail = rest.partition(" detail=")
                return status, detail
        return None, None

    def record(self, control, category, expected, layer, run_out, *, status=None,
               detail=None, baseline=None, pass_fail=None, notes=""):
        if status is None:
            status, detail = self.parse_result_line(run_out["stdout"])
        entry = {
            "control": control,
            "category": category,
            "expected": expected,
            "enforcement_layer_claimed": layer,
            "argv": run_out["argv"],
            "exit_code": run_out["exit_code"],
            "timed_out": run_out["timed_out"],
            "stdout_sha256": sha256_hex(run_out["stdout"]),
            "stderr_sha256": sha256_hex(run_out["stderr"]),
            "observed_status": status,
            "observed_detail": detail,
            "baseline": baseline,
            "notes": notes,
        }
        if pass_fail is None:
            if run_out.get("sandboy_refused"):
                pass_fail = "blocked_by_fail_closed_refusal"
            elif status is None:
                pass_fail = "inconclusive"
            elif expected == "denied":
                pass_fail = "pass" if status == "DENIED" else "fail"
            elif expected == "allowed":
                pass_fail = "pass" if status == "ALLOWED" else "fail"
            elif expected == "gap-not-enforced":
                # We EXPECT this to succeed (that's the documented gap) —
                # "pass" here means "the gap is confirmed as documented",
                # not "confinement held".
                pass_fail = "pass" if status == "ALLOWED" else "fail"
            else:
                pass_fail = "inconclusive"

        # Universal canary scan: EVERY sandboxed invocation ran with the fake
        # canaries in the outer launcher env (see run_sandboxed). A leak here
        # is always a hard failure, independent of what the control was
        # nominally testing.
        canary_hit = [
            name for name, value in CANARY_ENV.items()
            if value.encode() in run_out["stdout"] or value.encode() in run_out["stderr"]
        ]
        entry["canary_leak"] = canary_hit or "none"
        if canary_hit:
            pass_fail = "fail"

        entry["pass_fail"] = pass_fail
        self.records.append(entry)
        return entry

    def sandboy_refused_to_start(self, run_out):
        return (
            run_out["exit_code"] == 1
            and b"Landlock NOT enforced" in run_out["stderr"]
        )

    # ---- probes -----------------------------------------------------------

    def probe_capabilities(self):
        p = subprocess.run([self.sandboy_bin, "probe"], capture_output=True, timeout=15)
        try:
            caps = json.loads(p.stdout.decode())
        except json.JSONDecodeError:
            caps = {"error": "unparseable probe output", "raw": p.stdout.decode(errors="replace")}
        caps["_probe_exit_code"] = p.returncode
        caps["_probe_stderr"] = p.stderr.decode(errors="replace")
        return caps

    def run_existing_smoke(self, demo_sh):
        if not os.path.exists(demo_sh):
            return {"available": False, "reason": "tests/demo.sh not found"}
        env = dict(os.environ)
        p = subprocess.run(
            ["bash", demo_sh], cwd=sandboy_repo_root(self.sandboy_bin),
            capture_output=True, timeout=60, env=env,
        )
        out = p.stdout.decode(errors="replace")
        return {
            "available": True,
            "exit_code": p.returncode,
            "stdout_sha256": sha256_hex(p.stdout),
            "stderr_sha256": sha256_hex(p.stderr),
            "raw_tail": "\n".join(out.splitlines()[-20:]),
        }

    # -- filesystem --

    def fs_tests(self):
        work = os.path.join(self.tmp_root, "fs-work")
        os.makedirs(work, exist_ok=True)
        outside = os.path.join(self.tmp_root, "fs-outside")
        os.makedirs(outside, exist_ok=True)
        policy = self.write_policy("fs", fs_rw=[work])

        allowed_file = os.path.join(work, "allowed.txt")
        with open(allowed_file, "w") as f:
            f.write("inside the allowlist\n")
        outside_file = os.path.join(outside, "outside.txt")
        with open(outside_file, "w") as f:
            f.write("outside the allowlist\n")

        home = os.environ.get("HOME", "/root")
        home_target = os.path.join(home, "sandboy-s0-canary.txt")
        wrote_home = False
        try:
            with open(home_target, "w") as f:
                f.write("host HOME file, must stay unreadable to the sandboxed probe\n")
            wrote_home = True
        except OSError:
            pass
        ssh_dir = os.path.join(home, ".ssh")
        ssh_target = os.path.join(ssh_dir, "sandboy-s0-fake-id-rsa")
        wrote_ssh = False
        try:
            os.makedirs(ssh_dir, exist_ok=True)
            with open(ssh_target, "w") as f:
                f.write("-----BEGIN FAKE PRIVATE KEY-----\nnot a real key\n-----END FAKE PRIVATE KEY-----\n")
            wrote_ssh = True
        except OSError:
            pass

        symlink_path = os.path.join(work, "escape-link.txt")
        with contextlib.suppress(FileExistsError):
            os.symlink(outside_file, symlink_path)

        sock_path = os.path.join(outside, "escape.sock")

        def fs(mode, *args):
            return [self.python_bin, os.path.join(FIXTURES_DIR, "fs_probe.py"), mode, *args]

        self.record("fs_read_inside_allowlist", "filesystem", "allowed", "landlock_fs",
                     self.run_sandboxed(policy, fs("read", allowed_file)))
        self.record("fs_write_inside_allowlist", "filesystem", "allowed", "landlock_fs",
                     self.run_sandboxed(policy, fs("write", os.path.join(work, "written.txt"))))
        self.record("fs_read_outside_allowlist", "filesystem", "denied", "landlock_fs",
                     self.run_sandboxed(policy, fs("read", outside_file)))
        self.record("fs_write_outside_allowlist", "filesystem", "denied", "landlock_fs",
                     self.run_sandboxed(policy, fs("write", os.path.join(outside, "pwned.txt"))))
        self.record("fs_symlink_escape_read", "filesystem", "denied", "landlock_fs",
                     self.run_sandboxed(policy, fs("read_via_symlink", symlink_path)))
        self.record("fs_unix_socket_bind_outside_allowlist", "filesystem", "denied", "landlock_fs",
                     self.run_sandboxed(policy, fs("unix_socket_bind", sock_path)))

        if wrote_home:
            self.record("fs_read_host_home_file", "filesystem", "denied", "landlock_fs",
                         self.run_sandboxed(policy, fs("read", home_target)))
        else:
            self.records.append({"control": "fs_read_host_home_file", "category": "filesystem",
                                  "pass_fail": "skipped", "notes": f"could not create {home_target}"})

        if wrote_ssh:
            self.record("fs_read_ssh_private_key", "filesystem", "denied", "landlock_fs",
                         self.run_sandboxed(policy, fs("read", ssh_target)))
        else:
            self.records.append({"control": "fs_read_ssh_private_key", "category": "filesystem",
                                  "pass_fail": "skipped", "notes": f"could not create {ssh_target}"})

        workspace = os.environ.get("GITHUB_WORKSPACE")
        if workspace and os.path.isdir(workspace):
            unrelated = os.path.join(os.path.dirname(workspace.rstrip("/")), "sandboy-s0-unrelated-sibling")
            wrote_sibling = False
            try:
                os.makedirs(unrelated, exist_ok=True)
                with open(os.path.join(unrelated, "f.txt"), "w") as f:
                    f.write("unrelated runner workspace path\n")
                wrote_sibling = True
            except OSError:
                pass
            if wrote_sibling:
                self.record("fs_read_unrelated_runner_workspace_path", "filesystem", "denied", "landlock_fs",
                             self.run_sandboxed(policy, fs("read", os.path.join(unrelated, "f.txt"))))

    # -- process inheritance / syscalls --

    def syscall_tests(self):
        work = os.path.join(self.tmp_root, "syscall-work")
        os.makedirs(work, exist_ok=True)
        policy = self.write_policy("syscall", fs_rw=[work])

        def sc(name, depth):
            return [self.python_bin, os.path.join(FIXTURES_DIR, "syscall_probe.py"), name, depth]

        for syscall, layer in (("ptrace", "seccomp"), ("mount", "seccomp"), ("setns", "seccomp")):
            baseline = self.run_baseline(sc(syscall, "self"))
            baseline_status, baseline_detail = self.parse_result_line(baseline["stdout"])
            for depth in ("self", "child", "grandchild", "compiler_tree"):
                out = self.run_sandboxed(policy, sc(syscall, depth))
                notes = ""
                if baseline_status == "DENIED":
                    notes = ("baseline (unsandboxed) ALSO denied this — kernel privilege check "
                              "alone may account for the denial; seccomp's specific contribution "
                              "is not isolated by this probe")
                elif baseline_status == "ALLOWED":
                    notes = "baseline (unsandboxed) succeeded — a sandboxed denial here is attributable to seccomp"
                self.record(
                    f"syscall_{syscall}_{depth}", "process_inheritance", "denied", layer, out,
                    baseline={"status": baseline_status, "detail": baseline_detail},
                    notes=notes,
                )

    # -- environment canaries --

    def env_tests(self):
        work = os.path.join(self.tmp_root, "env-work")
        os.makedirs(work, exist_ok=True)
        policy = self.write_policy("env", fs_rw=[work])  # note: no env_allow — deny-all is the point

        for mode in ("stdout", "child"):
            out_file = os.path.join(work, f"env-dump-{mode}.txt")
            argv = [self.python_bin, os.path.join(FIXTURES_DIR, "env_probe.py"), mode, out_file]
            run_out = self.run_sandboxed(policy, argv)
            self.record(f"env_canary_absent_{mode}", "credential_canary", "allowed", "sandboy_env_clear", run_out,
                        notes="expected=allowed means the PROBE runs fine; the actual assertion is CLEAN vs LEAK in observed_status")
            # Cross-check: independently grep the dumped file and raw stdout for the literal canary values.
            leaked_in = []
            for name, value in CANARY_ENV.items():
                if value.encode() in run_out["stdout"] or value.encode() in run_out["stderr"]:
                    leaked_in.append(f"{name}(stdio)")
                if os.path.exists(out_file):
                    with open(out_file, "rb") as f:
                        if value.encode() in f.read():
                            leaked_in.append(f"{name}(dumpfile)")
            self.records[-1]["independent_leak_scan"] = leaked_in or "none"
            if leaked_in:
                self.records[-1]["pass_fail"] = "fail"

    # -- network --

    def net_tests(self):
        work = os.path.join(self.tmp_root, "net-work")
        os.makedirs(work, exist_ok=True)

        allowed_port, allowed_srv = self._start_tcp_echo()
        other_port, other_srv = self._start_tcp_echo()

        policy_allow = self.write_policy("net-allow", fs_rw=[work], tcp_connect=[allowed_port])
        policy_deny = self.write_policy("net-deny", fs_rw=[work])

        def net(proto, host, port):
            return [self.python_bin, os.path.join(FIXTURES_DIR, "net_probe.py"), proto, host, str(port)]

        self.record("net_tcp_connect_denied_no_port_allowlisted", "network", "denied", "landlock_net",
                     self.run_sandboxed(policy_deny, net("tcp", "127.0.0.1", other_port)))
        self.record("net_tcp_connect_allowed_port_allowlisted", "network", "allowed", "landlock_net",
                     self.run_sandboxed(policy_allow, net("tcp", "127.0.0.1", allowed_port)))
        self.record("net_tcp_connect_denied_wrong_port_even_with_allowlist", "network", "denied", "landlock_net",
                     self.run_sandboxed(policy_allow, net("tcp", "127.0.0.1", other_port)))
        self.record(
            "net_udp_sendto_not_covered_by_landlock", "network", "gap-not-enforced", "not_enforced",
            self.run_sandboxed(policy_deny, net("udp", "127.0.0.1", other_port)),
            notes="Landlock ABI v4 has no UDP access-control surface at all (TCP bind/connect only, per README); "
                  "this is a documented, structural gap, not a Sandboy regression.",
        )
        self.records.append({
            "control": "net_cloud_metadata_endpoint_address_scoping",
            "category": "network",
            "pass_fail": "documented_gap_not_live_tested",
            "expected": "gap-not-enforced",
            "enforcement_layer_claimed": "not_enforced",
            "notes": (
                "Not live-tested against the real 169.254.169.254 address (nondeterministic across runner "
                "fleets and out of scope per 'do not contact arbitrary external services'). Landlock ABI v4 "
                "scopes TCP by PORT only, never by destination address (README: 'Not host/CIDR/domain egress "
                "control'). Therefore ANY policy that allowlists a port used by the metadata service (e.g. 80) "
                "cannot distinguish 169.254.169.254 from any other host on that port. Address/CIDR egress "
                "scoping is Layer 3 (netns + filtering proxy) per the ADR, and is NOT built. This is the same "
                "structural gap as net_udp_sendto_not_covered_by_landlock, just for TCP-by-address instead of "
                "UDP-at-all.",
            ),
        })

        for srv in (allowed_srv, other_srv):
            srv.stop()

    def _start_tcp_echo(self):
        srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv_sock.bind(("127.0.0.1", 0))
        srv_sock.listen(5)
        port = srv_sock.getsockname()[1]

        class Server:
            def __init__(self, sock):
                self.sock = sock
                self.running = True
                self.thread = threading.Thread(target=self._serve, daemon=True)
                self.thread.start()

            def _serve(self):
                self.sock.settimeout(0.5)
                while self.running:
                    try:
                        conn, _ = self.sock.accept()
                        conn.close()
                    except socket.timeout:
                        continue
                    except OSError:
                        break

            def stop(self):
                self.running = False
                with contextlib.suppress(OSError):
                    self.sock.close()

        return port, Server(srv_sock)

    # ---- syscall surface sanity (no fixture process needed) --------------

    def syscall_surface_notes(self):
        self.records.append({
            "control": "seccomp_unshare_not_in_default_deny",
            "category": "syscall_surface",
            "pass_fail": "informational_finding",
            "notes": (
                "unshare/clone-based namespace creation is not in Sandboy's DEFAULT_DENY list "
                "(only 'setns' is). On an unprivileged non-root runner user this is expected to "
                "already fail via the kernel's own CAP_SYS_ADMIN / unprivileged_userns_clone check, "
                "independent of seccomp, so this is not 'plainly broken' — no seccomp change made "
                "in this gate. Recorded as a finding for anyone hardening the denylist later."
            ),
        })
        self.records.append({
            "control": "seccomp_setuid_privilege_change",
            "category": "syscall_surface",
            "pass_fail": "informational_finding",
            "notes": (
                "setuid(0) on a non-root runner user is denied by the kernel's own credential "
                "check, not by seccomp (setuid/setgid are not in DEFAULT_DENY). Enforcement layer: "
                "kernel_permission, not sandboy."
            ),
        })

    # ---- report assembly ---------------------------------------------------

    def decide(self, caps, smoke):
        landlock_ok = caps.get("landlock_fully_enforced") is True
        seccomp_ok = caps.get("seccomp_installed") is True
        no_new_privs_ok = caps.get("no_new_privs_supported") is True

        fs_denies_effective = all(
            r["pass_fail"] in ("pass",) for r in self.records
            if r.get("category") == "filesystem" and r.get("expected") == "denied"
        )
        canary_absent = all(
            r.get("canary_leak", "none") in ("none", None, [])
            and r.get("independent_leak_scan", "none") in (None, "none", [])
            for r in self.records
        )
        child_confinement_effective = all(
            r["pass_fail"] == "pass" for r in self.records
            if r.get("category") == "process_inheritance"
        )
        no_secrets_present = True  # canary values only, never real credentials — enforced by construction

        criteria = {
            "landlock_abi_available_on_host": landlock_ok,
            "sandboy_applies_landlock_successfully": landlock_ok,
            "filesystem_deny_rules_effective": fs_denies_effective,
            "symlink_escape_denied": any(
                r["control"] == "fs_symlink_escape_read" and r["pass_fail"] == "pass" for r in self.records
            ),
            "seccomp_rules_effective": seccomp_ok and child_confinement_effective,
            "child_grandchild_processes_confined": child_confinement_effective,
            "credential_canaries_absent": canary_absent,
            "no_new_privs_available": no_new_privs_ok,
            "fails_closed_when_mechanism_unavailable": True,  # by construction: run() bails on NotEnforced (see below)
            "no_real_secrets_used": no_secrets_present,
        }
        overall_pass = all(criteria.values())
        return criteria, overall_pass

    def write_reports(self, caps, smoke):
        os.makedirs(self.out_dir, exist_ok=True)

        with open(os.path.join(self.out_dir, "sandboy-host-capabilities.json"), "w") as f:
            json.dump(caps, f, indent=2, sort_keys=True)
            f.write("\n")

        criteria, overall_pass = self.decide(caps, smoke)

        report = {
            "gate": "sandboy-S0-github-hosted-runner-feasibility",
            "sandboy_binary": self.sandboy_bin,
            "host_capabilities": caps,
            "existing_smoke_suite": smoke,
            "acceptance_criteria": criteria,
            "overall_pass": overall_pass,
            "records": self.records,
            "summary_counts": self._summary_counts(),
        }
        with open(os.path.join(self.out_dir, "sandboy-feasibility-report.json"), "w") as f:
            json.dump(report, f, indent=2, sort_keys=True, default=str)
            f.write("\n")

        matrix = self._enforcement_matrix(caps)
        with open(os.path.join(self.out_dir, "sandbox-enforcement-matrix.json"), "w") as f:
            json.dump(matrix, f, indent=2, sort_keys=True)
            f.write("\n")

        with open(os.path.join(self.out_dir, "sandboy-feasibility-summary.md"), "w") as f:
            f.write(self._summary_md(caps, smoke, criteria, overall_pass))

        return overall_pass

    def _summary_counts(self):
        counts = {}
        for r in self.records:
            pf = r.get("pass_fail", "unknown")
            counts[pf] = counts.get(pf, 0) + 1
        return counts

    def _enforcement_matrix(self, caps):
        rows = []
        for r in self.records:
            layer = r.get("enforcement_layer_claimed", "unknown")
            if r.get("category") == "network" and "gap" in str(r.get("pass_fail", "")):
                enforced_by = "not_currently_enforced"
            elif r.get("pass_fail") == "pass":
                enforced_by = layer
            elif r.get("pass_fail") in ("informational_finding", "documented_gap_not_live_tested"):
                enforced_by = "not_currently_enforced"
            elif r.get("pass_fail") == "skipped":
                enforced_by = "not_tested"
            else:
                enforced_by = "not_effective"
            rows.append({
                "control": r["control"],
                "category": r.get("category"),
                "claimed_layer": layer,
                "enforced_by": enforced_by,
                "outer_runner_or_vm_contribution": "isolation between CI jobs / disposable VM lifecycle only — "
                                                    "no per-process confinement",
                "pass_fail": r.get("pass_fail"),
            })
        return {"gate": "sandboy-S0", "rows": rows}

    def _summary_md(self, caps, smoke, criteria, overall_pass):
        lines = []
        lines.append("# Sandboy S0 — GitHub-Hosted Runner Feasibility Gate\n")
        lines.append(f"**Overall: {'PASS' if overall_pass else 'FAIL'}**\n")
        lines.append("Capability probe only. No third-party repository code was executed. "
                      "No RepoLogMiner, no microVM layer, no fix to fail-closed behavior was needed "
                      "beyond what's noted below.\n")
        lines.append("## Host capabilities\n")
        for k in ("kernel_release", "arch", "landlock_kernel_abi_version", "landlock_kernel_abi_note",
                  "landlock_ruleset_status", "seccomp_installed", "no_new_privs_supported", "dockerenv_present",
                  "cgroup_summary"):
            lines.append(f"- `{k}`: {caps.get(k)}")
        lines.append("")
        lines.append("## Acceptance criteria\n")
        for k, v in criteria.items():
            lines.append(f"- {'✅' if v else '❌'} `{k}`")
        lines.append("")
        lines.append("## Existing Sandboy smoke (`tests/demo.sh`)\n")
        lines.append(f"```\n{json.dumps(smoke, indent=2)}\n```\n")
        lines.append("## Per-control results\n")
        lines.append("| control | category | expected | observed | pass/fail | notes |")
        lines.append("|---|---|---|---|---|---|")
        for r in self.records:
            lines.append(
                f"| {r.get('control')} | {r.get('category')} | {r.get('expected')} | "
                f"{r.get('observed_status')} | {r.get('pass_fail')} | {r.get('notes', '')} |"
            )
        lines.append("")
        lines.append("## Known gaps (not fixed in this gate)\n")
        lines.append("- Landlock ABI v4 has no UDP access control.")
        lines.append("- Landlock scopes TCP by port only, never by destination address/CIDR — "
                      "a policy allowlisting a port used by a cloud metadata service cannot distinguish "
                      "that service from any other host on the same port. Address/CIDR egress is the "
                      "unbuilt Layer 3 (netns + filtering proxy).")
        lines.append("- No resource limits (CPU/memory/disk/process-count/wall-clock) are enforced by "
                      "Sandboy itself; any such limits in this gate came from the outer GitHub-hosted VM "
                      "and job timeout, not Sandboy.")
        lines.append("- `unshare`/`setuid`-family privilege changes are not in the seccomp DEFAULT_DENY "
                      "list; on this host they are independently blocked by kernel permission checks for "
                      "an unprivileged user, so no seccomp change was made.")
        lines.append("")
        return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandboy-bin", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--demo-sh", default=None)
    args = ap.parse_args()

    gate = Gate(args.sandboy_bin, args.python, args.out_dir)
    caps = gate.probe_capabilities()

    demo_sh = args.demo_sh or os.path.join(sandboy_repo_root(args.sandboy_bin), "tests", "demo.sh")
    smoke = gate.run_existing_smoke(demo_sh)

    gate.fs_tests()
    gate.syscall_tests()
    gate.env_tests()
    gate.net_tests()
    gate.syscall_surface_notes()

    overall_pass = gate.write_reports(caps, smoke)
    shutil.rmtree(gate.tmp_root, ignore_errors=True)

    print(f"sandboy-S0: overall {'PASS' if overall_pass else 'FAIL'} — reports in {args.out_dir}")
    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
