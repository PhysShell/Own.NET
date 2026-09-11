#!/usr/bin/env python3
"""Round 7's execution schedule — CALIBRATION_ONLY, and pure.

Round 7 compares three arms. The preregistration fixed how many sessions and
halves, and said nothing about ORDER, which is a hole big enough to drive the
whole result through: run every A, then every B, then every C, and a machine
that drifts over an hour hands back a beautiful "effect of the real binary".
After several pages spent fighting environmental variation, that would be a
particularly embarrassing way to lose.

The ratified schedule, fixed here before any measurement exists:

    block = (regime, n, session_index)          40 blocks = 2 x 2 x 10
    within a block:  all three arms run, each arm's two halves ADJACENT,
                     arm order deterministically shuffled
    across blocks:   block order deterministically shuffled
    seed:            fixed and committed before measurement
    recorded:        seed, planned order, actual order

Blocked randomisation, not a Latin square. Drift is spread across arms instead
of aligning with them, and every block still contains all three arms, so a
within-block comparison is never a comparison across an hour of machine time.

No clock here, no files, no I/O: a schedule is arithmetic on a seed, and it can
be checked exhaustively before anything is measured.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

ARMS = ("A", "B", "C")
HALVES = ("first", "second")
REGIMES = ("process-cold", "warm")
REPETITION_COUNTS = (5, 15)
SESSIONS = 10

# The seed is the first 16 hex digits of the Round 6 helper's sha256, as
# recorded in docs/evidence/round6/p022-263a-round6-scales.linux.json months of
# review before this round existed.
#
# A literal I invented would be just as deterministic and strictly less
# auditable: nothing but my word would stop me re-rolling it until the printed
# order looked tidy. This value was fixed by a compiler in a previous round and
# I cannot move it. `round7-schedule` checks the two against each other rather
# than trusting this comment.
SCHEDULE_SEED = 0xF937B36BD4DAC422
SCHEDULE_SEED_SOURCE = ("first 16 hex digits of helper_sha256 in "
                        "docs/evidence/round6/p022-263a-round6-scales.linux.json")


@dataclass(frozen=True)
class Half:
    """One measured half: an arm's first or second run inside one block."""

    regime: str
    n: int
    session: int
    arm: str
    half: str

    @property
    def key(self) -> str:
        return f"{self.regime}|n{self.n}|s{self.session}|{self.arm}|{self.half}"


@dataclass(frozen=True)
class Block:
    """One (regime, n, session): all three arms, each arm's halves adjacent."""

    regime: str
    n: int
    session: int
    arm_order: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.regime}|n{self.n}|s{self.session}"

    @property
    def halves(self) -> tuple[Half, ...]:
        return tuple(Half(self.regime, self.n, self.session, arm, half)
                     for arm in self.arm_order for half in HALVES)


def _block_seed(seed: int, regime: str, n: int, session: int) -> int:
    """A block's own seed, derived from its identity rather than its position.

    Shuffling arms with one running generator would make a block's arm order
    depend on where the block landed in the outer shuffle, so a change to the
    block order would silently reshuffle every arm order too. Deriving from the
    block's identity keeps the two independent and each reproducible on its own.
    """
    material = f"{seed:x}|{regime}|{n}|{session}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def blocks(seed: int = SCHEDULE_SEED) -> tuple[Block, ...]:
    """The 40 blocks in execution order, arms shuffled within each."""
    out = []
    for regime in REGIMES:
        for n in REPETITION_COUNTS:
            for session in range(1, SESSIONS + 1):
                arms = list(ARMS)
                random.Random(_block_seed(seed, regime, n, session)).shuffle(arms)
                out.append(Block(regime, n, session, tuple(arms)))
    random.Random(seed).shuffle(out)
    return tuple(out)


def planned_halves(seed: int = SCHEDULE_SEED) -> tuple[Half, ...]:
    """Every half in the order it will be executed. 40 blocks x 6 = 240."""
    return tuple(h for b in blocks(seed) for h in b.halves)


def plan(seed: int = SCHEDULE_SEED) -> dict[str, object]:
    """The schedule as a recordable object, seed included.

    The seed travels with the plan because a randomisation nobody can replay is
    a fond memory rather than a method — the same reason the instrument records
    its own interleave order.
    """
    bs = blocks(seed)
    return {
        "seed": f"0x{seed:016x}",
        "seed_source": SCHEDULE_SEED_SOURCE,
        "design": "blocked randomisation; block = (regime, n, session)",
        "blocks": len(bs),
        "halves": len(bs) * len(ARMS) * len(HALVES),
        "regimes": list(REGIMES),
        "repetition_counts": list(REPETITION_COUNTS),
        "sessions_per_cell": SESSIONS,
        "planned_order": [{"block": b.key, "arm_order": list(b.arm_order)} for b in bs],
        "tag": "CALIBRATION_ONLY",
    }


def process_spawns(seed: int = SCHEDULE_SEED, warmup_discards: int = 2) -> int:
    """How many child processes the whole round will spawn, from the plan itself.

    Derived rather than asserted, because the preregistration quotes a number
    and a quoted number that nothing computes is a number that drifts.
    """
    total = 0
    for b in blocks(seed):
        per_half = b.n + (warmup_discards if b.regime == "warm" else 0)
        total += per_half * len(ARMS) * len(HALVES)
    return total
