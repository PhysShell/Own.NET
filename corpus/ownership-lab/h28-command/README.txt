H-28-CMD: the DbCommand half of the `DataTable.Load(reader)` family.

WHAT THIS IS
  The original H-28 (corpus/ownership-lab/h28/, on the research branch
  research/ownership-semantics-lab-v1 at 298b305 -- NOT on main) asked about argument
  ownership transfer. Its runtime falsifier settled `DataTable.Load(reader)`: the reader IS
  closed (RELEASE_IF_LAST_RESULT_SET, not BORROW). The same record then wrote down one
  sentence and never classified it:

      "what remains is the never-disposed DbCommand `cmd` (an object leak without a
       protocol consequence)"
      -- h28/scripts/h28_anchors_record.py, consequence_for_the_demanding_instance

  This directory closes that sentence. Read docs/notes/h28-npgsql-command-resolution.md.

  Verdict: H28-PROVIDER-SPECIFIC. Not disposing the command is a real resource defect on
  Microsoft.Data.Sqlite and releases nothing on Npgsql / Microsoft.Data.SqlClient /
  MySqlConnector. Details, citations and falsifiers are in the report.

LAYOUT
  fx/CommandDispose.cs     the fixture, 9 methods (A/B/C/D + 5 controls), written against the
                           ABSTRACT ADO.NET types on purpose -- that is what the extractor's
                           IsOwningFactory matches, so one fixture shows the analyzer's verdict
                           for every provider at once. Expectations are marked PREDICTED: the
                           Roslyn extractor was not runnable where this was produced.
  fx/CommandDispose.own    the ENGINE-RUNNABLE reduction of the same family. Needs only
                           python3. This half WAS executed; see evidence/.
  falsifier/Program.cs     the runtime falsifier: probes P1-P6 over variants A/B/C/D.
  falsifier/h28cmd.csproj  net8.0, Npgsql 10.0.3, Microsoft.Data.Sqlite 10.0.12 -- the exact
                           versions of the original H-28 falsifier, so the two runs compare.
  run.sh                   driver. `engine` always runs; `runtime` prints SKIP-WHY and exits 0
                           when there is no .NET SDK / NuGet / PostgreSQL, rather than faking it.
  scripts/derive_source_evidence.py
                           re-fetches all 31 pinned source citations and rewrites evidence/.
                           Non-zero exit = the report's source arm is stale.
  evidence/*.txt           the artifacts every claim in the report cites. Each carries repo,
                           ref, path, git blob sha, file sha256 and the extracted line range,
                           so a quotation is checkable against git rather than against memory.

REPRODUCE
  corpus/ownership-lab/h28-command/run.sh engine     # python3 only; ~1s
  corpus/ownership-lab/h28-command/run.sh runtime    # needs .NET 8 SDK + NuGet + PostgreSQL
  python3 corpus/ownership-lab/h28-command/scripts/derive_source_evidence.py

  The runtime half starts PostgreSQL itself via pgserver (PyPI, self-contained PostgreSQL 16 on
  a Unix socket) -- the same harness the original H-28 falsifier used -- or takes H28_PG_DSN.

WHAT WAS AND WAS NOT EXECUTED WHERE THIS WAS PRODUCED
  executed   : the engine half (evidence/engine-CommandDispose.txt), the source derivation of
               all 31 citations (evidence/*.txt + MANIFEST.txt), a live PostgreSQL 16.2 via
               pgserver (used only for the server-side lifecycle checks quoted in the report).
  NOT executed: the Roslyn extractor (no .NET SDK, no NuGet feed) and the runtime falsifier
               (same). fx/CommandDispose.cs expectations and falsifier probes P2/P4/P6 are
               therefore PREDICTED from source, and the report says so at each one.

NO PRODUCTION CHANGE
  Nothing here alters the extractor, the core, the vocabulary or any diagnostic. corpus/
  ownership-lab/ is not globbed by tests/test_corpus.py (only corpus/real-world/ is), so these
  fixtures are inert data until someone decides to act on the report's section 10.
