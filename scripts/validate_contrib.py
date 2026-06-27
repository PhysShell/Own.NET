#!/usr/bin/env python3
"""
Contribution-format validator — PR and issue bodies vs. the repo templates.

GitHub issue **forms** (`.github/ISSUE_TEMPLATE/*.yml`) already block submission
on missing required fields, so issues are validated *at creation* natively. PRs
have no such native gate, so this script is the gate: a `pull_request` CI check
(see `.github/workflows/pr-issue-validation.yml`) reads the PR body and fails the
run when it does not follow `.github/pull_request_template.md`. The same logic
backstops issues opened out-of-band (API / blank issue) where the form gate is
bypassed.

What "follows the template" means here is deliberately light — enough to catch a
PR opened with an empty body, the untouched template, or a missing "what/why" —
without policing prose. Concretely, per kind:
  * every REQUIRED section heading is present;
  * each PROSE section carries real text (not just the `<!-- hint -->`);
  * each CHECKBOX section has at least one box ticked (e.g. the change *type*);
  * the body is not the verbatim, unfilled template.

zero-dependency: stdlib only, like the rest of scripts/. The CI step writes the
body to a file (never interpolates it into the shell) and passes `--pr`/`--issue`.

Usage:
  validate_contrib.py --pr   body.md      # validate a PR body, exit 1 on problems
  validate_contrib.py --issue body.md     # validate a free-form issue body
  validate_contrib.py --selftest
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

# --- template specs -------------------------------------------------------
#
# Kept in lockstep with the markdown templates by the selftest, which loads the
# real `.github/pull_request_template.md` and asserts every required/checkbox
# heading below actually exists in it. Edit a template heading and the selftest
# fails until the spec follows — the two cannot silently drift.


@dataclass(frozen=True)
class Spec:
    """One contribution kind's required shape. Headings are matched normalized
    (case-folded, stripped of markdown/emoji/punctuation), so cosmetic edits to a
    template heading do not need a code change — only renaming the wording does."""

    kind: str
    required: tuple[str, ...]  # section headings that must be present
    prose: tuple[str, ...] = ()  # of `required`: must carry real text
    checkbox: tuple[str, ...] = ()  # of `required`: must have >=1 box ticked


PR_SPEC = Spec(
    kind="pull request",
    required=("Что и зачем", "Тип изменения", "Как проверено", "Чеклист"),
    prose=("Что и зачем",),
    checkbox=("Тип изменения",),
)

# Free-form issues are the backstop case (the forms are the real gate), so the
# bar is just "not empty, has the headline question". Forms emit `### ` h3 labels;
# we accept either, so a body pasted from a form still passes.
ISSUE_SPEC = Spec(
    kind="issue",
    required=("Описание",),
    prose=("Описание",),
)

SPECS = {"pr": PR_SPEC, "issue": ISSUE_SPEC}

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", re.MULTILINE)
_CHECKED = re.compile(r"^\s*[-*]\s*\[[xX]\]", re.MULTILINE)


def _norm(text: str) -> str:
    """Heading -> comparison key: drop markdown/emoji/punctuation, collapse space,
    case-fold. The change-type heading and its emoji/punctuation-laden variant
    compare equal. Built without a literal alphabet range so the source stays
    confusable-char-clean for ruff (RUF001) — `isalnum()` keeps Cyrillic too."""
    text = _HTML_COMMENT.sub("", text)
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass
class Section:
    heading: str
    body: str


def split_sections(text: str) -> list[Section]:
    """Carve the body into (heading, content-until-next-heading) chunks. Text
    before the first heading is ignored — templates lead with a heading."""
    out: list[Section] = []
    matches = list(_HEADING.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append(Section(heading=m.group(1).strip(), body=text[m.end() : end]))
    return out


def _has_prose(body: str) -> bool:
    """True if, after stripping HTML hint-comments and checkbox/list lines, any
    real text remains. A section left as just its `<!-- hint -->` is not filled."""
    stripped = _HTML_COMMENT.sub("", body)
    lines = []
    for ln in stripped.splitlines():
        s = ln.strip()
        if not s or re.match(r"^[-*]\s*\[[ xX]\]", s):
            continue
        lines.append(s)
    return bool(lines)


def _looks_like_template(body: str, template: str | None) -> bool:
    """The verbatim, unedited template submitted as the body. Compared with hint
    comments and whitespace squeezed out, so trivial reflow does not fool it."""
    if not template:
        return False

    def squeeze(t: str) -> str:
        return re.sub(r"\s+", " ", _HTML_COMMENT.sub("", t)).strip()

    return squeeze(body) == squeeze(template)


@dataclass
class Result:
    ok: bool
    problems: list[str] = field(default_factory=list)


def validate(body: str, spec: Spec, template: str | None = None) -> Result:
    """Check `body` against `spec`. `template` (the raw markdown) enables the
    unfilled-template guard. Returns every problem found, not just the first."""
    problems: list[str] = []

    if not body or not body.strip():
        problems.append(f"{spec.kind} body is empty — fill in the template.")
        return Result(ok=False, problems=problems)

    if _looks_like_template(body, template):
        problems.append(
            f"{spec.kind} body is the unfilled template — replace the hints with "
            "your own content."
        )

    sections = {_norm(s.heading): s for s in split_sections(body)}

    for heading in spec.required:
        sec = sections.get(_norm(heading))
        if sec is None:
            problems.append(f"missing required section: '{heading}'")
            continue
        if heading in spec.prose and not _has_prose(sec.body):
            problems.append(f"section '{heading}' is empty — add a description.")
        if heading in spec.checkbox and not _CHECKED.search(sec.body):
            problems.append(
                f"section '{heading}' has no box ticked — mark at least one '[x]'."
            )

    return Result(ok=not problems, problems=problems)


# --- selftest -------------------------------------------------------------


def _load_template(name: str) -> str | None:
    """Best-effort read of a template shipped in `.github/` next to this checkout.
    Returns None when run outside the repo (the unfilled-template guard then no-ops
    rather than crashing)."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    path = root / ".github" / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _selftest() -> int:
    fails: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    pr_template = _load_template("pull_request_template.md")

    # The spec must not drift from the real template: every heading the validator
    # demands has to exist in the shipped markdown.
    if pr_template is not None:
        present = {_norm(s.heading) for s in split_sections(pr_template)}
        for h in PR_SPEC.required:
            check(_norm(h) in present, f"PR template is missing required heading '{h}'")
        # And the template itself must pass nothing-but-itself == fail.
        r = validate(pr_template, PR_SPEC, pr_template)
        check(not r.ok, "raw PR template should fail validation (it is unfilled)")

    # Empty body fails.
    check(not validate("", PR_SPEC).ok, "empty body should fail")
    check(not validate("   \n  ", PR_SPEC).ok, "whitespace body should fail")

    # A fully, correctly filled PR passes.
    good = (
        "## Что и зачем\n"
        "Добавляет валидатор формата PR/issue.\n\n"
        "## Тип изменения\n"
        "- [x] feat — новая возможность\n"
        "- [ ] fix\n\n"
        "## Как проверено\n"
        "- [x] python tests/run_tests.py\n\n"
        "## Чеклист\n"
        "- [x] есть селфтест\n"
    )
    r = validate(good, PR_SPEC)
    check(r.ok, f"well-formed PR should pass, got: {r.problems}")

    # Missing a whole section.
    r = validate(good.replace("## Как проверено\n- [x] python tests/run_tests.py\n\n", ""), PR_SPEC)
    check(not r.ok, "PR missing a required section should fail")
    check(
        any("Как проверено" in p for p in r.problems),
        f"problem should name the missing section, got: {r.problems}",
    )

    # 'Что и зачем' present but only a hint comment -> empty prose.
    only_hint = good.replace(
        "Добавляет валидатор формата PR/issue.",
        "<!-- опишите изменение -->",
    )
    r = validate(only_hint, PR_SPEC)
    check(not r.ok, "PR with hint-only prose section should fail")
    check(any("empty" in p for p in r.problems), f"should flag empty prose, got: {r.problems}")

    # No change-type box ticked.
    no_type = good.replace("- [x] feat — новая возможность", "- [ ] feat — новая возможность")
    r = validate(no_type, PR_SPEC)
    check(not r.ok, "PR with no change-type ticked should fail")
    check(any("ticked" in p for p in r.problems), f"should flag no ticked box, got: {r.problems}")

    # Heading normalization: emoji / trailing punctuation / case still match.
    fancy = good.replace("## Тип изменения", "##  тип ИЗМЕНЕНИЯ 🏷️ :")
    check(
        validate(fancy, PR_SPEC).ok,
        "heading normalization (emoji/case/punct) should still match",
    )

    # Issue backstop: empty fails, a real description passes.
    check(not validate("", ISSUE_SPEC).ok, "empty issue should fail")
    check(
        validate("## Описание\nChecker crashes on an empty file.\n", ISSUE_SPEC).ok,
        "issue with a filled description should pass",
    )
    # Form-style h3 heading is accepted too.
    check(
        validate("### Описание\nFalse positive in codegen.\n", ISSUE_SPEC).ok,
        "form-style ### heading should be accepted",
    )

    total = 16
    for f in fails:
        print(f"VALIDATE SELFTEST FAIL: {f}")
    print(f"validate_contrib selftest: {total - len(fails)}/{total} checks passed")
    return 1 if fails else 0


# --- cli ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate a PR or issue body against the repo templates."
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pr", metavar="FILE", help="path to a file holding the PR body")
    g.add_argument("--issue", metavar="FILE", help="path to a file holding the issue body")
    g.add_argument("--selftest", action="store_true", help="run internal checks and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.pr is not None:
        kind, path, template = "pr", args.pr, _load_template("pull_request_template.md")
    else:
        kind, path, template = "issue", args.issue, None

    try:
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
    except OSError as exc:
        print(f"cannot read body file '{path}': {exc}", file=sys.stderr)
        return 2

    result = validate(body, SPECS[kind], template)
    if result.ok:
        print(f"{SPECS[kind].kind} format OK")
        return 0

    print(f"{SPECS[kind].kind} format check failed:")
    for problem in result.problems:
        print(f"  • {problem}")
    print(
        "\nSee the template and edit the description to match. "
        "Re-run after editing — this check re-runs on every edit."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
