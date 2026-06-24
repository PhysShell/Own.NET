# Plan — Own.NET Audit: полный «анамнез здоровья» легаси WPF-проекта

> **Статус: план / RFC.** Не нормативная спека (`spec/` — это), не proposal про
> ядро (`docs/proposals/` — это). Это карта работ по **аудит-оркестратору**:
> инструменту, который натравливает максимум *готовых, реальных* анализаторов и
> профайлеров на наш древний `.NET Framework 4.7.2` / WPF / DevExpress 12.2 проект,
> сводит их находки в один структурированный отчёт и отвечает на вопрос
> «где болит, насколько и почему» — с доказательствами, а не догадками.

## Одно предложение

> **Own.NET Audit — это оркестратор диагностики, а не ещё один анализатор:** он
> запускает чужие зрелые инструменты (Roslyn-аналайзеры, CodeQL, Infer#, own-check,
> профайлеры), нормализует всё в SARIF, скорит по cross-tool-согласию и выдаёт
> категоризированный отчёт о здоровье проекта с ранжированием «где хуже всего».

## Что это НЕ (зафиксировать, чтобы не расползлось)

- **Не новый чекер.** Ни одной собственной эвристики «на регулярках», которая
  плодит FP. Если для класса проблем нет надёжного готового инструмента — пишем в
  отчёт **`NO-TOOL: skipped`** с причиной, а не имитируем покрытие. Это прямое
  следствие культуры репозитория (honest skip / `OWN050`) и явного требования
  заказчика на минимальный FP.
- **Не раздувание ядра.** Код аудита живёт в изолированном поддереве `audit/` и
  **не импортирует `ownlang/`**. own-check потребляется как *внешний инструмент*
  через его CLI и SARIF — ровно так же, как CodeQL или Infer#. Единственный общий
  контракт — SARIF. Поддерево можно поднять в отдельный репозиторий в один `git mv`.
- **Не «AI сам найдёт баги».** LLM подключается **строго ниже** детерминированного
  слоя как фальсифицируемый ревьюер/объяснятель/генератор фиксов. Он никогда не
  решает «это точно leak» — это решают инструменты и рантайм-доказательства
  (позиция из `docs/notes/research-landscape-2026.md`, раздел про LLM).

---

## 0. Несущие принципы

| Принцип | Откуда и почему |
|---|---|
| **Оркестратор, не анализатор** | Заказчик: «помимо own.net разработок нет, время на свои детекторы тратить не хотим». Берём готовое. |
| **SARIF — единственный нормализованный формат** | Уже так в репозитории: `scripts/oracle_compare.py` и `mine_report.py` читают все инструменты через один `parse_sarif`. Любой инструмент, не умеющий SARIF, оборачивается тонким адаптером `raw → SARIF`. |
| **Cross-tool agreement = confidence** | Прямое обобщение oracle-паттерна (`docs/notes/oracle.md`): нашли двое+ независимых движков в одном месте — high confidence; один — кандидат/уникальный улов. Это, а не «severity из тулзы», определяет приоритет. |
| **Honest skip / минимальный FP** | Категория без надёжного инструмента помечается `NO-TOOL`, а не закрывается regex-скриптом. Каждый прогон несёт **coverage-карту** (что реально проверено, что пропущено и почему) — обобщение `own-check --stats` и `OWN050`. |
| **Детектируемость-матрица** | Не обещаем рантайм-баг статике. Каждая категория заранее привязана к слою (static / runtime / impossible) по матрице из `docs/ROADMAP.md`. |
| **Decoupling / extractability** | Высокая cohesion внутри `audit/`, нулевой coupling к ядру. Лифтится как самостоятельный продукт. |
| **Reproducible & deterministic** | Прогон по фиксированному коммиту даёт стабильный, диффабельный артефакт (как mining/oracle сейчас). Версии инструментов пиннятся и печатаются в шапке отчёта. |
| **AI downstream, фальсифицируемо** | LLM предлагает — детерминированный слой и рантайм проверяют. Никогда не trusted-base. |

---

## 1. Архитектура: три слоя

```
Слой 1 — СТАТИКА (делаем первым, это основной deliverable)
  target.sln ──► [fleet прогонов, каждый → SARIF] ──► normalize ──► score ──► health report
  build-free:   own-check, CodeQL (build-mode: none)            [в CI на каждый коммит]
  build-req:    Roslyn analyzer packs, Infer#                    [вручную на Windows dev-машине с DevExpress]

Слой 2 — РАНТАЙМ (после статики)
  FlaUI-сценарии (открыть/загрузить/закрыть ×N) + SematixTrace breadcrumbs
    ──► PerfView/ETW + procdump + ClrMD heap-diff ──► retained/duplicate/storm evidence ──► тот же отчёт

Слой 3 — AI REVIEWER (поверх готовых доказательств)
  structured findings + сниппеты ──► кластеризация / объяснение retained paths / кандидаты-фиксы / confidence
```

### Детектируемость-матрица → к какому слою привязана категория

Берём матрицу из `docs/ROADMAP.md` «What static analysis can and cannot catch» и
расширяем её на наши категории. Это не косметика: она **запрещает** вешать
рантайм-проблему (дубликаты в куче, storm частоты, LOH) на статический инструмент,
тем самым убивая целый класс FP заранее.

---

## 2. Категории проблем → реальные инструменты (coverage matrix)

Это сердце плана и прямой ответ на «какими тулзами что гоним, и где у нас дырка».
`HIGH/MED/LOW` — ожидаемая уверенность статического покрытия; `→ RUNTIME` означает,
что статикой честно не ловится и переносится в Слой 2; `NO-TOOL` — нет надёжного
готового инструмента, помечаем в отчёте, **не** имитируем.

| # | Категория | Слой | Реальные инструменты | Уверенность | Честная дырка |
|---|---|---|---|---|---|
| 1 | `IDisposable` leak (local/field, dispose-on-throw) | static | CA2000/CA2213, IDisposableAnalyzers (`IDISP0xx`), CodeQL `cs/local-not-disposed`&friends, Infer# `*RESOURCE_LEAK`, own-check `OWN001` | **HIGH** (4–5 движков → agreement) | interproc-передача владения даёт расхождения — это и есть сигнал, не шум |
| 2 | Event/subscription leak (`+=` без `-=`, static event, EventAggregator/Messenger) | static + runtime-confirm | **own-check `OWN001/OWN014`** (наш дифференциатор), WpfAnalyzers — частично | **MED** static (уникален own-check, warn-tier), **HIGH** если подтверждён рантаймом | CodeQL/Infer# этот класс не выражают вообще (`oracle.md`); подтверждаем leak-harness'ом |
| 3 | Timer leak (`DispatcherTimer`/`Timer` без stop/detach) | static + runtime-confirm | own-check `WPF002`, WpfAnalyzers — частично | **MED** | — |
| 4 | `DependencyPropertyDescriptor.AddValueChanged` leak | runtime | — (нет надёжного выделенного аналайзера) | **NO-TOOL** static | переносим в leak-harness (retained после закрытия окна) |
| 5 | INPC-корректность (нет equality-check, кривой/пустой `nameof`, неверный arg) | static | **PropertyChangedAnalyzers (`INPC0xx`)** | **HIGH** | измеряет корректность, не частоту |
| 6 | PropertyChanged-штормы/каскады, дорогие getter'ы под binding | runtime | SematixTrace counters + INPC-инструментация; PerfView CPU/alloc | **NO-TOOL** static → **RUNTIME** | частота — это рантайм, статикой не мерится |
| 7 | WPF binding errors (битые байндинги) | runtime | `PresentationTraceSources`/WPF-trace во время FlaUI-сценариев | **NO-TOOL** static → **RUNTIME** | — |
| 8 | Сломанная/выключенная virtualization (ScrollViewer вокруг virtualized, `StackPanel` вместо `VirtualizingStackPanel`) | runtime | visual-tree element counts + render-профиль (PerfView WPF ETW, Perforator) | **NO-TOOL** static → **RUNTIME** | регексом по XAML — это FP-генератор, сознательно отказываемся |
| 9 | Freezable не заморожен; brush/geometry per-instance | static (частично) + runtime | WpfAnalyzers (часть правил); иначе alloc-профиль | **LOW–MED** | остаток → runtime alloc stacks |
| 10 | Аллокации в конвертерах/getter'ах, layout-invalidation storms | runtime | PerfView allocation stacks + WPF render ETW | **NO-TOOL** static → **RUNTIME** | — |
| 11 | **Размножение immutable/should-be-static данных** (units/countries/currencies, повторяющиеся строки, копии справочников по строкам) | runtime | **ClrMD/PerfView heap grouping** (duplicate detector) — free-стек | **NO-TOOL** static → **RUNTIME** | зависит от данных рантайма, не от формы кода; статикой = FP. **Это «золото» проекта — приоритет в Слое 2.** dotMemory не используем (нет лицензии) → retention paths считаем сами по дампу ClrMD. |
| 12 | Тяжёлые справочники / LOH-фрагментация / Gen2-bloat / eager-load | runtime | PerfView (GC stats, LOH, Gen2), счётчики | **impossible** static → **RUNTIME** | — |
| 13 | Cross-thread `ObjectDisposedException`, PropertyChanged из бэкграунд-потока | runtime | WPF dispatcher-checks + ETW во время сценариев | **impossible**/weak static → **RUNTIME** | happens-before, не структура |
| 14 | Общие баги / perf / best-practice / async (топливо для «где хуже») | static | .NET SDK NetAnalyzers, Meziantou.Analyzer, Roslynator, AsyncFixer, SonarAnalyzer.CSharp, CodeQL `security-and-quality` | **HIGH** breadth | — |
| 15 | Архитектурные метрики / циклы / hotspots / coupling-cohesion (ранжирование «где хуже») | static | Roslynator/SonarAnalyzer метрики (free); CodeQL `cs/` quality-запросы | **LOW–MED** | NDepend не используем (нет лицензии) → ранжирование архитектуры деградирует до метрик из Sonar/Roslynator + CodeQL; помечаем это в coverage |

> **Ключевой разворот для own-check.** В категориях 2–4 (subscription/timer/region
> leaks) own-check — единственный, кто их вообще выражает; CodeQL и Infer# тут слепы
> (доказано на ScreenToGif, см. `docs/notes/real-world-mining.md`). А в категории 1
> own-check пересекается с ними → их совпадение даёт нам high-confidence, а
> расхождения — материал для корпуса. То есть аудит *попутно* прогоняет наш
> oracle-харнес наоборот и кормит обратную связь в OwnLang (см. §6).

---

## 3. Слой 1 — статический аудит (первый и основной этап)

### 3.1. Механизм «анализаторы только на время аудита, в dev невидимы»

Требование: понаставить максимум Roslyn-аналайзеров, но чтобы при обычной разработке
их не было и они не светили 900 warnings в IDE.

**Решение (zero-touch для dev-копий):** прогон в одноразовом `git worktree` с
инъекцией `Directory.Build.props`/`.targets`, гейтнутых флагом `OwnAudit=true`.

```
git worktree add ../target-audit <commit>     # рабочие копии разработчиков не трогаем
cp audit/static/inject/OwnAudit.Directory.Build.{props,targets} ../target-audit/
msbuild Target.sln /p:OwnAudit=true /p:Configuration=Release \
        /bl:artifacts/build.binlog
git worktree remove ../target-audit
```

`OwnAudit.Directory.Build.props` (по сути — `<Analyzer Include=…>` из
восстановленного audit-кэша + общий `ErrorLog`/`ReportAnalyzer`):

```xml
<Project>
  <PropertyGroup Condition="'$(OwnAudit)' == 'true'">
    <EnableNETAnalyzers>true</EnableNETAnalyzers>
    <AnalysisMode>All</AnalysisMode>
    <ReportAnalyzer>true</ReportAnalyzer>
    <!-- SARIF на проект; aggregate/ их потом сольёт -->
    <ErrorLog>$(MSBuildProjectDirectory)\..\artifacts\own-audit\$(MSBuildProjectName).sarif,version=2.1</ErrorLog>
  </PropertyGroup>
  <ItemGroup Condition="'$(OwnAudit)' == 'true'">
    <!-- DLL из заранее restore'нутого audit-кэша, НЕ PackageReference в дереве проекта -->
    <Analyzer Include="$(OwnAuditAnalyzers)\**\*.dll" />
  </ItemGroup>
</Project>
```

Почему так, а не `<PackageReference … PrivateAssets="all">`:
- легаси-проект почти наверняка **non-SDK csproj + `packages.config`** (ему 12 лет),
  где условный `PackageReference` — боль; `<Analyzer Include>` из вынесенного кэша
  работает и там, и там;
- `Directory.Build.props` MSBuild подхватывает и для легаси-csproj (VS2017+), а
  worktree гарантирует, что в IDE разработчика этого файла нет в принципе.

Конфиг-профили (что включать) держим отдельно — `audit/config/profiles/`:
`desktop-wpf`, `paranoid`, `backend-di`. Включается через `.editorconfig`/rulesets,
сгенерированные из профиля; severity-разрешение — там же.

### 3.2. Tiering инструментов: build-free vs build-required

Это критично и должно быть в отчёте честно (как асимметрия в `oracle.md`):

| Tier | Инструменты | Нужен ли успешный билд target'а |
|---|---|---|
| **Build-free** (бегут всегда, даже на сломанном solution; **гоняются в CI**) | own-check (error-tolerant `SemanticModel`), CodeQL (`build-mode: none`, из исходников) | нет |
| **Build-required** (**вручную на Windows dev-машине** с установленным DevExpress 12.2 + рабочий MSBuild) | NetAnalyzers, Meziantou, Roslynator, AsyncFixer, SonarAnalyzer, IDisposableAnalyzers, WpfAnalyzers, PropertyChangedAnalyzers; Infer# (нужны `.dll`+`.pdb`) | да |

**Решение по окружению (подтверждено):** выделенного Windows-CI с DevExpress нет.
Поэтому **CI гоняет только build-free tier** (own-check + CodeQL — даёт каркас отчёта
автоматически на каждый коммит), а **build-required tier запускается вручную** на
Windows-машине разработчика и его SARIF подкладывается в `artifacts/own-audit/` для
агрегации. NDepend выпадает (нет лицензии) — ранжирование архитектуры идёт на
free-метриках (Roslynator/Sonar/CodeQL), что помечается в coverage.

Каждый build-required прогон — `continue-on-error`: упавший билд даёт **частичный**
отчёт, а не пустой, и явную пометку «tier недоступен: билд не собрался».

### 3.3. Fleet прогонов (каждый → SARIF)

`audit/static/run_static.py` оркеструет; по одному тонкому runner'у на инструмент в
`audit/static/tools/`. Каждый кладёт SARIF в `artifacts/own-audit/<tool>.sarif`.

- **Roslyn-пак** (один билд, много аналайзеров) → per-project SARIF через `ErrorLog`.
  Пиннить версии паков к тем, чей Roslyn-рантайм совместим с MSBuild build-окружения:
  свежайшие паки иногда требуют новее SDK, чем легаси-билд. Несовместимый пак —
  помечаем `NO-TOOL: incompatible toolchain`, не тянем силой.
- **CodeQL** — `init build-mode: none` + `analyze` с `security-and-quality` (dispose/leak —
  это *quality*-запросы, в default security-сьюте их нет; иначе CodeQL молча даст ноль —
  грабли уже задокументированы в `oracle.yml`).
- **Infer#** — `dotnet build -o _bin` → `microsoft/infersharpaction` по бинарям (нужен
  pdb). Для net472 на CI это самый хрупкий шаг — отсюда `continue-on-error`.
- **own-check** — `scripts/own-check.sh --format sarif --severity warning` (переиспользуем
  как есть; `OWN_EXTRA_REF_DIRS` для WPF/WinForms ref-паков, как в `oracle.yml`).
- ~~NDepend~~ — не используем (нет лицензии); архитектурное ранжирование (§2 кат. 15)
  идёт на free-метриках Roslynator/Sonar/CodeQL с пометкой о деградации.

**DevExpress-шум (подтверждено): baseline-suppress целиком.** Находки из
DevExpress-namespace (`DevExpress.*`) глушатся на этапе нормализации (§3.4) — первый
отчёт чище и сфокусирован на нашем коде. Сам факт глушения и счётчик подавленных
находок печатаются в coverage-секции (ничего не прячем молча).

### 3.4. Нормализация и таксономия категорий

`audit/aggregate/normalize.py` — читает все SARIF через **тот же `parse_sarif`**, что и
`oracle_compare.py` (переиспользуем, не дублируем парсер). Затем мэппит `(tool, ruleId)`
→ нашу категорию из §2 по таблице знаний `audit/static/taxonomy/categories.yml`:

```yaml
# rule-id (или префикс) -> категория §2
"CA2000":           {category: 1, name: "idisposable-leak"}
"IDISP0*":          {category: 1, name: "idisposable-leak"}
"cs/local-not-disposed": {category: 1}
"*RESOURCE_LEAK":   {category: 1}
"OWN001":           {category: 1}
"OWN014":           {category: 2, name: "subscription-leak"}
"INPC0*":           {category: 5, name: "inpc-correctness"}
# ... правила без маппинга падают в "uncategorized" и видны отдельно (не теряются)
```

Непромэпленные правила **не выкидываются**, а собираются в `uncategorized` — чтобы
таксономия росла осознанно, а не глотала находки молча (та же дисциплина, что
«unparsed-line bucket» в `oracle_compare`).

**DevExpress baseline-suppress** — отдельный фильтр нормализации: находки в путях/типах
`DevExpress.*` (сторонний код) отбрасываются из основного отчёта, но **считаются** и
попадают в coverage отдельной строкой («suppressed: DevExpress — N findings»). Это не
regex-эвристика по нашему коду (тех заказчик запретил), а honest-фильтр стороннего
namespace — снижает шум, ничего не пряча.

### 3.5. Скоринг и отчёт «где хуже всего»

`audit/aggregate/score.py` — обобщение `oracle_compare.compare()`:

1. **Cross-tool agreement** на (basename + line-window), как в `oracle_compare`
   (устойчиво к разным префиксам путей). Финдинг, подтверждённый ≥2 независимыми
   инструментами → `confidence: high`; одиночный → `confidence: candidate` (+ помечен,
   уникальный это улов own-check или кандидат-FP).
2. **Severity-нормализация** между инструментами (у всех своя шкала) в единую
   `P0..P3` по таблице из ROADMAP («как ранжировать по impact»).
3. **Roll-up по локации** → heatmap: per-file → per-namespace/module → per-assembly,
   взвешенный по (категория × severity × agreement × плотность). Это и есть прямой
   ответ «где хуже всего / где почти норм»: отсортированный список модулей с
   индексом боли, а не свалка из 3000 «possible issue».
4. **Coverage / honesty** секция: какие tiers отработали, какие категории `NO-TOOL`,
   что пропущено и почему (категории 6–13 со статус-пометкой «deferred to runtime»).

`audit/aggregate/report.py` — рендереры:
- **Markdown** (для людей / GitHub run summary — как сейчас в oracle/mine),
- **HTML** (heatmap, сортировки),
- **JSON** (машинный, для AI-слоя и регрессий),
- **merged SARIF** (один лог → GitHub code scanning, переиспользуя exporter из
  `docs/notes/sarif-export.md`).

Формат одной находки — как уже принято в проекте (стабильно, годно для AI и diff):

```json
{
  "id": "SUBSCRIPTION-LEAK-0001", "category": 2, "severity": "P1",
  "confidence": "high", "tools": ["own-check", "<runtime:leak-harness>"],
  "file": "VideoSource.xaml.cs", "line": 123,
  "evidence": ["own-check OWN014: subscribes to AppEventBus.Changed, no -=",
               "leak-harness: +10 VideoSource retained after close ×10"],
  "suggested_fix": "Unsubscribe on Unloaded/Dispose or WeakEventManager"
}
```

---

## 4. Слой 2 — рантайм (после того, как статика устаканилась)

UI «надо проверять на вшивость», и руками кликать мы не хотим — значит автоматизация
сценариев. Стек под net472/WPF/DevExpress (точность важнее моды — `dotnet-gcdump`/
`dotnet-counters` заточены под CoreCLR, для Framework честнее ETW + дамп):

| Роль | Инструмент | Заметка по net472 |
|---|---|---|
| Драйвер UI (детерминированные сценарии вместо кликов) | **FlaUI** (UIA3) | .NET-библиотека поверх MS UI Automation; гоняет Win32/WinForms/WPF |
| Семантические breadcrumbs (связать сценарий ↔ снимок) | **SematixTrace** | `Step/Entity/Counter/Mark/RequestGc`; только в diagnostic-билде |
| GC/alloc/CPU/WPF-render телеметрия | **PerfView** (ETW) | отлично работает с Framework: GC stats, alloc stacks, LOH, `Microsoft-Windows-WPF` провайдер |
| Снимок кучи / дамп | **procdump** + (heap snapshot PerfView) | `dotnet-dump`/`gcdump` к Framework-процессу не цепляются; берём full dump |
| Разбор кучи (retained, duplicates, retention paths) | **ClrMD** (`Microsoft.Diagnostics.Runtime`) | по дампу: типы, counts, кто держит; движок duplicate-детектора и retention-paths (считаем сами) |
| Битые байндинги | **`PresentationTraceSources`** capture | включаем WPF binding trace на время сценария |

> **Стек подтверждён как полностью бесплатный** (нет NDepend/dotMemory): retention
> paths и duplicate-grouping считаем сами поверх ClrMD по full-dump'у (procdump) —
> чуть больше своего кода в `audit/runtime/`, нулевая лицензионная зависимость.

### 4.1. Leak-harness (категории 2–4, 13)

Детерминированный раннер (C#, `audit/runtime/`): сценарий из YAML, который ИИ
набрасывает, а ассерты — детерминированные:

```yaml
scenario: open-close-declaration
repeat: 10
steps:
  - launch: LegacyApp.exe
  - click:  { automationId: OpenDeclarationButton }
  - wait:   { automationId: DeclarationGrid }
  - close:  { automationId: DeclarationWindow }
  - force_gc: true
assert:
  retained:        { DeclarationWindow: 0, DeclarationViewModel: 0 }
  max_growth:      { DeclarationRowVm: 100 }     # baseline + допуск
```

Петля: open → load → close → `RequestGc` → snapshot → повторить N. Diff baseline vs
after по counts типов (`Window`/`ViewModel`/domain/`BindingExpression`/DevExpress
grid/editor). Признак leak — **unbounded growth при повторении**, не разовый рост
(методика из PerfView heap-leak tutorial). Ассерт детерминированный — ИИ не оракул.

### 4.2. Duplicate-immutable detector (категория 11 — приоритет)

ClrMD по full-dump'у (procdump): группировка объектов по `type + value-signature`, поиск
`N×` одинаковых мелких объектов / строк / справочных DTO, размноженных по строкам
грида/отчёта; для топ-кандидатов считаем retention path до GC-root тем же ClrMD (без
dotMemory). Выхлоп — кандидаты на `static readonly`/flyweight/intern/reference-id.
Это «архитектурный ксерокс», который маскируется под утечку, и которого статикой не
видно — поэтому он живёт здесь, а не в Слое 1.

### 4.3. PropertyChanged-storm profiler (категория 6)

SematixTrace-counter + лёгкая INPC-инструментация (только diagnostic-билд): за одну
пользовательскую операцию считаем, какие свойства как часто стреляют, какие — без
изменения значения, где getter под байндингом аллоцирует/делает тяжёлый расчёт.
Выхлоп — топ-«крикунов» с числами, скоррелированный с PerfView CPU/alloc.

### 4.4. Корреляция

Связываем `SematixTrace`-события (`WindowClosed`/`ForcedGC`/`Mark`) ↔ ETW ↔ heap-diff
↔ статические находки по тому же файлу/типу. Результат — не «возможно leak», а
судебная экспертиза: сценарий → событие → снимок → удерживается → плюс статическая
улика «подписался, не отписался». Эти runtime-находки текут в **тот же отчёт** §3.5.

---

## 5. Слой 3 — AI reviewer (строго downstream)

Поверх готовых структурированных находок + сниппетов кода. LLM полезен и **безопасен
по построению** только в фальсифицируемых ролях:
- кластеризация и дедуп находок между инструментами;
- объяснение retained paths человеческим языком;
- кандидаты-фиксы (`-=`, `using`, `static readonly`, `WeakEventManager`) — каждый как
  *гипотеза*, которую пере-проверяет чекер + компиляция + тесты;
- ранжирование «top risks / likely root cause / next diagnostic step»;
- черновики FlaUI-сценариев (но ассерт всегда детерминированный).

LLM **никогда** не выносит вердикт «это leak» и не является источником спеки/правды
(аргументация trusted-base vs falsifiable — `research-landscape-2026.md`). Если когда-то
появится fix-loop — он gated детерминированным чекером + метаморфным харнесом, а не
доверием к модели.

---

## 6. Обратная связь: аудит кормит OwnLang (это и был второй мотив заказчика)

«Натаскать наш анализатор» получается бесплатно как побочка:
- **agree** (own-check ∩ зрелые тулзы) → подтверждённые кейсы для регресс-корпуса;
- **own-only** → кандидат-FP (харденить) **или** уникальный улов (фича) →
  `corpus/real-world/` минимальным reduced-кейсом (`before.cs`/`after.cs`/
  `expected-diagnostics.txt`), по той же дисциплине, что уже есть;
- **oracle-only** → recall-gap own-check → задача на ядро;
- **рантайм-подтверждённые leak'и** → лейблы (bug/no-bug) для benchmark-корпуса (P-012),
  которого, по `research-landscape-2026.md`, проекту как раз и не хватает.

То есть аудит — это масштабный mining-прогон по *нашему* проекту, чьи находки
становятся labeled-корпусом. Связь односторонняя по коду (audit → corpus артефактами),
без code-coupling.

---

## 7. Раскладка поддерева (лифтится как отдельный проект)

```
audit/                              # cohesive; ничего не импортирует из ownlang/
  README.md
  static/
    run_static.py                   # оркестратор статики
    tools/                          # по одному тонкому runner'у; каждый → SARIF
      roslyn_pack.ps1  codeql.sh  infersharp.sh  owncheck.py  ndepend.ps1
    inject/
      OwnAudit.Directory.Build.props / .targets
    taxonomy/
      categories.yml                # (tool, ruleId) -> категория §2  (база знаний)
  aggregate/
    normalize.py                    # SARIF -> findings (переиспользует parse_sarif)
    score.py                        # agreement / severity / heatmap (обобщает oracle_compare)
    report.py                       # md / html / json / merged-sarif рендереры
  runtime/
    OwnAudit.Runtime.sln            # C#: FlaUI driver + ClrMD heap tool + SematixTrace hooks
    scenarios/*.yml
  config/profiles/                  # desktop-wpf, paranoid, backend-di
  artifacts/                        # gitignored выхлоп (как corpus/mined/)
```

Правило decoupling (тест в CI): grep по `audit/` не должен содержать `import ownlang`
или ссылок в `ownlang/`. own-check вызывается только через `scripts/own-check.sh`.
Язык оркестрации — **Python** (подтверждено; переиспользуем `parse_sarif`/oracle-логику,
OS-agnostic, нулевой coupling); C# — только там, где вынужденно (Infer#-билд, FlaUI, ClrMD).

---

## 8. Предпосылки и риски (честно, заранее)

| Риск / предпосылка | Влияние | Что делаем |
|---|---|---|
| **Build-required tier — только на Windows dev-машине** (CI его не гоняет) | Roslyn-паки и Infer# не автоматизированы в CI, запускаются руками | принято осознанно: CI = build-free (own-check + CodeQL) на каждый коммит; build-required tier — ручной прогон, его SARIF подкладывается в агрегацию |
| Легаси `packages.config`/non-SDK csproj | условный `PackageReference` ненадёжен | механизм §3.1 (`<Analyzer Include>` + worktree) специально под это |
| Свежие версии аналайзеров требуют новее Roslyn/SDK, чем легаси-билд | пак не грузится | пиннинг версий под toolchain; несовместимый → `NO-TOOL`, не силой |
| `dotnet-gcdump`/`dotnet-counters` не цепляются к net472 | ложная надежда на CoreCLR-тулинг | рантайм-стек на ETW(PerfView) + procdump + ClrMD, не на `dotnet-*` |
| Infer# на net472-бинарях на Linux-CI хрупок | частые пропуски | `continue-on-error`, частичный отчёт честно помечается |
| DevExpress генерит шум в аналайзерах | FP-вал | **принято: baseline-suppress `DevExpress.*` целиком** на нормализации, со счётчиком подавленного в coverage |
| Коммерции нет (NDepend/dotMemory) | слабее ранжирование архитектуры (кат. 15) и retention paths (кат. 11) | **принято: только free-стек**; архитектуру ранжируем метриками Sonar/Roslynator/CodeQL, retention paths считаем сами по ClrMD — помечаем деградацию, не блокер |

---

## 9. Фазовый план (порядок и deliverables)

> Делаем в рамках Own.NET, но в изолированном `audit/`, готовом к выносу.

**Фаза 0 — Каркас и решения (S)**
- `audit/` скелет, decoupling-CI-тест, `categories.yml` v0, профиль `desktop-wpf`.
- Deliverable: пустой, но связный конвейер «прогон → SARIF → normalize → отчёт» на
  одном инструменте (own-check) end-to-end.

**Фаза 1 — Статический fleet (основной этап, M–L)**
- 1a: механизм audit-only анализаторов (worktree + props + `OwnAudit`), `desktop-wpf` профиль.
- 1b: runner'ы build-free (own-check, CodeQL) → SARIF — **в CI на каждый коммит**.
- 1c: runner'ы build-required (Roslyn-пак, Infer#) — **ручной прогон на Windows dev-машине**;
  `continue-on-error`; SARIF кладётся в `artifacts/own-audit/` для агрегации.
- 1d: `normalize` + таксономия + **DevExpress baseline-suppress**; `score`
  (agreement/severity/heatmap); рендереры. (NDepend нет — кат. 15 на free-метриках.)
- **Deliverable: первый «анамнез» — категоризированный отчёт с ранжированием
  «где хуже / где почти норм» + честной coverage-картой.** Это то, ради чего всё.

**Фаза 2 — Рантайм (M–L)**
- 2a: FlaUI-харнес + YAML-формат сценариев (ИИ-черновики, детерминированные ассерты).
- 2b: SematixTrace-интеграция (diagnostic-билд).
- 2c: capture-пайплайн PerfView/procdump/ClrMD; leak-harness; duplicate-detector;
  binding-error collector; PropertyChanged-storm profiler.
- 2d: корреляция → рантайм-находки в общий отчёт.
- Deliverable: для топ-N экранов (тяжёлый справочник, декларация/графа 47, отчёт,
  DevExpress-грид, часто открываемое окно) — open/close-leak отчёт, дубликаты в куче,
  storm-профиль.

**Фаза 3 — AI reviewer (S–M)**
- кластеризация/объяснение/кандидаты-фиксы/ранжирование поверх JSON-находок.
- Deliverable: «старший ревьюер с доказательствами», не шаман.

**Фаза 4 — Вынос и обратная связь (S)**
- `git mv audit/` → отдельный репозиторий (coupling уже нулевой).
- промоушн подтверждённых находок в `corpus/` + benchmark-лейблы (§6).

**Первый практический прогон** (минимальный путь к ценности, не дожидаясь всего):
build-free tier (own-check + CodeQL) по target'у → normalize → черновой heatmap-отчёт.
Это даёт «карту минного поля» за день-два, дальше наслаиваем build-required и рантайм.

---

## 10. Сознательные non-goals (против расползания)

- Не пишем собственные детекторы/регексы для закрытия дырок — `NO-TOOL` честнее.
- Не тащим `roslyn-tools`/NDepend как зависимость ядра (см. `roslyn-tools-and-cli.md`).
- Не делаем autonomous-агента с shell-доступом по 600k строк; делаем детерминированный
  runner + AI-ревьюер сверху.
- Не чиним всё подряд: фиксим **топ-5 подтверждённых** после первого отчёта, остальное —
  в backlog по индексу боли.
- AI не становится оракулом и источником спеки.

---

## 11. Принятые решения (подтверждено заказчиком)

1. **Build-окружение — только Windows dev-машина.** Выделенного Windows-CI с
   DevExpress 12.2 нет. → CI гоняет **build-free tier** (own-check + CodeQL) на каждый
   коммит; **build-required tier** (Roslyn-паки, Infer#) — ручной прогон на dev-машине,
   SARIF подкладывается в агрегацию. (§3.2, §9-1c)
2. **Язык оркестрации статики/агрегации — Python.** Переиспользуем `parse_sarif` и
   oracle-логику, нулевой coupling к ядру, OS-agnostic. C# — только в рантайме (FlaUI,
   ClrMD). (§7)
3. **Только free-стек, без коммерции.** Нет NDepend → архитектурное ранжирование
   (кат. 15) на метриках Roslynator/Sonar/CodeQL с пометкой о деградации. Нет dotMemory
   → duplicate-detector и retention paths (кат. 11) считаем сами поверх ClrMD по
   full-dump'у. Помечаем деградацию, не блокер. (§2, §4, §8)
4. **DevExpress — baseline-suppress целиком.** Находки в `DevExpress.*` глушатся на
   нормализации, со счётчиком подавленного в coverage-секции (honest-фильтр стороннего
   namespace, не regex по нашему коду). (§3.3, §3.4)

### Остаётся открытым (не блокирует старт)

- Точный список топ-N экранов для рантайм-сценариев Фазы 2 (тяжёлый справочник,
  декларация/графа 47, отчёт, DevExpress-грид, часто открываемое окно) — уточним перед
  Фазой 2.
- Пиннинг версий Roslyn-паков под toolchain легаси-билда (свежие могут требовать новее
  MSBuild) — выяснится на 1c, несовместимые помечаем `NO-TOOL`.
```
