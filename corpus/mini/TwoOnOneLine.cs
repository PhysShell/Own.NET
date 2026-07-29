using System;

namespace Own.Corpus.Mini;

// THE CASE A COLUMN EXISTS FOR. Two DIFFERENT subscriptions on ONE physical line.
//
// With a line-only anchor these two findings sit at the same coordinate and are
// told apart only by their messages. With a column they are told apart by where
// they are, which is what a physical anchor is supposed to do. Two properties of
// the differential rest on this file:
//
//   * the two columns must be DIFFERENT. If both came back as the same number the
//     coordinate is decoration, and `fabricated_column_collision` fires.
//   * neither may become 1. A column that is the line's indentation rather than the
//     expression's position is the caret heuristic leaking into an anchor, and
//     `fabricated_column_uniform` is the corpus-scale version of that check.
//
// Formatted deliberately: two statements, one line, neither at the line start.
public sealed class TwoLeaksOneLine
{
    public TwoLeaksOneLine(IEventBus bus)
    {
        bus.CustomerChanged += OnCustomer; bus.OrdersChanged += OnOrders;
    }

    private void OnCustomer(object? sender, EventArgs e) { }
    private void OnOrders(object? sender, EventArgs e) { }
}

// The SAME event and the SAME handler twice on one line. These two collapse into
// one finding by design: the dedup keys on the pattern-level identity and NOT on the
// column, precisely so that adding a column cannot change the finding population.
// If this file ever starts producing two findings here, the anchor slice has quietly
// become a multiplicity change.
public sealed class SameLeakTwiceOneLine
{
    public SameLeakTwiceOneLine(IEventBus bus)
    {
        bus.CustomerChanged += OnCustomer; bus.CustomerChanged += OnCustomer;
    }

    private void OnCustomer(object? sender, EventArgs e) { }
}
