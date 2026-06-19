using System;

// Self-rooted `this.WhenAnyValue(...).Subscribe(...)` classifier (P-004 / WPF004).
// An ignored Subscribe over a chain rooted at `this`'s OWN single-hop properties is
// a GC-collectible self-cycle — the observable, its handler and `this` collect
// together — so the extractor tags `source: "self"` and the core stays SILENT. A
// nested path through an injected object, or a combinator that mixes in an external
// observable, can keep `this` alive and stays a FLAGGED leak (OWN001).
//
// The detection is purely syntactic, so the ReactiveUI surface (`WhenAnyValue`,
// `Where`, `CombineLatest`, `Subscribe`) need not be referenced — the chains only
// have to parse. See docs/notes/self-whenany-precision.md.

namespace Sample
{
    public sealed class WhenAnyValueViewModel
    {
        public string A { get; set; } = "";
        public string B { get; set; } = "";
        public AppSettings Svc { get; }            // injected, long-lived dependency
        private readonly Feed _bus;

        public WhenAnyValueViewModel(AppSettings svc, Feed bus)
        {
            Svc = svc;
            _bus = bus;

            // SILENCED — single-hop self property (the original supported shape).
            this.WhenAnyValue(x => x.A).Subscribe(v => A = v);

            // SILENCED — multi-arg, every selector a single-hop self property. This
            // observes only `this`, the same self-cycle as a single selector. The
            // classifier used to miss it solely because it required one argument.
            this.WhenAnyValue(x => x.A, x => x.B).Subscribe(t => { });

            // SILENCED — single-hop self + a self-preserving operator chain.
            this.WhenAnyValue(x => x.A).Where(v => v.Length > 0).Subscribe(v => B = v);

            // FLAGGED — nested path through the injected `Svc`: the PropertyChanged
            // handler attaches to the long-lived settings object and keeps `this`
            // alive. A real leak, not a self-cycle.
            this.WhenAnyValue(x => x.Svc.Name).Subscribe(v => A = v);

            // FLAGGED — a combinator mixes in an external observable (`_bus.Stream`),
            // rooting the subscription outside `this`.
            this.WhenAnyValue(x => x.A).CombineLatest(_bus.Stream).Subscribe(t => { });
        }
    }

    // Minimal in-sample stand-ins so the chains resolve cleanly (no ReactiveUI).
    public sealed class AppSettings { public string Name { get; set; } = ""; }

    public sealed class Feed { public IObservable<string> Stream => null!; }
}
