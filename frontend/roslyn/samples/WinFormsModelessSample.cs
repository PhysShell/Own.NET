using System;

// P-016 precision (--flow-locals): WinForms owns a *modeless* form's lifetime.
// A form shown modeless via Form.Show() is disposed by the framework when the user
// closes it, so the extractor models that Show() as a RELEASE at the show site —
// ownership transfers to the framework there (the same call-site release shape as
// pool Return and the consume contract). Because it is modeled per-path, not as a
// method-wide exemption, a form shown only on one branch still leaks on the branch
// that never shows it (see OpenModelessConditional). A *modal* dialog shown via
// ShowDialog() is the caller's to dispose: ShowDialog is NOT a release, so it stays
// tracked, and an undisposed one is a real OWN001.
//
// Reduced from a false positive found mining ShareX (WinForms), where our WPF-tuned
// local-disposable detector over-fired on the idiomatic `new SomeForm().Show()`.
//
// Self-contained: the stub System.Windows.Forms.Form below stands in for the
// framework type (the WinForms reference pack is not loaded in this flow step). The
// extractor matches Form by simple name + `System.Windows.Forms` namespace, walking
// the base chain, so these stubs reproduce the real shape exactly.
public class WinFormsModelessSample
{
    // NOT a leak: a modeless form (`.Show()`) transfers ownership to the framework
    // on that path -> acquire+release balanced -> silent (the precision fix; was a
    // false OWN001 before).
    public void OpenModeless()
    {
        var modeless = new ModelessForm();
        modeless.Show();
    }

    // OWN001 (recall, Codex review on PR #57): a form shown only on ONE branch leaks
    // on the path that never shows it. Show() is a release AT THE SHOW SITE, so the
    // `open == false` path — construct, never shown, never disposed — is correctly
    // caught ('condForm' may not be disposed on every path). A method-wide exemption
    // would have wrongly silenced this.
    public void OpenModelessConditional(bool open)
    {
        var condForm = new ModelessForm();
        if (open)
            condForm.Show();
    }

    // OWN001: a modal dialog (`.ShowDialog()`) is the caller's to dispose; this one
    // never is -> real leak. ShowDialog() is NOT modeled as a release (only Show is).
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
