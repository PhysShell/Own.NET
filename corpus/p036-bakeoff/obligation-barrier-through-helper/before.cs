// BUGGY (synthetic conformance, #272 / #274 — an obligation protocol crossing a
// helper). `IsLoaded = false` opens the DocumentLoading obligation; publishing
// `PropertyChanged("Document")` while it is open is the forbidden barrier.
// The barrier is raised INSIDE the helper `Rebuild()`, so only a summary of
// the helper's effects (notify(Document): may) can see it from the caller.
// No general-purpose analyzer knows what `IsLoaded` means; this is a
// project-declared protocol, not a universal rule.
using System.ComponentModel;

public sealed class DocumentViewModel : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler PropertyChanged;

    public bool IsLoaded { get; private set; } = true;
    public string Document { get; private set; } = "";

    public void Reload(string text)
    {
        IsLoaded = false;                                    // opens DocumentLoading
        Rebuild(text);                                       // helper raises the barrier
        IsLoaded = true;                                     // closes it — too late
    }

    private void Rebuild(string text)
    {
        Document = text;
        OnPropertyChanged(nameof(Document));                 // forbidden while loading
    }

    private void OnPropertyChanged(string name) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
