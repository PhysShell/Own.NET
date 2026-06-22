using System;
using System.Threading.Tasks;

namespace Own.Samples;

// P-004 static-context exemption (mined from ScreenToGif's ProcessHelper).
//
// A `+=` lexically inside a STATIC member has no enclosing `this`, so the handler —
// a method group or a lambda over locals/parameters/statics — retains no instance of
// the enclosing type. The "keeps <Type> alive" subscriber leak is then structurally
// impossible, so these subscriptions must stay SILENT. The negative control
// (`InstanceSetup`) proves the skip does NOT bleed into ordinary instance
// subscriptions to an injected source, which must still WARN (OWN001).
public interface IPublisher
{
    event EventHandler Fired;
}

// ScreenToGif's `static ProcessHelper.RestartAsAdmin`: a static helper subscribes a
// method-local publisher's event with a lambda capturing only locals. No instance of
// the static class exists -> nothing to leak -> SILENT.
public static class StaticHelperSubscription
{
    public static bool Run(IPublisher publisher)
    {
        var done = new TaskCompletionSource<bool>();
        publisher.Fired += (s, e) => done.SetResult(true);
        return done.Task.Result;
    }
}

public class MixedSubscription
{
    private readonly IPublisher _bus;

    public MixedSubscription(IPublisher bus) => _bus = bus;

    // A static method on an INSTANCE class is still a static context (no `this`),
    // so this subscription to the parameter's event must also stay SILENT.
    public static void StaticSetup(IPublisher publisher)
    {
        publisher.Fired += (s, e) => Console.WriteLine("static");
    }

    // Control: an INSTANCE method subscribing an instance handler to an INJECTED
    // source (a ctor-param bus of unknown lifetime) is the classic leak -> must WARN.
    public void InstanceSetup()
    {
        _bus.Fired += OnFired;
    }

    private void OnFired(object sender, EventArgs e) => Console.WriteLine(_bus);
}
