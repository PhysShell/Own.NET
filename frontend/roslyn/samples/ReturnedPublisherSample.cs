using System;

// #146 — interprocedural "constructed-and-returned" publisher provenance.
//
// A `+=` on a PARAMETER publisher is tiered `injected` (unknown lifetime ->
// OWN001 warning) because inside the method a DI singleton bus and a
// caller-owned fresh publisher look identical. The compilation-wide provenance
// pass proves the bounded case: when EVERY visible caller passes a publisher it
// freshly constructs and lets escape only into the call / its own `return`, the
// handler dies with the returned publisher -> `source_provenance:
// "returned_fresh"` -> the bridge drops it (SILENT). Mined shape: Newtonsoft
// `JsonSerializer.Create` -> `ApplySerializerSettings` (field-notes #7).
//
// Every OTHER class in this file is a deliberate denial case and must KEEP the
// honest OWN001 warning: same param->param syntax, but the proof fails.

public class ProvPublisher
{
    public event EventHandler? Error;    // bounded case (silent)
    public event EventHandler? Faulted;  // public candidate (warning)
    public event EventHandler? Mixed;    // mixed callers (warning)
    public event EventHandler? Stored;   // field-stored fresh local (warning)
    public event EventHandler? Deferred; // callee-side local-function capture (warning)
    public event EventHandler? Later;    // caller-side local-function capture (warning)
}

public class ProvSettings
{
    public EventHandler? Error;
}

public class ProvBus
{
    public event EventHandler? Changed;  // param->param DI shape (warning)
}

// BOUNDED (silent): the Newtonsoft shape. `Create` constructs the publisher,
// hands it to a private helper that subscribes, and returns it — the handler
// lives exactly as long as the serializer the caller now holds.
public static class ProvFactory
{
    public static ProvPublisher Create(ProvSettings? settings)
    {
        var publisher = new ProvPublisher();
        if (settings != null) ApplyBounded(publisher, settings);
        return publisher;
    }

    private static void ApplyBounded(ProvPublisher publisher, ProvSettings settings)
    {
        if (settings.Error != null)
            publisher.Error += settings.Error;   // provenance proven -> SILENT
    }
}

// PUBLIC candidate (warning stays): same body, but the subscribing method is
// public — a caller outside this compilation could pass anything, so the
// caller audit can never be complete.
public static class ProvPublicFactory
{
    public static ProvPublisher CreatePublic(ProvSettings settings)
    {
        var pub = new ProvPublisher();
        ApplyPublic(pub, settings);
        return pub;
    }

    public static void ApplyPublic(ProvPublisher pub, ProvSettings settings)
    {
        pub.Faulted += settings.Error;           // stays the OWN001 warning
    }
}

// MIXED callers (warning stays): one caller passes a fresh local, another
// passes a long-lived FIELD — the field caller breaks the every-caller proof.
public class ProvMixedFactory
{
    private readonly ProvPublisher _shared = new ProvPublisher();

    public static ProvPublisher CreateMixed(ProvSettings settings)
    {
        var fresh = new ProvPublisher();
        ApplyMixed(fresh, settings);
        return fresh;
    }

    public void WireShared(ProvSettings settings) => ApplyMixed(_shared, settings);

    private static void ApplyMixed(ProvPublisher target, ProvSettings settings)
    {
        target.Mixed += settings.Error;          // stays the OWN001 warning
    }
}

// FIELD-STORED fresh local (warning stays): the caller constructs the publisher
// but ALSO parks it in a static field before the call — it escapes beyond the
// return, so "dies with the returned object" is no longer provable.
public static class ProvStoredFactory
{
    private static ProvPublisher? _cached;

    public static ProvPublisher CreateStored(ProvSettings settings)
    {
        var made = new ProvPublisher();
        _cached = made;
        ApplyStored(made, settings);
        return made;
    }

    private static void ApplyStored(ProvPublisher stored, ProvSettings settings)
    {
        stored.Stored += settings.Error;         // stays the OWN001 warning
    }
}

// CALLEE-SIDE LOCAL-FUNCTION CAPTURE (warning stays; Codex P2 regression): the
// `+=` sits inside a local function that captures the publisher parameter and is
// STORED into a delegate field — the closure can run from a longer-lived root
// after the call returns, so the parameter escaped and provenance must deny.
public static class ProvLocalFuncFactory
{
    private static Action? _pending;

    public static ProvPublisher CreateDeferred(ProvSettings settings)
    {
        var fresh = new ProvPublisher();
        ApplyDeferred(fresh, settings);
        return fresh;
    }

    private static void ApplyDeferred(ProvPublisher deferred, ProvSettings settings)
    {
        void Later() { deferred.Deferred += settings.Error; }  // captures the param
        _pending = Later;                        // closure escapes -> deny
    }
}

// CALLER-SIDE LOCAL-FUNCTION CAPTURE (warning stays; Codex P2 regression): the
// fresh local is passed to the audited helper FROM a stored local function — the
// closure may run after `made` escaped, so the target-argument use inside it
// must deny the "bounded" proof.
public static class ProvCallerLocalFuncFactory
{
    private static Action? _wire;

    public static ProvPublisher CreateLater(ProvSettings settings)
    {
        var made = new ProvPublisher();
        void Wire() => ApplyLater(made, settings);   // capture of the fresh local
        _wire = Wire;                                // closure escapes -> deny
        return made;
    }

    private static void ApplyLater(ProvPublisher later, ProvSettings settings)
    {
        later.Later += settings.Error;           // stays the OWN001 warning
    }
}

// PARAM->PARAM (warning stays) — the DUAL this feature must never silence: the
// caller forwards ITS OWN parameter (e.g. a DI-injected bus), not a fresh
// local. If `bus` is a singleton this is a genuine subscription leak.
public class ProvBusWiring
{
    public void Attach(ProvBus bus)
    {
        Wire(bus);
    }

    private void Wire(ProvBus bus)
    {
        bus.Changed += OnChanged;                // stays the OWN001 warning
    }

    private void OnChanged(object? sender, EventArgs e) { }
}
