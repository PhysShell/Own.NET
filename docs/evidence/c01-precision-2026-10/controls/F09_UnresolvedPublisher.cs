// Form 9 — UNRESOLVED provenance (guard control): the publisher's type lives in a package the extractor's
// loose compilation does not reference (Newtonsoft.Json; the controls project references it, so this
// compiles). Own.NET must not guess: OWN050 advisory note, never a leak, before and after.
using System;
using Newtonsoft.Json;
using Newtonsoft.Json.Serialization;

namespace C01P1.F09
{
    public sealed class Subscriber
    {
        private readonly JsonSerializer _serializer;

        public Subscriber(JsonSerializer serializer)
        {
            _serializer = serializer;
            _serializer.Error += OnError; // EXPECT before=OWN050 after=OWN050
        }

        private void OnError(object? sender, ErrorEventArgs e) { }
    }
}
