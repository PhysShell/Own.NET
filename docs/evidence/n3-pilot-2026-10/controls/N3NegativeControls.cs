// N3 pilot G2 controls (01-preregistration-g1-g4.md §5). Written before the PoC was first run.
// Every method named C<n>_* must be SILENT. Every method named P_<S>_<D>_* must be REPORTED.
// Combinations marked "n/a" have no meaningful shape (e.g. an IServiceProvider is not awaited as a receiver).
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace N3Controls;

public class AppDbContext : DbContext
{
    public DbSet<Order> Orders => Set<Order>();
}

public class Order { public int Id { get; set; } }

public interface IOrderService { Task NotifyAsync(int id); Task PingAsync(); }

public class OrderService : IOrderService
{
    private readonly AppDbContext _db;
    public OrderService(AppDbContext db) { _db = db; }
    public async Task NotifyAsync(int id) { await Task.Delay(1); _db.Orders.Find(id); }
    public Task PingAsync() => Task.CompletedTask;
}

public interface IMixed { void Touch(); }
public class Mixed : IMixed { public void Touch() { } }

public interface IClock { DateTime Now { get; } }
public class Clock : IClock { public DateTime Now => DateTime.UtcNow; }

public interface IBackgroundTaskQueue { void QueueBackgroundWorkItem(Func<CancellationToken, Task> work); }
public class BackgroundTaskQueue : IBackgroundTaskQueue
{
    public void QueueBackgroundWorkItem(Func<CancellationToken, Task> work) { }
}

public class SingletonWorker
{
    private readonly IClock _clock;
    private readonly IServiceProvider _root;
    public SingletonWorker(IClock clock, IServiceProvider root) { _clock = clock; _root = root; }

    // C6: singleton holder with singleton deps
    public void C6_SingletonHolder() { _ = Task.Run(() => Console.WriteLine(_clock.Now)); }

    // C10: root provider in a singleton
    public void C10_RootProvider() { _ = Task.Run(() => _root.GetRequiredService<IClock>()); }
}

public static class Registrations
{
    public static void Register(IServiceCollection services)
    {
        services.AddDbContext<AppDbContext>();
        services.AddScoped<IOrderService, OrderService>();
        services.AddScoped<IMixed, Mixed>();
        services.AddSingleton<IMixed, Mixed>();
        services.AddSingleton<IClock, Clock>();
        services.AddSingleton<SingletonWorker>();
        services.AddSingleton<IBackgroundTaskQueue, BackgroundTaskQueue>();
        services.AddHttpClient();
    }
}

[ApiController]
public class ControlsController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly IOrderService _orders;
    private readonly IServiceProvider _sp;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly HttpClient _http;
    private readonly IHttpClientFactory _httpFactory;
    private readonly IMixed _mixed;
    private readonly IHttpContextAccessor _accessor;
    private readonly IBackgroundTaskQueue _queue;

    public ControlsController(AppDbContext db, IOrderService orders, IServiceProvider sp,
        IServiceScopeFactory scopeFactory, HttpClient http, IHttpClientFactory httpFactory, IMixed mixed,
        IHttpContextAccessor accessor, IBackgroundTaskQueue queue)
    {
        _db = db; _orders = orders; _sp = sp; _scopeFactory = scopeFactory; _http = http;
        _httpFactory = httpFactory; _mixed = mixed; _accessor = accessor; _queue = queue;
    }

    // ---- negative controls: must be silent ----

    public async Task C1_Awaited() { await Task.Run(() => _db.Orders.Count()); }

    public Task<int> C2_Returned() { return Task.Run(() => _db.Orders.Count()); }

    public async Task C3_StoredThenAwaited()
    {
        var t = Task.Run(() => _db.Orders.Count());
        Console.WriteLine("work");
        await t;
    }

    public async Task C4_WhenAll()
    {
        var t1 = Task.Run(() => _db.Orders.Count());
        var t2 = Task.Run(() => _orders.PingAsync());
        await Task.WhenAll(t1, t2);
    }

    public void C5_OwnScope()
    {
        _ = Task.Run(async () =>
        {
            using var s = _scopeFactory.CreateScope();
            var db = s.ServiceProvider.GetRequiredService<AppDbContext>();
            await db.SaveChangesAsync();
        });
    }

    public void C7_CopiedData()
    {
        var id = _db.Orders.First().Id;
        var name = HttpContext.User.Identity!.Name;
        _ = Task.Run(() => Log(id, name));
    }

    public void C8_SameClassUseBeforeAwait() { _ = SaveBeforeAwaitAsync(); }

    private async Task SaveBeforeAwaitAsync()
    {
        var n = _db.Orders.Count();
        await Task.Delay(n);
        Console.WriteLine("done");
    }

    public void C9_HttpClientField() { _ = Task.Run(() => _http.GetAsync("https://example.org")); }

    public void C11_HttpClientFactory()
    {
        _ = Task.Run(() => _httpFactory.CreateClient().GetAsync("https://example.org"));
    }

    public void C12_SyncCompletedReceiver() { _ = _orders.PingAsync(); }

    public void C13_MixedLifetime() { _ = Task.Run(() => _mixed.Touch()); }

    public void C14_AccessorInsideWork() { _ = Task.Run(() => Log(0, _accessor.HttpContext?.TraceIdentifier)); }

    // C15 (added after the first pair run, PoC v1 bug): a void same-class call is not D3b, and an await
    // inside a nested lambda is not the callee's own first await.
    public void C15_VoidSameClassNestedAwait() { KickOff(); }

    private void KickOff()
    {
        Func<Task> f = async () => { await Task.Delay(1); _db.Orders.Count(); };
        f().Wait();
    }

    // ---- positive samples: must be reported ----

    // S1 HttpContext
    public void P_S1_D1_HttpContextInTaskRun() { _ = Task.Run(() => Log(0, HttpContext.TraceIdentifier)); }

    public void P_S1_D2_HttpContextInQueue()
    {
        _queue.QueueBackgroundWorkItem(async ct => { await Task.Delay(1, ct); Log(0, HttpContext.TraceIdentifier); });
    }

    public void P_S1_D3a_HttpContextReceiver() { _ = HttpContext.Response.WriteAsync("late"); }

    public void P_S1_D3b_HttpContextSameClass() { _ = LogLaterAsync(HttpContext); }

    private async Task LogLaterAsync(HttpContext ctx)
    {
        await Task.Delay(10);
        Log(0, ctx.TraceIdentifier);
    }

    // S2 DbContext
    public void P_S2_D1_DbInTaskRun() { _ = Task.Run(() => _db.Orders.Count()); }

    public void P_S2_D2_DbInQueue() { _queue.QueueBackgroundWorkItem(async ct => await _db.SaveChangesAsync(ct)); }

    public void P_S2_D3a_DbReceiver() { _ = _db.SaveChangesAsync(); }

    public void P_S2_D3b_DbSameClass() { _ = SaveAfterAwaitAsync(); }

    private async Task SaveAfterAwaitAsync()
    {
        await Task.Delay(10);
        await _db.SaveChangesAsync();
    }

    // S3 scoped service
    public void P_S3_D1_ScopedInTaskRun() { _ = Task.Run(() => _orders.NotifyAsync(1)); }

    public void P_S3_D2_ScopedInQueue() { _queue.QueueBackgroundWorkItem(ct => _orders.NotifyAsync(2)); }

    public void P_S3_D3a_ScopedReceiver() { _ = _orders.NotifyAsync(3); }

    public void P_S3_D3b_ScopedSameClass() { _ = NotifyLaterAsync(); }

    private async Task NotifyLaterAsync()
    {
        await Task.Delay(10);
        await _orders.NotifyAsync(4);
    }

    // S4 request-scope IServiceProvider
    public void P_S4_D1_ScopeProviderInTaskRun() { _ = Task.Run(() => _sp.GetRequiredService<IOrderService>()); }

    public void P_S4_D2_ScopeProviderInQueue()
    {
        _queue.QueueBackgroundWorkItem(ct => _sp.GetRequiredService<IOrderService>().NotifyAsync(5));
    }

    // P_S4_D3a: n/a (an IServiceProvider call does not return a Task)

    public void P_S4_D3b_ScopeProviderSameClass() { _ = ResolveLaterAsync(); }

    private async Task ResolveLaterAsync()
    {
        await Task.Delay(10);
        _sp.GetRequiredService<IOrderService>();
    }

    private static void Log(int id, string? s) => Console.WriteLine($"{id} {s}");
}
