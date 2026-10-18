# Dictionary-ref PoC — precision gate pre-registration (written before the independent sample was fetched)

- Independent sample: GitHub code search, queries different from the development sample
  (`docs/evidence/next-bug-class-2026-10/data/sample-index.tsv`); files whose repo+path appear in the development
  index are excluded, and so are meziantou/Meziantou.Framework and dotnet/maui (the targets).
- Each file is analysed alone (single-file compilation, implicit usings on), exactly as the probe runs on the
  targets. Probe version = the build that passed controls and both targets; it is frozen before labelling.
- Every warning is labelled by reading the source:
  - TP: on some execution the event can mutate the same dictionary while the ref is live (direct mutation, or
    code reachable from the event that can reach the dictionary and change it);
  - FP: the event provably cannot mutate that dictionary;
  - UNCLEAR: cannot decide from the file.
- Precision = TP / (TP + FP); conservative precision = TP / all warnings (UNCLEAR counted as FP). Target >= 80 %
  on the conservative figure.
- Fewer than 10 warnings in total -> INCONCLUSIVE (insufficient data), regardless of the ratio.
- No probe change after this point except to fix a crash; any change re-runs controls, targets and the sample.

## Round 1 result (probe sha256 cd49e9a5…, recorded before any change)

18 warnings / 274 sites / 429 files: TP 9, FP 5, UNCLEAR 4 -> precision 64 %, conservative 50 %. **Gate FAILED.**
FP causes: (a) the event is followed by `return`/`throw` in its own block, so it cannot reach the later use (3);
(b) a method-local dictionary that escapes only AFTER the event is treated as reachable (2).

## Round 2 pre-registration (written before the round-2 sample is fetched)

- Exactly two probe changes, both principled and both answering a round-1 FP cause:
  (a) an event whose own block, after it, unconditionally leaves (`return`/`throw`) before the block ends does not
      reach a use outside that block;
  (b) a method-local dictionary is reachable at an event only through an escape (capture, argument, alias, return)
      that occurs textually BEFORE the event.
- Both shapes become mandatory negative controls; all round-1 controls and both targets must still pass.
- The UNCLEAR rule is NOT changed (no tuning toward opaque delegates).
- Fresh sample: new code-search queries; files already in the development sample or the round-1 sample, and the
  two target repos, are excluded. Same labelling rules, same thresholds (>= 80 % conservative, >= 10 warnings).
- Round 2 is the last round within this PoC budget; its result is final.
