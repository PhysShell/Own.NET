// Native side of the RyuJIT-vs-LLVM comparison. Same kernel, same semantics
// (per-element range check that traps), compiled by clang -O3.
#include <stdlib.h>
#include <stdint.h>

__attribute__((noreturn)) static void own_throw_ioor(void) { abort(); }

// noalias + lengths hoisted (the "frontend knows array length is immutable"
// variant that LLVM vectorizes).
void axpy_noalias(int *restrict dst, const int *restrict a, const int *restrict b,
                  long n, long ld, long la, long lb) {
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)la) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)lb) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)ld) own_throw_ioor();
        dst[i] = a[i] + b[i] * 3;
    }
}

// same, but aliasing unknown -> LLVM emits a runtime alias check + versioned loop.
void axpy_alias(int *dst, const int *a, const int *b,
                long n, long ld, long la, long lb) {
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)la) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)lb) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)ld) own_throw_ioor();
        dst[i] = a[i] + b[i] * 3;
    }
}
