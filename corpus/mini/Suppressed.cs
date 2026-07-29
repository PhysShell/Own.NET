using System;

namespace Own.Corpus.Mini;

// AN IN-SOURCE SUPPRESSION. The leak is real and the decision to accept it is
// documented: `[OwnIgnore("reason")]` on the field. The core still MINTS the
// finding and marks it suppressed — excluded from the exit code and the human
// stream, still counted, and carried in SARIF `suppressions` (visibility over
// silence, never a silent drop).
//
// Frozen here for the same reason as the advisory: the suppressed population lives
// in the coverage ledger, not in `findings`, so a vanished suppression is only
// visible through the census comparison.
public sealed class SuppressedFieldLeak
{
    [OwnIgnore("owned by the host process; disposed at shutdown")]
    private readonly Handle _handle = new Handle();

    public bool Open => _handle.IsOpen;
}

// CONTROL: a reason-less [OwnIgnore] must NOT suppress — a suppression without a
// documented reason is never a silent accept. This one still fires.
public sealed class ReasonlessIgnore
{
    [OwnIgnore]
    private readonly Handle _handle = new Handle();

    public bool Open => _handle.IsOpen;
}
