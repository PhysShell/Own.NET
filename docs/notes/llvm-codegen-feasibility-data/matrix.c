// 2x2: {alias info} x {range checks eliminated}  ->  does LLVM -O3 vectorize?
#include <stddef.h>
void own_throw_ioor(void) __attribute__((noreturn));

// --- A: aliasing unknown, per-element range check (naive CIL lowering) ---
void a_alias_check(int *dst, const int *a, const int *b, long n, long ld, long la, long lb) {
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)la) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)lb) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)ld) own_throw_ioor();
        dst[i] = a[i] + b[i] * 3;
    }
}

// --- B: noalias, per-element range check ---
void b_noalias_check(int *restrict dst, const int *restrict a, const int *restrict b,
                     long n, long ld, long la, long lb) {
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)la) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)lb) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)ld) own_throw_ioor();
        dst[i] = a[i] + b[i] * 3;
    }
}

// --- C: aliasing unknown, checks hoisted out of the loop (frontend RCE) ---
void c_alias_nocheck(int *dst, const int *a, const int *b, long n, long ld, long la, long lb) {
    if (n > la || n > lb || n > ld) own_throw_ioor();
    for (long i = 0; i < n; i++) dst[i] = a[i] + b[i] * 3;
}

// --- D: noalias + checks hoisted ---
void d_noalias_nocheck(int *restrict dst, const int *restrict a, const int *restrict b,
                       long n, long ld, long la, long lb) {
    if (n > la || n > lb || n > ld) own_throw_ioor();
    for (long i = 0; i < n; i++) dst[i] = a[i] + b[i] * 3;
}
