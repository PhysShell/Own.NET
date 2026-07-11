using System;

namespace Own.Samples;

// Issue #218 — DP/property-changed old->new subscription ROTATION must not be flagged as a leak:
// a callback detaches the SAME handler from the OLD value and re-attaches it to the NEW one across
// a value change, so at most one subscription is ever live (no leak). Two recognised forms plus
// three negative controls that must STAY flagged (proving the fix does not over-widen). Stand-in
// types (the extractor build has no WPF ref) mirror the real cases: MahApps CommandTriggerAction,
// MaterialDesign SmartHint, AvalonEdit margins.

public interface ICommand
{
    event EventHandler CanExecuteChanged;
}

// A different type that also exposes CanExecuteChanged — used by a negative control so the
// discriminator is the parameter *types*, not the event/handler names.
public interface IOtherCommand
{
    event EventHandler CanExecuteChanged;
}

// Stand-in for System.Windows.DependencyPropertyChangedEventArgs (matched syntactically by its
// OldValue/NewValue members, the canonical DP-changed shape).
public sealed class DependencyPropertyChangedEventArgs
{
    public object? OldValue { get; init; }
    public object? NewValue { get; init; }
}

public class TextView
{
    public event EventHandler VisualLinesChanged = delegate { };
}

// FORM (1) — DependencyProperty callback, pattern-cast old/new (the MahApps CommandTriggerAction
// shape). unsub OLD, sub NEW, same handler -> one paired lifecycle -> SILENT.
public sealed class CommandTriggerAction
{
    private void OnCommandCanExecuteChanged(object? sender, EventArgs e) { }

    private static void OnCommandChanged(CommandTriggerAction action, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is ICommand oldCommand)
            oldCommand.CanExecuteChanged -= action.OnCommandCanExecuteChanged;   // unsub OLD
        if (e.NewValue is ICommand newCommand)
            newCommand.CanExecuteChanged += action.OnCommandCanExecuteChanged;   // sub NEW -> paired (SILENT)
    }
}

// FORM (2) — plain virtual OnXChanged(old, new) override, two SAME-type parameters (the AvalonEdit
// AbstractMargin shape — not even a DP callback). unsub param0, sub param1, same handler -> SILENT.
public class AbstractMargin
{
    private void OnVisualLinesChanged(object? sender, EventArgs e) { }

    protected virtual void OnTextViewChanged(TextView oldTextView, TextView newTextView)
    {
        if (oldTextView != null)
            oldTextView.VisualLinesChanged -= OnVisualLinesChanged;   // unsub OLD (param 0)
        if (newTextView != null)
            newTextView.VisualLinesChanged += OnVisualLinesChanged;   // sub NEW (param 1) -> paired (SILENT)
    }
}

// NEGATIVE CONTROL (a) — the rotation shape but a DIFFERENT handler on the += than the -=: the new
// subscription is genuinely unpaired (the -= detached a different delegate) -> STAYS FLAGGED.
public sealed class MismatchedHandlerRotation
{
    private void HandlerA(object? sender, EventArgs e) { }
    private void HandlerB(object? sender, EventArgs e) { }

    private static void OnChanged(MismatchedHandlerRotation self, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is ICommand oldCommand)
            oldCommand.CanExecuteChanged -= self.HandlerA;   // unsub OLD with HandlerA
        if (e.NewValue is ICommand newCommand)
            newCommand.CanExecuteChanged += self.HandlerB;   // sub NEW with HandlerB (different!) -> LEAK
    }
}

// NEGATIVE CONTROL (b) — a rotation-LIKE pair outside a property-changed context: two UNRELATED
// parameters of DIFFERENT types (same event/handler names, but not the old/new halves of one value
// change) -> the += is a real unpaired subscription -> STAYS FLAGGED.
public sealed class UnrelatedPairRotation
{
    private void Handler(object? sender, EventArgs e) { }

    private void Wire(ICommand primary, IOtherCommand secondary)
    {
        primary.CanExecuteChanged -= Handler;     // unsub on primary (ICommand)
        secondary.CanExecuteChanged += Handler;   // sub on secondary (IOtherCommand — different type) -> LEAK
    }
}

// NEGATIVE CONTROL (c) — `-=` on one class FIELD, `+=` on another (same event + handler). Fields are
// not the old/new halves of a change; this is two independent subscriptions -> STAYS FLAGGED.
public sealed class TwoFieldsRotation
{
    private ICommand _a = default!;
    private ICommand _b = default!;

    private void Handler(object? sender, EventArgs e) { }

    private void Swap()
    {
        _a.CanExecuteChanged -= Handler;   // unsub on field _a
        _b.CanExecuteChanged += Handler;   // sub on field _b (not an old/new pair) -> LEAK
    }
}
