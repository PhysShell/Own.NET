// The flagship leak in its native habitat (the #278 shape, WPF edition).
//
// A document window subscribes to the process-lifetime settings hub in its
// constructor so it can restyle itself when the theme changes. An unsubscribe
// EXISTS — `Cleanup` — but it sits behind a parameter guard, and the close
// path calls `Cleanup(keepAlive: true)`, so the `-=` never runs. Every closed
// window stays reachable through the hub's delegate list: its whole visual
// tree, its data context, its images — all of it, one leaked window per
// document the user ever opened.
//
// This is exactly the bug class where "a matching -= exists somewhere in the
// class" reads as safe. Owen does not accept existence as evidence: a
// parameter-guarded `-=` in a non-teardown method cannot be proven to run, so
// the subscription is flagged (OWN001).
using System.ComponentModel;
using System.Windows;

namespace Owen.Flagship.Wpf;

public partial class DocumentWindow : Window
{
    private readonly AppSettings _settings;

    public DocumentWindow(AppSettings settings)
    {
        InitializeComponent();
        _settings = settings;
        _settings.PropertyChanged += OnSettingsChanged;
        Closed += (_, _) => Cleanup(keepAlive: true);
        Render();
    }

    private void OnSettingsChanged(object? sender, PropertyChangedEventArgs e) => Render();

    private void Render() => ThemeText.Text = $"theme: {_settings.Theme}";

    public void Cleanup(bool keepAlive)
    {
        if (!keepAlive)
        {
            _settings.PropertyChanged -= OnSettingsChanged;
        }
        // detach only the cheap extras when the caller asked to keep the core
    }
}
