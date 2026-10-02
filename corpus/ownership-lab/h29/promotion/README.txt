ownership-semantics-lab H-29 -> OWN053 promotion: the fixture run on the PRODUCTION build.

Build: frontend/roslyn/OwnSharp.Extractor of this tree (net8.0, Release), the rule always on under
--flow-locals (the own-check default). Run from the repository root on the committed fixture, with
the H-29 falsifier's Npgsql build output as the reference directory (Npgsql 10.0.3; any directory
holding that Npgsql.dll gives the same facts):
  dotnet ownsharp-extract.dll --flow-locals corpus/ownership-lab/h29/fx/Orphan.cs --ref-dir <dir with Npgsql.dll> -o promo-u.facts.json
  python -m ownlang ownir promo-u.facts.json   > promo-u.py.txt
  own-cli ownir promo-u.facts.json             > promo-u.rust.txt

promo-u.facts.json                      the production build's facts (file paths repository-relative)
promo-u.py.txt / promo-u.rust.txt       both engines: identical (parity), 5 advisory OWN053 at
                                        Orphan.cs 11 / 12 / 21 / 22 / 23 (O01, O02, O11, O12, O13 --
                                        exactly the five frozen primary sites of the H-29 scan), 0
                                        findings, exit code 0; the eleven twins silent
fixture-diff-prototype-vs-promoted.txt  research-branch provenance: the diff between the OWEN_H29=1
                                        prototype build's facts and the promoted research build's
                                        (only the entries' file-path form moved); both builds live on
                                        research/ownership-semantics-lab-v1, whose facts also carry
                                        the research-only params[].ordinal field this tree does not emit
build.txt                               the extractor's stderr for the run above
