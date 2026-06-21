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
    // DI002 transitive — a singleton weakly holds a TRANSIENT (UnitOfWork) that strongly
    // depends on a scoped service (AppDbContext). The weak edge enters the transient, but the
    // scoped it drags in is still root-resolved and app-lived: DI002 (path WeakReport ->
    // UnitOfWork -> AppDbContext). NOT a DI001 (the entry edge is weak).
    public sealed class WeakReport { public WeakReport(WeakReference<UnitOfWork> uow) { } }
    // control: a weak reference to a SINGLETON is no lifetime mismatch -> SILENT.
    public sealed class WeakClockHolder { public WeakClockHolder(WeakReference<Clock> clock) { } }

    // DI004 — a singleton that resolves a TRANSIENT IDisposable from its injected ROOT
    // IServiceProvider BY HAND (the service-locator anti-pattern). For a singleton the
    // injected provider IS the root container; the root tracks every IDisposable it resolves
    // and frees them only at app shutdown, so each GetRequiredService call accumulates a
    // PooledConnection — an unbounded leak the registration graph (DI001/2/3) cannot see: it
    // is a call site, not a constructor edge. A warning, read from the resolution call site.
    public sealed class ConnectionResolver
    {
        private readonly IServiceProvider _sp;
        public ConnectionResolver(IServiceProvider sp) { _sp = sp; }
        public void Warm() { var c = _sp.GetRequiredService<PooledConnection>(); }            // DI004
    }

    // control: a singleton that resolves the transient IDisposable from a SCOPE it creates
    // (`scope.ServiceProvider`) — the CORRECT pattern; the scope owns and disposes it. The
    // receiver is `scope.ServiceProvider`, not the injected provider, so DI004 stays SILENT.
    public sealed class ScopedResolver
    {
        private readonly IServiceProvider _sp;
        public ScopedResolver(IServiceProvider sp) { _sp = sp; }
        public void Warm()
        {
            using var scope = _sp.CreateScope();
            var c = scope.ServiceProvider.GetRequiredService<PooledConnection>();             // SILENT (scope-resolved)
        }
    }

    // control: a singleton that resolves a NON-disposable transient (UnitOfWork) from the
    // root — the root does not track non-disposables, so nothing leaks. SILENT (the target
    // must be transient AND disposable).
    public sealed class PlainResolver
    {
        private readonly IServiceProvider _sp;
        public PlainResolver(IServiceProvider sp) { _sp = sp; }
        public void Make() { var u = _sp.GetRequiredService<UnitOfWork>(); }                  // SILENT (not disposable)
    }

    // control: a SCOPED service resolving the transient IDisposable from its injected provider
    // — that provider is the request scope (not the root), which disposes what it resolves.
    // SILENT (only a SINGLETON's injected provider is the root).
    public sealed class RequestResolver
    {
        private readonly IServiceProvider _sp;
        public RequestResolver(IServiceProvider sp) { _sp = sp; }
        public void Warm() { var c = _sp.GetRequiredService<PooledConnection>(); }            // SILENT (scoped class)
    }

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
            // FLAGGED (DI002, transitive) — singleton weakly holds the transient UnitOfWork,
            // which strongly drags in scoped AppDbContext (WeakReport -> UnitOfWork -> AppDbContext).
            services.AddSingleton<WeakReport>();
            // SILENT — a weak reference to the SINGLETON Clock is no lifetime mismatch.
            services.AddSingleton<WeakClockHolder>();

            // FLAGGED (DI004, warning) — singleton ConnectionResolver resolves the transient
            // IDisposable PooledConnection by hand off its injected ROOT IServiceProvider
            // (service locator), tracked to app shutdown. A call site, not a ctor edge.
            services.AddSingleton<ConnectionResolver>();
            // SILENT — resolves from a SCOPE it creates (scope.ServiceProvider), the correct shape.
            services.AddSingleton<ScopedResolver>();
            // SILENT — resolves a NON-disposable transient (UnitOfWork) from the root (untracked).
            services.AddSingleton<PlainResolver>();
            // SILENT — a SCOPED service's injected provider is the request scope, not the root.
            services.AddScoped<RequestResolver>();
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

    // Stand-ins for the IServiceProvider resolution surface (DI004). `IServiceProvider` is the
    // real System interface; the generic GetService/GetRequiredService and CreateScope are the
    // Microsoft.Extensions.DependencyInjection extensions — provided here so the sample binds.
    public interface IServiceScope : IDisposable { IServiceProvider ServiceProvider { get; } }

    public static class ServiceProviderExtensions
    {
        public static T GetRequiredService<T>(this IServiceProvider sp) => default!;
        public static T GetService<T>(this IServiceProvider sp) => default!;
        public static IServiceScope CreateScope(this IServiceProvider sp) => null!;
    }
}
