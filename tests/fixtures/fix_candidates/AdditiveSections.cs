using System;
using System.ComponentModel;
using System.IO;
using System.Threading.Tasks;

// S0 additivity fixture — read by `tests/check_fix_candidates_facts.py --additive-sections`
// (the CI step "S0 fix-candidates — extractor metadata (Part A)").
//
// `--fix-candidates` only ADDS: take the S0 fields out of a flag-on document and what is left
// must be the flag-off document. That claim is only as strong as the document it is checked
// on, and FixCandidatesSample.cs has subscriptions and nothing else — so a flag-on envelope
// that dropped a whole section (it dropped `orphaned_awaitables`) passed it. This one file
// makes EVERY top-level section the Roslyn extractor can write non-empty under
// `--flow-locals`, and the checker refuses the pair if a section the extractor can write is
// missing from it. A new section therefore means a new block here, or a red build.
//
// It lives under tests/fixtures/, not frontend/roslyn/samples/: that directory is scanned as
// a whole by jobs that pin its findings. It is self-contained on purpose (no reference
// directory): the two OWN053 families are reached through types declared in this file.
namespace Own.Samples.FixCandidates.Additive
{
    // components[] — a subscription that is never released (under --fix-candidates it also
    // carries the S0 `fix` block, and its component the S0 shape fields).
    public sealed class Subscriber
    {
        private readonly INotifyPropertyChanged _source;

        public Subscriber(INotifyPropertyChanged source)
        {
            _source = source;
            _source.PropertyChanged += OnChanged;
        }

        private void OnChanged(object? sender, PropertyChangedEventArgs e) { }
    }

    // services[] — a DI registration graph. The extraction is syntactic, so the surface only
    // has to parse.
    public sealed class ScopedThing { }

    public sealed class Holder { public Holder(ScopedThing thing) { } }

    public interface IRegistrar
    {
        IRegistrar AddScoped<T>();
        IRegistrar AddSingleton<T>();
    }

    public static class Registration
    {
        public static void Configure(IRegistrar services)
        {
            services.AddScoped<ScopedThing>();
            services.AddSingleton<Holder>();
        }
    }

    // functions[] — a flow-sensitive disposable local.
    public static class Flow
    {
        public static long Leak(string path)
        {
            var stream = new FileStream(path, FileMode.Open);
            return stream.Length;
        }
    }

    // orphaned_awaitables[] — both frozen OWN053 families.
    public sealed class Connection : IDisposable
    {
        private bool _open = true;

        public bool IsOpen => _open;

        public void Dispose() { _open = false; }
    }

    public sealed class Store
    {
        public Task<Connection> OpenConnectionAsync() => Task.FromResult(new Connection());

        public Task CommitAsync() => Task.CompletedTask;
    }

    public static class Orphans
    {
        public static void Run(Store store)
        {
            var connection = store.OpenConnectionAsync();   // A_owned_result: a disposable, never observed
            var commit = store.CommitAsync();               // B_protocol_lifecycle: a lifecycle call, never observed
        }
    }
}
