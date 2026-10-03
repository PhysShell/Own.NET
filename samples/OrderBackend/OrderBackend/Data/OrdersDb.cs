using Microsoft.EntityFrameworkCore;
using OrderBackend.Domain;

namespace OrderBackend.Data;

/// A plain DbContext: no custom base, no repository, no interceptor, no query provider.
public sealed class OrdersDb(DbContextOptions<OrdersDb> options) : DbContext(options)
{
    public DbSet<Order> Orders => Set<Order>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Order>(order =>
        {
            order.HasKey(o => o.Id);
            order.Property(o => o.Customer).IsRequired();
            // the exact member name, strictly: an unknown stored value is an exception at
            // materialization, never a state (OrderStatusStorage is generated)
            order.Property(o => o.Status).HasConversion(
                state => OrderStatusStorage.ToStore(state),
                raw => OrderStatusStorage.FromStore(raw));
        });
    }
}
