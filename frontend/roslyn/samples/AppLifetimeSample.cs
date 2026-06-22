using System;
using System.Windows;

namespace Own.Samples.WpfApp;

// P-004 process-lived-subscriber exemption (mined from ScreenToGif + its Translator).
//
// The WPF application object (`App`) is a process-lived singleton: subscribing it to
// a process-lived static event (AppDomain.CurrentDomain.UnhandledException) is the
// textbook global-exception hook and promotes nothing — App already lives for the
// whole process. So the static-source region escape (OWN014) must NOT fire on it.
// Two detection shapes, both must stay SILENT:

// (1) name-based: ScreenToGif's real shape — `partial class App` whose `: Application`
//     lives in the generated `App.g.cs` partial the extractor never sees (here the
//     only visible base is IDisposable).
public partial class App : IDisposable
{
    private void App_Startup(object sender, EventArgs e)
    {
        AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;
    }

    private void CurrentDomain_UnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        Console.WriteLine(e.ExceptionObject);
    }

    public void Dispose() { }
}

// (2) base-based: a custom-named application object deriving from `Application`
//     directly in the .cs (the base stays unresolved on the Linux runner, but the
//     syntactic base-name detection still applies).
public class BootstrapApp : Application
{
    public void Init()
    {
        AppDomain.CurrentDomain.UnhandledException += OnUnhandled;
    }

    private void OnUnhandled(object sender, UnhandledExceptionEventArgs e)
    {
        Console.WriteLine(e.ExceptionObject);
    }
}
