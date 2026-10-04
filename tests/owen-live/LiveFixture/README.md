# OX-02 live fixture

The sources of the small project the live gate (`scripts/owen_live_gate.py`) and the real
Visual Studio run (`scripts/vs/owen-vs-acceptance.ps1`) analyse. Stored as `.cs.txt` so no
scan of this repository picks them up; both copy them, as `.cs`, into a project created
outside the checkout that references `Owen.TypedBuilder` (and, for K8, `Owen.TestProtocol`).

- `Order.cs` — the TB-MVP `Order`, declared for the Typed Builder generator.
- `Use.cs` — one clean `WithDraft` region. The acceptance inserts a second
  `draft.Submit(now);` after `var submitted = draft.Submit(now);` (OWN002) and deletes it.
- `Gate.cs` — the synthetic second extension's turnstile, clean (K8 inserts a second
  `locked.Coin();`).
