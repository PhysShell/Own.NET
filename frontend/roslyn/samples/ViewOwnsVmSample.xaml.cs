using System;

namespace Own.Samples.Wpf;

// P-004 WPF MVVM ownership (mined: ScreenToGif VideoSource). This view constructs its
// view-model in its OWN XAML (`<...DataContext><OwnedVm/></...DataContext>` — see the
// sibling ViewOwnsVmSample.xaml), so it OWNS the VM: the view<->VM reference cycle is
// GC-collectable and subscribing to the VM's events is NOT a leak. The extractor reads
// the sibling `.xaml` to see this (it parses only `.cs` otherwise). Must be SILENT.
public partial class ViewOwnsVm
{
    private readonly OwnedVm _vm;

    public ViewOwnsVm()
    {
        _vm = DataContext as OwnedVm;
    }

    public void OnLoaded()
    {
        _vm.Changed += OnChanged;        // owned source -> collectable cycle -> silent
    }

    private void OnChanged(object sender, EventArgs e) { }
}

public class OwnedVm
{
    public event EventHandler Changed;
}
