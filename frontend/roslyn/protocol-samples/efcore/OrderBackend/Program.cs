using Microsoft.EntityFrameworkCore;
using OrderBackend;
using OrderBackend.Data;

var app = Backend.Build(args, options =>
    options.UseSqlite("Data Source=orders.db"));

using (var scope = app.Services.CreateScope())
    scope.ServiceProvider.GetRequiredService<AppDbContext>().Database.EnsureCreated();

app.Run();

public partial class Program
{
}

namespace OrderBackend
{
    /// The composition root, shared by `Program` and the acceptance runner so both serve
    /// exactly the same endpoints over a real HTTP listener.
    public static class Backend
    {
        public static WebApplication Build(string[] args, Action<DbContextOptionsBuilder> database)
        {
            var builder = WebApplication.CreateBuilder(args);
            builder.Services.AddDbContext<AppDbContext>(database);

            var app = builder.Build();
            app.MapPost("/orders", OrderHandlers.Create);
            app.MapGet("/orders/{id:int}", OrderHandlers.Get);
            app.MapPost("/orders/{id:int}/submit-and-approve", OrderHandlers.SubmitAndApprove);
            app.MapPost("/orders/{id:int}/ship", OrderHandlers.Ship);
            return app;
        }
    }
}
