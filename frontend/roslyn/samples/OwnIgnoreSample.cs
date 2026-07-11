using System;

namespace Own.Samples;

// Issue #209 — [OwnIgnore("reason")] per-site suppression (P-004), on an IDisposable field.
// The reason string is MANDATORY by design: a suppression is a documented decision, never a
// silent one. Three contrasting shapes prove the contract end to end:
//   - UnsuppressedLeak   : the plain leak, no attribute            -> OWN001 fires (control)
//   - SuppressedLeak     : same leak + [OwnIgnore("reason")]       -> silent-but-COUNTED
//                                                                      (SARIF `suppressions`),
//                                                                      never fails the run
//   - ReasonlessLeak     : [OwnIgnore] with no reason              -> must NOT suppress (fires)
//   - EmptyReasonLeak    : [OwnIgnore("")]                         -> must NOT suppress (fires)
//
// The attribute is matched by SIMPLE name, so a project may declare its own; this sample
// declares a local one (two ctors) so all four shapes compile.

[AttributeUsage(AttributeTargets.Field | AttributeTargets.Property
              | AttributeTargets.Method | AttributeTargets.Class, AllowMultiple = false)]
public sealed class OwnIgnoreAttribute : Attribute
{
    public OwnIgnoreAttribute() { }
    public OwnIgnoreAttribute(string reason) { Reason = reason; }
    public string? Reason { get; }
}

// A plain owned IDisposable — no BCL special-casing, so it is an unambiguous OWN001.
public sealed class Handle : IDisposable
{
    public void Dispose() { }
}

// CONTROL: a `new`'d IDisposable field never disposed -> OWN001 fires.
public sealed class UnsuppressedLeak
{
    private readonly Handle _h = new Handle();
}

// SUPPRESSED: the same leak, but a documented [OwnIgnore("reason")] -> silent-but-counted.
public sealed class SuppressedLeak
{
    [OwnIgnore("owned and disposed by the DI container, not by this type")]
    private readonly Handle _h = new Handle();
}

// REASON-LESS: [OwnIgnore] carries no reason -> must NOT suppress (never a silent accept).
public sealed class ReasonlessLeak
{
    [OwnIgnore]
    private readonly Handle _h = new Handle();
}

// EMPTY REASON: [OwnIgnore("")] is not a documented decision -> must NOT suppress.
public sealed class EmptyReasonLeak
{
    [OwnIgnore("")]
    private readonly Handle _h = new Handle();
}
