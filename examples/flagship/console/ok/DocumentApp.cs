// The fix for the flagship console leak: teardown belongs in a teardown.
//
// The subscription is released in `Dispose()` — unconditionally, on every
// close path. Owen treats a `-=` in a real teardown as a provable release, so
// this variant scans clean; at runtime the publisher's delegate list stays
// empty after the views are closed.
//
// Run it:            dotnet run --project examples/flagship/console/ok
// Analyze it:        owen check examples/flagship/console/ok --fail-on-finding
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
public sealed class DocumentView : IDisposable
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

    public void Dispose()
    {
        _settings.PropertyChanged -= OnSettingsChanged;
    }

    // Every close path releases the subscription.
    public void Close() => Dispose();
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
            $"{AppSettings.Instance.SubscriberCount} still subscribed.");
        if (Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_HOLD") == "1")
        {
            // Keep the heap alive for a runtime witness (the demo script and
            // the CI end-to-end smoke attach retention-path to this process).
            Console.WriteLine($"holding (pid {Environment.ProcessId}) — send a line to exit.");
            Console.ReadLine();
        }
    }
}
