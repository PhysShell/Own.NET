# subscription-static-class-host

A subscription to a process-lived static event (`AppDomain.ProcessExit`,
`Console.CancelKeyPress`) from inside a **`static class`** is not an OWN014 region
escape. Mined on CsvHelper's static `ConsoleHost`:

```csharp
public static class ConsoleHost
{
    // ...
    AppDomain.CurrentDomain.ProcessExit += delegate { ShutDown(); };
    Console.CancelKeyPress += (sender, eventArgs) => { ShutDown(); eventArgs.Cancel = true; };
}
```

OWN014's premise is that a long-lived source **promotes the subscribing component
instance** to its lifetime (the zombie pattern). A `static class` has **no instance** —
the promotion target does not exist, and the class's own state is process-lived by the
language definition. So the finding is vacuously false.

- **before.cs** — an **instance** `Host` subscribes a `this`-capturing handler to
  `Console.CancelKeyPress` (process-lived static event), never `-=` → real `OWN014`
  (the source pins the instance for the whole process).
- **after.cs** — the host is a `static class` → no instance to promote → **silent**.

## Recognition rule

The static-source region-escape exemption already drops a subscription whose subscriber
is the process-lived WPF `App` singleton (`IsProcessLivedApplication`) — it cannot be
over-promoted. This adds the analogous, **language-guaranteed** case: a `static class`
subscriber (`clsIsStatic`). Both gate the same `source == "static"` (process-lived
source) region escape, and both are scoped to NON-timers (a never-stopped timer is a
real leak regardless of who owns it).

This is sound, not a heuristic: `static class` is a compile-time guarantee of no
instances. It does **not** suppress an instance class's subscription, nor a static
class's subscription to a *shorter-lived* (non-static) source — only the process-lived
source escape, where there is provably nothing to over-promote.
