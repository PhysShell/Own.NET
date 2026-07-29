using System;

namespace Own.Corpus.Mini;

// A FINDING WITH NO AVAILABLE COLUMN — on purpose, and not as an oversight.
//
// DI001 (a captive dependency) is not an acquire/release finding at all: it comes
// from the `services[]` registration graph, not from a `subscriptions[]` record, and
// the startColumn slice deliberately did not touch that producer. So these findings
// keep a line-only anchor while everything else in this corpus gains a column.
//
// That mixed population is the point. An expectation that permits
// `null-to-positive-integer` must TOLERATE findings whose column stays null — it
// allows a transition, it does not demand one. A gate that required every finding to
// gain a column would fail this file, and the pressure would then be to fabricate a
// coordinate for it, which is the exact outcome the nullable design exists to
// prevent. It also keeps `occurrence_coverage` honestly flat for part of the corpus.
//
// The registration surface only has to parse — the extraction is syntactic, so this
// is not the real Microsoft.Extensions.DependencyInjection.
public sealed class AppDbContext { }                                   // scoped
public sealed class EmailSender { public EmailSender(AppDbContext db) { } }   // singleton
public sealed class Clock { }                                          // singleton, no deps
public sealed class Metrics { public Metrics(Clock clock) { } }         // singleton -> singleton

public interface IServiceCollection { }

public static class MiniRegistrations
{
    public static void Register(IServiceCollection services)
    {
        services.AddScoped<AppDbContext>();
        services.AddSingleton<EmailSender>();   // DI001: singleton captures scoped AppDbContext
        services.AddSingleton<Clock>();
        services.AddSingleton<Metrics>();       // singleton -> singleton: clean, stays silent
    }

    // Local stand-ins so the registration calls above bind and parse.
    internal static void AddScoped<T>(this IServiceCollection s) { }
    internal static void AddSingleton<T>(this IServiceCollection s) { }
}
