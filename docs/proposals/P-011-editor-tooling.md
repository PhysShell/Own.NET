# P-011 — Editor tooling & syntax highlighting

- **Status:** draft
- **Depends on:** the CLI `check` command (`python -m ownlang check`);
  `ownlang/diagnostics.py` (the OWN### code/severity vocabulary); the lexer and
  parser (`ownlang/lexer.py`, `spec/Grammar.md`) as the *only* canonical grammar.
  Complements **P-003** (lifetime visualization): P-003 draws lifetimes/loans as a
  graph/timeline; P-011 makes `.own` a first-class *editor* language — coloring,
  diagnostics squiggles, hover. Strategy hub: [`docs/ROADMAP.md`](../ROADMAP.md).

## Motivation

A `.own` file today opens in any editor as undifferentiated grey text: `fn`,
`move`, `release`, the diagnostic codes, the buffer modes — all the same color as
a comma. The checker is genuinely good; the *experience of writing the input to
it* is "Notepad after a head injury". The cheapest possible win in developer
goodwill is coloring keywords. The next-cheapest is drawing the diagnostics the
CLI already produces as red squiggles under the offending span, instead of making
the author re-run `check` in a terminal and count lines by hand.

This proposal is deliberately staged cheapest-first, so each layer ships value
before the next is begun. The expensive layers (a language server, a second
grammar) are explicitly *not* the starting point.

## Scope

A 3-layer plan (plus two optional later layers), in strict cost order:

- **Layer 1 — VS Code TextMate grammar.** A `vscode-ownlang/` extension that
  registers the `ownlang` language id for `.own` and colors keywords, types,
  buffer modes, comments, strings, numbers, and diagnostic codes. One evening.
- **Layer 2 — CLI diagnostics in the editor.** The extension shells out to
  `python -m ownlang check file.own --json`, parses the result, draws squiggles.
  Requires a `--json` output mode on the CLI. A crutch — but a useful one.
- **Layer 3 — LSP + semantic highlighting.** A minimal language server: diagnostics,
  hover, go-to-def, document outline, and the headline feature — **semantic tokens**
  that color resource *state* (owned / moved / released), not just words.
- **Layer 4 — tree-sitter** (only on cross-editor demand): `tree-sitter-ownlang`
  for Neovim/Helix/Zed/Emacs/GitHub.

Ideal ordering, stated plainly:
**v0** TextMate grammar → **v1** CLI `--json` diagnostics in VS Code →
**v2** LSP diagnostics + hover → **v3** semantic tokens (owned/borrowed/moved/
released) → **v4** tree-sitter → **v5** visual lifetime graph (= **P-003**).

## Non-goals

- **JetBrains-grade IntelliJ-for-`.own` in v0.** Refactorings, full completion,
  rename-across-files: no. We are trying to color `fn`, not clone Rider.
- **Writing a three-week language server before `.own` even has colored keywords.**
  The LSP is Layer 3 for a reason. If keywords aren't colored, the LSP is premature.
- **A second canonical grammar.** TextMate and tree-sitter are presentation-only
  approximations; the Python lexer/parser stays the single source of truth.
- A debugger, a formatter, or a build-system integration. Out of scope here.

## Sketch

**Layer 1 (TextMate).** `vscode-ownlang/` contains `package.json` (contributes the
`ownlang` language, `.own` extension, the grammar), `language-configuration.json`
(line `//` comments, brackets, autoclose/surrounding pairs — note: the grammar has
**no block comments**, so don't invent `/* */`), and
`syntaxes/ownlang.tmLanguage.json` (scopeName `source.ownlang`). A regex grammar
covering:

- **keywords:** `module resource acquire release extern fn let move borrow
  borrow_mut consume as use if else return mut policy lifetime subscribe` and the
  emit templates `emit_type emit_acquire emit_release emit_borrow`;
- **buffer modes:** `Buffer.(stack|scratch|pooled|native|inline)`;
- **types / built-ins:** identifiers in type position (`int`, `Span<...>`,
  `Buffer`, resource names) — TextMate can only approximate this;
- **rejected keywords** (`while for loop async await yield spawn`) colored as
  "invalid" so the OWN020 refusal is visible before `check` runs;
- comments (`//`), strings (with `\n \t \" \\` escapes), integer literals;
- **diagnostic codes:** `OWN[0-9]{3}` (the real namespace — see
  `ownlang/diagnostics.py`; there is exactly one code prefix today).

Verify every list above against `ownlang/lexer.py` / `spec/Grammar.md` at build
time — the keyword set is small and authoritative, and this proposal will drift.

**Layer 2 (`--json` diagnostics).** Add a `--json` mode to `check` emitting an
array of `{code, severity, message, file, line, column, endLine, endColumn}`.
The extension runs it on save, parses, draws squiggles colored by `severity`
(ERROR / WARNING per `Severity`). Honest framing: this is editor UX without
writing a language server — diagnostics in the gutter while we still haven't built
Layer 3.

**Layer 3 (LSP + semantic tokens).** TextMate colors *words*; it cannot know that
after `let b = move a;` the symbol `a` is moved-out. Semantic tokens can color the
resource *state* over its lifetime — the signature feature, a Rust borrow
visualizer but inline and for OwnLang:

```text
let a = Buffer.pooled(n);  // a: owned    (green)
let b = move a;            // a: moved (orange/grey), b: owned (green)
release b;                 // b: released (grey)
use b;                     // red squiggle (OWN002)
```

Proposed legend: **owned = green, borrowed = blue, borrow_mut = purple,
moved = orange, released = grey, error = red**; plus token kinds for *lifetime
name*, *policy name*, *diagnostic code*, and *acquire function*. The state facts
are not recomputed in the server — they are the same CFG/state facts P-003
consumes. This is exactly where P-011 and P-003 meet: semantic tokens are the
in-line cousin of P-003's graph/timeline.

**Layer 4 (tree-sitter).** `tree-sitter-ownlang` (`grammar.js`,
`queries/{highlights,locals,folds}.scm`) for the non-VS-Code world. Faster and
more accurate than regex, cross-editor, GitHub-renderable. But it is a *second*
grammar duplicating a Python parser that already exists. Do **not** start here:
it's premature duplication until cross-editor demand is real.

## Open questions

1. **One grammar or many?** The Python lexer/parser is canonical; TextMate and
   tree-sitter necessarily duplicate it and will drift. Generate them from a shared
   token spec, or accept manual sync with a CI test that lexes a sample both ways?
2. **Where does `--json` live?** A first-class core CLI mode (stable, tested,
   reusable by P-003 and P-001), or a thin adapter outside the core so the CLI's
   human output stays the only blessed surface?
3. **How are semantic-token states fed to the server?** Reuse the CFG/state facts
   the checker already computes (as P-003 does) rather than re-deriving ownership
   in the language server — one analysis, two presentations.
4. Bundle a Python runtime / pin a version for the LSP, or assume `python -m
   ownlang` is on the user's PATH? (Affects how painful Layer 2/3 install is.)
