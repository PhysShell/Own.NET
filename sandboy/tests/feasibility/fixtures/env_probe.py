#!/usr/bin/env python3
"""Credential-canary probe: try to read/leak the canary environment
variables the harness injects into the OUTER job environment, from inside
the sandboxed process (and, for `child`, from a forked descendant of it).

Usage: env_probe.py <mode> <out_file>
  mode: stdout | file | child

Prints RESULT=LEAK if ANY canary name is present in os.environ (regardless
of value — presence alone is the failure, since sandboy is expected to
env_clear() before exec), else RESULT=CLEAN. Also writes the full (attempted)
environment dump to <out_file> so run_gate.py can grep it independently of
this script's own judgement.
"""
import os
import sys

CANARY_NAMES = [
    "GITHUB_TOKEN",
    "AZURE_DEVOPS_PAT",
    "NUGET_AUTH_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "SSH_AUTH_SOCK",
]


def dump_and_judge(out_file):
    with open(out_file, "w") as f:
        for k, v in sorted(os.environ.items()):
            f.write(f"{k}={v}\n")
    present = [n for n in CANARY_NAMES if n in os.environ]
    if present:
        print(f"RESULT=LEAK detail=present={','.join(present)}", flush=True)
    else:
        print("RESULT=CLEAN detail=no canary names in environ", flush=True)


def main():
    mode, out_file = sys.argv[1], sys.argv[2]
    if mode in ("stdout", "file"):
        dump_and_judge(out_file)
    elif mode == "child":
        pid = os.fork()
        if pid == 0:
            dump_and_judge(out_file)
            os._exit(0)
        os.waitpid(pid, 0)
    else:
        print(f"RESULT=ERROR detail=unknown mode {mode!r}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
