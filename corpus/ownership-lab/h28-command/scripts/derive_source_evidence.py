#!/usr/bin/env python3
"""H-28-CMD evidence deriver: re-fetch every source citation used by
docs/notes/h28-npgsql-command-resolution.md from its PINNED upstream ref and
write the exact cited region to evidence/<name>.txt.

Nothing in the report is a hand-copied quotation: each artifact here carries the
repo, the ref (a tag where one exists, so the bytes are immutable), the path, the
byte count, the sha256 of the fetched file and the line range that was extracted.
Re-run this and diff evidence/ to re-verify the whole source arm of the finding.

    python3 corpus/ownership-lab/h28-command/scripts/derive_source_evidence.py

Read-only: touches no production code, builds nothing, needs only github.com +
api.github.com. Set GH_TOKEN for a higher rate limit (works unauthenticated too).
Exit code is non-zero if any pinned citation could not be re-derived, so this
doubles as a staleness gate on the report.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "evidence")

API = "https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"

# (artifact name, repo, ref, path, marker that starts the region, max lines)
# The marker is matched literally; the region runs from the marker's line to
# marker+maxlines, so the citation is stable even if the file shifts.
CITATIONS: list[tuple[str, str, str, str, str, int]] = [
    # ---- Npgsql: what NpgsqlCommand.Dispose actually releases -----------------
    (
        "npgsql-10.0.3-NpgsqlCommand-Dispose.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlCommand.cs",
        "protected override void Dispose(bool disposing)", 16,
    ),
    (
        "npgsql-10.0.3-NpgsqlCommand-Reset.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlCommand.cs",
        "internal void Reset()", 14,
    ),
    (
        "npgsql-10.0.3-NpgsqlCommand-ctor-SuppressFinalize.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlCommand.cs",
        "public NpgsqlCommand(string? cmdText, NpgsqlConnection? connection)", 10,
    ),
    (
        "npgsql-10.0.3-NpgsqlCommand-CreateCachedCommand.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlCommand.cs",
        "internal static NpgsqlCommand CreateCachedCommand", 3,
    ),
    (
        "npgsql-10.0.3-NpgsqlCommand-TraceCommandStart.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlCommand.cs",
        "internal void TraceCommandStart(NpgsqlTracingOptions tracingOptions", 26,
    ),
    (
        "npgsql-10.0.3-NpgsqlCommand-TraceCommandStop.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlCommand.cs",
        "internal void TraceCommandStop()", 8,
    ),
    (
        "npgsql-10.0.3-NpgsqlConnection-CreateCommand.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlConnection.cs",
        "public new NpgsqlCommand CreateCommand()", 15,
    ),
    (
        "npgsql-10.0.3-NpgsqlDataReader-Dispose.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlDataReader.cs",
        "protected override void Dispose(bool disposing)", 26,
    ),
    (
        "npgsql-10.0.3-NpgsqlDataReader-Close-public.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlDataReader.cs",
        "public override void Close() => Close(connectionClosing: false", 2,
    ),
    (
        "npgsql-10.0.3-NpgsqlDataReader-Cleanup.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlDataReader.cs",
        "internal async Task Cleanup(bool async, bool connectionClosing", 80,
    ),
    (
        "npgsql-10.0.3-NpgsqlActivitySource-IsEnabled.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlActivitySource.cs",
        "internal static bool IsEnabled", 2,
    ),
    (
        # The ActivitySource NAME is load-bearing for falsifier probe P4: the listener must
        # match it or NpgsqlActivitySource.IsEnabled stays false and the whole tracing arm
        # is inert (CurrentActivity never assigned), so P4 would prove nothing.
        "npgsql-10.0.3-NpgsqlActivitySource-SourceName.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/NpgsqlActivitySource.cs",
        "static readonly ActivitySource Source = new(\"Npgsql\"", 3,
    ),
    (
        "npgsql-10.0.3-NpgsqlConnector-PreparedStatementManager.txt",
        "npgsql/npgsql", "v10.0.3", "src/Npgsql/Internal/NpgsqlConnector.cs",
        "internal PreparedStatementManager PreparedStatementManager", 2,
    ),
    # ---- Npgsql main: is it still the same? -----------------------------------
    (
        "npgsql-main-NpgsqlCommand-Dispose.txt",
        "npgsql/npgsql", "main", "src/Npgsql/NpgsqlCommand.cs",
        "protected override void Dispose(bool disposing)", 16,
    ),
    (
        "npgsql-main-NpgsqlDataReader-Close-public.txt",
        "npgsql/npgsql", "main", "src/Npgsql/NpgsqlDataReader.cs",
        "public override void Close() => Close(connectionClosing: false", 2,
    ),
    # ---- BCL: the contract, at the ref the old falsifier ran on and at HEAD ---
    (
        "runtime-v8.0.20-DataTable-Load.txt",
        "dotnet/runtime", "v8.0.20",
        "src/libraries/System.Data.Common/src/System/Data/DataTable.cs",
        "public virtual void Load(IDataReader reader, LoadOption loadOption, "
        "FillErrorEventHandler? errorHandler)", 30,
    ),
    (
        "runtime-v10.0.12-DataTable-Load.txt",
        "dotnet/runtime", "v10.0.12",
        "src/libraries/System.Data.Common/src/System/Data/DataTable.cs",
        "public virtual void Load(IDataReader reader, LoadOption loadOption, "
        "FillErrorEventHandler? errorHandler)", 30,
    ),
    (
        "runtime-v10.0.12-DbCommand-class.txt",
        "dotnet/runtime", "v10.0.12",
        "src/libraries/System.Data.Common/src/System/Data/Common/DbCommand.cs",
        "public abstract class DbCommand", 4,
    ),
    (
        "runtime-v10.0.12-DbCommand-DisposeAsync.txt",
        "dotnet/runtime", "v10.0.12",
        "src/libraries/System.Data.Common/src/System/Data/Common/DbCommand.cs",
        "public virtual ValueTask DisposeAsync()", 6,
    ),
    (
        "runtime-v10.0.12-DbDataReader-Close-Dispose.txt",
        "dotnet/runtime", "v10.0.12",
        "src/libraries/System.Data.Common/src/System/Data/Common/DbDataReader.cs",
        "public virtual void Close() { }", 32,
    ),
    (
        "runtime-v10.0.12-IDbCommand.txt",
        "dotnet/runtime", "v10.0.12",
        "src/libraries/System.Data.Common/src/System/Data/IDbCommand.cs",
        "public interface IDbCommand", 3,
    ),
    (
        "runtime-v8.0.20-Activity-Dispose.txt",
        "dotnet/runtime", "v8.0.20",
        "src/libraries/System.Diagnostics.DiagnosticSource/src/System/Diagnostics/Activity.cs",
        "Dispose will stop the Activity if it is already started", 12,
    ),
    (
        "runtime-v8.0.20-Activity-IDisposable.txt",
        "dotnet/runtime", "v8.0.20",
        "src/libraries/System.Diagnostics.DiagnosticSource/src/System/Diagnostics/Activity.cs",
        "public partial class Activity : IDisposable", 2,
    ),
    # ---- Cross-provider: does command.Dispose release anything there? ---------
    (
        "mssqlite-SqliteCommand-Dispose.txt",
        "dotnet/efcore", "main",
        "src/Microsoft.Data.Sqlite.Core/SqliteCommand.cs",
        "protected override void Dispose(bool disposing)", 12,
    ),
    (
        "mssqlite-SqliteCommand-DisposePreparedStatements.txt",
        "dotnet/efcore", "main",
        "src/Microsoft.Data.Sqlite.Core/SqliteCommand.cs",
        "private void DisposePreparedStatements(bool disposing = true)", 22,
    ),
    (
        "mssqlite-SqliteCommand-PrepareAndEnumerate-head.txt",
        "dotnet/efcore", "main",
        "src/Microsoft.Data.Sqlite.Core/SqliteCommand.cs",
        "private IEnumerable<(sqlite3_stmt Statement, int ParamCount)> "
        "PrepareAndEnumerateStatements()", 6,
    ),
    (
        "mssqlite-SqliteCommand-preparedStatements-field.txt",
        "dotnet/efcore", "main",
        "src/Microsoft.Data.Sqlite.Core/SqliteCommand.cs",
        "_preparedStatements =", 2,
    ),
    (
        "mssqlite-SqliteDataReader-Close-Dispose.txt",
        "dotnet/efcore", "main",
        "src/Microsoft.Data.Sqlite.Core/SqliteDataReader.cs",
        "public override void Close()", 42,
    ),
    (
        "mssqlite-SqliteConnection-commands-weakrefs.txt",
        "dotnet/efcore", "main",
        "src/Microsoft.Data.Sqlite.Core/SqliteConnection.cs",
        "List<WeakReference<SqliteCommand>> _commands", 2,
    ),
    (
        "sqlitepclraw-sqlite3_stmt-SafeHandle.txt",
        "ericsink/SQLitePCL.raw", "main",
        "src/SQLitePCLRaw.core/handles.cs",
        "public class sqlite3_stmt : SafeHandle", 26,
    ),
    (
        "sqlclient-SqlCommand-Dispose.txt",
        "dotnet/SqlClient", "main",
        "src/Microsoft.Data.SqlClient/src/Microsoft/Data/SqlClient/SqlCommand.cs",
        "protected override void Dispose(bool disposing)", 14,
    ),
    (
        "mysqlconnector-MySqlCommand-Dispose.txt",
        "mysql-net/MySqlConnector", "master",
        "src/MySqlConnector/MySqlCommand.cs",
        "protected override void Dispose(bool disposing)", 6,
    ),
]


def _get(url: str, accept: str) -> bytes | None:
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    req = urllib.request.Request(url, headers={"User-Agent": "own-net-h28cmd",
                                               "Accept": accept})
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"  FETCH-FAIL {url} ({accept}): {e}", file=sys.stderr)
        return None


def fetch(repo: str, path: str, ref: str) -> tuple[bytes, str] | None:
    """Return (raw bytes, git blob sha) for one pinned path, or None.

    Two calls: the raw accept gives the file bytes, the json accept gives the git
    blob sha. The sha is what makes each citation checkable against git itself
    rather than against whatever the API happened to serve.
    """
    url = API.format(repo=repo, path=path, ref=ref)
    raw = _get(url, "application/vnd.github.raw+json")
    if raw is None:
        return None
    sha = "?"
    meta = _get(url, "application/vnd.github+json")
    if meta is not None:
        try:
            sha = str(json.loads(meta).get("sha", "?"))
        except (ValueError, AttributeError):
            pass
    return raw, sha


def region(text: str, marker: str, maxlines: int) -> tuple[int, str] | None:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if marker in line:
            chunk = lines[i:i + maxlines]
            start = i + 1
            body = "\n".join(f"{start + j:5d}| {ln}" for j, ln in enumerate(chunk))
            return start, body
    return None


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    manifest: list[str] = []
    failed = 0
    for name, repo, ref, path, marker, maxlines in CITATIONS:
        got = fetch(repo, path, ref)
        if got is None:
            failed += 1
            manifest.append(f"MISSING\t{name}\t{repo}@{ref}\t{path}")
            continue
        raw, sha = got
        text = raw.decode("utf-8", "replace")
        reg = region(text, marker, maxlines)
        if reg is None:
            failed += 1
            manifest.append(f"MARKER-NOT-FOUND\t{name}\t{repo}@{ref}\t{path}\t{marker!r}")
            continue
        start, body = reg
        digest = hashlib.sha256(raw).hexdigest()
        header = (
            f"# H-28-CMD source citation (auto-derived, do not edit by hand)\n"
            f"# repo      : {repo}\n"
            f"# ref       : {ref}\n"
            f"# path      : {path}\n"
            f"# blob sha  : {sha}\n"
            f"# file sha256: {digest}\n"
            f"# file bytes : {len(raw)}\n"
            f"# marker    : {marker!r}\n"
            f"# region    : lines {start}..{start + maxlines - 1}\n"
            f"# derived by: scripts/derive_source_evidence.py\n"
        )
        with open(os.path.join(OUT, name), "w") as f:
            f.write(header + body.rstrip("\n") + "\n")
        manifest.append(f"OK\t{name}\t{repo}@{ref}\tsha256={digest[:16]}\tlines={start}")
        print(f"  ok  {name}  ({repo}@{ref} line {start})")

    with open(os.path.join(OUT, "MANIFEST.txt"), "w") as f:
        f.write("# H-28-CMD evidence manifest: one line per pinned citation.\n")
        f.write("# OK = re-derived now; MISSING/MARKER-NOT-FOUND = the report is stale.\n")
        f.write("\n".join(manifest) + "\n")
    print(f"\n{len(CITATIONS) - failed}/{len(CITATIONS)} citations re-derived "
          f"-> {os.path.relpath(OUT)}")
    if failed:
        print(f"{failed} FAILED: the report's source arm is not reproducible as pinned",
              file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
