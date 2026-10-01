ownership-semantics-lab H-29 -> OWN053 promotion: the fixture re-run on the PROMOTED build.

Build: frontend/roslyn/OwnSharp.Extractor at the promotion commit (net8.0, Release,
--no-incremental), the research flag OWEN_H29 removed, the rule always on.
Command (cwd = the Own.NET checkout, fixture = corpus/ownership-lab/h29/fx/Orphan.cs
at its scratchpad path, references = the H-29 falsifier's Npgsql build output):
  dotnet ownsharp-extract.dll --flow-locals <fx>/Orphan.cs --ref-dir <falsifier>/bin/Release/net8.0 -o promo-u.facts.json
  python -m ownlang ownir promo-u.facts.json   > promo-u.py.txt
  own-cli ownir promo-u.facts.json             > promo-u.rust.txt

promo-u.facts.json                      the promoted build's facts
promo-u.py.txt / promo-u.rust.txt       both engines: identical (parity), 5 advisory OWN053
                                        at Orphan.cs 11 / 12 / 21 / 22 / 23 (O01, O02, O11,
                                        O12, O13 -- exactly the five frozen primary sites),
                                        0 findings, exit code 0; the eleven twins silent
fixture-diff-prototype-vs-promoted.txt  diff against rule/on-u.facts.json (the OWEN_H29=1
                                        prototype build): the ONLY difference is the `file`
                                        of the five entries, now written through the same
                                        cwd-relative helper every other record uses
                                        (prototype: the raw syntax-tree path); sites, lines,
                                        columns, callees, families, result types unchanged
build.txt                               the build log's error / warning / elapsed lines
