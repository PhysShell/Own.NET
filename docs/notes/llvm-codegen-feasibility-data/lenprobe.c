// Isolate the real blocker: is it aliasing, the range check, or the fact that
// `ldlen` is a MEMORY LOAD inside the loop (array length not known immutable)?
#include <stddef.h>
void own_throw_ioor(void) __attribute__((noreturn));
typedef struct { long len; int data[]; } Arr;   // a .NET array object

// 1. length reloaded from the object header every iteration, no alias info.
//    This is what a naive CIL->LLVM frontend emits for ldlen.
void p1_reload_alias(Arr *dst, Arr *a, Arr *b, long n) {
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)a->len)   own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)b->len)   own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)dst->len) own_throw_ioor();
        dst->data[i] = a->data[i] + b->data[i] * 3;
    }
}

// 2. same, but the three objects are known distinct (type-safety / ownership).
void p2_reload_noalias(Arr *restrict dst, Arr *restrict a, Arr *restrict b, long n) {
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)a->len)   own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)b->len)   own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)dst->len) own_throw_ioor();
        dst->data[i] = a->data[i] + b->data[i] * 3;
    }
}

// 3. lengths hoisted once (frontend knows array length is IMMUTABLE), aliasing
//    still unknown, per-element range check kept.
void p3_hoistlen_alias(Arr *dst, Arr *a, Arr *b, long n) {
    long la = a->len, lb = b->len, ld = dst->len;
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)la) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)lb) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)ld) own_throw_ioor();
        dst->data[i] = a->data[i] + b->data[i] * 3;
    }
}

// 4. lengths hoisted + noalias.
void p4_hoistlen_noalias(Arr *restrict dst, Arr *restrict a, Arr *restrict b, long n) {
    long la = a->len, lb = b->len, ld = dst->len;
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)la) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)lb) own_throw_ioor();
        if ((unsigned long)i >= (unsigned long)ld) own_throw_ioor();
        dst->data[i] = a->data[i] + b->data[i] * 3;
    }
}
