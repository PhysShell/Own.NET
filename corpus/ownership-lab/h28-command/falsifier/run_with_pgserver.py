#!/usr/bin/env python3
"""Start a temporary pgserver and keep it alive while the Npgsql falsifier runs.

Called by run.sh only when no explicit H28_PG_DSN was supplied. pgserver must be
installed (`python3 -m pip install pgserver`). The server and its data directory are
cleaned in finally; dotnet is a child process, not a shell substitution that could
outlive the PostgreSQL handle.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def connection_string(uri: str) -> str:
    parsed = urlsplit(uri)
    query = parse_qs(parsed.query)
    host = query.get("host", [None])[0] or parsed.hostname or "127.0.0.1"
    parts = [f"Host={host}", f"Username={unquote(parsed.username or 'postgres')}"]
    database = unquote(parsed.path.lstrip("/"))
    if database:
        parts.append(f"Database={database}")
    if parsed.port:
        parts.append(f"Port={parsed.port}")
    if parsed.password:
        parts.append(f"Password={unquote(parsed.password)}")
    return ";".join(parts)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_with_pgserver.py <built-falsifier.dll>", file=sys.stderr)
        return 2
    try:
        import pgserver
    except ImportError:
        print("SKIP: pgserver is not installed; pip install pgserver or set H28_PG_DSN",
              file=sys.stderr)
        return 3

    server = None
    with tempfile.TemporaryDirectory(prefix="h28cmd-pg-") as temp:
        try:
            server = pgserver.get_server(Path(temp) / "pgdata", cleanup_mode="delete")
            dsn = connection_string(server.get_uri(database="postgres"))
            env = os.environ.copy()
            env["H28_PG_DSN"] = dsn
            print("# pgserver is ready; running Npgsql falsifier against PostgreSQL 16", flush=True)
            return subprocess.run(["dotnet", sys.argv[1]], env=env, check=False).returncode
        finally:
            if server is not None:
                server.cleanup()


if __name__ == "__main__":
    sys.exit(main())
