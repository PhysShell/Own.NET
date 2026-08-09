#include <stdlib.h>
__attribute__((noreturn)) static void own_throw_ioor(void) { abort(); }

// K2: reduction.
long sum_native(const int *restrict a, long n, long la) {
    long s = 0;
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)la) own_throw_ioor();
        s += a[i];
    }
    return s;
}

// K3: data-dependent branch -- shaped like business logic, not a math kernel.
long filter_sum_native(const int *restrict a, long n, long la, int lo, int hi) {
    long s = 0;
    for (long i = 0; i < n; i++) {
        if ((unsigned long)i >= (unsigned long)la) own_throw_ioor();
        int v = a[i];
        if (v > lo && v < hi) s += v * 2; else s -= v;
    }
    return s;
}

// K4: pointer-chasing / indirection -- the shape of object-graph traversal.
typedef struct Node { struct Node *next; long value; } Node;
long chase_native(Node *head, long n) {
    long s = 0;
    for (long i = 0; i < n && head; i++) { s += head->value; head = head->next; }
    return s;
}
