#include <stdlib.h>
__attribute__((noreturn)) static void own_throw_ioor(void) { abort(); }
// same kernels, but the range check is hoisted out of the loop (frontend RCE)
long sum_free(const int *restrict a, long n, long la) {
    if (n > la) own_throw_ioor();
    long s = 0; for (long i = 0; i < n; i++) s += a[i]; return s;
}
long filter_sum_free(const int *restrict a, long n, long la, int lo, int hi) {
    if (n > la) own_throw_ioor();
    long s = 0;
    for (long i = 0; i < n; i++) { int v = a[i]; if (v > lo && v < hi) s += v*2; else s -= v; }
    return s;
}
