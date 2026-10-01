using System;
using System.Data;
using System.IO;
using System.Threading.Tasks;
// H-28 fixture: the three hostile anchors (external DataTable.Load witnessed RELEASE; a wrapper ADOPT; Close(s) RELEASE) and their twins; the method name carries the expectation.
public sealed class Wrapper : IDisposable { readonly Stream _s; public Wrapper(Stream s) { _s = s; } public void Dispose() => _s.Dispose(); }
public static class Callees
{
    public static void Close(Stream s) { s.Dispose(); }                                              // RELEASE_ALL_PATHS
    public static bool Close2(Stream s) { s.Dispose(); return true; }                                // RELEASE_ALL_PATHS (non-statement caller form)
    public static async Task CloseAsync(Stream s) { await s.DisposeAsync(); }                        // RELEASE_ALL_PATHS
    public static void CloseInFinally(Stream s) { try { s.Flush(); } finally { s.Dispose(); } }     // RELEASE_ALL_PATHS (finally)
    public static void CloseConditional(Stream s) { s?.Dispose(); }                                  // RELEASE_ALL_PATHS (conditional access at top level)
    public static void MaybeClose(Stream s, bool b) { if (b) s.Dispose(); }                          // RELEASE_SOME_PATH
    public static void UsingIt(Stream s) { using (s) { s.Flush(); } }                                // RELEASE_ALL_PATHS (using statement on the parameter)
    public static Stream Identity(Stream s) => s;                                                    // ALIAS_TO_RESULT
    public static Stream Wrap(Stream s) => new BufferedStream(s);                                    // ALIAS_TO_RESULT (wrapped)
    public static void Forward(Stream s) => Close(s);                                                // FORWARD -> Close
    public static long Use(Stream s) => s.Length;                                                    // BORROW
    public static void Ignore(Stream s) { }                                                          // UNUSED
    public static Stream _kept; public static void Keep(Stream s) { _kept = s; }                     // ADOPT (static field store)
}
public class Caller
{
    Stream _f; Wrapper _w;
    public void N01_borrow_nothing() { var s = new FileStream("x", FileMode.Open); Callees.Use(s); }                        // ESCAPE_UNTRACKED | NOTHING | BORROW  <- the primary shape
    public void N02_release_statement() { var s = new FileStream("x", FileMode.Open); Callees.Close(s); }                   // EXEMPT_CONSUMED | NOTHING | RELEASE_ALL_PATHS
    public void N03_release_nonstatement() { var s = new FileStream("x", FileMode.Open); var ok = Callees.Close2(s); }      // ESCAPE_UNTRACKED | NOTHING | RELEASE_ALL_PATHS
    public void N04_adopt_bounded_wrapper() { var s = new FileStream("x", FileMode.Open); var w = new Wrapper(s); w.Dispose(); }   // EXEMPT_ADOPTED_WRAPPER | NOTHING | ADOPT
    public void N05_adopt_stored_wrapper() { var s = new FileStream("x", FileMode.Open); _w = new Wrapper(s); }             // ESCAPE_UNTRACKED | NOTHING | ADOPT
    public Stream N06_alias() { var s = new FileStream("x", FileMode.Open); return Callees.Identity(s); }                   // ESCAPE_UNTRACKED | NOTHING | ALIAS_TO_RESULT
    public Stream N06b_alias_wrapped() { var s = new FileStream("x", FileMode.Open); return Callees.Wrap(s); }              // ESCAPE_UNTRACKED | NOTHING | ALIAS_TO_RESULT
    public void N07_forward() { var s = new FileStream("x", FileMode.Open); Callees.Forward(s); }                           // ? | NOTHING | FORWARD (to Close)
    public void N08_unused() { var s = new FileStream("x", FileMode.Open); Callees.Ignore(s); }                             // ESCAPE_UNTRACKED | NOTHING | UNUSED
    public void N09_borrow_then_dispose() { var s = new FileStream("x", FileMode.Open); Callees.Use(s); s.Dispose(); }      // ESCAPE_UNTRACKED | RELEASE_CALL | BORROW
    public Stream N10_borrow_then_return() { var s = new FileStream("x", FileMode.Open); Callees.Use(s); return s; }        // ESCAPE_UNTRACKED | RETURNED | BORROW
    public void N11_borrow_then_store() { var s = new FileStream("x", FileMode.Open); Callees.Use(s); _f = s; }             // ESCAPE_UNTRACKED | STORED | BORROW
    public void N12_external_borrow() { var s = new FileStream("x", FileMode.Open); Console.WriteLine(s); }                 // ESCAPE_UNTRACKED | NOTHING | EXTERNAL_UNKNOWN
    public void N13_external_datatable_load() { var r = new DataTableReader(new DataTable()); var t = new DataTable(); t.Load(r); }   // ESCAPE_UNTRACKED | NOTHING | EXTERNAL_UNKNOWN (witnessed table: RELEASE_IF_LAST_RESULT_SET)
    public void N14_adopt_static_field() { var s = new FileStream("x", FileMode.Open); Callees.Keep(s); }                   // ? | NOTHING | ADOPT
    public void N15_some_path() { var s = new FileStream("x", FileMode.Open); Callees.MaybeClose(s, true); }                // ? | NOTHING | RELEASE_SOME_PATH
    public async Task N16_release_async() { var s = new FileStream("x", FileMode.Open); await Callees.CloseAsync(s); }      // ESCAPE_UNTRACKED | NOTHING | RELEASE_ALL_PATHS (await form is not a bare statement call)
    public void N17_release_finally() { var s = new FileStream("x", FileMode.Open); Callees.CloseInFinally(s); }            // ? | NOTHING | RELEASE_ALL_PATHS
    public void N18_release_conditional() { var s = new FileStream("x", FileMode.Open); Callees.CloseConditional(s); }      // ? | NOTHING | RELEASE_ALL_PATHS
    public void N19_release_using_param() { var s = new FileStream("x", FileMode.Open); Callees.UsingIt(s); }               // ? | NOTHING | RELEASE_ALL_PATHS
    public void N20_closure_capture() { var s = new FileStream("x", FileMode.Open); Action a = () => Callees.Use(s); a(); } // not recorded (closure capture escapes before the argument rule)
    public void N21_using_local_borrow() { using var s = new FileStream("x", FileMode.Open); Callees.Use(s); }               // a using local: not a candidate of the escape loop (expected absent)
    public void N22_named_arg() { var s = new FileStream("x", FileMode.Open); Callees.MaybeClose(b: false, s: s); }         // named argument -> parameter by name
}
