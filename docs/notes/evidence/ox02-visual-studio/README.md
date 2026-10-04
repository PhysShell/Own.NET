# OX-02 real Visual Studio evidence

From CI run 37175674769 (job `owen-visual-studio`, head `fbdc978`), Visual Studio Enterprise
2026 18.10.12217.157 on the hosted `windows-2025-vs2026` image, driven by
`scripts/vs/owen-vs-acceptance.ps1`. Kept byte-for-byte as uploaded.

- `acceptance.log`: every check, 19/19 passed.
- `results.json`: the checks and the measurements (edit -> squiggle / disappearance per edit, UI-thread maximum, service timings, working set).
- `trace.jsonl`: Owen.VisualStudio's own trace (`OWEN_LIVE_TRACE`): load, workspace snapshots (unsaved `Use.cs` + Roslyn's in-memory generated documents), publications with the service's timings, the tags the tagger produced per text version, UI-thread maxima.
- `k2-squiggle.png`: `Use.cs*` unsaved; squiggles on `OrderProtocol.WithDraft(order, draft =>` (the finding) and on the inserted `draft.Submit(now);` (its witness step); the Error List row `OWN002 … LiveFixture Use.cs 10`.
- `k2-navigated.png`: after double-clicking the row: caret at 10:9.
- `p9-cs-and-own.png`: CS0029 and OWN002 side by side.
- `k3-gone.png`: after deleting the line: no squiggle, no row.
