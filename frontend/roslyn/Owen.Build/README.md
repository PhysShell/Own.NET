# Owen.Build

The Owen build host. You normally do not reference it yourself: the Owen extensions you
reference depend on it.

On every `dotnet build`, after compilation, it runs Owen once for every active Owen
extension:
- the Roslyn extractor and the Rust analysis core, both shipped inside this package;
- no Python, no Rust toolchain, no global tool;
- findings are reported as ordinary build diagnostics (`file(line): warning OWNxxx: …`),
  including in Visual Studio's Error List.

| property | default | meaning |
|---|---|---|
| `OwenSeverity` | `warning` | `error` makes findings fail the build |
| `OwenEnabled` | `true` | `false` turns the host off |

Each project's active extensions are listed in `obj/owen/extensions.json`. Host errors use
the `OWENB` codes; see `spec/OwenExtension.md` in the Owen repository. Platforms: `linux-x64`
and `win-x64`.
