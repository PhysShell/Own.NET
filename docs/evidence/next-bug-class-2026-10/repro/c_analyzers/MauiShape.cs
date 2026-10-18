using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace Repro;

public sealed class Bindable
{
    private readonly Dictionary<int, object?> _properties = new();
    private readonly Func<Bindable, object>? _defaultValueCreator;

    public Bindable(Func<Bindable, object>? creator) => _defaultValueCreator = creator;

    public void Set(int id, object? value) => _properties[id] = value;

    // MAUI 7b051d1b BindableObject.GetOrCreateContext shape: a ref held across user code
    public object? GetOrCreate(int id)
    {
        ref var context = ref CollectionsMarshal.GetValueRefOrAddDefault(_properties, id, out var exists);
        if (!exists)
        {
            context = CreateContext();
        }
        return context;
    }

    private object CreateContext() => _defaultValueCreator?.Invoke(this) ?? new object();

    // List<T> AsSpan shape (#400 first slice)
    public static int StaleSpan()
    {
        var list = new List<int>(1) { 10 };
        Span<int> view = CollectionsMarshal.AsSpan(list);
        list.Add(20);
        view[0] = 99;
        return list[0];
    }
}
