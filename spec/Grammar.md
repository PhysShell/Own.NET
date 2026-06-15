# Grammar

> **Status: normative, descriptive.** Source of truth: `ownlang/lexer.py`,
> `ownlang/parser.py`. The surface syntax of OwnLang — what can be written.
> Semantics of each construct live in the other `spec/` files (linked inline).

## Tokens

- **Reserved keywords:** `module resource acquire release extern fn let move
  borrow borrow_mut consume as use if else return mut policy lifetime subscribe`
  and the emit templates `emit_type emit_acquire emit_release emit_borrow`.
- **Contextual keywords** (plain identifiers except in their one position, *not*
  reserved): `kind` (in a resource body), `self`/`to` (in `subscribe`).
- **Rejected keywords** (lexed only to refuse them, → OWN020): `while for loop
  async await yield spawn`.
- **Punctuation:** `( ) { } , : ; & = . -> <`
- **Literals:** `INT` (digits), `STRING` (`"..."` with `\n \t \" \\`), `IDENT`.
- Line comments `// ...`. No block comments.

## Grammar (EBNF-ish)

```text
module      := "module" IDENT item*
item        := resource | extern | fn | policy | lifetime

resource    := "resource" IDENT "{" rmember* "}"
rmember     := ("acquire" | "release") IDENT
             | ("emit_type"|"emit_acquire"|"emit_release"|"emit_borrow") STRING
             | "kind" STRING
extern      := "extern" "fn" IDENT "(" eparams? ")" ("->" type)? ";"
eparam      := ("borrow" | "borrow_mut" | "consume")? IDENT        // IDENT = type name
policy      := "policy" IDENT "{" (IDENT "=" atom ";")* "}"
lifetime    := "lifetime" IDENT ("<" IDENT)? ";"                   // "<" = shorter-than

fn          := "fn" IDENT "(" params? ")" ("->" type)? ("lifetime" IDENT)? block
param       := IDENT ":" type ("lifetime" IDENT)?
type        := "&" "mut"? IDENT | IDENT                            // "&" = borrow view

block       := "{" stmt* "}"
stmt        := let | release | use | call | borrow | if | return | subscribe
let         := "let" IDENT "=" rhs ";"
rhs         := "acquire" IDENT "(" args? ")" | "move" IDENT | bufferintent | IDENT | INT
bufferintent:= IDENT "." IDENT "(" bargs? ")"                      // e.g. Buffer.scratch(...)
barg        := IDENT "=" atom | atom                               // named option | positional size
release     := "release" IDENT ";"
use         := "use" IDENT ";"
call        := IDENT "(" args? ")" ";"
borrow      := ("borrow" | "borrow_mut") IDENT "as" IDENT block
if          := "if" "(" cond ")" block ("else" block)?            // cond is opaque text
return      := "return" IDENT? ";"
subscribe   := "subscribe" "self" "to" IDENT ";"
args        := atom ("," atom)*
atom        := INT | IDENT
```

## Construct → spec map

| Construct | Declares / does | Spec |
|---|---|---|
| `resource { acquire/release }` | a resource protocol (one acquire verb, one release verb) | [OwnCore §1,§7](OwnCore.md) |
| `resource { emit_* "..." }` | real-.NET lowering templates | [CodegenContract](CodegenContract.md) |
| `resource { kind "..." }` | domain-neutral metadata tag | [Lifetimes §L4](Lifetimes.md) |
| `Buffer.<mode>(size, opts)` | a storage-policy buffer | [BufferPolicies](BufferPolicies.md) |
| `policy P { k = v; }` | reusable buffer defaults | [BufferPolicies §Policies](BufferPolicies.md) |
| `extern fn` / param effects | the call boundary | [OwnCore §8](OwnCore.md) |
| `lifetime` / `subscribe` | regions + strong capture | [Lifetimes](Lifetimes.md) |
| `if` | control flow only — the condition is opaque text, values are not modelled | [OwnCore §10](OwnCore.md) |

Loops and `async` are out of scope and refused at lex time (**OWN020**).
