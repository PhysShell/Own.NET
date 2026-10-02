using System.Net;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using OrderBackend;
using OrderBackend.Data;
using OrderBackend.Domain;

// Backend acceptance: the real backend, over a real HTTP listener and a real SQLite file.
// Exit code 0 only when every check holds.

var failures = 0;
void Check(string id, bool holds, string detail)
{
    Console.WriteLine($"{(holds ? "ok" : "FAIL")}[{id}]: {detail}");
    if (!holds)
        failures++;
}

var dbPath = Path.Combine(Path.GetTempPath(), $"own-protocol-{Guid.NewGuid():N}.db");
var sql = new List<string>();
void Database(DbContextOptionsBuilder options) => options
    .UseSqlite($"Data Source={dbPath}")
    .LogTo(text => { lock (sql) sql.Add(text); },
           new[] { RelationalEventId.CommandExecuted });

AppDbContext FreshContext()
{
    var options = new DbContextOptionsBuilder<AppDbContext>();
    Database(options);
    return new AppDbContext(options.Options);
}

var app = Backend.Build(new[] { "--urls", "http://127.0.0.1:0" }, Database);
await using (var setup = FreshContext())
    await setup.Database.EnsureCreatedAsync();
await app.StartAsync();
try
{
    using var http = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };

    async Task<int> Create(string customer)
    {
        var response = await http.PostAsync($"/orders?customer={customer}", null);
        response.EnsureSuccessStatusCode();
        return int.Parse(response.Headers.Location!.OriginalString.Split('/')[^1]);
    }

    async Task<OrderStatus> StoredStatus(int id)
    {
        // a SEPARATE context and connection: what this reads is what was committed
        await using var db = FreshContext();
        return (await db.Orders.AsNoTracking().SingleAsync(o => o.Id == id)).Status;
    }

    // ---- 1. the happy path over HTTP: Draft -> (Submit, Approve) -> Ship ----------------
    var a = await Create("alice");
    Check("http-created-draft", await StoredStatus(a) == OrderStatus.Draft,
          "POST /orders stores a Draft");
    var step = await http.PostAsync($"/orders/{a}/submit-and-approve", null);
    Check("http-two-transitions", step.StatusCode == HttpStatusCode.OK
          && await StoredStatus(a) == OrderStatus.Approved,
          "two transitions inside one region are saved: Draft -> Approved");
    step = await http.PostAsync($"/orders/{a}/ship", null);
    Check("http-ship", step.StatusCode == HttpStatusCode.OK
          && await StoredStatus(a) == OrderStatus.Shipped,
          "POST /orders/{id}/ship commits Shipped inside the handler's transaction");

    // ---- 2. the runtime refinement refuses the wrong state, and nothing is written -------
    var b = await Create("bob");
    step = await http.PostAsync($"/orders/{b}/ship", null);
    Check("http-ship-refused", step.StatusCode == HttpStatusCode.Conflict
          && await StoredStatus(b) == OrderStatus.Draft,
          "shipping a Draft is 409 (the region entry's check), and the row is untouched");
    step = await http.PostAsync($"/orders/{a}/submit-and-approve", null);
    Check("http-resubmit-refused", step.StatusCode == HttpStatusCode.Conflict
          && await StoredStatus(a) == OrderStatus.Shipped,
          "submitting a Shipped order is 409, and the row is untouched");
    step = await http.PostAsync("/orders/999999/ship", null);
    Check("http-missing", step.StatusCode == HttpStatusCode.NotFound, "an unknown id is 404");

    // ---- 3. the token mutates the instance EF tracks -----------------------------------
    var c = await Create("carol");
    (await http.PostAsync($"/orders/{c}/submit-and-approve", null)).EnsureSuccessStatusCode();
    await using (var db = FreshContext())
    {
        var order = await db.Orders.SingleAsync(o => o.Id == c);
        var entry = db.ChangeTracker.Entries<Order>().Single();
        Check("ef-same-instance", ReferenceEquals(entry.Entity, order),
              "the queried Order IS the instance the ChangeTracker holds");
        Check("ef-unchanged-before", entry.State == EntityState.Unchanged,
              "it is Unchanged before the region");

        var now = DateTime.UtcNow;
        OrderProtocol.WithApproved(order, approved =>
        {
            approved.Ship(now);
        });

        db.ChangeTracker.DetectChanges();
        Check("ef-change-tracked", entry.State == EntityState.Modified
              && entry.Property(o => o.Status).IsModified
              && entry.Property(o => o.ShippedAt).IsModified
              && !entry.Property(o => o.Customer).IsModified,
              "the transition is visible to the ChangeTracker as Status + ShippedAt, nothing else");
        Check("ef-no-reattach", db.ChangeTracker.Entries<Order>().Count() == 1,
              "no second entry appeared: nothing was attached, copied or re-materialized");
        var written = await db.SaveChangesAsync();
        Check("ef-saved", written == 1 && await StoredStatus(c) == OrderStatus.Shipped,
              "SaveChangesAsync writes one row and a separate context reads Shipped");
    }

    // ---- 4. plain EF queries: translated by the provider, nothing custom ----------------
    await using (var db = FreshContext())
    {
        var text = db.Orders.Where(o => o.Id == c).ToQueryString();
        Check("ef-query-translated", text.Contains("WHERE", StringComparison.Ordinal)
              && text.Contains("\"Id\"", StringComparison.Ordinal),
              "the handler's predicate is a server-side WHERE on Id");
    }
    string[] executed;
    lock (sql)
        executed = sql.ToArray();
    Check("ef-update-emitted", executed.Any(t => t.Contains("UPDATE \"Orders\" SET", StringComparison.Ordinal)
              && t.Contains("\"Status\"", StringComparison.Ordinal)),
          "the transitions reach the database as ordinary UPDATE statements");
}
finally
{
    await app.StopAsync();
    await app.DisposeAsync();
    Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
    try { File.Delete(dbPath); } catch (IOException) { }
}

Console.WriteLine(failures == 0
    ? "backend acceptance: all checks hold"
    : $"backend acceptance: {failures} check(s) FAILED");
return failures == 0 ? 0 : 1;
