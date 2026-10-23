// Form 5 — DANGEROUS: the setter unsubscribes the OLD value before subscribing the new one, but nothing
// detaches the current value when the owner goes away (the MAUI Picker.ItemsSource / Border.StrokeDashArray
// shape). A shared, long-lived value keeps the last owner alive.
// Oracle: real retention of the owner by the current value. Own.NET: OWN001. Must stay.
using System;
using C01P1.Common;

namespace C01P1.F05
{
    public sealed class Owner : IDisposable
    {
        private Publisher? _source;

        public Publisher? Source
        {
            get => _source;
            set
            {
                if (_source != null)
                    _source.Changed -= OnChanged;
                _source = value;
                if (_source != null)
                    _source.Changed += OnChanged; // EXPECT before=OWN001 after=OWN001
            }
        }

        public void Dispose() { }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
