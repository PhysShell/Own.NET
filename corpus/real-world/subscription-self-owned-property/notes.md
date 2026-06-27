# subscription-self-owned-property

An event subscription whose SOURCE is a member the component **owns** — accessed
through a get-only **property** — is a collectable self-cycle, not a leak. Mined on
protobuf-net's `CommandLineOptions`:

```csharp
private readonly XsltArgumentList xsltOptions = new XsltArgumentList();
public  XsltArgumentList XsltOptions => xsltOptions;          // get-only, owned
...
XsltOptions.XsltMessageEncountered += delegate { messageCount++; };  // handler captures `this`
```

The owned `XsltArgumentList`, the `CommandLineOptions` instance, and the handler form
one object graph the GC collects together — no `-=` needed.

- **before.cs** — the same subscription on an **injected** `Bus` (external, unknown
  lifetime), never detached → a real subscription leak (`OWN001`, warning: the source
  may outlive `this`).
- **after.cs** — the source is now a **get-only property over a constructed field** the
  component owns → self-cycle → **silent**.

## Recognition rule

The self-owned-source exemption already drops a subscription whose source is `this`, or
a field/local the class constructs (`owned`). This case adds the missing receiver shape:
a `this`-instance **get-only property** whose value the class owns —
`PropertyReturnsOwnedMember`:

- an auto-property `public T X { get; } = new T();` (value constructed in place), or
- a getter that returns a constructed member: `=> _owned`, `get => _owned`, or
  `get { return _owned; }` where the returned field/property is in `owned`.

**Get-only is required.** A settable property could be reassigned to an injected,
longer-lived object after construction, which we cannot prove bounded — so a property
with any setter falls through to the honest "injected" warning (precision-first: never
silently drop a real leak). Computed getters and getters returning a parameter/injected
field likewise fall through.
