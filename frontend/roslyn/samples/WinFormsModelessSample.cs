using System;

// P-016 precision (--flow-locals): WinForms owns a *modeless* form's lifetime.
// A form shown modeless via Form.Show() is disposed by the framework when the user
// closes it, so an undisposed local is NOT a leak — the flow detector exempts it
// (IsModelessShownForm in the extractor). A *modal* dialog shown via ShowDialog() is
// the caller's to dispose: it stays tracked, and an undisposed one is a real OWN001.
// Reduced from a false positive found mining ShareX (WinForms), where our WPF-tuned
// local-disposable detector over-fired on the idiomatic `new SomeForm().Show()`.
//
// Self-contained: the stub System.Windows.Forms.Form below stands in for the
// framework type (the WinForms reference pack is not loaded in this flow step). The
// extractor matches Form by simple name + `System.Windows.Forms` namespace, walking
// the base chain, so these stubs reproduce the real shape exactly.
public class WinFormsModelessSample
{
    // NOT a leak: a modeless form (`.Show()`) is owned by the framework, which
    // disposes it on close -> silent (the precision fix; was a false OWN001 before).
    public void OpenModeless()
    {
        var modeless = new ModelessForm();
        modeless.Show();
    }

    // OWN001: a modal dialog (`.ShowDialog()`) is the caller's to dispose; this one
    // never is -> real leak. The Show()-only exemption deliberately does not cover it.
    public void OpenModalLeak()
    {
        var modalLeak = new ModalDialog();
        modalLeak.ShowDialog();
    }

    // NOT a leak: the same modal dialog, this time disposed on every path -> silent.
    // Proves the ShowDialog leak above is about disposal (not poisoned by ShowDialog
    // itself): ShowDialog + Dispose is balanced, ShowDialog alone leaks.
    public void OpenModalOk()
    {
        var modalOk = new ModalDialog();
        modalOk.ShowDialog();
        modalOk.Dispose();
    }
}

public class ModelessForm : System.Windows.Forms.Form { }

public class ModalDialog : System.Windows.Forms.Form { }

// Stub standing in for the WinForms framework type (the reference pack is not loaded
// in the self-contained flow step). The extractor matches Form by simple name +
// `System.Windows.Forms` namespace, so this reproduces the real ownership shape.
namespace System.Windows.Forms
{
    public class Form : System.IDisposable
    {
        public void Show() { }
        public int ShowDialog() => 0;
        public void Dispose() { }
    }
}
