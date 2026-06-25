// AFTER (fixed). The standard remedy for a singleton that needs a scoped service:
// inject `IServiceScopeFactory` (a singleton itself) instead of the scoped
// `AppDbContext`, and open a fresh scope per operation — `using var scope =
// _scopes.CreateScope();` — resolving the DbContext inside it so it lives and is
// disposed within that operation. The singleton's constructor no longer depends on
// a scoped service, so there is no captive edge in the registration graph (DI001
// silent), and the resolve is off the scope's provider (not an injected root
// `IServiceProvider`), so the service-locator rule (DI004) stays silent too.
using System;

namespace Corpus
{
    public sealed class AppDbContext { }

    public sealed class NotificationService
    {
        private readonly IServiceScopeFactory _scopes;
        public NotificationService(IServiceScopeFactory scopes) { _scopes = scopes; }   // no scoped captured

        public void Notify()
        {
            using var scope = _scopes.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();           // per-operation scope
            // ... use db within the scope ...
        }
    }

    public static class Startup
    {
        public static void ConfigureServices(IServiceCollection services)
        {
            services.AddScoped<AppDbContext>();
            services.AddSingleton<NotificationService>();      // SILENT — injects IServiceScopeFactory, not the scoped service
        }
    }
}
