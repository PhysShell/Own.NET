// BEFORE (buggy). The canonical ASP.NET Core captive dependency (P-006 DI001):
// a SINGLETON service takes a SCOPED EF Core `DbContext` in its constructor, so
// the container builds one `AppDbContext` with the singleton and holds it for the
// whole application lifetime — an open DB connection pinned for the process, and
// request state shared across requests. Microsoft calls this "Cannot consume
// scoped service 'AppDbContext' from singleton 'NotificationService'." The
// extractor reads the conventional `IServiceCollection` registration graph
// (`Add{Singleton,Scoped}`) plus each implementation's constructor parameters, and
// ownlang/di.py flags the capture at the registration site, naming the consuming
// constructor. Representative of the pattern (a singleton background/notification
// service injecting a scoped DbContext), not verbatim from one project. The fix is
// a scope boundary — inject `IServiceScopeFactory` and resolve per operation (see
// after.cs).
using System;

namespace Corpus
{
    public sealed class AppDbContext { }                       // scoped (an EF Core DbContext is scoped)

    // registered as a SINGLETON below, but it captures the scoped DbContext:
    public sealed class NotificationService
    {
        public NotificationService(AppDbContext db) { }        // <-- captures scoped (DI001)
    }

    public static class Startup
    {
        public static void ConfigureServices(IServiceCollection services)
        {
            services.AddScoped<AppDbContext>();                // scoped
            services.AddSingleton<NotificationService>();      // FLAGGED: singleton -> scoped (DI001)
        }
    }
}
