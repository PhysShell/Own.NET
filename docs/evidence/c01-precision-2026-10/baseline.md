# C01-PRECISION-1 — baseline до изменения кода

Дата: 2026-10-23, 17:57–18:05Z. Всё — в WSL NixOS, инструменты разово из `nix shell` (ничего не устанавливалось).

## Состояние репозитория
| | значение |
|---|---|
| worktree | `~/Documents/ownnet-eng/Own.NET` (worktree blobless-клона `refs/Own.NET`) |
| ветка | `claude/c01-precision-1` |
| baseline SHA | `175076925058b6b4eb60087a3b1e834e7315ebad` (= `origin/main`, тот же SHA, что в H1) |
| незакоммиченные изменения | нет (`git status --porcelain` пуст) |
| инструменты | Python 3.12.13, .NET SDK 8.0.422, cargo/rustc 1.95.0, ruff и mypy из nixpkgs |
| NuGet | restore только с `--configfile` = nuget.org-only (`work/nuget.isolated.config`, копия H1) |

## Базовые результаты (команды выбраны по `AGENTS.md` и `.github/workflows/ci.yml`)
Скрипт: `work/gates.sh baseline` (тот же скрипт потом гоняется на патче). Журналы: `work/logs/baseline/`.

| шаг | команда | результат |
|---|---|---|
| Python core | `python tests/run_tests.py` | **rc 0** (первый запуск rc 1 только потому, что `cargo` не был в PATH — `tests/test_mutate_campaign` вызывает cargo; с cargo в окружении rc 0) |
| lint | `ruff check .` | rc 0 |
| типы | `mypy` (strict для `ownlang`) | rc 0 |
| extractor | `dotnet restore … --configfile` + `dotnet build` `OwnSharp.Extractor` | rc 0 |
| Tier-B extractor (`OWN_TIERB_REQUIRED=1`) | `test_extractor_columns`, `_deep_flow`, `_sibling_locals`, `_partial_dispose`, `test_guarded_consume` | все rc 0 |
| CI samples | блоки «Extract OwnIR facts from sample C#» + «Check facts through the core» из `ci.yml`, перенесены дословно генератором `work/mk_ci_samples.py` | rc 0, `CI_SAMPLES_ALL_ASSERTIONS_PASSED` |
| corpus benchmark (реальный C#) | `python scripts/benchmark.py --min-recall 25` (engine python) | rc 0: **58/62 bugs caught · 62/62 fixes clean · 0 FP on fixes** |
| Rust | `cargo build -p own-cli --release && cargo test -p own-cli && cargo test -p own-bridge` | rc 0 |

Не запускалось на baseline (и на патче): полный `cargo test` по всему workspace, `cargo clippy`, formal/Kani,
Windows-джобы CI, workflow `oracle`/`mine` (сеть и сторонние репозитории), `owen --engine` Stage-1/2/3-контроли.
Причина: бюджет одного агент-дня и то, что патч не трогает Rust/ядро (см. `result.md`).
