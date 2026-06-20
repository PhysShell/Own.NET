using System;

// P-006 — DI captive-dependency classifier (DI001). A *singleton* that depends —
// directly, transitively through a *transient*, or through an interface
// registration — on a *scoped* service captures that scoped instance for the
// whole application lifetime (the classic ASP.NET Core "Cannot consume scoped
// service from singleton" bug). The extractor reads the conventional
// `IServiceCollection` registration graph (`Add{Singleton,Scoped,Transient}`, the
// generic `<TService[, TImpl]>` form and the `typeof(...)` form) plus each
// implementation's constructor parameters, and ownlang/di.py flags the capture at
// the registration site. A singleton->singleton edge and the clean registrations
// stay silent. The extraction is purely syntactic, so the DI surface need not be
// the real Microsoft.Extensions.DependencyInjection — the calls only have to
// parse. See docs/proposals/P-006-di-lifetimes.md.

namespace Sample
{
    public sealed class AppDbContext { }                                  // scoped
    public sealed class Clock { }                                         // singleton, no deps

    public interface IRepo { }
    public sealed class Repo : IRepo { public Repo(AppDbContext db) { } } // scoped impl

    // singleton captors:
    public sealed class EmailSender { public EmailSender(AppDbContext db) { } }     // -> scoped (direct)
    public sealed class UnitOfWork { public UnitOfWork(AppDbContext db) { } }       // transient
    public sealed class ReportService { public ReportService(UnitOfWork uow) { } }  // -> transient -> scoped
    public sealed class CacheService { public CacheService(IRepo repo) { } }        // -> IRepo (scoped)
    public sealed class Metrics { public Metrics(Clock clock) { } }                 // -> singleton (clean)

    public static class Startup
    {
        public static void ConfigureServices(IServiceCollection services)
        {
            services.AddScoped<AppDbContext>();                       // scoped leaf
            services.AddSingleton<Clock>();                           // SILENT — singleton, no deps
            services.AddScoped<IRepo, Repo>();                        // interface -> impl, scoped

            // FLAGGED — singleton captures a scoped service directly.
            services.AddSingleton<EmailSender>();

            services.AddTransient<UnitOfWork>();                      // transient

            // FLAGGED — transitive: singleton -> transient UnitOfWork -> scoped AppDbContext.
            services.AddSingleton<ReportService>();

            // FLAGGED — through the interface registration: singleton -> IRepo (scoped).
            services.AddSingleton<CacheService>();

            // SILENT — singleton -> singleton (Clock); the typeof(...) registration form.
            services.AddSingleton(typeof(Metrics), typeof(Metrics));
        }
    }

    // Minimal in-sample stand-ins so the registrations resolve cleanly (no real
    // Microsoft.Extensions.DependencyInjection dependency). The extractor matches
    // the calls syntactically, so these only need to parse/bind.
    public interface IServiceCollection { }

    public static class ServiceCollectionExtensions
    {
        public static IServiceCollection AddSingleton<T>(this IServiceCollection s) => s;
        public static IServiceCollection AddScoped<T>(this IServiceCollection s) => s;
        public static IServiceCollection AddScoped<TService, TImpl>(this IServiceCollection s) => s;
        public static IServiceCollection AddTransient<T>(this IServiceCollection s) => s;
        public static IServiceCollection AddSingleton(this IServiceCollection s, Type service, Type impl) => s;
    }
}
