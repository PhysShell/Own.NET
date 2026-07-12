# GitHub Action Marketplace readiness (P-013 gate B)

Companion to [`docs/notes/ownsharp-cli-release.md`](ownsharp-cli-release.md)
(the NuGet-package side of release readiness) — this note covers `action.yml`,
the composite action at the repo root. As with the CLI note, **no Marketplace
listing was published**; this documents what was validated and what a
maintainer still has to do to actually list it.

## Metadata / branding audit

`action.yml`'s Marketplace-required fields were checked against GitHub's
actual constraints, not just "does it have the keys":

- `name`, `description`, `author` — present, accurate to what the action does.
- `branding.icon: "shield"` — a real [Feather icon](https://feathericons.com/),
  in Marketplace's allowed icon set.
- `branding.color: "purple"` — in Marketplace's fixed 8-color list (`white`,
  `yellow`, `blue`, `green`, `orange`, `red`, `purple`, `gray-dark`).
- `description` is 230 characters flattened — Marketplace's card view
  truncates around ~125; left as-is since shortening it would cost real
  information and this is a cosmetic nicety, not a publish blocker.

**Fixed:** both nested `uses:` steps inside the composite action
(`actions/setup-python@v5`, `actions/setup-dotnet@v4`) were floating major-
version tags, inconsistent with this repo's own stated convention (`ci.yml`:
"every third-party `uses:` is pinned to a commit SHA"). Pinned to the exact
SHAs `ci.yml` already uses and verified independently via `git ls-remote
--tags` against both upstream repos (not copied on faith).

## Versioning policy — immutable release tag + explicitly-gated moving major tag

Distinct tag namespace from the CLI's `ownsharp-cli-v*` (same repo, two
release surfaces — a shared bare `v*` would be ambiguous about which
artifact a tag names):

- **Action release tags are bare SemVer: `vMAJOR.MINOR.PATCH`** (e.g.
  `v0.1.0`) — the form GitHub's own "Releasing and maintaining actions" guide
  documents, and what a consumer's `uses: owner/repo@v1` expects to resolve.
- **Immutable once pushed.** `.github/workflows/action-marketplace-readiness.yml`'s
  `validate-release-tag` job runs on a `v*.*.*` tag push and only *validates*
  (metadata sanity + the consumer-simulation checks via `needs:`) — it never
  writes to the repository.
- **The moving major tag (`v0` while pre-1.0, `v1` after) only ever moves
  through a separate, explicit `workflow_dispatch`** (`move-major-tag` job,
  input `move_major_tag_to: vX.Y.Z`) — never as a side effect of pushing a
  patch release. Force-moving a tag is equivalent to a force-push (rewrites
  what a consumer pinned to the major tag gets next), so the job additionally
  requires the `action-major-tag-move` GitHub Environment — **a repo admin
  must configure that with required reviewers before this can run
  unattended; it does not exist yet.**
- Both `github.event_name == 'push'` *and* the ref-prefix check gate the
  tag-triggered jobs — `github.ref` alone doesn't prove a tag was actually
  pushed, since a `workflow_dispatch` run can be pointed `--ref` at an
  existing tag too (the same class of gap independent review caught on the
  CLI's publish gate in PR #244 — fixed here from the start).

## Consumer-simulation fixture

`fixtures/marketplace-consumer-demo/` — deliberately separate from
`frontend/roslyn/samples/` (Own.NET's own extractor precision-test corpus,
not representative of an ordinary consumer's code): one file with an
unambiguous leak (`Leaky.cs`, `OWN001`), one clean negative control
(`Clean.cs`). `action-marketplace-readiness.yml`'s `consumer-simulation` job
runs the action against it via `uses: ./`.

**Correction (Codex review, PR #245):** an earlier version of this job tried
`uses: PhysShell/Own.NET@${{ github.sha }}`, intending a genuinely remote,
resolved-by-the-runner reference instead of a local path. That does not
work: GitHub Actions does not evaluate expressions in
`jobs.<job_id>.steps.uses` at all (it is not among the fields the
context-availability docs list as expression-capable, unlike `with`/`env`/
`if`/`run`) — the string would have been passed through literally and the
job would never have resolved an action, let alone run one. There is no
mechanism to parameterize `uses:` with "the commit currently under test";
a genuinely dynamic remote-ref proof is not automatable in a pre-tag
workflow. `uses: ./` is the correct, honest mechanism — the same one
`ci.yml`'s `own-check-codescan` job already relies on. The meaningful
difference from that job is the fixture (a small consumer-style pair, not
the precision-test corpus) and the release/tag-validation wiring around it,
not the resolution mechanism, which was never a real option here.

Verifies: the leak sample fails the step (`fail-on-finding: true`, asserted
via `steps.leak.outcome`), the clean sample does not, and the SARIF surface
produces a non-empty `sarif-file` output that `github/codeql-action/upload-sarif`
accepts (skipped on fork PRs, which get a read-only `GITHUB_TOKEN` that can
never satisfy `security-events: write` — same guard `own-check-codescan`
already uses, applied here after Codex flagged the same gap on this job).

**Honest limitation:** even `uses: ./` is not a full substitute for a
genuinely separate consumer repository (which would additionally prove
resolution against an entirely different git remote/identity, and would be
the only way to actually exercise a real `owner/repo@vX.Y.Z` reference).
A second public repository was not created for this — creating a new public
repo is a visible, user-facing action, not this session's call to make
without being asked. If a maintainer wants that stronger proof, cloning
`fixtures/marketplace-consumer-demo/` into a throwaway public repo and
pointing the 6-line README snippet at a real pushed tag is a five-minute
follow-up — and the only way to genuinely exercise dynamic remote `uses:`
resolution at all, pre-tag CI or not.

`ci.yml`'s pre-existing `own-check-codescan` job (dog-fooding via `uses: ./`
against `frontend/roslyn/samples` on every push/PR) is untouched — this
workflow is the release-readiness path, not a replacement for that fast
per-push proof.

## README accuracy

Fixed a repo-name casing drift in both `README.md` and `README.ru.md`:
`PhysShell/own.net@main` → `PhysShell/Own.NET@main` (GitHub resolves both
case-insensitively, but a Marketplace listing and consumer-facing docs
should use the actual casing). Added a pointer to this note's versioning
policy so the "6-line" snippet tells a reader what to switch to once a
release exists, instead of only describing the pre-release state.

## Marketplace publish checklist (not run — for whoever does)

1. Confirm a `LICENSE` exists (same blocker `ownsharp-cli-release.md`
   tracks for the NuGet package — Marketplace listing requires a license on
   the repo too).
2. Push a `vX.Y.Z` tag; confirm `validate-release-tag` and
   `consumer-simulation` both pass on it.
3. `workflow_dispatch` → `move-major-tag` with that tag, approve the
   `action-major-tag-move` environment gate (once configured).
4. Update the README's "Run it in CI" snippet to the real tag (`@v0` or
   `@v0.1.0`), replacing the `@main` pre-release note.
5. List on Marketplace via the repository's own Release UI ("Publish this
   Action to the GitHub Marketplace" checkbox on a Release) — a manual,
   human step; nothing in this repo's workflows does this automatically, by
   design (Marketplace listing is a one-way, account-linked action).

## Boundaries honored

- Not published to Marketplace.
- No analyzer logic touched — `scripts/own-check.sh`/`.ps1` and the core
  detectors are unchanged; only `action.yml`'s nested step pins, the new
  release/consumer-simulation workflow, the fixture, and doc/README
  accuracy changed.
- No failure hidden behind `continue-on-error`: the one place it's used
  (`consumer-simulation`'s leak-sample step) is immediately followed by an
  explicit assertion on `steps.leak.outcome` — the point is to observe and
  check a *specific expected* failure, not to swallow an unexpected one.
