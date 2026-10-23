# Holdout — запечатан до изменения кода

## Часть 1. Выбор и правила (зафиксировано 2026-10-23 до правки `Program.cs`; коммит до коммита патча)

### Как выбраны репозитории
1. Список кандидатов задан до проверки (UI/MVVM-код .NET с подписками на события), в этом порядке:
   `canton7/Stylet`, `punker76/gong-wpf-dragdrop`, `Wox-launcher/Wox`, `shadowsocks/shadowsocks-windows` (резерв),
   `panthernet/XamlFlair` (резерв).
2. Исключение «уже участвовал»: имя `owner/repo` **или** только имя репозитория встречается где-либо в
   `ownnet-research/runs` (R, K, H1, H1-annotation), `ownnet-research/refs/ownnet-direction-research` (вся
   прежняя работа, включая holdout и sweep), `ownnet-explore`, Own.NET `corpus/`, `docs/`, `scripts/`, исходниках
   extractor (майнинг фильтров P-004). Скрипт `work/used_repos.py` → `work/used-repos.tsv`, проверка
   `work/check_candidates.sh`. Отсеяны этим правилом до выбора: Uno, Files, ShareX, dnSpy, HandyControl, ModernWpf,
   WPF-UI, AvalonEdit, MahApps, AvalonDock, Avalonia, GitExtensions, PowerToys, WPF Toolkit, ILSpy, Prism,
   Caliburn.Micro, Fluent.Ribbon, NAudio, OxyPlot, ScottPlot, LiveCharts2, Flow.Launcher, SubtitleEdit, LiveSplit,
   v2rayN, MvvmCross, Greenshot, Duplicati и др. `xamarin/xamarin.forms` отсеян отдельно: предшественник MAUI
   (общий код, не независим от H1).
3. Существование и SHA — `git ls-remote` (только чтение, 2026-10-23). `XamlFlair` не существует.
4. Взяты **первые три** существующих: 

| репозиторий | ветка по умолчанию | SHA |
|---|---|---|
| canton7/Stylet | master | `6992976d1d567acfb832fc80085dbb5f894078e5` |
| punker76/gong-wpf-dragdrop | develop | `f1d728ec873ca542a16b0cd66442c89dd407bd4b` |
| Wox-launcher/Wox | master | `ced76a7e3ef2f815f9ad9e83bca64ff8f867ca0d` |
| резерв: shadowsocks/shadowsocks-windows | v4 | `891d971682eefcaa2e640258d3b352a3ad3b2233` |

Замена на резерв — только механически: если в области репозитория меньше 50 файлов `.cs` (счёт файлов, не
предупреждений) или extractor падает.

### Область и прогон
- Только в qubix scanbox. Клон `--depth 1 --filter=blob:none` на указанном SHA.
- Область: все `*.cs` и `*.xaml` репозитория, кроме путей, где любой каталог содержит (без учёта регистра)
  `test`, `sample`, `demo`, `example`, `benchmark`; плюс стандартные пропуски extractor (bin/obj, `*.g.cs`,
  `*.Designer.cs`). Файлы копируются с сохранением путей в отдельный каталог; одна копия — для обоих анализаторов.
- Анализаторы: baseline extractor `1750769` и patched extractor (SHA патча), одинаковые флаги
  `--flow-locals --stats`, одинаковое ядро (Python reference), одинаковый loose-режим без reference packs
  (одинаковые «reference packs» = отсутствуют у обоих).
- Предупреждения holdout **не читаются** до завершения патча и прогона обоих анализаторов.

### Измерения и разметка
- По каждому репозиторию: число результатов по правилам, множество снятых и новых (ключ — rule, файл, строка,
  колонка, сообщение), изменение OWN050.
- Разметку изменений делает **отдельный субагент** без доступа к диффу патча, к этому каталогу, к гипотезе и к
  разметке H1: получает только пакет «место + текст предупреждения + путь к исходникам области». Чтобы он не мог
  узнать, какие записи изменились, в пакет подмешиваются неизменившиеся C01 того же репозитория
  (`random.Random(20261023)`, столько же, сколько изменившихся, минимум 5 на репозиторий, если есть). Метки:
  ACTIONABLE / BENIGN / UNRESOLVED + флаг «зависит от того, как приложение использует издателя».
- Степень независимости: та же модель (`claude-opus-5-5`), другой контекст, без доступа к гипотезе — это «independent
  of implementation», а не независимый эксперт.
- Если изменений нет — результат «нет изменений», разметка не нужна; это значит «регрессий не видно» и «улучшения
  точности на holdout не показано».
- Статистика: доли с точным интервалом Клоппера–Пирсона; при < 10 изменений интервал описательный, вывод о
  точности не делается (см. критерии в `hypothesis-preregistration.md`).

## Часть 2. Результаты
(заполняется после патча)
