/* #263-A Round 7 arm B padding — CALIBRATION_ONLY.
 *
 * Arm B is arm A's work plus an inert image. This translation unit carries the
 * image and nothing else: it defines no function, runs no code, and is never
 * referenced by the work. The whole point is that arm B does exactly what arm A
 * does while being as large as own-cli.
 *
 * const  -> .rodata, so the padding is mapped read-only like a real image's
 *           text and constants rather than landing in a writable segment.
 * volatile + external linkage -> neither the compiler nor --gc-sections may
 *           decide an unreferenced constant array is dead. B1 checks that this
 *           worked rather than trusting it.
 * = { 1 } -> one non-zero element, so the array cannot be moved to .bss. A .bss
 *           array occupies no file bytes and would make arm B a large PROMISE
 *           of an image rather than an image.
 *
 * The element count is supplied at build time and recorded in the preflight,
 * because it is tuned to match own-cli's mapped size and that target will move
 * whenever own-cli does.
 */
#include <stdint.h>

#ifndef OWN_ROUND7_PAD_ELEMENTS
#error "OWN_ROUND7_PAD_ELEMENTS must be supplied by the preflight"
#endif

const volatile uint64_t own_round7_padding[OWN_ROUND7_PAD_ELEMENTS] = { 1 };
