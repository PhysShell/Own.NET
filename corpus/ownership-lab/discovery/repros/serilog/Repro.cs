using Serilog;
using Serilog.Core;

// minimal repro of the Serilog discovery class: LoggerConfiguration.CreateLogger (WITNESSED fresh: SERI-W1)
public static class Repro
{
    // finding site: the Logger (owning its sinks) is never disposed -> Own.NET KEY OWN001 expected; OFF silent
    public static void Leak()
    {
        var log = new LoggerConfiguration().CreateLogger();
        log.Information("hello");
    }

    // control: disposed -> no finding expected
    public static void Ok()
    {
        using var log = new LoggerConfiguration().CreateLogger();
        log.Information("hello");
    }

    // control: the ambient-context bookmark (BODY_PROVED LogContext.Push / WITNESSED PushProperty) discarded
    // as an expression statement: not a local, so Own.NET has no site to report; IDISP004 territory
    public static void DiscardedScope()
    {
        Serilog.Context.LogContext.PushProperty("k", 1);
    }
}
