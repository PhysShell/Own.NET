// The driver, unchanged from `bad/`: open and close document windows the way a
// user would, then ask the publisher how many of them it is still holding.
// Same program, same windows, same subscription — the count is zero because
// the release moved into a teardown.
//
// Run it (Windows):  dotnet run --project examples/flagship/wpf/ok
// Analyze it:        owen check examples/flagship/wpf/ok --fail-on-finding
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
            $"{AppSettings.Instance.SubscriberCount} still subscribed.");

        if (!Hold.Requested)
        {
            Shutdown();
            return;
        }

        // Hold with the message loop STILL RUNNING (see Hold.cs): a parked UI
        // thread is indistinguishable, to a witness, from a leak.
        Hold.Announce();
        var timer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(200),
        };
        timer.Tick += (_, _) =>
        {
            if (!Hold.ShouldRelease()) return;
            timer.Stop();
            Shutdown();
        };
        timer.Start();
    }
}
