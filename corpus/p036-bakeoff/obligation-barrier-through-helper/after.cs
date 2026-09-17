// FIXED (synthetic conformance). The helper only mutates; the notification is
// published after the obligation is closed.
using System.ComponentModel;

public sealed class DocumentViewModel : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler PropertyChanged;

    public bool IsLoaded { get; private set; } = true;
    public string Document { get; private set; } = "";

    public void Reload(string text)
    {
        IsLoaded = false;
        Rebuild(text);
        IsLoaded = true;
        OnPropertyChanged(nameof(Document));                 // published after close
    }

    private void Rebuild(string text)
    {
        Document = text;
    }

    private void OnPropertyChanged(string name) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
