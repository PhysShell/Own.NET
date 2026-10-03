using System.Net;
using System.Text;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using OrderBackend;
using OrderBackend.Data;
using OrderBackend.Domain;

// TB-MVP-01 acceptance: the real backend, over a real HTTP listener and a real SQLite file.
//
// The oracles do not go through the typed API:
//   * persisted state  — a raw Microsoft.Data.Sqlite connection, not EF (`Row`);
//   * object identity  — EF's ChangeTracker, against the reference the query returned;
//   * HTTP             — the status code and the exact response body.
//
// Every line is `ok[id]: ...` or `FAIL[id]: ...` and holds no port, path, GUID or wall-clock
// time (the backend's clock is fixed), so two runs print the same bytes. Exit 0 only when
// every check holds.

var failures = 0;
void Check(string id, bool holds, string detail)
{
    Console.WriteLine($"{(holds ? "ok" : "FAIL")}[{id}]: {detail}");
    if (!holds)
        failures++;
}

var dbPath = Path.Combine(Path.GetTempPath(), $"tb-mvp-{Guid.NewGuid():N}.db");
var clock = new FixedClock(new DateTimeOffset(2026, 1, 2, 3, 4, 5, TimeSpan.Zero));
var now = clock.GetUtcNow().UtcDateTime;
var sql = new List<string>();
void Database(DbContextOptionsBuilder options) => options
    .UseSqlite($"Data Source={dbPath}")
    .LogTo(text => { lock (sql) sql.Add(text); }, new[] { RelationalEventId.CommandExecuted });

OrdersDb Fresh()
{
    var options = new DbContextOptionsBuilder<OrdersDb>();
    Database(options);
    return new OrdersDb(options.Options);
}

// ---- the raw oracle: SQL on its own connection, nothing from EF or the typed API ----------
const string Columns = "Id, Customer, Status, SubmittedAt, ApprovedAt, ShippedAt, TrackingNumber";
string[] ColumnNames = Columns.Split(", ");

string[]? Row(long id)
{
    using var c = new SqliteConnection($"Data Source={dbPath};Pooling=False");
    c.Open();
    using var cmd = c.CreateCommand();
    cmd.CommandText = $"SELECT {Columns} FROM Orders WHERE Id = $id";
    cmd.Parameters.AddWithValue("$id", id);
    using var r = cmd.ExecuteReader();
    if (!r.Read())
        return null;
    return Enumerable.Range(0, r.FieldCount)
        .Select(i => r.IsDBNull(i) ? "NULL" : Convert.ToString(r.GetValue(i), System.Globalization.CultureInfo.InvariantCulture)!)
        .ToArray();
}

string Show(string[]? row) => row is null ? "<no row>" : string.Join(" | ", row);

long Scalar(string text)
{
    using var c = new SqliteConnection($"Data Source={dbPath};Pooling=False");
    c.Open();
    using var cmd = c.CreateCommand();
    cmd.CommandText = text;
    return Convert.ToInt64(cmd.ExecuteScalar(), System.Globalization.CultureInfo.InvariantCulture);
}

long InsertRaw(string customer, string status)
{
    using var c = new SqliteConnection($"Data Source={dbPath};Pooling=False");
    c.Open();
    using var cmd = c.CreateCommand();
    cmd.CommandText = "INSERT INTO Orders (Customer, Status) VALUES ($c, $s); SELECT last_insert_rowid();";
    cmd.Parameters.AddWithValue("$c", customer);
    cmd.Parameters.AddWithValue("$s", status);
    return Convert.ToInt64(cmd.ExecuteScalar(), System.Globalization.CultureInfo.InvariantCulture);
}

// the columns two snapshots differ in
string Diff(string[]? before, string[]? after) =>
    before is null || after is null
        ? "<missing row>"
        : string.Join(",", ColumnNames.Where((_, i) => before[i] != after[i]));

var app = Backend.Build(
    // the host's console log would carry the port and timings: this transcript is the output
    new[] { "--urls", "http://127.0.0.1:0", "--Logging:LogLevel:Default=None" }, Database, clock);
await using (var setup = Fresh())
    await setup.Database.EnsureCreatedAsync();
await app.StartAsync();
try
{
    using var http = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };

    async Task<(HttpStatusCode Code, string Body, string? Location)> Send(HttpMethod method, string path, string? json = null)
    {
        using var request = new HttpRequestMessage(method, path);
        if (json is not null)
            request.Content = new StringContent(json, Encoding.UTF8, "application/json");
        using var response = await http.SendAsync(request);
        return (response.StatusCode, await response.Content.ReadAsStringAsync(), response.Headers.Location?.OriginalString);
    }

    Task<(HttpStatusCode Code, string Body, string? Location)> Post(string path, string? json = null) => Send(HttpMethod.Post, path, json);
    Task<(HttpStatusCode Code, string Body, string? Location)> Get(string path) => Send(HttpMethod.Get, path);

    const string stamp = "2026-01-02 03:04:05";   // EF's SQLite text for the fixed clock

    Check("db-fresh", Scalar("SELECT COUNT(*) FROM Orders") == 0,
          "EnsureCreated made the schema in a new database file: 0 rows");

    // ---- P15: the HTTP happy path, one database, the raw row after every step ---------------
    var created = await Post("/orders", "{\"customer\":\"alice\"}");
    Check("http-create", created.Code == HttpStatusCode.Created && created.Location == "/orders/1"
          && created.Body == "{\"id\":1,\"status\":\"Draft\"}",
          $"POST /orders -> {(int)created.Code} {created.Location} {created.Body}");
    Check("oracle-create", Show(Row(1)) == "1 | alice | Draft | NULL | NULL | NULL | NULL",
          $"raw row: {Show(Row(1))}");

    var step = await Post("/orders/1/submit");
    Check("http-submit", step.Code == HttpStatusCode.OK && step.Body == "{\"id\":1,\"status\":\"Submitted\"}",
          $"POST /orders/1/submit -> {(int)step.Code} {step.Body}");
    Check("oracle-submit", Show(Row(1)) == $"1 | alice | Submitted | {stamp} | NULL | NULL | NULL",
          $"raw row: {Show(Row(1))}");

    step = await Post("/orders/1/approve");
    Check("http-approve", step.Code == HttpStatusCode.OK && step.Body == "{\"id\":1,\"status\":\"Approved\"}",
          $"POST /orders/1/approve -> {(int)step.Code} {step.Body}");
    Check("oracle-approve", Show(Row(1)) == $"1 | alice | Approved | {stamp} | {stamp} | NULL | NULL",
          $"raw row: {Show(Row(1))}");

    var tracking = Shipping.TrackingNumber(1);
    step = await Post("/orders/1/ship");
    Check("http-ship", step.Code == HttpStatusCode.OK
          && step.Body == $"{{\"id\":1,\"status\":\"Shipped\",\"trackingNumber\":{tracking}}}",
          $"POST /orders/1/ship -> {(int)step.Code} {step.Body}");
    Check("oracle-ship", Show(Row(1)) == $"1 | alice | Shipped | {stamp} | {stamp} | {stamp} | {tracking}",
          $"raw row: {Show(Row(1))}");

    var got = await Get("/orders/1");
    Check("http-get-shipped", got.Code == HttpStatusCode.OK && got.Body ==
          "{\"id\":1,\"customer\":\"alice\",\"status\":\"Shipped\",\"submittedAt\":\"2026-01-02T03:04:05\","
          + $"\"approvedAt\":\"2026-01-02T03:04:05\",\"shippedAt\":\"2026-01-02T03:04:05\",\"trackingNumber\":{tracking}}}",
          $"GET /orders/1 -> {(int)got.Code} {got.Body}");

    // ---- P14: the builder's required field, at the HTTP boundary -----------------------------
    var rows = Scalar("SELECT COUNT(*) FROM Orders");
    foreach (var body in new[] { "{}", "{\"customer\":\"  \"}" })
    {
        var bad = await Post("/orders", body);
        Check("http-create-required", bad.Code == HttpStatusCode.BadRequest
              && bad.Body == "{\"error\":\"customer_required\"}" && Scalar("SELECT COUNT(*) FROM Orders") == rows,
              $"POST /orders {body} -> {(int)bad.Code} {bad.Body}, no row written");
    }

    // ---- H9: wrong runtime transitions are 409 and leave the row byte-identical ---------------
    var b = await Post("/orders", "{\"customer\":\"bob\"}");
    Check("http-create-b", b.Code == HttpStatusCode.Created && b.Location == "/orders/2", $"second order -> {b.Location}");
    async Task Refused(string id, long order, string verb, string state, string required)
    {
        var before = Row(order);
        var r = await Post($"/orders/{order}/{verb}");
        var after = Row(order);
        Check(id, r.Code == HttpStatusCode.Conflict
              && r.Body == $"{{\"error\":\"invalid_transition\",\"id\":{order},\"state\":\"{state}\",\"required\":\"{required}\"}}"
              && Show(before) == Show(after),
              $"{verb} {(state[0] == 'A' ? "an" : "a")} {state} order -> {(int)r.Code} {r.Body}; row unchanged: {Show(before) == Show(after)}");
    }
    await Refused("h9-approve-draft", 2, "approve", "Draft", "Submitted");
    await Refused("h9-ship-draft", 2, "ship", "Draft", "Approved");
    Check("h9-b-submit", (await Post("/orders/2/submit")).Code == HttpStatusCode.OK && Row(2)?[2] == "Submitted",
          "the legal submit in between goes through: Submitted");
    await Refused("h9-ship-submitted", 2, "ship", "Submitted", "Approved");
    await Refused("h9-submit-submitted", 2, "submit", "Submitted", "Draft");
    Check("h9-b-approve", (await Post("/orders/2/approve")).Code == HttpStatusCode.OK && Row(2)?[2] == "Approved",
          "the legal approve in between goes through: Approved");
    await Refused("h9-submit-approved", 2, "submit", "Approved", "Draft");
    await Refused("h9-approve-approved", 2, "approve", "Approved", "Submitted");
    Check("h9-b-ship", (await Post("/orders/2/ship")).Code == HttpStatusCode.OK && Row(2)?[2] == "Shipped",
          "the legal ship in between goes through: Shipped");
    await Refused("h9-submit-shipped", 2, "submit", "Shipped", "Draft");
    await Refused("h9-approve-shipped", 2, "approve", "Shipped", "Submitted");
    await Refused("h9-ship-shipped", 2, "ship", "Shipped", "Approved");

    foreach (var verb in new[] { "submit", "approve", "ship" })
    {
        var missing = await Post($"/orders/999999/{verb}");
        Check($"http-404-{verb}", missing.Code == HttpStatusCode.NotFound, $"{verb} an unknown id -> {(int)missing.Code}");
    }
    Check("http-404-get", (await Get("/orders/999999")).Code == HttpStatusCode.NotFound, "GET an unknown id -> 404");

    // ---- H8: a persisted state that is not a state never becomes a token ---------------------
    foreach (var raw in new[] { "Bogus", "7", "approved", "" })
    {
        var id = InsertRaw("mallory", raw);
        var before = Row(id);
        var answers = new List<string>();
        foreach (var verb in new[] { "submit", "approve", "ship" })
        {
            var r = await Post($"/orders/{id}/{verb}");
            answers.Add($"{verb}={(int)r.Code}");
            if (r.Code != HttpStatusCode.InternalServerError || r.Body != $"{{\"error\":\"corrupt_state\",\"id\":{id}}}")
                answers.Add("WRONG:" + r.Body);
        }
        var g = await Get($"/orders/{id}");
        answers.Add($"get={(int)g.Code}");
        if (g.Code != HttpStatusCode.InternalServerError || g.Body != $"{{\"error\":\"corrupt_state\",\"id\":{id}}}")
            answers.Add("WRONG:" + g.Body);
        string thrown;
        await using (var db = Fresh())
        {
            try
            {
                var o = await db.Orders.SingleAsync(x => x.Id == id);
                thrown = $"loaded as {o.Status}";
            }
            catch (CorruptOrderStateException e)
            {
                thrown = $"CorruptOrderStateException('{e.Raw}')";
            }
        }
        Check($"h8-corrupt-'{raw}'", !answers.Any(a => a.StartsWith("WRONG", StringComparison.Ordinal))
              && thrown == $"CorruptOrderStateException('{raw}')" && Show(before) == Show(Row(id)),
              $"stored '{raw}': {string.Join(" ", answers)}; EF load: {thrown}; row unchanged: {Show(before) == Show(Row(id))}");
    }
    var storage = new List<string>();
    foreach (var raw in new[] { "Bogus", "7", "approved", "", " Draft" })
        storage.Add(OrderStatusStorage.TryFromStore(raw, out _) ? $"'{raw}'=state" : $"'{raw}'=refused");
    try
    {
        OrderStatusStorage.ToStore((OrderStatus)7);
        storage.Add("ToStore(7)=written");
    }
    catch (CorruptOrderStateException)
    {
        storage.Add("ToStore(7)=refused");
    }
    Check("h8-storage-strict", storage.All(s => s.EndsWith("refused", StringComparison.Ordinal)),
          string.Join(" ", storage));

    // ---- H10/H11: the typed transition writes the instance EF tracks, and nothing else -------
    long c;
    await using (var db = Fresh())
    {
        var fresh = Order.Create().Customer("carol").Build();
        Check("builder-draft", fresh.Status == OrderStatus.Draft && fresh.Customer == "carol" && fresh.Id == 0,
              $"Order.Create().Customer(\"carol\").Build() is a new {fresh.Status} for {fresh.Customer}");
        db.Orders.Add(fresh);
        await db.SaveChangesAsync();
        c = fresh.Id;
    }
    await using (var db = Fresh())
    {
        var order = await db.Orders.SingleAsync(o => o.Id == c);
        var entry = db.ChangeTracker.Entries<Order>().Single();
        Check("h10-same-instance-before", ReferenceEquals(entry.Entity, order) && entry.State == EntityState.Unchanged,
              $"the queried Order IS the instance the ChangeTracker holds, {entry.State}");

        var before = Row(c);
        OrderProtocol.WithDraft(order, draft =>
        {
            draft.Submit(now);
        });
        db.ChangeTracker.DetectChanges();
        var modified = entry.Properties.Where(p => p.IsModified).Select(p => p.Metadata.Name).OrderBy(n => n, StringComparer.Ordinal);
        Check("h10-same-instance-after", ReferenceEquals(db.ChangeTracker.Entries<Order>().Single().Entity, order)
              && db.ChangeTracker.Entries<Order>().Count() == 1 && order.Status == OrderStatus.Submitted,
              "after the region the tracked instance is still the queried one, now Submitted; one entry, nothing re-attached");
        Check("h10-tracked-change", entry.State == EntityState.Modified
              && string.Join(",", modified) == "Status,SubmittedAt",
              $"the ChangeTracker sees {entry.State}: {string.Join(",", modified)}");

        var written = await db.SaveChangesAsync();
        var after = Row(c);
        Check("h11-saved-exactly", written == 1 && Diff(before, after) == "Status,SubmittedAt"
              && after![2] == "Submitted" && after[3] == stamp,
              $"SaveChangesAsync wrote {written} row; raw columns changed: {Diff(before, after)}; raw row: {Show(after)}");
    }

    // ---- H12: reload, refine by the persisted state --------------------------------------
    await using (var db = Fresh())
    {
        var order = await db.Orders.SingleAsync(o => o.Id == c);
        string wrong;
        try
        {
            OrderProtocol.WithDraft(order, draft =>
            {
                draft.Submit(now);
            });
            wrong = "admitted";
        }
        catch (InvalidOrderStateException e)
        {
            wrong = $"InvalidOrderStateException({e.Actual}, required {e.Required})";
        }
        var untouched = db.ChangeTracker.Entries<Order>().Single().State;
        OrderProtocol.WithSubmitted(order, submitted =>
        {
            submitted.Approve(now);
        });
        await db.SaveChangesAsync();
        Check("h12-reload-refine", wrong == "InvalidOrderStateException(Submitted, required Draft)"
              && untouched == EntityState.Unchanged && Row(c)?[2] == "Approved",
              $"reloaded Submitted: WithDraft -> {wrong} ({untouched}); WithSubmitted -> Approve saved {Row(c)?[2]}");
    }

    // ---- H13: ordinary LINQ ----------------------------------------------------------------
    var list = await Get("/orders?status=Approved");
    Check("h13-linq-endpoint", list.Code == HttpStatusCode.OK && list.Body == $"[{{\"id\":{c},\"customer\":\"carol\"}}]",
          $"GET /orders?status=Approved -> {(int)list.Code} {list.Body} (the corrupt 'approved' row is not Approved)");
    var unknown = await Get("/orders?status=approved");
    Check("h13-linq-unknown-status", unknown.Code == HttpStatusCode.BadRequest && unknown.Body == "{\"error\":\"unknown_status\"}",
          $"GET /orders?status=approved -> {(int)unknown.Code} {unknown.Body}");
    await using (var db = Fresh())
    {
        var text = db.Orders.Where(o => o.Status == OrderStatus.Approved).OrderBy(o => o.Id).Select(o => o.Id).ToQueryString();
        Check("h13-linq-translated", text.Contains("WHERE \"o\".\"Status\" = 'Approved'", StringComparison.Ordinal)
              && text.Contains("ORDER BY", StringComparison.Ordinal),
              "the predicate is server-side SQL over the stored name: WHERE \"o\".\"Status\" = 'Approved' ... ORDER BY");
    }

    string[] executed;
    lock (sql)
        executed = sql.ToArray();
    Check("ef-update-emitted", executed.Any(t => t.Contains("UPDATE \"Orders\" SET \"Status\"", StringComparison.Ordinal)),
          "the transitions reach the database as ordinary UPDATE statements");
}
finally
{
    await app.StopAsync();
    await app.DisposeAsync();
    SqliteConnection.ClearAllPools();
    try
    {
        File.Delete(dbPath);
    }
    catch (IOException)
    {
    }
}

Console.WriteLine(failures == 0
    ? "typed builder acceptance: all checks hold"
    : $"typed builder acceptance: {failures} check(s) FAILED");
return failures == 0 ? 0 : 1;

/// The backend's clock in this run: fixed, so the transcript is the same bytes every time.
sealed class FixedClock(DateTimeOffset at) : TimeProvider
{
    public override DateTimeOffset GetUtcNow() => at;
}
