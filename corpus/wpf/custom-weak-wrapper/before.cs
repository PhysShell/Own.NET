// LEAKY. The ViewModel subscribes to a process-lived settings publisher in its
// constructor and never unsubscribes. An ordinary event subscription is a STRONG
// reference from the publisher to the listener; because the publisher outlives the
// VM and the handler is an instance method, the publisher's invocation list pins
// the VM for the life of the process. Every VM built and dropped leaks its graph.
// OWN001 (owned subscription not released on all paths).
using System.ComponentModel;

public sealed class DocumentViewModel
{
    public DocumentViewModel(ISettings settings)
    {
        settings.PropertyChanged += OnSettingsChanged;   // strong: pins `this`
    }

    private void OnSettingsChanged(object sender, PropertyChangedEventArgs e)
    {
        // recompute a display string when a global setting toggles
    }
}

public interface ISettings : INotifyPropertyChanged { }
