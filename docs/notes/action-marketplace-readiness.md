# GitHub Action Marketplace readiness (P-013 gate B)

Companion to [`docs/notes/owen-cli-release.md`](owen-cli-release.md)
(the NuGet-package side of release readiness) — this note covers `action.yml`,
the composite action at the repo root, publicly displayed as **"Owen
lifetime/resource check"** (public facade rebrand,
[`docs/notes/owen-public-facade.md`](owen-public-facade.md) / PR #246). As
with the CLI note, **no Marketplace listing was published**; this documents
what was validated and what a maintainer still has to do to actually list it.

## Metadata / branding audit

`action.yml`'s Marketplace-required fields were checked against GitHub's
actual constraints, not just "does it have the keys":

- `name: "Owen lifetime/resource check"`, `description`, `author` — present,
  accurate to what the action does. `author: "Own.NET"` is deliberately kept
  as the repository/project identity (PR #246's own documented decision, not
  reopened here) while `name` carries the public Owen branding.
- `branding.icon: "shield"` — a real [Feather icon](https://feathericons.com/),
  in Marketplace's allowed icon set.
- `branding.color: "purple"` — in Marketplace's fixed 8-color list (`white`,
  `yellow`, `blue`, `green`, `orange`, `red`, `purple`, `gray-dark`).
- `description` is 230 characters flattened — Marketplace's card view
  truncates around ~125; left as-is since shortening it would cost real
  information and this is a cosmetic nicety, not a publish blocker.

Both nested `uses:` steps inside the composite action
(`actions/setup-python`, `actions/setup-dotnet`) are pinned to exact commit
SHAs — done by PR #246 alongside the rest of the public facade rebrand, not
redone here; re-verified as still correct (matching `ci.yml`'s own pins).

## Versioning policy — immutable release tag + explicitly-gated moving major tag

Distinct tag namespace from the CLI's **`owen-cli-v*`**
([`docs/notes/owen-cli-release.md`](owen-cli-release.md)) — same repo, two
release surfaces, a shared bare `v*` would be ambiguous about which artifact
a tag names:

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
  unattended; it does not exist yet.** **Correction (Codex review):**
  referencing a never-configured environment auto-creates it with zero
  protection rules, so `environment: action-major-tag-move` alone is not
  proof a human ever approves this job. The `move-major-tag` job now checks
  out the repo, fetches the environment via `gh api`, and refuses to
  force-move the tag — right after checkout, before the force-push — unless
  it has a `required_reviewers` rule with at least one reviewer.
  **Second correction (Codex review):** a bare `protection_rules` count
  accepted a `wait_timer`- or `branch_policy`-only environment too, neither
  of which waits for a human, and a `required_reviewers` rule can itself be
  saved with zero reviewers. The check now calls
  `scripts/check_environment_protection.sh` — the same small, fixture-tested
  predicate `owen-cli-release.yml`'s `publish` job uses for `nuget-release`
  — which only accepts a `required_reviewers` rule with >=1 reviewer. The
  job's `permissions:` also gained `actions: read`, which the
  environment-read endpoint requires alongside `contents: write`. See
  `docs/notes/owen-cli-release.md`'s "Testing the environment-protection
  predicate" for the fixture-driven `ci.yml` job that exercises this on
  every ordinary push/PR, offline.
  **Third correction (final review):** the SHA resolution
  `git rev-parse "refs/tags/$TARGET"` returns the annotated tag object's own
  SHA when `$TARGET` is an annotated tag, not the commit it points at —
  moving the major ref onto that SHA would make it a tag-of-a-tag rather
  than a tag pointing at the release commit. `^{commit}` peels an annotated
  tag to the commit it references (a no-op on a lightweight tag, which
  already points at a commit), so the major tag always ends up pointing at
  a commit either way.
- Both `github.event_name == 'push'` *and* the ref-prefix check gate the
  tag-triggered jobs — `github.ref` alone doesn't prove a tag was actually
  pushed, since a `workflow_dispatch` run can be pointed `--ref` at an
  existing tag too (the same class of gap independent review caught on the
  CLI's publish gate, PR #244 — fixed here from the start).

## Consumer-simulation fixture

`fixtures/marketplace-consumer-demo/` — deliberately separate from
`frontend/roslyn/samples/` (Own.NET's own extractor precision-test corpus,
not representative of an ordinary consumer's code): one file with an
unambiguous leak (`Leaky.cs`, `OWN001`), one clean negative control
(`Clean.cs`) — diagnostic codes untouched by the public facade rebrand, per
its own explicit scope boundary. `action-marketplace-readiness.yml`'s
`consumer-simulation` job runs the action against it via `uses: ./`.

**On the resolution mechanism:** an earlier version of this job tried
`uses: PhysShell/Own.NET@${{ github.sha }}`, intending a genuinely remote,
resolved-by-the-runner reference instead of a local path. That does not
work: GitHub Actions does not evaluate expressions in
`jobs.<job_id>.steps.uses` at all (it is not among the fields the
context-availability docs list as expression-capable, unlike `with`/`env`/
`if`/`run`) — the string would have been passed through literally and the
job would never have resolved an action, let alone run one (Codex review,
PR #245, caught this before it ever merged). There is no mechanism to
parameterize `uses:` with "the commit currently under test"; a genuinely
dynamic remote-ref proof is not automatable in a pre-tag workflow. `uses:
./` is the correct, honest mechanism this workflow has used from the
start of what actually shipped — the same one `ci.yml`'s
`own-check-codescan` job already relies on. The meaningful difference from
that job is the fixture (a small consumer-style pair, not the
precision-test corpus) and the release/tag-validation wiring around it,
not the resolution mechanism, which was never a real option here.

Verifies: the leak sample fails the step (`fail-on-finding: true`, asserted
via `steps.leak.outcome`), the clean sample does not, and the SARIF surface
produces a non-empty `sarif-file` output that `github/codeql-action/upload-sarif`
accepts (skipped on fork PRs, which get a read-only `GITHUB_TOKEN` that can
never satisfy `security-events: write` — same guard `own-check-codescan`
already uses, applied here after Codex flagged the same gap on this job).
The SARIF file itself carries the `Owen` driver name and the default
`owen.sarif` filename (`action.yml`'s own default, PR #246) — this workflow
does not override either.

**Honest limitation:** even `uses: ./` is not a full substitute for a
genuinely separate consumer repository (which would additionally prove
resolution against an entirely different git remote/identity, and would be
the only way to actually exercise a real `owner/repo@vX.Y.Z` reference).
A second public repository was not created for this — creating a new public
repo is a visible, user-facing action, not this session's call to make
without being asked. If a maintainer wants that stronger proof, cloning
`fixtures/marketplace-consumer-demo/` into a throwaway public repo and
pointing the 6-line README snippet at a real pushed tag is a five-minute
follow-up, and remains the one genuine way to exercise dynamic remote
`uses:` resolution — a real post-publication gate for whoever runs the
first actual release, not something to fake here in its place.

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

1. Confirm a `LICENSE` exists (same blocker `owen-cli-release.md`
   tracks for the NuGet package — Marketplace listing requires a license on
   the repo too). **This is the repository owner's decision, not this
   session's.**
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
6. For the strongest possible consumer proof, clone the fixture into a
   throwaway public repo pointed at the real tag (see "Honest limitation"
   above) — genuinely optional, but the only way to exercise a real dynamic
   `owner/repo@vX.Y.Z` reference at all.

## Boundaries honored

- Not published to Marketplace.
- No license chosen on the repository owner's behalf.
- No analyzer logic touched — `scripts/own-check.sh`/`.ps1` and the core
  detectors are unchanged; only `action.yml`'s nested step pins (PR #246),
  the release/consumer-simulation workflow, the fixture, and doc/README
  accuracy changed.
- No failure hidden behind `continue-on-error`: the one place it's used
  (`consumer-simulation`'s leak-sample step) is immediately followed by an
  explicit assertion on `steps.leak.outcome` — the point is to observe and
  check a *specific expected* failure, not to swallow an unexpected one.
- No second public repository was created for the stronger consumer proof
  described above — that is a visible, user-facing action left for the
  repository owner to take if/when they want it, not simulated here.
