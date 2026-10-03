using System;

namespace OrderBackend.Domain;

// The Typed Builder vocabulary. Matched by NAME — by the generator
// (frontend/roslyn/Own.TypedBuilder) and by the Own.NET extractor — so the domain depends on
// neither of them.

/// The entity whose state protocol is generated. A `partial class`.
[AttributeUsage(AttributeTargets.Class)]
public sealed class TypedProtocolAttribute : Attribute
{
}

/// The one property that holds the state. Its enum's first member is the initial state.
[AttributeUsage(AttributeTargets.Property)]
public sealed class ProtocolStateAttribute : Attribute
{
}

/// A field the builder demands before Build() exists.
[AttributeUsage(AttributeTargets.Property)]
public sealed class BuilderRequiredAttribute : Attribute
{
}

/// A transition: its name, the state it leaves, the state it enters. On a non-public hook
/// that writes the transition's data; the state itself is written by generated code.
[AttributeUsage(AttributeTargets.Method)]
public sealed class TransitionAttribute(string name, object from, object to) : Attribute
{
    public string Name { get; } = name;

    public object From { get; } = from;

    public object To { get; } = to;
}

/// A state: a ref struct over the entity (Own.NET state-protocol profile).
[AttributeUsage(AttributeTargets.Struct)]
public sealed class ProtocolTokenAttribute : Attribute
{
}

/// A region entry: (entity, callback) (Own.NET state-protocol profile).
[AttributeUsage(AttributeTargets.Method)]
public sealed class ProtocolRegionAttribute : Attribute
{
}
