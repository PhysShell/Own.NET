using System;
using Microsoft.AspNetCore.Builder;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using OrderBackend;
using OrderBackend.Data;

var app = Backend.Build(args, options => options.UseSqlite("Data Source=orders.db"), TimeProvider.System);

using (var scope = app.Services.CreateScope())
    scope.ServiceProvider.GetRequiredService<OrdersDb>().Database.EnsureCreated();

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
        public static WebApplication Build(string[] args, Action<DbContextOptionsBuilder> database, TimeProvider clock)
        {
            var builder = WebApplication.CreateBuilder(args);
            builder.Services.AddDbContext<OrdersDb>(database);
            builder.Services.AddSingleton(clock);

            var app = builder.Build();
            app.MapPost("/orders", OrderEndpoints.Create);
            app.MapGet("/orders", OrderEndpoints.List);
            app.MapGet("/orders/{id:int}", OrderEndpoints.Get);
            app.MapPost("/orders/{id:int}/submit", OrderEndpoints.Submit);
            app.MapPost("/orders/{id:int}/approve", OrderEndpoints.Approve);
            app.MapPost("/orders/{id:int}/ship", OrderEndpoints.Ship);
            return app;
        }
    }
}
