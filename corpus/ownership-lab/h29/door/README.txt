P-OWN053-DOOR: orphaned_awaitables[] bound at both OwnIR strict doors (after the OWN053 promotion;
prereg frozen in Own.NET-paperwork before code). Produced by the PRODUCTION build of this tree, from
the repository root.

promo-u.door.py.txt / promo-u.door.rust.txt
    ../promotion/promo-u.facts.json through both CLIs, whose path IS the strict door: accepted,
    5 advisory OWN053, 0 findings, exit 0, Python == Rust -- the rule and the message did not move.
neg-garbage.facts.json      an entry whose local is a list, callee an object, result_type a number
                            (the exact shape the unbound list rendered as a real OWN053)
neg-line_above.facts.json   an entry with line 2147483648 (above the §4.2 domain; the unbound
                            list degraded it to 0)
neg-family.facts.json       an entry with family "C_whatever" (outside the closed set)
neg-*.py.txt / neg-*.rust.txt
    both CLIs refuse each document with exit code 2 (ordinary bad input) naming the same rule;
    the message text differs by language, as the cp1 ledger allows (verdict + category are the
    cross-language contract, tests/fixtures/ownir_validation.json section orphaned_awaitables).
