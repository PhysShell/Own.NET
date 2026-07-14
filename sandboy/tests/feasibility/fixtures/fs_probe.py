#!/usr/bin/env python3
"""One filesystem probe, selected by argv[1]. Each probe attempts exactly one
operation and prints a single machine-parseable RESULT line, then exits 0
regardless of outcome — the *outcome* is the data point, not the exit code.
Never invoked via a shell string: always `sandboy run --policy P -- python3
fs_probe.py <mode> <path> [<path2>]`.
"""
import errno
import os
import socket
import sys


def result(status, detail=""):
    print(f"RESULT={status} detail={detail}", flush=True)
    sys.exit(0)


def main():
    mode = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) > 2 else None

    if mode == "read":
        try:
            with open(path, "rb") as f:
                f.read(1)
            result("ALLOWED")
        except OSError as e:
            result("DENIED", f"errno={e.errno} {errno.errorcode.get(e.errno, '?')}")

    elif mode == "write":
        try:
            with open(path, "wb") as f:
                f.write(b"sandboy-fs-probe\n")
            result("ALLOWED")
        except OSError as e:
            result("DENIED", f"errno={e.errno} {errno.errorcode.get(e.errno, '?')}")

    elif mode == "read_via_symlink":
        # path = the symlink (inside the allowed tree); its target lives
        # outside. Landlock is documented to enforce on the RESOLVED target,
        # not the symlink's own directory.
        try:
            with open(path, "rb") as f:
                f.read(1)
            result("ALLOWED")
        except OSError as e:
            result("DENIED", f"errno={e.errno} {errno.errorcode.get(e.errno, '?')}")

    elif mode == "unix_socket_bind":
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(path)
            s.close()
            os.unlink(path)
            result("ALLOWED")
        except OSError as e:
            result("DENIED", f"errno={e.errno} {errno.errorcode.get(e.errno, '?')}")

    else:
        print(f"RESULT=ERROR detail=unknown mode {mode!r}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
