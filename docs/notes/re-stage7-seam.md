# resource-effects Stage 7 — the effect model as a cross-frontend seam (EXPLORATORY)

Research branch `research/resource-effects-v1`. Pre-registered in Own.NET-paperwork
`paper-eval/resource-effects/stage7-seam-prereg-v1.json`; evidence in `stage7-seam-v1.json`. A seam
proof for one shape; never TypeScript support. #304 frozen and unchanged; #382 untouched.

The OwnTS twin emitter (`frontend/ownts/ownts_p037x.py`, +49/-4 lines) reads the SAME key file the C#
extractor reads (`--effects <key.json>`): an ambient factory listed `return_fresh_owned` mints an
`acquire` even when its declared type carries no `close()`/`dispose()`, and `x.m()` where `<Type>.m` is
listed `receiver_terminal_release` on a tracked handle is a `release`; the same provenance rule applies
(DECLARED / BODY_PROVED / MODELLED applied, MINED / SUGGESTED shadow, `--trust-all` = the M6 twin).
The ops are the ordinary acquire/release; the core (Rust and Python) has 0 changed lines.

Measured on the two twins (`corpus/re-controls/ownts/e7-effects-*.ts`; `tests/test_re_ownts_seam.py`
pins the 8 rows): without effects both are silent (untracked); with the MODELLED key the bug twin reports
OWN001 and the safe twin nothing; with the same rows as SUGGESTED both are silent and the emitter counts
two shadow rows; with `--trust-all` the SUGGESTED rows act. Python == Rust on every row; the eight
P-037-X twins still pass.

What this shows: the effect vocabulary of this track (two effects), its carrier (the key file) and its
trust policy (the provenance gate) live outside any language; a frontend contributes only an identity
matcher (~40 lines here). What it does not show: anything about TypeScript beyond these two twins.
