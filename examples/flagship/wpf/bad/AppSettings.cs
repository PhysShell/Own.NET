// The process-lifetime publisher — the WPF idiom, unchanged from a thousand
// real apps: one settings hub, reachable from anywhere, raising
// PropertyChanged so that every open view re-renders itself.
//
// Nothing here is wrong. The bug is in what subscribes to it and never leaves.
using System.ComponentModel;

namespace Owen.Flagship.Wpf;

/// <summary>Static settings hub; lives as long as the process does.</summary>
public sealed class AppSettings : INotifyPropertyChanged
{
    public static readonly AppSettings Instance = new();

    public event PropertyChangedEventHandler? PropertyChanged;

    private string _theme = "Light";

    public string Theme
    {
        get => _theme;
        set
        {
            if (_theme == value) return;
            _theme = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Theme)));
        }
    }

    /// <summary>How many handlers the publisher is still holding — the leak,
    /// counted by the leaking program itself.</summary>
    public int SubscriberCount => PropertyChanged?.GetInvocationList().Length ?? 0;
}
