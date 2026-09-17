/* #263-A Round 6 metrology helper — CALIBRATION_ONLY.
 *
 * Deterministic work, no I/O, no allocation, no branching on data. Neither
 * Rust nor Python product code: this exists so the duration ladder measures
 * the INSTRUMENT's timed interval rather than either engine.
 *
 * Compiled rather than interpreted because the timed interval includes process
 * spawn, and a Python interpreter's floor (~11.8 ms here) sits above most of
 * the ladder. /bin/true spawns in ~1.14 ms, so a compiled helper can reach the
 * 2 ms rung that a Python one could not.
 */
#include <stdint.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    uint64_t n = strtoull(argv[1], NULL, 10);
    volatile uint64_t x = 1;
    for (uint64_t i = 0; i < n; i++) {
        x = x * 1103515245ull + 12345ull;
    }
    /* x is read so the loop cannot be optimised away; the value is discarded. */
    return (x == 0xFFFFFFFFFFFFFFFFull) ? 1 : 0;
}
