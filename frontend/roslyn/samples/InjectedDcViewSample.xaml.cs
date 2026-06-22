using System;

namespace Own.Samples.Wpf;

// Negative control for the XAML-ownership exemption. This view's XAML BINDS its
// DataContext (`<Window.DataContext><Binding/></...>` — see the sibling
// InjectedDcViewSample.xaml): it does NOT construct the VM, the DataContext is
// inherited / externally supplied and may outlive the view. So the field is NOT owned
// and the subscription must still WARN (OWN001). This proves the gate suppresses only
// PROVEN construction, not every `DataContext as T`.
public partial class InjectedDcView
{
    private readonly InjectedVm _vm;

    public InjectedDcView()
    {
        _vm = DataContext as InjectedVm;
    }

    public void OnLoaded()
    {
        _vm.Changed += OnChanged;        // unowned source -> possible leak -> warns
    }

    private void OnChanged(object sender, EventArgs e) { }
}

public class InjectedVm
{
    public event EventHandler Changed;
}
