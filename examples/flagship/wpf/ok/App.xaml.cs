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

        GC.Collect();
        GC.WaitForPendingFinalizers();
        GC.Collect();

        Console.WriteLine(
            $"opened and closed {Cycles} document windows; " +
            $"{AppSettings.Instance.SubscriberCount} still subscribed.");

        Hold.IfAsked();
        Shutdown();
    }
}
