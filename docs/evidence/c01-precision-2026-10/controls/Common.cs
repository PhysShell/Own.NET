// C01-PRECISION-1 controls: shared publisher types. Not a control by itself.
using System;
using System.Collections.Generic;

namespace C01P1.Common
{
    // A plain strong event: the publisher's delegate list keeps every subscriber reachable.
    public sealed class Publisher
    {
        public event EventHandler? Changed;
        public void Raise() => Changed?.Invoke(this, EventArgs.Empty);
    }

    // The detach contract the target mechanism is about (MAUI's IDisconnectable shape).
    public interface IDetachable
    {
        void Detach();
        void Pause();
    }

    // Process-lived holder for the static-source forms.
    public static class Hub
    {
        public static readonly Publisher Shared = new Publisher();
    }

    // Form 8: a publisher whose event stores handlers weakly in its own add/remove accessors.
    public sealed class WeakPublisher
    {
        private readonly List<(WeakReference Target, System.Reflection.MethodInfo Method)> _handlers = new();

        public event EventHandler Changed
        {
            add => _handlers.Add((new WeakReference(value.Target), value.Method));
            remove => _handlers.RemoveAll(h => ReferenceEquals(h.Target.Target, value.Target) && h.Method == value.Method);
        }

        public void Raise()
        {
            foreach (var (target, method) in _handlers.ToArray())
                if (target.Target is { } t)
                    method.Invoke(t, new object[] { this, EventArgs.Empty });
        }
    }
}
