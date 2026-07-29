using System;
using System.IO;

// Own.NET#317 - the extractor's source COLUMN, and the one property that proves it is
// a real coordinate rather than decoration: TWO anchor sites on ONE line.
//
// Every other sample in this directory puts one finding on one line, so a `column` that
// was always 1, or always the indentation, or always the first site's, would pass all of
// them. Here each pair shares a line and differs only in column, so a column that does
// not come from the right node collapses two findings into one (the bridge's dedupe key
// carries `column` exactly so it cannot) or points at the wrong site.
//
// PLAIN ASCII SPACES ONLY, and no non-ASCII anywhere in this file. Roslyn's
// `LinePosition.Character` counts UTF-16 code units from the line start, expanding no
// tabs and folding no surrogate pairs, so a tab or an astral character would make the
// expected columns a statement about this file's byte layout rather than about the
// extractor. tests/test_extractor_columns.py asserts that too, before it asserts
// anything else.
public class ColumnAnchorsSample
{
    public event EventHandler? Alpha;
    public event EventHandler? Beta;

    // Two `+=` on one line, neither ever `-=`'d -> two OWN001 subscription leaks. The
    // record anchors on the EVENT ACCESS (`src.Alpha` / `src.Beta`), which is the node
    // the extractor has always taken `line` from - not the statement, and not `+=`.
    // `src` is a parameter, so the source is `injected` and both are warnings.
    public void SubscribeBoth(ColumnAnchorsSample src)
    {
        src.Alpha += OnAlpha; src.Beta += OnBeta;
    }

    private void OnAlpha(object? sender, EventArgs e) { }

    private void OnBeta(object? sender, EventArgs e) { }

    // Two undisposed IDisposable locals on one line. Neither is `using`-guarded, neither
    // escapes (`first.Length` reads THROUGH the local; the identifier's parent is the
    // member access, not the return), and neither is disposed - so both leak, in both
    // extractor modes:
    //
    //   * without --flow-locals the D1 detector emits two `local-disposable` records,
    //     each anchored on its own declarator;
    //   * with --flow-locals the flow pass emits two `acquire` ops instead, again one
    //     per declarator, and the core reports OWN001 at the acquire.
    //
    // Both modes are exercised, because the two paths mint their coordinate in different
    // code and only one of them was on the obvious route.
    public long TwoLeaksOneLine()
    {
        var first = new MemoryStream(); var second = new MemoryStream();
        first.WriteByte(1);
        second.WriteByte(2);
        return first.Length + second.Length;
    }
}
