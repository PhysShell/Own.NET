// The driver: open and close document windows the way a user would, then ask
// the publisher how many of them it is still holding. The program proves its
// own leak — no profiler required to see the number.
//
// Run it (Windows):  dotnet run --project examples/flagship/wpf/bad
// Analyze it:        owen check examples/flagship/wpf/bad --fail-on-finding
using System;
using System.Windows;
using System.Windows.Threading;

namespace Owen.Flagship.Wpf;

public partial class App : Application
{
    private const int Cycles = 200;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        // Show()/Close() are message-driven. Driving them straight from
        // OnStartup would run them before the loop that delivers those
        // messages exists, so the cycle is queued onto the dispatcher and
        // runs once the application is pumping.
        Dispatcher.BeginInvoke(new Action(OpenAndCloseDocuments), DispatcherPriority.ApplicationIdle);
    }

    private void OpenAndCloseDocuments()
    {
        for (var i = 0; i < Cycles; i++)
        {
            var window = new DocumentWindow(AppSettings.Instance);
            window.Show();
            window.Close();
        }

        // Measure only after WPF has finished tearing the closed windows down.
        // `Close()` completes through the dispatcher, so counting (or holding)
        // right here would report the framework mid-teardown rather than the
        // steady state — which is exactly what a witness would then see.
        Dispatcher.BeginInvoke(new Action(ReportAndHold), DispatcherPriority.SystemIdle);
    }

    private void ReportAndHold()
    {
        // Whatever survives this is retained by a live reference, not by
        // collection lag.
        GC.Collect();
        GC.WaitForPendingFinalizers();
        GC.Collect();

        Console.WriteLine(
            $"opened and closed {Cycles} document windows; " +
            $"{AppSettings.Instance.SubscriberCount} still subscribed — " +
            "every one of them, with its whole visual tree, is retained by the " +
            "static settings hub.");

        if (!Hold.Requested)
        {
            Shutdown();
            return;
        }

        // Hold with the message loop STILL RUNNING (see Hold.cs): a parked UI
        // thread is indistinguishable, to a witness, from a leak.
        Hold.Announce();
        DateTime deadline = DateTime.UtcNow.AddSeconds(Hold.Seconds);
        var timer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(200),
        };
        timer.Tick += (_, _) =>
        {
            if (!Hold.ShouldRelease(deadline)) return;
            timer.Stop();
            Shutdown();
        };
        timer.Start();
    }
}
