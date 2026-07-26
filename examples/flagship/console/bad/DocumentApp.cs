// The flagship console leak (the #278 shape, minus the corporate archaeology).
//
// A static publisher lives for the whole process. Every "document view"
// subscribes in its constructor. An unsubscribe EXISTS — `Cleanup` — but it
// sits behind a parameter guard, and the close path calls `Cleanup(keepAlive:
// true)`, so the `-=` never runs. Every closed view stays reachable through
// the publisher's delegate list: the process accumulates one dead view per
// open/close cycle, forever.
//
// This is exactly the bug class where "a matching -= exists somewhere in the
// class" reads as safe. Owen does not accept existence as evidence: a
// parameter-guarded `-=` in a non-teardown method cannot be proven to run, so
// the subscription is flagged (OWN001).
//
// Run it:            dotnet run --project examples/flagship/console/bad
// Analyze it:        owen check examples/flagship/console/bad --fail-on-finding
using System;
using System.ComponentModel;

namespace Owen.Flagship;

/// <summary>Process-lifetime settings hub (the static publisher).</summary>
public sealed class AppSettings : INotifyPropertyChanged
{
    public static readonly AppSettings Instance = new();

    public event PropertyChangedEventHandler? PropertyChanged;

    public int SubscriberCount => PropertyChanged?.GetInvocationList().Length ?? 0;

    public void Touch() =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs("Theme"));
}

/// <summary>Opened per document; subscribes to the process-lifetime hub.</summary>
public sealed class DocumentView
{
    private readonly AppSettings _settings;

    public DocumentView(AppSettings settings)
    {
        _settings = settings;
        _settings.PropertyChanged += OnSettingsChanged;
    }

    private void OnSettingsChanged(object? sender, PropertyChangedEventArgs e)
    {
        // re-render with the new settings
    }

    public void Cleanup(bool keepAlive)
    {
        if (!keepAlive)
        {
            _settings.PropertyChanged -= OnSettingsChanged;
        }
        // detach only the cheap extras when the caller asked to keep the core
    }

    // The bug: every close path keeps the core subscription alive.
    public void Close() => Cleanup(keepAlive: true);
}

public static class Program
{
    public static void Main()
    {
        for (var i = 0; i < 1000; i++)
        {
            var view = new DocumentView(AppSettings.Instance);
            view.Close();
        }
        GC.Collect();
        GC.WaitForPendingFinalizers();
        GC.Collect();
        Console.WriteLine(
            $"opened and closed 1000 views; " +
            $"{AppSettings.Instance.SubscriberCount} still subscribed — " +
            "every one of them is retained by the static publisher.");
        if (Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_HOLD") == "1")
        {
            // Keep the heap alive for a runtime witness (the demo script and
            // the CI end-to-end smoke attach retention-path to this process).
            Console.WriteLine($"holding (pid {Environment.ProcessId}) — send a line to exit.");
            Console.ReadLine();
        }
    }
}
