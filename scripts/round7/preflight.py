#!/usr/bin/env python3
"""Round 7 arm construction and the B1-B4 structural preflight — CALIBRATION_ONLY.

No clock is started here and none may be added. This builds the three arms and
answers four structural questions about arm B, each of which would silently
invalidate the round if it went the wrong way:

    B1  did the padding survive compilation and linking, or was it dropped?
    B2  is the padding actually MAPPED, or merely present in the file?
    B3  does arm B's mapped size match arm C's, to within one page?
    B4  is arm B's work byte-identical to arm A's?

All four are stop conditions. A padded binary whose padding was optimised away,
left unmapped, mis-sized, or accompanied by a change to the work confounds the
two things arm B exists to separate, and the failure would show up as a
measurement rather than as a build problem.

Arm A and arm B are linked from THE SAME spin.o. Compiling the work twice and
comparing the results would test the compiler's determinism; linking one object
into both binaries removes the question instead of answering it, and B4 then
checks the only thing left that could differ — what the linker did.

    python scripts/round7/preflight.py --candidate <own-cli> --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from elfread import Elf64, NotAnElf64, Section, Symbol

ROOT = Path(__file__).resolve().parent.parent.parent
WORK_SOURCE = ROOT / "scripts/round6/spin.c"      # arm A is the Round 6 helper, unchanged
PAD_SOURCE = ROOT / "scripts/round7/pad.c"
CFLAGS = ("-O2",)                                  # exactly Round 6's, so arm A is arm A
PAD_SYMBOL = "own_round7_padding"
PAD_MACRO = "OWN_ROUND7_PAD_ELEMENTS"   # pad.c refuses to compile without it
WORK_SYMBOL = "main"
PAGE = 4096
TAG = "CALIBRATION_ONLY"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"{cmd[0]} failed: {' '.join(cmd)}\n"
                         + r.stderr.decode("utf-8", "replace"))


def build_arms(out_dir: Path, target_mapped: int, max_attempts: int = 12
               ) -> dict[str, object]:
    """Compile the work once, link arm A from it, and tune arm B onto arm C's size.

    The tuning loop is a build step, not a measurement: it links, reads the
    resulting ELF's mapped size, and adjusts the element count. Its trace is
    recorded so the final element count is not a number that simply appeared.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    work_obj = out_dir / "spin.o"
    arm_a = out_dir / "arm-a"
    arm_b = out_dir / "arm-b"
    pad_obj = out_dir / "pad.o"

    _run(["gcc", *CFLAGS, "-c", "-o", str(work_obj), str(WORK_SOURCE)])
    _run(["gcc", *CFLAGS, "-o", str(arm_a), str(work_obj)])

    elements = (target_mapped - Elf64(arm_a).mapped_bytes) // 8
    trace = []
    for _ in range(max_attempts):
        _run(["gcc", *CFLAGS, "-c", f"-D{PAD_MACRO}={elements}",
              "-o", str(pad_obj), str(PAD_SOURCE)])
        _run(["gcc", *CFLAGS, "-o", str(arm_b), str(work_obj), str(pad_obj)])
        mapped = Elf64(arm_b).mapped_bytes
        delta = mapped - target_mapped
        trace.append({"pad_elements": elements, "mapped_bytes": mapped, "delta": delta})
        if abs(delta) <= PAGE:
            break
        elements -= (delta + 7) // 8
    return {"work_object_sha256": hashlib.sha256(work_obj.read_bytes()).hexdigest(),
            "arm_a": str(arm_a), "arm_b": str(arm_b),
            "pad_elements": elements, "tuning_trace": trace,
            "cflags": list(CFLAGS)}


# --- the four checks -------------------------------------------------------


SHF_ALLOC = 0x2
SHN_UNDEF = 0
SHN_LORESERVE = 0xFF00


def _padding_section(b: Elf64) -> tuple[Symbol | None, Section | None]:
    """The section the padding symbol says it is in — st_shndx, not its address.

    st_shndx names the section outright. Looking it up by address instead would
    be inferring the answer from a coincidence of ranges, and a non-allocated
    section has address 0, where that inference quietly finds nothing at all.
    """
    sym = b.symbol_named(PAD_SYMBOL)
    if sym is None:
        return None, None
    if sym.shndx == SHN_UNDEF or sym.shndx >= SHN_LORESERVE or sym.shndx >= len(b.sections):
        return sym, None
    return sym, b.sections[sym.shndx]


def check_b1(b: Elf64) -> dict[str, object]:
    """The padding survived linking, and its section is big enough to hold it."""
    sym, sec = _padding_section(b)
    if sym is None:
        return {"pass": False, "why": f"{PAD_SYMBOL} is absent from arm B's symbol "
                                      "table: the compiler or the linker dropped it, "
                                      "and arm B is not padded at all"}
    if sec is None:
        return {"pass": False, "symbol_size": sym.size, "shndx": sym.shndx,
                "why": f"{PAD_SYMBOL} names section index {sym.shndx}, which is "
                       "undefined or reserved: it is a declaration, not an image"}
    ok = sec.size >= sym.size
    return {"pass": ok, "symbol_size": sym.size, "section": sec.name,
            "section_size": sec.size,
            "why": (f"{PAD_SYMBOL} is {sym.size} bytes in {sec.name} ({sec.size} bytes)"
                    if ok else
                    f"{sec.name} is {sec.size} bytes but {PAD_SYMBOL} claims {sym.size}")}


def check_b2(b: Elf64) -> dict[str, object]:
    """The padding is MAPPED — inside a PT_LOAD, not merely present in the file.

    Padding that lives in the file and outside every PT_LOAD costs a disk read
    and nothing else. Arm B would then be a large file rather than a large
    image, and would test nothing the round is asking about.
    """
    sym, sec = _padding_section(b)
    if sym is None or sec is None:
        return {"pass": False, "why": "no padding section to locate; see B1"}
    if not sec.flags & SHF_ALLOC:
        return {"pass": False, "section": sec.name, "section_flags": sec.flags,
                "why": f"{sec.name} is not SHF_ALLOC: the padding occupies file bytes "
                       "the kernel never maps, so arm B is a large file rather than a "
                       "large image"}
    lo, hi = sym.value, sym.value + sym.size
    holder = next((s for s in b.loads if s.vaddr <= lo and hi <= s.vaddr + s.memsz), None)
    if holder is None:
        near = [f"[0x{s.vaddr:x},0x{s.vaddr + s.memsz:x})" for s in b.loads]
        return {"pass": False, "section": sec.name,
                "why": f"the padding spans [0x{lo:x},0x{hi:x}) and no PT_LOAD contains "
                       f"it; segments are {near}"}
    return {"pass": True, "section": sec.name, "segment_vaddr": holder.vaddr,
            "segment_memsz": holder.memsz, "segment_flags": holder.flags,
            "why": f"the padding lies in SHF_ALLOC section {sec.name}, wholly inside "
                   f"the PT_LOAD at 0x{holder.vaddr:x} ({holder.memsz} bytes mapped)"}


def check_b3(b: Elf64, c: Elf64) -> dict[str, object]:
    """Arm B's mapped size matches arm C's to within one page.

    Mapped, not file: the file is read once and the image is mapped for the
    process's whole life, and it is the image arm B exists to imitate. File
    sizes are recorded alongside because they are cheap and someone will ask.
    """
    delta = b.mapped_bytes - c.mapped_bytes
    ok = abs(delta) <= PAGE
    return {"pass": ok, "arm_b_mapped_bytes": b.mapped_bytes,
            "arm_c_mapped_bytes": c.mapped_bytes, "delta_bytes": delta,
            "page_bytes": PAGE, "arm_b_file_bytes": len(b.data),
            "arm_c_file_bytes": len(c.data),
            "why": (f"arm B maps {b.mapped_bytes} bytes against arm C's "
                    f"{c.mapped_bytes}, a difference of {delta:+} bytes"
                    + ("" if ok else
                       f" — wider than one {PAGE}-byte page. The round STOPS for a "
                       "ruling rather than running with a mismatched arm."))}


def check_b4(a: Elf64, b: Elf64) -> dict[str, object]:
    """Arm B's work is byte-identical to arm A's.

    Raw bytes first. Where linking leaves a relocated displacement inside the
    function the bytes legitimately differ, and the preregistration permits
    falling back to address-stripped disassembly — recording WHICH test decided,
    because the two do not prove the same thing.
    """
    sa, sb = a.symbol_named(WORK_SYMBOL), b.symbol_named(WORK_SYMBOL)
    if sa is None or sb is None:
        return {"pass": False, "test": "none",
                "why": f"{WORK_SYMBOL} is missing from arm "
                       f"{'A' if sa is None else 'B'}'s symbol table"}
    if sa.size != sb.size:
        return {"pass": False, "test": "raw-bytes", "arm_a_size": sa.size,
                "arm_b_size": sb.size,
                "why": f"{WORK_SYMBOL} is {sa.size} bytes in arm A and {sb.size} in "
                       "arm B: the work is not the same work"}
    ba, bb = a.bytes_at_vaddr(sa.value, sa.size), b.bytes_at_vaddr(sb.value, sb.size)
    if ba is None or bb is None:
        return {"pass": False, "test": "raw-bytes",
                "why": f"{WORK_SYMBOL}'s bytes are not backed by file contents"}
    if ba == bb:
        return {"pass": True, "test": "raw-bytes", "size": sa.size,
                "sha256": hashlib.sha256(ba).hexdigest(),
                "why": f"{WORK_SYMBOL} is {sa.size} bytes and byte-identical in both "
                       "arms; the disassembly fallback was not needed"}
    da, db = _disassemble(a.path, sa.value, sa.size), _disassemble(b.path, sb.value, sb.size)
    ok = da is not None and da == db
    return {"pass": ok, "test": "address-stripped-disassembly",
            "arm_a_sha256": hashlib.sha256(ba).hexdigest(),
            "arm_b_sha256": hashlib.sha256(bb).hexdigest(),
            "why": (f"{WORK_SYMBOL}'s raw bytes differ, as relocation can make them; "
                    "the address-stripped disassembly is "
                    + ("identical" if ok else "NOT identical, so the work differs"))}


def _disassemble(path: Path, vaddr: int, size: int) -> list[str] | None:
    """Instruction mnemonics only, with every address and displacement dropped."""
    r = subprocess.run(["objdump", "-d", "--start-address", hex(vaddr),
                        "--stop-address", hex(vaddr + size), str(path)],
                       capture_output=True)
    if r.returncode != 0:
        return None
    out = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        if ":\t" not in line:
            continue
        body = line.split(":\t", 1)[1]
        text = body.split("\t", 1)[1] if "\t" in body else body
        out.append(text.split("#", 1)[0].split("<", 1)[0].strip())
    return out


# --- the pass --------------------------------------------------------------


def preflight(candidate: Path, out_dir: Path) -> dict[str, object]:
    try:
        arm_c = Elf64(candidate)
    except NotAnElf64 as exc:
        raise SystemExit(f"arm C is not usable: {exc}") from exc

    built = build_arms(out_dir, arm_c.mapped_bytes)
    arm_a, arm_b = Elf64(Path(str(built["arm_a"]))), Elf64(Path(str(built["arm_b"])))

    checks = {"B1": check_b1(arm_b), "B2": check_b2(arm_b),
              "B3": check_b3(arm_b, arm_c), "B4": check_b4(arm_a, arm_b)}
    failed = sorted(k for k, v in checks.items() if not v["pass"])
    return {
        "tag": TAG,
        "note": "structural preflight only; no clock was started and no timing exists",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size}
                    for p in (WORK_SOURCE, PAD_SOURCE)},
        "build": {k: v for k, v in built.items() if k != "arm_a" and k != "arm_b"},
        "arms": {
            "A": _arm_record("synth", arm_a),
            "B": _arm_record("synth-padded", arm_b),
            "C": _arm_record("core-usage (own-cli)", arm_c),
        },
        "checks": checks,
        "all_passed": not failed,
        "failed": failed,
        "verdict": ("B1-B4 all pass; the round's structural precondition holds"
                    if not failed else
                    f"STOP: {failed} failed. Arm B does not test what it exists to "
                    "test, and no timing may be taken."),
    }


def _rel(path: Path) -> str:
    """Repo-relative where possible, bare name otherwise.

    An absolute build path is a fact about one machine's temporary directory and
    would differ on every runner while claiming to identify the same binary. The
    sha256 below is the identity; this is only a label.
    """
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _arm_record(role: str, e: Elf64) -> dict[str, object]:
    return {"role": role, "name": _rel(e.path), "sha256": sha256_file(e.path),
            "file_bytes": len(e.data), "mapped_bytes": e.mapped_bytes,
            "pt_load_segments": len(e.loads)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Round 7 B1-B4 structural preflight")
    ap.add_argument("--candidate", required=True, type=Path,
                    help="arm C: the production own-cli binary")
    ap.add_argument("--out", type=Path, help="write the record here as JSON")
    ap.add_argument("--build-dir", type=Path, help="where the arms are built")
    args = ap.parse_args()

    out_dir = args.build_dir or (args.out.parent / "arms" if args.out
                                 else Path("round7-arms"))
    record = preflight(args.candidate.resolve(), out_dir)
    blob = json.dumps(record, indent=2, sort_keys=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({record['verdict']})")
    else:
        print(blob)
    return 0 if record["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
