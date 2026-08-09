# Harness for `../llvm-codegen-feasibility.md`

Reproduces every number in the note. Requires `clang` (tested 18.1.3), the
.NET SDK 9 (tested 9.0.316), and an x86-64-v3 CPU.

```console
$ ./run.sh [workdir]
```

| File | Role |
|---|---|
| `lenprobe.c` | 2x2: array length re-loaded vs hoisted, x aliasing unknown vs `restrict` |
| `matrix.c` | 2x2: aliasing x range-check-eliminated, lengths passed as arguments |
| `checkfree.c` | the K2/K3 kernels with the range check hoisted out of the loop |
| `native.c` | K1 (`dst[i] = a[i] + b[i]*3`), noalias and aliasing variants |
| `native2.c` | K2 reduction, K3 data-dependent branch, K4 pointer chase |
| `Program.cs` | K1 harness: RyuJIT scalar / `Vector256` / `Vector256` x4 / native |
| `Kernels.cs` | K2-K4 harness, incl. the correctness gate across all K3 variants |

Two things the harness enforces on purpose, both because they were got wrong
first (see "Two measurement traps" in the note):

- **`DOTNET_TieredCompilation=0` plus a 5000-call warmup.** A short warmup
  measures partly-tier-0 code and inflates LLVM's advantage by ~40%.
- **A correctness gate.** All K3 variants must return `25830282`; an unequal
  accumulator width silently makes one variant do less work.
