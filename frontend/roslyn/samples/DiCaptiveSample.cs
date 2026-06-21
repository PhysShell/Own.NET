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

    // primary-constructor (C# 12) injection — the dependency is on the class
    // declaration, not a ConstructorDeclarationSyntax member.
    public sealed class PrimaryCtorService(AppDbContext db)                          // -> scoped (direct, primary ctor)
    { public AppDbContext Db { get; } = db; }

    // DI's default provider uses the PUBLIC ctor (no deps); the wider PRIVATE ctor's
    // scoped dependency is never resolved, so it must not be a captive.
    public sealed class PublicCtorOnly
    {
        public PublicCtorOnly() { }
        private PublicCtorOnly(AppDbContext db) { }
    }

    // DI003 — a singleton that captures a TRANSIENT IDisposable. The container builds
    // the connection once with the singleton and holds it for the whole app; it is
    // disposed only at root disposal, not per use. A warning (the lifetime promotion is
    // the smell), distinct from the DI001 captives above. `PooledConnection` is
    // `: IDisposable`, so the extractor marks its service `disposable`.
    public sealed class PooledConnection : System.IDisposable { public void Dispose() { } } // transient, IDisposable
    public sealed class ConnectionWarmer { public ConnectionWarmer(PooledConnection c) { } } // singleton -> captures it

    // DI002 — a singleton that holds a SCOPED service via WeakReference<T>. A weak ref is
    // the usual "fix" for a DI001 captive (it stops pinning the scoped instance for the
    // GC), but the scoped service is still resolved from the root and lives for the app
    // lifetime — the lifetime contract is still violated. A warning. The weak ref keeps it
    // OFF the DI001 strong graph (`deps`), so it surfaces as DI002, not DI001.
    public sealed class WeakCache { public WeakCache(WeakReference<AppDbContext> db) { } }      // -> WeakReference<scoped> : DI002
    // a NULLABLE weak reference (`WeakReference<AppDbContext>?`) is the same weak captive — the
    // `?` annotation does not change the service type, so it is DI002 too (CodeRabbit review).
    public sealed class WeakCacheOpt { public WeakCacheOpt(WeakReference<AppDbContext>? db) { } }
    // control: a weak reference to a SINGLETON is no lifetime mismatch -> SILENT.
    public sealed class WeakClockHolder { public WeakClockHolder(WeakReference<Clock> clock) { } }

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

            // FLAGGED — primary-constructor injection: singleton -> scoped AppDbContext.
            services.AddSingleton<PrimaryCtorService>();

            // SILENT — DI resolves the public parameterless ctor; the private ctor's
            // scoped dependency is never used (no false captive).
            services.AddSingleton<PublicCtorOnly>();

            // SILENT — singleton -> singleton (Clock); the typeof(...) registration form.
            services.AddSingleton(typeof(Metrics), typeof(Metrics));

            // FLAGGED (DI003, warning) — singleton ConnectionWarmer captures the
            // transient IDisposable PooledConnection: promoted to application lifetime,
            // disposed only at root disposal. NOT a DI001 (no scoped captured).
            services.AddTransient<PooledConnection>();
            services.AddSingleton<ConnectionWarmer>();

            // FLAGGED (DI002, warning) — singleton holds a SCOPED service via WeakReference:
            // the weak ref hides the GC-pinning symptom, but scoped AppDbContext is still
            // root-resolved and app-lived (the captive lifetime violation remains). NOT a
            // DI001 (the weak edge is off the strong graph).
            services.AddSingleton<WeakCache>();
            // FLAGGED (DI002) — a NULLABLE WeakReference<AppDbContext>? is the same weak captive
            // (the `?` annotation is unwrapped, so the scoped service is still seen).
            services.AddSingleton<WeakCacheOpt>();
            // SILENT — a weak reference to the SINGLETON Clock is no lifetime mismatch.
            services.AddSingleton<WeakClockHolder>();
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
