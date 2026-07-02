// BUGGY — handler-use-after-dispose reached through an explicit-delegate `+=` subscription.
//
// The view owns its event source (`_source = new Publisher()`), so the subscription is NOT a
// leak (self-owned cycle, no OWN001). But the handler stays live and a late `Changed` event —
// fired after Dispose() — reads the disposed `_conn` DIRECTLY. That is a use-after-dispose
// (OWN002). The subscription is written with an explicit delegate creation
// `new EventHandler(OnSourceChanged)`: the extractor must normalize it to register `OnSourceChanged`
// as a live subscription target, else this OWN002 is missed (Codex P2 on #163).
using System;
using System.Data.SqlClient;

public sealed class SourceView : IDisposable
{
    private readonly Publisher _source;      // self-owned -> the subscription is not a leak
    private readonly SqlConnection _conn;

    public SourceView()
    {
        _source = new Publisher();
        _conn = new SqlConnection("Server=.;Database=Customers");
        _source.Changed += new EventHandler(OnSourceChanged);   // explicit delegate-creation subscription
    }

    private void OnSourceChanged(object sender, EventArgs e)
    {
        // a late event: runs after Dispose() and reads the disposed connection directly
        _conn.ChangeDatabase("customers");   // <-- use-after-dispose
    }

    public void Dispose()
    {
        _conn.Dispose();
    }
}

// Minimal in-file stand-in so the reduction is self-contained.
public sealed class Publisher { public event EventHandler Changed; }
