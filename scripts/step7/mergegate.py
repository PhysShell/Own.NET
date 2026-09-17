#!/usr/bin/env python3
"""P-022 — the merge gate: does the world a freeze enters satisfy its references?

The frozen T0 names things that live outside itself: an accepted harness
identity, the step-7 machinery that enforces the campaign join, the T0-0
amendment that revoked automatic collection authority. On the branch where T0
was frozen, some of those referents arrive through *other* pull requests. That
is fine while the merge order holds — and merge order held by agreement is one
stray click away from becoming an archaeological artifact, with a document
saying FROZEN in a tree where its referent does not exist yet.

So the order is checked rather than promised, and it is checked against the
**target tree**, never against pull-request numbers. A PR number proves that
someone pressed a button; it proves nothing about what the merged tree contains.

Run it on the commit a merge would produce:

    python scripts/step7/mergegate.py --repo . --commit <sha>

Exit 0 only when every predicate holds. Any failure means the frozen contract
would become reachable from a tree that cannot satisfy it, and the merge is
refused however mergeable the forge believes it to be.

The digest is not hard-coded here: it is read out of the frozen T0 and then
RECOMPUTED from the instrument sources in the target tree, by the frozen
formula, without importing the instrument. A gate that trusted a constant in
its own source would be checking itself.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import execbinding as eb  # the single implementation of the harness-digest formula

T0_PATH = "docs/notes/p022-263-t0-protocol-freeze.md"
STEP7_NOTE = "docs/notes/p022-263a-step7-environment-capture.md"
# Each artifact binds the digest at its own exact path. Named here so the check
# reads the binding rather than searching the file for a hopeful substring.
BINDING_ARTIFACTS = {
    "docs/evidence/calibration/p022-263a-policy-freeze.json":
        ("measurement_harness_digest",),
    "docs/evidence/calibration/p022-263a-design-constants.json":
        ("bound_measurement_harness_digest",),
    "docs/evidence/calibration/p022-263a-training-preregistration.json":
        ("bindings", "measurement_harness_digest"),
}
STEP7_TOOLS = ("scripts/step7/envcapture.py", "scripts/step7/hostqual.py",
               "scripts/step7/execbinding.py")
DIGEST_RE = re.compile(r"measurement_harness_digest\s*\n?\s*([0-9a-f]{64})")


def blob(repo: Path, commit: str, path: str) -> bytes | None:
    proc = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{path}"],
                          capture_output=True, check=False)
    return proc.stdout if proc.returncode == 0 else None


# The witness runs INSIDE the candidate tree's own modules, in a subprocess, so
# that importing them cannot bind to this gate's copies and a passing result
# cannot come from anything but the code being merged.
WITNESS_SOURCE = r"""
import json, sys, subprocess
from pathlib import Path
sys.path.insert(0, "scripts/step7")
import hostqual as hq
import execbinding as eb

tmp = Path(sys.argv[1])
POWER = {"platform": "windows", "plan_guid": hq.WIN_ACCEPTED_PLANS[0],
         "processor_min_ac": 100, "processor_max_ac": 100,
         "processor_min_dc": 100, "processor_max_dc": 100}
hq.power_snapshot = lambda: dict(POWER)
failures = []

def repo_with(name, files):
    root = tmp / name
    root.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], capture_output=True, check=True)
    if not (root / ".git").exists():
        run("init", "-q"); run("config", "user.email", "w@x"); run("config", "user.name", "w")
    for rel, text in files.items():
        f = root / rel; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    run("add", "-A"); run("commit", "-q", "-m", "w")
    return root, subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()

def w(name, doc):
    f = tmp / name; f.write_text(json.dumps(doc), encoding="utf-8"); return f

# --- W3/W4: the authority state must bite on both readers -------------------
for label, status, flag, must_pass in (("FROZEN+false", "FROZEN.", "false", False),
                                       ("NOT_FROZEN+true", "NOT_FROZEN.", "true", False),
                                       ("NOT_FROZEN+false", "NOT_FROZEN.", "false", False),
                                       ("FROZEN+true", "FROZEN.", "true", True)):
    body = "```text\nStatus:\n  %s\n  collection_authorized: %s\n```\n" % (status, flag)
    root, commit = repo_with("t0-" + flag + status[:4], {"t0.md": body})
    got = hq.bind_t0(root, "t0.md", commit)[1]["result"] == "pass"
    if got != must_pass:
        failures.append("hostqual accepted " + label if got else
                        "hostqual refused " + label)
    try:
        eb.t0_at(root, "t0.md", commit); accepted = True
    except eb.BindingRefused:
        accepted = False
    if accepted != must_pass:
        failures.append("execbinding accepted " + label if accepted else
                        "execbinding refused " + label)

# --- W1/W2: the campaign link must be verified, not merely mentioned --------
froot, fcommit = repo_with("freeze", {"d7/payload.json": '{"kind": "d7"}\n',
                                      "d7/attestation.json": '{"kind": "att"}\n'})
payload, att = froot / "d7/payload.json", froot / "d7/attestation.json"
blob = subprocess.run(["git", "-C", str(froot), "rev-parse", fcommit + ":d7/payload.json"],
                      capture_output=True, text=True, check=True).stdout.strip()
binding = w("binding.json", {"kind": "own.net/p022/execution-binding"})
link = {"kind": hq.CAMPAIGN_LINK_SCHEMA, "schema": 1,
        "execution_binding_sha256": hq.sha256_file(binding),
        "d7_payload": {"path": "d7/payload.json", "sha256": hq.sha256_file(payload),
                       "blob_sha": blob, "commit": fcommit},
        "d7_attestation": {"path": "d7/attestation.json", "sha256": hq.sha256_file(att)},
        "recorded_at": "w"}
if hq.check_campaign_link(link, binding, froot)["result"] != "pass":
    failures.append("a correct campaign link was refused")
wrong = dict(link, execution_binding_sha256="f" * 64)
if hq.check_campaign_link(wrong, binding, froot)["result"] != "fail":
    failures.append("a link naming another execution binding was accepted")
payload.write_text('{"kind": "d7", "edited": true}\n', encoding="utf-8")
if hq.check_campaign_link(link, binding, froot)["result"] != "fail":
    failures.append("a freeze edited after linking was accepted")

# --- W5: a campaign cannot be swapped between preflight and postflight ------
QUAL = {"kind": hq.QUALIFICATION_SCHEMA, "schema": 1, "stratum": "linux",
        "t0": {"commit": "c" * 40, "path": "t0.md", "blob_sha": "b" * 40,
               "sha256": "f" * 64, "status": "FROZEN"},
        "environment_id": "env-1", "host_fingerprint": "sha256:abc",
        "provisioning": {"sha256": "0" * 64}, "environment_manifest": {"sha256": "1" * 64},
        "qualification_tool": {"sha256": "2" * 64}, "power_snapshot": dict(POWER),
        "predicate": {k: "pass" for k in hq.PREDICATE_KEYS},
        "memory_metric": hq.STRATUM_METRIC["linux"], "qualified": True, "qualified_at": "w"}
MANIFEST = {"schema": hq.ENVCAPTURE_SCHEMA,
            "identity": {"environment_id": {"status": "observed", "value": "env-1"},
                         "host_fingerprint": {"status": "observed", "value": "sha256:abc"}},
            "provenance": {"ci": False}}
QUAL["environment_identity_sha256"] = hq.canonical_sha256(MANIFEST["identity"])
CAND = b"candidate bytes"
cand = tmp / "cand.bin"; cand.write_bytes(CAND)
qpath = w("qual.json", QUAL)
IDENT = QUAL["environment_identity_sha256"]
stratum_block = lambda m, extra: {"qualification_sha256": hq.sha256_file(qpath),
                                  "environment_id": "env-1",
                                  "host_fingerprint": "sha256:abc",
                                  "environment_identity_sha256": IDENT,
                                  "candidate_sha256": hq.sha256_bytes(CAND),
                                  "candidate_bytes": len(CAND), "memory_metric": m, **extra}
BINDING = {"kind": eb.BINDING_SCHEMA, "schema": 1,
           "t0": {"commit": "c" * 40, "path": "t0.md", "blob_sha": "b" * 40, "sha256": "f" * 64},
           "instrument": {"accepted_commit": "a" * 40, "harness_digest": "d" * 64},
           "workloads": {"path": eb.WORKLOAD_MANIFEST, "manifest_sha256": "9" * 64},
           "linux": stratum_block(hq.STRATUM_METRIC["linux"], {}),
           "windows": stratum_block(hq.STRATUM_METRIC["windows"], {})}
bpath = w("exec-binding.json", BINDING)
mpath = w("manifest.json", MANIFEST)
dpath = w("declaration.json", {"kind": hq.DECLARATION_SCHEMA, "schema": 1,
                               "no_campaign_workload": True,
                               "no_interactive_user_workload": True,
                               "no_prohibited_background_job_active": True,
                               "operator": "w", "recorded_at": "w"})
probe = tmp / "probe.json"; probe.write_text("{}", encoding="utf-8")
quiet = {"eligible": True, "reason": "", "samples": [0.01], "mean": 0.01, "max": 0.01}

def link_for(binding_file, root, commit_sha, payload_file, att_file, blob_sha):
    return {"kind": hq.CAMPAIGN_LINK_SCHEMA, "schema": 1,
            "execution_binding_sha256": hq.sha256_file(binding_file),
            "d7_payload": {"path": "d7/payload.json", "sha256": hq.sha256_file(payload_file),
                           "blob_sha": blob_sha, "commit": commit_sha},
            "d7_attestation": {"path": "d7/attestation.json", "sha256": hq.sha256_file(att_file)},
            "recorded_at": "w"}

r2, c2 = repo_with("freeze2", {"d7/payload.json": '{"kind": "d7", "campaign": "two"}\n',
                               "d7/attestation.json": '{"kind": "att"}\n'})
p2, a2 = r2 / "d7/payload.json", r2 / "d7/attestation.json"
b2 = subprocess.run(["git", "-C", str(r2), "rev-parse", c2 + ":d7/payload.json"],
                    capture_output=True, text=True, check=True).stdout.strip()
r3, c3 = repo_with("freeze3", {"d7/payload.json": '{"kind": "d7", "campaign": "three"}\n',
                               "d7/attestation.json": '{"kind": "att"}\n'})
p3, a3 = r3 / "d7/payload.json", r3 / "d7/attestation.json"
b3 = subprocess.run(["git", "-C", str(r3), "rev-parse", c3 + ":d7/payload.json"],
                    capture_output=True, text=True, check=True).stdout.strip()
l2 = w("link2.json", link_for(bpath, r2, c2, p2, a2, b2))
l3 = w("link3.json", link_for(bpath, r3, c3, p3, a3, b3))

pre = hq.session_eligibility(bpath, qpath, mpath, dpath, cand, l2, r2, quiesce_result=quiet)
if not pre["eligible"]:
    failures.append("a correctly linked session was refused: " + str(pre["reasons"])[:120])
ppath = w("preflight.json", pre)
# The positive half first. Without it a postflight hard-wired to inadmissible
# would satisfy the negative half, and this witness would read "everything is
# refused" as "the swap is refused" — a broken closing probe standing in for the
# check it was meant to prove.
kept = hq.session_admissibility(bpath, qpath, ppath, mpath, cand, probe, l2, r2)
if not kept["admissible"]:
    failures.append("an unchanged campaign was inadmissible at postflight: "
                    + str(kept.get("reasons"))[:140])
after = hq.session_admissibility(bpath, qpath, ppath, mpath, cand, probe, l3, r3)
if after["admissible"]:
    failures.append("a campaign swapped between preflight and postflight was admissible")
elif not any("campaign link" in str(r) for r in after.get("reasons", ())):
    failures.append("the swapped campaign was refused, but by no reason naming the campaign "
                    "link: " + str(after.get("reasons"))[:140])

print(json.dumps(failures))
"""


def witness(repo: Path, commit: str) -> list[str]:
    """Run the target tree's own tools and require them to refuse.

    A name in a source file proves nothing: a comment, a dead function or
    `def check_campaign_link(): pass` all satisfy a lexical check, and an earlier
    revision of this gate was satisfied by exactly that — its own fixture shipped
    the no-op and called the world compliant. So the tools are extracted from the
    target tree, imported in a subprocess, and driven against attacks they are
    claimed to stop.
    """
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        for tool in STEP7_TOOLS:
            data = blob(repo, commit, tool)
            if data is None:
                return [f"{tool} is absent"]
            target = work / tool
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        script = work / "witness.py"
        script.write_text(WITNESS_SOURCE, encoding="utf-8")
        fixtures = work / "fixtures"
        fixtures.mkdir()
        proc = subprocess.run([sys.executable, str(script), str(fixtures)],
                              capture_output=True, text=True, cwd=str(work), check=False)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["<no output>"]
            return [f"the machinery could not be exercised: {tail[0][:160]}"]
        try:
            return list(json.loads(proc.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            return [f"the witness produced no verdict: {proc.stdout[:120]!r}"]

def check(name: str, ok: bool, detail: str) -> dict[str, object]:
    return {"check": name, "result": "pass" if ok else "fail", "detail": detail}


def gate(repo: Path, commit: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []

    raw_t0 = blob(repo, commit, T0_PATH)
    if raw_t0 is None:
        return [check("t0_present", False, f"{T0_PATH} does not exist at {commit}")]
    text = raw_t0.decode("utf-8", "replace")
    frozen = re.search(r"^\s*(NOT_FROZEN|FROZEN)\.?\s*$", text, re.MULTILINE)
    flag = re.search(r"^\s*collection_authorized:\s*(true|false)\s*$", text, re.MULTILINE)
    declared = frozen.group(1) if frozen else "<no status line>"
    authorized = (flag.group(1) == "true") if flag else None
    results.append(check(
        "t0_frozen_and_authorized", declared == "FROZEN" and authorized is True,
        f"T0 declares {declared}, collection_authorized={json.dumps(authorized)}"))

    named = DIGEST_RE.search(text)
    results.append(check("t0_names_a_digest", named is not None,
                         f"T0 names {named.group(1)[:12] if named else '<none>'} as the accepted "
                         "harness identity"))
    if named is None:
        return results
    expected = named.group(1)

    # Recomputed from the target tree's own sources, by the frozen formula.
    live = eb.harness_digest_at(repo, commit)
    results.append(check(
        "instrument_matches_t0", live == expected,
        f"the instrument at {commit[:12]} hashes to {live[:12] if live else '<unreadable>'}; "
        f"T0 names {expected[:12]}. The frozen contract would otherwise point at an identity "
        "this tree does not contain"))

    rebound = []
    for path, field in BINDING_ARTIFACTS.items():
        raw = blob(repo, commit, path)
        if raw is None:
            rebound.append(f"{Path(path).name}: absent")
            continue
        try:
            doc = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            rebound.append(f"{Path(path).name}: not readable JSON ({exc})")
            continue
        # The exact field, by its own path in that artifact. A substring search
        # would accept the right digest sitting in any passing field while the
        # real binding stayed old — which is the same defect one level down.
        node: object = doc
        for key in field:
            node = node.get(key) if isinstance(node, dict) else None
        if node != expected:
            got = str(node)[:12] if node is not None else "<absent>"
            rebound.append(f"{Path(path).name}: {'.'.join(field)} is {got}, not {expected[:12]}")
    results.append(check(
        "steps_4_5_6_rebound", not rebound,
        "; ".join(rebound) if rebound else
        f"the policy freeze, the design constants and the training preregistration all bind "
        f"{expected[:12]}"))

    missing_tools = [t for t in STEP7_TOOLS if blob(repo, commit, t) is None]
    if missing_tools:
        results.append(check("step7_machinery_enforces", False, f"missing: {missing_tools}"))
    else:
        refusals = witness(repo, commit)
        results.append(check(
            "step7_machinery_enforces", not refusals,
            "; ".join(refusals) if refusals else
            "the target tree's own tools were run: both readers refused all three forbidden "
            "authority states and accepted FROZEN+true; a link naming another binding and a "
            "freeze edited after linking were refused; an unchanged campaign survived "
            "preflight to postflight and a swapped one was refused by campaign-link "
            "continuity"))

    note = (blob(repo, commit, STEP7_NOTE) or b"").decode("utf-8", "replace")
    revoked = "AUTOMATIC AUTHORISATION OF THE FIRST STEP-7 COLLECTION IS REVOKED" in note
    lingering = "SINGLE STEP-7 COLLECTION AUTHORISED automatically" in note
    results.append(check(
        "t0_zero_prerequisite", revoked and not lingering,
        "the step-7 status block revokes the automatic collection authority"
        if revoked and not lingering else
        "the step-7 note still authorises the first collection automatically, so hosts plus a "
        "binding would again be enough to start a clock"))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    results = gate(args.repo, args.commit)
    failed = [r for r in results if r["result"] != "pass"]
    if args.json:
        print(json.dumps({"commit": args.commit, "checks": results,
                          "merge_allowed": not failed}, indent=2))
    else:
        for r in results:
            print(f"{'ok  ' if r['result'] == 'pass' else 'FAIL'} [{r['check']}] {r['detail']}")
        print()
        print("merge gate: allowed" if not failed else
              f"merge gate: REFUSED, {len(failed)} predicate(s) unsatisfied — the frozen "
              "contract must not become reachable from this tree")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
