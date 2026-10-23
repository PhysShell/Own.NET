# Phase 0 — Rust parity на замороженных фактах

## Что сделано
- Вход: **замороженный** `facts.json` H1 (`runs/H1/scanbox/out-main/run/main/facts.json`, sha256
  `2bf2e4e3…8aa68`) и, дополнительно, `facts.json` прогона OpenSilver (`ownnet-explore/opensilver/out/run/main/`,
  sha256 `4072c882…8292`). MAUI и OpenSilver не пересканировались; оба файла только читались.
- Движки на Own.NET `1750769` без изменений:
  - Python reference: `python3 -s -m ownlang ownir <facts> --format sarif|human --severity warning` (вызов H1);
  - Rust: `rust/target/release/own-cli ownir <facts> --format sarif|human --severity warning`, собран
    `cargo build -p own-cli --release` из этого же дерева (sha256 бинарника
    `e2ad06d0b180347e2115732856683924397f187bef0a62441da08e4f936f0f0c`).
- Сравнение — `work/parity.py`: байты stdout, JSON после разбора, семантическое мультимножество
  `(ruleId, level, uri, startLine, startColumn, message)`, разрезы по rule/severity и resource kind, CRLF.
- Где: WSL хоста. Это обработка уже извлечённых фактов (данные, не исходники и не сборка чужого кода);
  сторонний код не исполнялся.

## Результат
| | H1 MAUI | OpenSilver |
|---|---|---|
| код выхода Python / Rust | 1 / 1 («есть находки») | 1 / 1 |
| stderr | одинаковый: `416 findings, 548 advisory (OWN050).` | одинаковый: `403 findings, 22 advisory (OWN050).` |
| SARIF побайтно | **идентичен** (sha256 `db6d3a46…eef035` = SARIF, замороженный в H1) | **идентичен** (`b5528345…d910d84` = SARIF прогона OpenSilver) |
| human-вывод побайтно | идентичен | идентичен |
| CRLF | 0 / 0 | 0 / 0 |
| OWN001 warning / OWN014 warning / OWN050 note | 391 / 25 / 548 у обоих | 396 / 7 / 22 у обоих |
| resource kind | subscription token 405, unresolved 548, disposable field 8, timer 2, disposable 1 — у обоих | subscription token 370, timer 18, unresolved 22, disposable field 10, disposable 5 — у обоих |
| семантических расхождений | 0 | 0 |
| расхождений сериализации/переносов | 0 | 0 |

## Вывод
- **Факт:** на замороженных фактах H1 Rust `own-cli` и Python reference выдают одно и то же, байт в байт; по rule ID,
  месту, severity, resource kind, тексту и числу находок расхождений нет. Повторный прогон Python воспроизвёл
  замороженный SARIF H1 (тот же sha256).
- **Следствие для H1:** числа H1 (401 C01 в знаменателе и т. д.) относятся и к Rust-ядру — но только для **этого
  входа** (одни и те же факты). Parity проверялась на уровне ядра; extractor у обоих общий (C#), так что вопрос
  «Rust vs Python» к extractor не относится.
- **Не проверено:** другие входы и опции (`--verbosity`, `--format github|msbuild`, `owen --engine compare`),
  Windows-сборка Rust. Parity на фактах **после** патча — в `result.md` (патч меняет только extractor, ядро
  получает другие факты; проверено тем же скриптом).
