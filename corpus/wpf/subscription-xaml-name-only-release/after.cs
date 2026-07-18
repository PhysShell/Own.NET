// FIXED. The SAME handler name — but now the ctor provably wires it to the
// view's own Closing lifecycle event (`this.Closing += Window_Closing`), so
// the `-=` inside it runs at teardown. A second class pins the inline-lambda
// form of the same wiring.
//
// own-check MUST treat both as released (silent): the release is credited by
// the code wiring, never by the name.
using System;
using System.ComponentModel;

public sealed class SettingsView
{
    private readonly INotifyPropertyChanged _settings;   // injected, unknown lifetime

    public event EventHandler Closing;                   // raised by the host at teardown

    public SettingsView(INotifyPropertyChanged settings)
    {
        _settings = settings;
        _settings.PropertyChanged += OnSettingsChanged;
        this.Closing += Window_Closing;                  // the wiring is the proof
    }

    private void Window_Closing(object sender, EventArgs e)
    {
        _settings.PropertyChanged -= OnSettingsChanged;
    }

    private void OnSettingsChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}

// The inline-lambda handler on the same lifecycle event — equally wired,
// equally silent.
public sealed class SettingsPane
{
    private readonly INotifyPropertyChanged _settings;   // injected, unknown lifetime

    public event EventHandler Closing;                   // raised by the host at teardown

    public SettingsPane(INotifyPropertyChanged settings)
    {
        _settings = settings;
        _settings.PropertyChanged += OnSettingsChanged;
        this.Closing += (s, e) => _settings.PropertyChanged -= OnSettingsChanged;
    }

    private void OnSettingsChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
