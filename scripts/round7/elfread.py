#!/usr/bin/env python3
"""A minimal ELF64 reader for the Round 7 structural preflight — CALIBRATION_ONLY.

Why parse the file rather than shell out to readelf: the preflight's whole job
is to prove a structural claim about a linked binary, and a check that greps a
tool's prose is reading a rendering of the thing rather than the thing. The
fields below are read from the actual headers. It also keeps binutils off the
dependency list for everything except B4's disassembly fallback, which genuinely
needs a disassembler.

Deliberately partial: 64-bit little-endian only, and only the structures B1-B4
need. An ELF this does not understand is REFUSED rather than guessed at.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

PT_LOAD = 1
SHT_SYMTAB = 2
SHT_NOBITS = 8


class NotAnElf64(Exception):
    """The file is not a little-endian 64-bit ELF, so nothing below applies."""


@dataclass(frozen=True)
class Section:
    name: str
    sh_type: int
    flags: int
    addr: int
    offset: int
    size: int


@dataclass(frozen=True)
class Segment:
    p_type: int
    flags: int
    offset: int
    vaddr: int
    filesz: int
    memsz: int
    align: int


@dataclass(frozen=True)
class Symbol:
    name: str
    value: int
    size: int
    shndx: int


class Elf64:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()
        if self.data[:4] != b"\x7fELF":
            raise NotAnElf64(f"{path}: no ELF magic")
        if self.data[4] != 2 or self.data[5] != 1:
            raise NotAnElf64(f"{path}: not 64-bit little-endian (class={self.data[4]}, "
                             f"data={self.data[5]})")
        (self.e_phoff, self.e_shoff) = struct.unpack_from("<QQ", self.data, 0x20)
        (self.e_phentsize, self.e_phnum, self.e_shentsize, self.e_shnum,
         self.e_shstrndx) = struct.unpack_from("<HHHHH", self.data, 0x36)
        self.segments = tuple(self._segments())
        self.sections = tuple(self._sections())
        self.symbols = tuple(self._symbols())

    # -- program headers ---------------------------------------------------

    def _segments(self) -> list[Segment]:
        out = []
        for i in range(self.e_phnum):
            off = self.e_phoff + i * self.e_phentsize
            p_type, flags = struct.unpack_from("<II", self.data, off)
            offset, vaddr, _paddr, filesz, memsz, align = struct.unpack_from(
                "<QQQQQQ", self.data, off + 8)
            out.append(Segment(p_type, flags, offset, vaddr, filesz, memsz, align))
        return out

    @property
    def loads(self) -> tuple[Segment, ...]:
        return tuple(s for s in self.segments if s.p_type == PT_LOAD)

    @property
    def mapped_bytes(self) -> int:
        """Summed p_memsz of every PT_LOAD — what the kernel must map.

        The mapped size, not the file size, is what B3 compares: a file is read
        from disk once and an image is mapped for the process's whole life.
        """
        return sum(s.memsz for s in self.loads)

    # -- section headers ---------------------------------------------------

    def _raw_sections(self) -> list[tuple[int, int, int, int, int, int]]:
        out = []
        for i in range(self.e_shnum):
            off = self.e_shoff + i * self.e_shentsize
            sh_name, sh_type, flags, addr, offset, size = struct.unpack_from(
                "<IIQQQQ", self.data, off)
            out.append((sh_name, sh_type, flags, addr, offset, size))
        return out

    def _sections(self) -> list[Section]:
        raw = self._raw_sections()
        if not raw:
            return []
        strtab_off, strtab_size = raw[self.e_shstrndx][4], raw[self.e_shstrndx][5]
        blob = self.data[strtab_off:strtab_off + strtab_size]

        def name_at(i: int) -> str:
            end = blob.find(b"\x00", i)
            return blob[i:end].decode("utf-8", "replace")

        return [Section(name_at(n), t, f, a, o, s) for n, t, f, a, o, s in raw]

    def section_named(self, name: str) -> Section | None:
        return next((s for s in self.sections if s.name == name), None)

    def section_index_of_addr(self, addr: int) -> int | None:
        for i, s in enumerate(self.sections):
            if s.addr and s.addr <= addr < s.addr + s.size:
                return i
        return None

    # -- symbols -----------------------------------------------------------

    def _symbols(self) -> list[Symbol]:
        symtab = next((i for i, s in enumerate(self.sections) if s.sh_type == SHT_SYMTAB),
                      None)
        if symtab is None:
            return []                       # stripped; B1 and B4 will say so
        raw = self._raw_sections()
        link = struct.unpack_from("<I", self.data,
                                  self.e_shoff + symtab * self.e_shentsize + 0x28)[0]
        str_off, str_size = raw[link][4], raw[link][5]
        blob = self.data[str_off:str_off + str_size]
        sec = self.sections[symtab]
        out = []
        for off in range(sec.offset, sec.offset + sec.size, 24):
            st_name, _info, _other, shndx, value, size = struct.unpack_from(
                "<IBBHQQ", self.data, off)
            end = blob.find(b"\x00", st_name)
            out.append(Symbol(blob[st_name:end].decode("utf-8", "replace"),
                              value, size, shndx))
        return out

    def symbol_named(self, name: str) -> Symbol | None:
        return next((s for s in self.symbols if s.name == name), None)

    def bytes_at_vaddr(self, vaddr: int, size: int) -> bytes | None:
        """File bytes backing a virtual address range, or None if not backed.

        .bss has an address and no bytes; asking for its contents must return
        nothing rather than whatever happens to sit at that file offset.
        """
        i = self.section_index_of_addr(vaddr)
        if i is None:
            return None
        sec = self.sections[i]
        if sec.sh_type == SHT_NOBITS or vaddr + size > sec.addr + sec.size:
            return None
        start = sec.offset + (vaddr - sec.addr)
        return self.data[start:start + size]
