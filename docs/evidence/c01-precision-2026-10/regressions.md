# Регрессии: потеряны ли подтверждённые дефекты

Сравнение: baseline `1750769` и патч `3c98df2`, одинаковый вход, одинаковые флаги. Полные диагностики (место, правило,
severity, текст) до и после — `before-after.json`; сырые SARIF/факты — `work/sb-dev-out/run/*/{base,patched}/`.

## 1. MAUI 10.0.0 (область и вызов H1, scanbox)
- Baseline воспроизвёл замороженный SARIF H1 побайтно (sha256 `db6d3a46…eef035`). Факты совпадают с замороженными
  как множество; отличается только порядок файлов (обход каталогов в новой ВМ).
- Патч: 964 → 959 результатов, **снято 5, добавлено 0**. OWN050 548 → 548. В фактах изменилось только
  `released: false → true` у этих 5 подписок; остальные 1 041 запись подписок не изменились.

| снято | слой H1 | метка | проверка |
|---|---|---|---|
| ShellItemRenderer.cs:400 `_displayedPage.PropertyChanged` | C01-U | не размечалась | оценщик: BENIGN, high |
| ShellSectionRenderer.cs:32 `_shellSection.PropertyChanged` | C01-U | **H1-024 BENIGN** (A, слепая) | — |
| ShellSectionRenderer.cs:386 `_displayedPage.PropertyChanged` | C01-U | не размечалась | оценщик: BENIGN, high |
| ShellSectionRootRenderer.cs:101 `ShellSection.PropertyChanged` | C01-U | **H1-065 BENIGN** (A, слепая) | — |
| ShellSectionRootRenderer.cs:102 `ShellSectionController.ItemsCollectionChanged` | C01-U | не размечалась | оценщик: BENIGN, high |

Все пути — `src/Controls/src/Core/Compatibility/Handlers/Shell/iOS/`. Ровно эти 5 были предсказаны в
`hypothesis-preregistration.md` до прогона.

| набор контроля | до | после |
|---|---|---|
| C01-K (41 предупреждение на известных дефектах) | 41 | **41** (ни одно не снято) |
| 6 дефектов, найденных людьми (все FULL в `recall.md`) | 6 FULL | **6 FULL** (место и текст не изменились) |
| полнота H1: FULL / PARTIAL / MISS по 33 дефектам | 22 / 6 / 5 | **22 / 6 / 5** (ни одно C01-K и ни одно OWN014 не изменились) |
| 25 ACTIONABLE после раскрытия, 11 ACTIONABLE независимой разметки | все на месте | **все на месте** |
| Phase 5 прежнего исследования (4 C01) | 4 | 4 |

## 2. OpenSilver `fa7c4c5a`
425 → 425, 0 снято, 0 добавлено, факты патча и baseline побайтно равны. Baseline SARIF = SARIF разведки
(`b5528345…`). Два ACTIONABLE разведки (TimerTrigger) на месте.

## 3. Пограничные случаи и фиксированные контроли
- Предрегистрированные контроли (`controls/`): 17 файлов, все компилируются; до патча 0 расхождений с колонкой
  `before`, после — 0 с колонкой `after`. Изменились только F04b/F04c (4 подписки, OWN001 → none), как и
  предсказано. Опасный общий издатель (F02, F03), сеттер без teardown (F05), `Reset` без `OldItems` (F06), `-=` новой
  лямбдой (F07) и все 6 отрицательных контролей механизма (N01–N06) остались с предупреждением. F08 (настоящее слабое
  событие) остался ложным, как и задумано; F09 остался OWN050.
- Corpus benchmark на реальном C# (`scripts/benchmark.py`, включает flagship WPF-случаи, #278-семейство
  `subscription-*`/`timer-stop-*`, `zombie-viewmodel`, `viewmodel-escapes-to-app`): **58/62 caught, 62/62 clean,
  0 FP — до и после; все 62 случая совпали поштучно**.
- #146 (`returned_fresh`), #199 (лямбды и захват), #218/#225/#227/#228/#229, #317 (колонки) — блок CI
  «Check facts through the core» пройден до и после. #380 — `tests/test_guarded_consume.py` пройден. #278/#305 —
  corpus `subscription-param-guarded-unregister`, `-teardown-early-return-guard`, `-disposing-else-branch-release`,
  `-finalizer-release`, `-uncalled-local-function`, `-overload-conflated-cleanup` (в benchmark) пройдены. #410 —
  `test_extractor_partial_dispose` пройден (патч затрагивает и межпартиальный путь `TeardownContextMethods`).

## 4. Тесты и gate'ы на патче
| | baseline | патч |
|---|---|---|
| `python tests/run_tests.py` | rc 0 (без собранного `own-cli`) | rc 0 (без собранного `own-cli`) |
| то же при собранном `rust/target/release/own-cli` | **rc 1**: 3 контроля round7 apparatus (хеш локально собранного Round-6-хелпера ≠ замороженного) | **rc 1**, та же причина |
| ruff / mypy | 0 / 0 | 0 / 0 |
| extractor build; Tier-B (5 тестов); CI samples | ok | ok |
| `cargo build -p own-cli --release`, `cargo test -p own-cli`, `cargo test -p own-bridge` | ok | ok |

round7: проверено отдельно, что та же ошибка возникает на baseline-дереве (`git archive 1750769`) с тем же
`own-cli` (`artifacts/round7_base.sh`) и что `tests/test_round7_apparatus.py`/`scripts/round7/` не ссылаются на
extractor. Это зависимость от тулчейна (nix rustc 1.95), не от патча. **Не пройдено в этой среде, независимо от патча.**

Не запускалось: полный `cargo test` workspace, `cargo clippy`, formal/Kani, Windows-джобы, `oracle`/`mine`,
`owen --engine` Stage-контроли. Патч не меняет Rust, ядро, OwnIR и тексты сообщений.

## 5. Итог
Подтверждённых TP потеряно: **0**. Новых предупреждений: **0**. Необъяснённых изменений: **0** (каждое из 5 снятых
имеет `-=` того же текста получателя и обработчика в собственной реализации `IDisconnectable.Disconnect()`, вызванной
из `Dispose(bool)` через `(this as IDisconnectable)`).
