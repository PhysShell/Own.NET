# Owen extensions: the build-host contract (schema 1)

Status: **implemented** in `Owen.Build` 0.1.0 (OX-01,
[`docs/notes/owen-extension-alpha-preregistration.md`](../docs/notes/owen-extension-alpha-preregistration.md)).
Extension #1 is `Owen.TypedBuilder`.

An **Owen extension** is a NuGet package that adds a frontend capability to Owen (a generator,
a vocabulary, a family of facts). It is checked by the **one** generic host, `Owen.Build`.

An extension does **not** bring:
- its own checker;
- its own engine copy;
- its own MSBuild wiring;
- its own IDE plugin.

There is one host for every extension, and at most one future IDE host and one future
language/diagnostic server.

## 1. Declaring an extension

The package depends on `Owen.Build`, with every asset flowing, and adds one item from its
`build/` and `buildTransitive/` props:

```xml
<ItemGroup>
  <OwenExtensionDescriptor Include="$(MSBuildThisFileDirectory)owen-extension.json" />
</ItemGroup>
```

The descriptor (JSON, [`owen-extension.schema.json`](owen-extension.schema.json)):

```json
{
  "owen_extension": 1,
  "id": "Owen.TypedBuilder",
  "version": "0.1.0",
  "requires": {
    "host": "0.1.0",
    "ownir": 2,
    "capabilities": ["ownership", "state-protocol", "heap-effects", "proven-call"]
  },
  "frontend": { "generators": ["Owen.TypedBuilder.Generator"] }
}
```

| field | meaning |
|---|---|
| `owen_extension` | the descriptor schema. The host reads exactly `1`. |
| `id`, `version` | the package identity. `id` is unique among a project's active extensions. |
| `requires.host` | the lowest `Owen.Build` version that serves the extension |
| `requires.ownir` | the OwnIR version (spec/OwnIR.md §2) the extension's facts assume |
| `requires.capabilities` | what the analysis must do for the extension |
| `frontend.generators` | Roslyn generator assembly names whose output must be scanned **as source**. An extension's protocol lives in generated code, and the extractor's own expansion skips generated files. |

Unknown extra fields are ignored. Anything the host must understand to stay sound is
`requires`, and `requires` fails closed.

## 2. What host 0.1.0 provides

| item | value |
|---|---|
| OwnIR | `2` |
| capabilities | `ownership` (OWN001/002/005/013…), `state-protocol` (`[ProtocolToken]` / `[ProtocolRegion]`, `borrow_mut`, `move`), `heap-effects` (H0 summaries), `proven-call` (H1) |
| platforms | `linux-x64`, `win-x64` |

A capability is added only when the packed extractor and core actually perform it.

## 3. What the host does on every build

**When:** after `CopyFilesToOutputDirectory`. The target is skipped in design-time builds and
when `OwenEnabled=false`.

1. **Validate** every descriptor (§4). Any violation is an error, and nothing is analysed.
2. **Write the manifest** `obj/owen/extensions.json`: the host version, OwnIR, and the active extensions sorted by `id`.
3. **Scan** the project, plus every C# file the declared generators wrote, named explicitly. The props set `EmitCompilerGeneratedFiles=true`.
4. **Judge** with the packed Rust core, once for all extensions, with `--format msbuild --severity $(OwenSeverity)`. The findings pass through as the core rendered them. Only the origin path is made absolute against the project directory, so the Error List never has to guess a base.

The host runs `owen build-check`, the `Owen.Cli` program packed in `Owen.Build`'s `tools/`,
through the `dotnet` that runs the build (`DOTNET_HOST_PATH`). It never searches PATH for any
Owen binary. The Rust core is resolved exactly as by `owen check` (the D6 packaged path). The
host source names no extension.

| property | default | |
|---|---|---|
| `OwenSeverity` | `warning` | `error` makes findings fail the build. Only how a finding is shown changes, never what is found. |
| `OwenEnabled` | `true` | |
| `OwenEmitFacts` | (none) | also write the OwnIR facts to this path |

## 4. Host diagnostics (`OWENB`)

| code | when | severity |
|---|---|---|
| OWENB001 | `Owen.Build` is referenced but no extension is declared; nothing is analysed | warning |
| OWENB002 | a descriptor cannot be read, has another schema, a missing or ill-typed field, or a duplicate `id` | error |
| OWENB003 | an incompatible extension: `requires.ownir` ≠ the host's, or `requires.host` newer than the host | error |
| OWENB004 | a required capability the host does not provide | error |
| OWENB005 | no packed Rust core for this platform, or it cannot be started | error |
| OWENB010 | the extractor refused a construct it cannot lower safely, at the refused `file(line)` | error |
| OWENB011 | the core refused the facts (e.g. a `proven_call` not proven harmless), at the `file(line)` it names | error |
| OWENB012 | an internal failure of the host or of a child process | error |

**Refusals are always errors**, whatever `OwenSeverity` says. They arise only in a protocol the
developer declared, and "could not be checked" must never read as clean.

**Generator diagnostic:** `OWENTB001` (Typed Builder) means a refused declaration, one error per
defect.

## 5. What the contract deliberately does not have

- **Dynamic loading of analysis code.** Extensions add frontends and vocabulary. The analysis is the one Rust core, and its semantics change only through OwnIR (spec/OwnIR.md).
- **Per-extension IDE integration.** A future `Owen.VisualStudio` or language server serves every active extension from the same manifest.
- **Version ranges.** `requires.host` is a lower bound. The host refuses what it does not understand; it does not guess.
