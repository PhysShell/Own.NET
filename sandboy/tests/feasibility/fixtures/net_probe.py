#!/usr/bin/env python3
"""Network probe. Usage: net_probe.py <proto> <host> <port> [timeout_s]
  proto: tcp | udp

Always connects/sends to a LOCAL listener the harness starts beforehand
(loopback only) — this probe never contacts an external network address.
Landlock ABI v4 scopes TCP bind/connect by PORT only (not address/CIDR), and
has no UDP coverage at all — this probe exists to make both facts observable,
not to reach any real external service.
"""
import socket
import sys


def main():
    proto, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
    timeout = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0

    if proto == "tcp":
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            s.sendall(b"sandboy-net-probe\n")
            print("RESULT=ALLOWED detail=tcp connect+send ok", flush=True)
        except OSError as e:
            print(f"RESULT=DENIED detail=errno={e.errno} {e}", flush=True)
        finally:
            s.close()
    elif proto == "udp":
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            s.sendto(b"sandboy-net-probe\n", (host, port))
            print("RESULT=ALLOWED detail=udp sendto ok", flush=True)
        except OSError as e:
            print(f"RESULT=DENIED detail=errno={e.errno} {e}", flush=True)
        finally:
            s.close()
    else:
        print(f"RESULT=ERROR detail=unknown proto {proto!r}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
