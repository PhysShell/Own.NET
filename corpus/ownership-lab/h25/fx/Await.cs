using System;
using System.Threading.Tasks;
using RLibA;
// H-25 await-wrapped acquire recognition: positive forms and hostile twins, frozen BEFORE any code (h25-prereg-v1.json).
// FA.FactoryAsync / FA.FactoryValueTaskAsync carry trusted rows (the LOGICAL result is fresh owned); BorrowedAsync,
// CachedAsync, UnknownAsync carry none. Expected classifications are in the prereg, not here. Census only: no lowering.
public static class Positive
{
    // AW1: Task<R> awaited in an existing-local assignment
    public static async Task AW1_task_assignment() { R x = null; x = await FA.FactoryAsync(); x.Ping(); x.Dispose(); }
    // AW2: the same through ConfigureAwait(false)
    public static async Task AW2_configure_await() { R x = null; x = await FA.FactoryAsync().ConfigureAwait(false); x.Ping(); x.Dispose(); }
    // AW3: ValueTask<R>
    public static async Task AW3_valuetask() { R x = null; x = await FA.FactoryValueTaskAsync(); x.Ping(); x.Dispose(); }
    // AW4: declaration form `var x = await FactoryAsync()`
    public static async Task AW4_declaration() { var x = await FA.FactoryAsync(); x.Ping(); x.Dispose(); }
    // AW5: declaration form through ConfigureAwait
    public static async Task AW5_declaration_configure_await() { var x = await FA.FactoryAsync().ConfigureAwait(false); x.Ping(); }
    // AW6: the try/finally initialisation idiom with an awaited trusted factory (the dominant population shape)
    public static async Task AW6_try_finally() { R x = null; try { x = await FA.FactoryAsync(); x.Ping(); } finally { x?.Dispose(); } }
}
public static class Hostile
{
    // HW1: the task is stored first and awaited later: the Task<R> local is NOT an R acquire; the obligation belongs to the awaited R
    public static async Task HW1_deferred_await() { var task = FA.FactoryAsync(); var x = await task; x.Ping(); }
    // HW2: awaited result is borrowed (no row): no acquire
    public static async Task HW2_borrowed() { R x = null; x = await FA.BorrowedAsync(); x.Ping(); }
    // HW3: awaited result is cached (no row): no acquire
    public static async Task HW3_cached() { R x = null; x = await FA.CachedAsync(); x.Ping(); }
    // HW4: Task without a resource result: nothing is written
    public static async Task HW4_fire_and_forget() { await FA.FireAndForgetAsync(); }
    // HW5: fresh in fact but NO row: must not be an acquire (the effect comes only from a trusted row)
    public static async Task HW5_unknown() { R x = null; x = await FA.UnknownAsync(); x.Ping(); }
    // HW6: the sync twin name has no row either; a name-based `Async` strip must never mint
    public static async Task HW6_name_twin() { R x = null; x = await FA.BorrowedTwinAsync(); x.Ping(); }
    // HW7: awaited result assigned to a field: an escape, classified only
    static R _f;
    public static async Task HW7_field_store() { _f = await FA.FactoryAsync(); }
    // HW8: `await using` declaration of an awaited factory: a using shape, classified only
    public static async Task HW8_using_declaration() { using var x = await FA.FactoryAsync(); x.Ping(); }
}
