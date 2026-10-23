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

## Часть 2. Результаты (после коммита патча `3c98df2`)
Прогон: scanbox, 2026-10-23 18:39–18:42Z (`artifacts/steps-holdout.log`, `artifacts/sb-holdout/run.sh`). Изоляция:
`/job` только чтение, хост 10.0.2.2 недоступен, NuGet — только nuget.org (`artifacts/isolation-holdout.txt`).
Обе сборки extractor из тех же тарболов, что и на dev-наборах (sha256 DLL baseline `e169519b…`, патч `92e1d5f8…`).

| репозиторий | .cs в области | baseline: всего / OWN050 | патч: всего / OWN050 | снято | добавлено |
|---|---:|---|---|---:|---:|
| Stylet `6992976d` | 95 | 20 / 6 | 20 / 6 | 0 | 0 |
| gong-wpf-dragdrop `f1d728ec` | 76 | 52 / 52 (0 предупреждений: WPF-события не разрешаются в loose-режиме) | 52 / 52 | 0 | 0 |
| Wox `ced76a7e` | **2** | — | — | — | — |
| shadowsocks-windows `891d9716` (резерв) | 79 | 55 / 31 | 55 / 31 | 0 | 0 |

- Wox на этом SHA почти не содержит C# (2 файла в области) → заменён резервом **по правилу части 1** (счёт файлов,
  предупреждения Wox не читались — их и нет: анализ не запускался).
- Факты baseline и патча побайтно совпали во всех трёх репозиториях (`before-after.json` → `holdout`).
- Разметки нет: изменившихся предупреждений нет, по протоколу размечать нечего. Субагент для holdout не запускался.

**Вывод.** На независимом holdout патч ничего не изменил: регрессий нет, но и **улучшения точности на holdout не
показано**. Механизм (`(this as I).M()` из teardown к собственной реализации) в этих трёх репозиториях не встретился.
Ни одно предупреждение holdout не читалось по содержанию и до сих пор не размечено.

## Часть 3. Независимый оценщик на dev-наборе (дополнительно, вне протокола holdout)
Чтобы закрыть пункт «результаты, требующие новой ручной проверки», три снятых на MAUI предупреждения без меток H1
(ShellItemRenderer:400, ShellSectionRenderer:386, ShellSectionRootRenderer:102) дал на разметку субагенту без
доступа к патчу, гипотезе, этому каталогу и меткам H1. В пакет подмешаны 3 неизменившихся C01-U, которых не видели
разметчики H1 (`random.Random(20261023)`), порядок перемешан; ключ — `artifacts/eval-key.json`, пакет —
`artifacts/eval-packet.jsonl` (sha256 `37f93776…`), ответ — `artifacts/eval-labels.jsonl`.

| пункт | снят патчем | метка | уверенность | зависит от приложения |
|---|---|---|---|---|
| P01 ShellItemRenderer:400 | да | BENIGN | high | нет |
| P04 ShellSectionRenderer:386 | да | BENIGN | high | нет |
| P05 ShellSectionRootRenderer:102 | да | BENIGN | high | нет |
| P02 Tizen ShellView:247 | нет | BENIGN | medium | да |
| P03 iOS CarouselViewController:259 | нет | BENIGN | medium | нет |
| P06 Windows ViewToHandlerConverter:54 | нет | ACTIONABLE | medium | да |

Оценщик прошёл цепочку дальше, чем Own.NET: `ShellRenderer` вызывает `Disconnect`/`Dispose` у уходящего
рендерера (ShellRenderer.cs:313–339), т. е. допущение AX4 для этих трёх классов он подтвердил по коду.

Степень независимости: та же модель (`claude-opus-5-5`), отдельный контекст. Список открытых файлов — со слов самого
оценщика (все внутри `eval-packet/`); журнал его вызовов я не проверял. Слепота частичная: три снятых пункта лежат в
одном каталоге iOS Shell, по этому признаку их можно отличить от подмешанных. Это dev-набор, не holdout.
