// The fix for the flagship WPF leak: teardown belongs in a teardown.
//
// The subscription is released in `OnClosed` — the method WPF itself calls at
// the end of a window's life — unconditionally, with no parameter to get it
// wrong. Owen treats a `-=` in a real teardown as a provable release, so this
// variant scans clean; at runtime the hub's delegate list is empty once the
// windows are closed.
//
// The whole diff against `bad/` is where the `-=` lives.
using System;
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
        Render();
    }

    private void OnSettingsChanged(object? sender, PropertyChangedEventArgs e) => Render();

    private void Render() => ThemeText.Text = $"theme: {_settings.Theme}";

    protected override void OnClosed(EventArgs e)
    {
        _settings.PropertyChanged -= OnSettingsChanged;
        base.OnClosed(e);
    }
}
