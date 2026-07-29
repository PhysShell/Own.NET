using System;

namespace Own.Corpus.Mini;

// THE SAME LEAK AT FOUR DIFFERENT INDENTATION DEPTHS.
//
// This file exists to catch one specific wrong answer. `Diagnostic._caret_col` — the
// renderer's caret heuristic — falls back to the line's INDENTATION when it cannot
// locate an identifier. A column sourced from that heuristic instead of from the
// syntax location would be "one past the leading whitespace", which is a plausible
// number, is different on every line here, and is WRONG.
//
// The corpus catches it because the real column of `bus.CustomerChanged` is the
// indentation plus zero only when the subscription starts the line. Wrap it in an
// `if` and the two diverge; nest it twice and they diverge further. A fixture with
// one indentation level cannot distinguish the two answers at all.
public sealed class IndentationDepths
{
    public IndentationDepths(IEventBus bus, bool flag, bool other)
    {
        bus.CustomerChanged += OnA;

        if (flag)
        {
            bus.CustomerChanged += OnB;
        }

        if (flag)
        {
            if (other)
            {
                bus.CustomerChanged += OnC;
            }
        }

        // Not at the start of its line: the column of the subscription is well past
        // the indentation, so an indentation-derived column is off by the width of
        // everything before it.
        if (flag) { bus.CustomerChanged += OnD; }
    }

    private void OnA(object? sender, EventArgs e) { }
    private void OnB(object? sender, EventArgs e) { }
    private void OnC(object? sender, EventArgs e) { }
    private void OnD(object? sender, EventArgs e) { }
}
