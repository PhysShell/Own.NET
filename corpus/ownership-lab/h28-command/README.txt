H-28-CMD: the DbCommand half of the `DataTable.Load(reader)` family.

STATUS
  Final verdict: H28-PROVIDER-SPECIFIC, narrowly bounded to Npgsql 10.0.3/PostgreSQL 16 and
  Microsoft.Data.Sqlite 10.0.12. Required G1-G3 passed in PR workflow run #38048287923; its
  `h28-command-falsifier` artifact contains runtime logs, OwnIR facts, summaries and SARIF. This
  does not label OWN001 a false positive or establish a universal provider rule. Read
  docs/notes/h28-npgsql-command-resolution.md before interpreting any artifact.

  The original H-28 (research/ownership-semantics-lab-v1@298b305, not on main) settled
  `DataTable.Load(reader)` for a one-result reader: it IS closed (`RELEASE_IF_LAST_RESULT_SET`,
  not BORROW). That same record wrote down one sentence and never classified it:

      "what remains is the never-disposed DbCommand `cmd` (an object leak without a
       protocol consequence)"
      -- h28/scripts/h28_anchors_record.py, consequence_for_the_demanding_instance

  This directory records falsifiable source and runtime checks. It does not call OWN001 a false
  positive, claim a native leak on Npgsql, or propose a universal rule from these provider runs.

LAYOUT
  fx/CommandDispose.cs       nine C# methods (A/B/C/D + controls), using abstract ADO.NET types.
                             G3 confirmed the expected finding anchors in workflow run #38048287923.
  fx/CommandDispose.own      engine-only manual reduction. This is not C# extraction evidence.
  falsifier/Program.cs       P1-P5 and G2/P6. P4 is isolated from P1-P3; P6 counts live SQLite
                             statements via sqlite3_next_stmt, not RSS or forced GC.
  falsifier/h28cmd.csproj    net8.0, Npgsql 10.0.3, Microsoft.Data.Sqlite 10.0.12; compiles
                             both the falsifier and fx/CommandDispose.cs.
  falsifier/run_with_pgserver.py
                             keeps the temporary pgserver alive while the .NET test runs.
  scripts/verify_g3.py       production Roslyn -> OwnIR -> summaries -> core SARIF; exact expected
                             finding anchors are checked, and all intermediate artifacts saved.
  scripts/derive_source_evidence.py
                             re-fetches 44 upstream excerpts plus the Npgsql finalizer negative
                             scan. Includes the SQLitePCLRaw opt-in required by sqlite3_next_stmt;
                             TFM evidence confirms Npgsql 10.0.3 targets net8.0 and
                             Microsoft.Data.Sqlite 10.0.12 has a netstandard2.0 asset usable by
                             this net8.0 falsifier. Non-zero = drift.
  run.sh                     PASS/FAIL/SKIP driver. `all-required` fails on any SKIP.
  evidence/*.txt              source excerpts with repository/ref/path/git blob sha/file sha256/
                             line range. Local engine output is saved. G3/runtime artifacts are
                             produced in CI and attached to workflow run #38048287923.
  .github/workflows/h28-command-falsifier.yml
                             runs `all-required` on the PR and preserves results as an artifact.

GATES
  ./corpus/ownership-lab/h28-command/run.sh engine          # Python only; current manual core pass
  ./corpus/ownership-lab/h28-command/run.sh g3-required     # production extractor and core
  ./corpus/ownership-lab/h28-command/run.sh runtime-required # compile + provider runtime
  ./corpus/ownership-lab/h28-command/run.sh all-required    # mandatory; SKIP is non-zero
  python3 corpus/ownership-lab/h28-command/scripts/derive_source_evidence.py

  Runtime dependencies: .NET 8 SDK, packages available from NuGet or already restored in cache,
  and PostgreSQL 16. The workflow installs pinned pgserver 0.1.4 from PyPI; locally either
  `pip install pgserver==0.1.4` or set H28_PG_DSN. There is no curl-only NuGet gate: the script attempts restore with
  `--ignore-failed-sources`, so a warm package cache can work offline.

WHAT HAS RUN IN THE PRODUCING SANDBOX
  PASS: Python engine reduction, matching three manual OWN001 expectations; 33/33 real-world
        corpus cases; whole-tree Ruff; mypy (60 source files); 44 source excerpts + finalizer scan;
        Python/shell syntax checks, C# grammar parse (not compilation), and pgserver supervisor
        API/Unix-socket DSN preflight (not a .NET/provider falsifier).
  PASS IN CI: G1 build/P4, G2 native SQLite statement checks, P5 PostgreSQL prepared-state check,
              and G3 production C# extraction all passed in workflow run #38048287923. The exact
              artifact is attached to that run; local status metadata is evidence/ci-run-38048287923.txt.
  BLOCKED LOCALLY: this sandbox has no .NET SDK, so its `all-required` run returned 1 on G1/G2/G3
                   SKIPs; see evidence/required-gates-local.txt.
  INCOMPLETE: `python tests/run_tests.py` passed its early analysis/codegen checks, then stopped at
              checkpoint validation because this checkout is shallow and `cargo` is absent. It is
              not counted as a green full-suite run. See evidence/local-validation.txt.

SCOPE
  No production analyzer code, OwnIR vocabulary, ownership semantics, or diagnostics are changed.
  The normal real-world corpus suite does not glob `corpus/ownership-lab/`; these are experiment
  fixtures. G3 now confirms the predicted extraction loss on this exact fixture. Any architecture
  follow-up, including #382, remains separate and is not proposed or implemented in this PR.
