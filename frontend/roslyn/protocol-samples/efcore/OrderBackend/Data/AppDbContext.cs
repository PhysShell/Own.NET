using Microsoft.EntityFrameworkCore;
using OrderBackend.Domain;

namespace OrderBackend.Data;

/// A plain DbContext: no custom base, no repository, no interceptor.
public sealed class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<Order> Orders => Set<Order>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Order>(order =>
        {
            order.HasKey(o => o.Id);
            order.Property(o => o.Status).HasConversion<string>();
        });
    }
}
