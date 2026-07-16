"""Minimal P-015 configuration carrier (the first, deliberately narrow slice).

Today this reads exactly ONE thing from an explicitly named ``own.toml``: the
``[weak-subscription]`` table's ``subscribe`` list — the ``"SimpleType.Method"``
names of a project's own weak-subscribe wrapper API (P-035). own-check forwards
these to the extractor, which then treats a matching call as a first-class,
already-released subscription instead of assuming the BCL ``WeakEventManager``.

Deliberately excluded for now (see the arbiter decision on P-035 / the P-015
proposal): auto-discovery, severity, per-path overrides, environment variables,
and every other table. The file is named with an explicit ``--config`` and nothing
else. A malformed declaration is a HARD error, never a silent skip — a typo in a
suppression-shaped config is a footgun, so it fails loudly.
"""

from __future__ import annotations

import tomllib


class ConfigError(Exception):
    """A configuration file that exists but is malformed. Callers surface this as a
    hard (non-zero) error; it is never swallowed into "no declaration"."""


def load_weak_subscribe(path: str) -> list[str]:
    """Return the declared weak-subscribe ``"SimpleType.Method"`` names from *path*.

    An absent ``[weak-subscription]`` table (or an absent ``subscribe`` key) yields
    ``[]`` — that is "no declaration", not an error. A present-but-malformed table
    raises :class:`ConfigError`.
    """
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    return _weak_subscribe_from(data, path)


def _weak_subscribe_from(data: dict[str, object], path: str) -> list[str]:
    table = data.get("weak-subscription")
    if table is None:
        return []
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: [weak-subscription] must be a table")

    # Only `subscribe` (P-035 recognition) and `target` (the S0 fix target, read by
    # `load_target_subscribe`) are honoured. Reject any other key so a typo
    # (`subscribes`, `unsubscribe` before it is designed, ...) is a hard error, not
    # a silently-ignored no-op that hides a caller mistake.
    unknown = sorted(set(table) - {"subscribe", "target"})
    if unknown:
        raise ConfigError(
            f"{path}: [weak-subscription] has unsupported key(s): "
            f"{', '.join(unknown)} (only `subscribe` and `target` are supported)"
        )

    entries = table.get("subscribe", [])
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        raise ConfigError(
            f"{path}: [weak-subscription].subscribe must be a list of strings"
        )
    for entry in entries:
        _validate_entry(entry, path)
    return list(entries)


def load_target_subscribe(path: str) -> str:
    """Return the ONE weak-subscribe wrapper the fixer should emit (S0 `target_api`).

    Pinned explicitly, never guessed: either ``[weak-subscription].target`` (a single
    ``"SimpleType.Method"``), or — as a convenience when there is no ambiguity — the sole
    ``subscribe`` entry when the list has exactly one. Zero or several ``subscribe`` entries
    with no explicit ``target`` is a :class:`ConfigError`: silently taking the first would
    bake an unintended API into a public candidates contract.
    """
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc

    # Validate the WHOLE table first (unknown keys, a malformed `subscribe`, ...) so an
    # explicit `target` can never smuggle a broken sibling key past the fail-loud
    # contract. `_weak_subscribe_from` raises on any table malformation and returns [] if
    # the table is absent.
    subscribe = _weak_subscribe_from(data, path)
    table = data.get("weak-subscription")
    if not isinstance(table, dict):
        raise ConfigError(
            f"{path}: a [weak-subscription] table is required to pin a fix target"
        )
    target = table.get("target")
    if target is not None:
        if not isinstance(target, str):
            raise ConfigError(f"{path}: [weak-subscription].target must be a string")
        _validate_entry(target, path)
        return target  # an explicit target wins over the (already-validated) subscribe list
    if len(subscribe) == 1:
        return subscribe[0]
    raise ConfigError(
        f"{path}: cannot pin a fix target: set [weak-subscription].target, or declare "
        f"exactly one [weak-subscription].subscribe entry (found {len(subscribe)})"
    )


def _validate_entry(entry: str, path: str) -> None:
    """A declared entry must be exactly ``"SimpleType.Method"``.

    Matching is by SIMPLE containing-type name + method name (the P-035 / #223
    allowlist shape), so a namespace-qualified name is rejected rather than silently
    never matching: exactly one dot, both sides non-empty valid identifiers.
    """
    parts = entry.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ConfigError(
            f"{path}: [weak-subscription].subscribe entry {entry!r} must be "
            f'"SimpleType.Method" — exactly one dot, e.g. "WeakEvents.AddPropertyChanged"'
        )
    for part in parts:
        if not part.isidentifier():
            raise ConfigError(
                f"{path}: [weak-subscription].subscribe entry {entry!r} has an "
                f"invalid identifier part {part!r}"
            )
