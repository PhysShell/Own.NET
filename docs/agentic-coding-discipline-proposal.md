# Agentic Coding Discipline — Proposal

> Статус: **proposal / design note**, не implementation plan. Зафиксировано как
> отправная точка для дисциплинированного agentic coding поверх Own.NET,
> OwnAudit и 007. Часть тезисов ниже уже реализована и задокументирована в
> репозиториях на момент коммита — см. раздел "Что уже есть". Остальное —
> открытые предложения, ждущие решения о приоритете.

## Что из этого уже реализовано/задокументировано

- **007** (`README.md`, `TODO.md`) — цикл `isolate → run → gate → harvest` уже
  работает: `o7 run` делает git worktree, гоняет `claude` full-auto, прогоняет
  `.007/gate.toml`, собирает `task.md / meta.json / agent.stdout / diff.patch /
  gate/*.log` (`src/agent.rs`, `gate.rs`, `worktree.rs`, `record.rs`,
  `verdict.rs`).
- **007/docs/security-layers.md** — источник тезисов про "deny-list ≠ sandbox",
  "worktree isolation ≠ security boundary", `bash -lc` из target repo как
  attacker-controlled code execution поверхность.
- **007/docs/performance.md** + **TODO.md** — тезис "007 subprocess/LLM-bound,
  единственный рычаг — bounded `--jobs N` для per-file judge calls" и план
  STS-run на 156 FP-suspects.
- **007/judge/** (`README.md`, `prompt.template.md`, `rubric.example.md`,
  `fp-verdicts.schema.json`) — `o7 judge` как отдельный read-only режим с
  machine-readable verdict уже реализован и верифицирован на oracle
  (contract-conforming `fp-verdicts.json`).
- **OwnAudit/docs/fp-judge/verdict-contract.md + rubric.md** — источник истины,
  под который подстроена схема `007/judge/fp-verdicts.schema.json`.
- **Own.NET/AGENTS.execution-surfaces.md** — живой пример agent-contract в духе
  предложения ниже: ADR-решение (accept/reject), секция "Что НЕ делать"
  (negative prompts), acceptance criteria, trigger table "пересмотреть если...".
- **Own.NET/AGENTS.md**, **OwnAudit/AGENTS.md** — repo-level своды правил для
  агентов уже существуют.

## Чего нет и что здесь предлагается как открытая задача

- Папка `.ai/` в Own.NET (`project-context.md`, `architecture-rules.md`,
  `forbidden-changes.md`, `task-template.md`, `review-template.md`,
  `domain-glossary.md`, `testing-policy.md`).
- Машиночитаемый `task.o7.toml` / `TaskContract` + `DiffPolicy` gate в 007 —
  сейчас есть только `examples/task.example.md` как обычный markdown-таск, без
  scope/forbidden-paths/dependency enforcement.
- Команды `o7 plan`, `o7 judge-run`, `o7 replay`, `trust_level`
  (trusted-local / semi-trusted / untrusted).
- Каталог analyzer rule id вида `OWNASYNC001` / `OWNLIFE00x` / `OWNWPF00x` /
  `OWNDATA00x` для Own.NET.

---

## Исходный текст предложения

Я бы забрал из NoBootCamp не "vibe coding", а disciplined agentic coding. То есть не "AI, сделай мне модуль", а "AI, вот клетка, вот правила, вот тесты, вот ножницы, шаг влево — review тебя сожрёт". Иначе это не разработка, а генератор PR'ов, которые выглядят уверенно, пока не открываешь diff.

### 1. Главное правило: AI не должен владеть задачей целиком

Плохой стиль:

```
Сделай модуль анализа async-проблем в Own.NET.
```

Это приглашение к катастрофе. Агент начнёт придумывать архитектуру, термины, классы, API, тесты, формат отчёта и, возможно, религию.

Правильный стиль:

```
Сделай только analyzer rule OWN0001:
- найти async void методы, кроме event handlers
- проект: .NET 8 analyzer
- целевые проекты: .NET Framework 4.7.2 legacy codebase
- diagnostic severity: Warning
- code fix пока не нужен
- не менять существующую архитектуру
- добавить unit tests на Roslyn analyzer test framework
```

Вот это уже задача. Маленькая, проверяемая, без "AI построит Рим, но на TypeScript".

### 2. Plan-then-build: сначала план, потом код

Для тебя это must-have. Особенно если агент работает с legacy WPF, графой расчётов, SQL, DevExpress, старым .NET Framework. Там любое "я просто чуть-чуть поправил" обычно означает "я переломал жизненный цикл окна и теперь форма держится в памяти до тепловой смерти Вселенной".

Шаблон:

```
Сначала НЕ пиши код.

Дай план изменения:
1. какие файлы надо менять;
2. какие файлы нельзя трогать;
3. какие public API останутся совместимыми;
4. какие риски есть;
5. какие тесты надо добавить;
6. как проверить, что поведение не изменилось.

После плана остановись.
```

Зачем это нужно: ты ловишь бред до того, как он превратился в diff на 900 строк. Если в плане агент пишет "создадим новый ServiceLocator", сразу бьёшь по рукам. Потому что ServiceLocator в legacy-проекте — это не паттерн, это плесень с интерфейсом.

### 3. Negative prompts: запрещай явно

AI очень любит "помочь" через скрытые побочные эффекты. Поэтому ему надо не только сказать, что делать, но и что категорически нельзя.

Для твоих проектов я бы держал постоянный блок:

```
Запрещено:
- менять public API без явного указания;
- добавлять NuGet-пакеты без отдельного разрешения;
- использовать static mutable state;
- добавлять service locator;
- глотать исключения через catch { };
- использовать async void, кроме UI event handlers;
- использовать Task.Run как маскировку синхронного IO;
- менять SQL-семантику без тестов;
- менять threading model WPF;
- трогать .csproj, packages.config, build scripts без отдельного разрешения;
- делать "рефакторинг заодно";
- переименовывать классы/методы, если задача не про это.
```

Это выглядит занудно, но это дешевле, чем потом спрашивать: "а почему checkout документа стал падать только на удалённом SQL Server после 17:30 по четвергам".

### 4. Для Own.NET это можно оформить как "Agent Contract"

Я бы сделал в репозитории папку:

```
.ai/
  project-context.md
  architecture-rules.md
  forbidden-changes.md
  task-template.md
  review-template.md
  domain-glossary.md
  testing-policy.md
```

Примерно так:

**`.ai/project-context.md`**

```
Проект Own.NET — набор инструментов для анализа .NET-кода:
- Roslyn analyzers;
- архитектурные проверки;
- async/threading diagnostics;
- IDisposable/lifetime diagnostics;
- WPF-specific diagnostics;
- legacy .NET Framework compatibility checks.

Цель: помогать безопасно улучшать legacy .NET/WPF код без массовых рискованных переписываний.
```

**`.ai/architecture-rules.md`**

```
Правила:
- analyzer rules должны быть маленькими и независимыми;
- каждая rule имеет ID, описание, severity, examples, tests;
- analyzer не должен требовать runtime execution;
- false positives должны быть явно описаны;
- dangerous autofix запрещён без отдельного review;
- diagnostics должны объяснять не только "что плохо", но и "почему".
```

**`.ai/forbidden-changes.md`**

```
Нельзя:
- делать глобальные refactorings;
- добавлять зависимости без обоснования;
- смешивать analyzer logic и reporting;
- добавлять rule без тестов;
- добавлять code fix без negative tests;
- ломать deterministic output.
```

Это превращает "чат с AI" в почти нормальный engineering workflow. Почти. Роботы всё ещё могут уверенно нести чушь, но хотя бы по форме.

### 5. Self-review: заставлять агента проверять собственный diff

После генерации кода не надо сразу верить. Это как верить junior'у, который говорит "у меня локально работает". Работает?! Телега с тремя колёсами тоже "работает", пока не надо повернуть.

Шаблон review:

```
Проверь этот diff как злой maintainer.

Ищи:
- изменение поведения;
- скрытые breaking changes;
- race conditions;
- memory leaks;
- swallowed exceptions;
- async/threading проблемы;
- слишком широкие изменения;
- отсутствие тестов;
- несоответствие задаче.

Формат ответа:
1. Blocking issues
2. Non-blocking issues
3. Missing tests
4. Safer alternative
```

Для Own.NET можно сделать это отдельным режимом: AI Review Pass.

Например:

```
Review rule OWN0003: EventSubscriptionLeakAnalyzer.
Проверь, не даёт ли analyzer false positive на weak event pattern, IDisposable cleanup, composite disposable, и WPF Binding events.
```

Вот это уже полезно. Не "похвали мой код", а "найди, где он врёт".

### 6. Для legacy WPF особенно важны agent-readable invariants

AI плохо понимает невидимые правила старого проекта. Поэтому их надо записывать явно.

Например:

```
WPF invariants:
- ViewModel не должен напрямую знать о View;
- подписки на events должны освобождаться;
- Dispatcher usage должен быть явным;
- long-running операции не должны блокировать UI thread;
- ObservableCollection изменяется только на UI thread;
- IDisposable ownership должен быть очевиден;
- Presenter/Coordinator не должен превращаться в God Object.
```

Или для твоих справочников/TNVED/ставок:

```
Data invariants:
- не материализовать весь справочник без необходимости;
- большие деревья загружать лениво;
- MessagePack blobs не декодировать полностью ради одного поля;
- SQL query должен быть parameterized;
- paging обязателен для больших выборок;
- LRU/cache не должен менять доменную семантику.
```

Это прям корм для AI-агентов. Без этого они будут "улучшать" код так, что справочник на 20k узлов внезапно грузится весь "для удобства". Удобство, ага. Для пожара.

### 7. Задачи надо резать на "атомы"

Не так:

```
Сделай модуль AsyncAnalyzer.
```

А так:

```
Task 1: OWN0001 async void detector
Task 2: OWN0002 .Result/.Wait() detector in UI context
Task 3: OWN0003 fire-and-forget Task without observation
Task 4: OWN0004 ConfigureAwait misuse policy
Task 5: OWN0005 Task.Run around synchronous DB call
Task 6: report formatter
Task 7: suppression mechanism
Task 8: documentation examples
```

Каждая задача должна иметь:

```
- вход;
- ожидаемый diagnostic;
- false positive cases;
- false negative acceptable cases;
- тесты;
- запреты;
- done criteria.
```

Иначе агент сделает функцию, которая делает больше работ, чем single parent on three shifts. IT'S FUCKING BUGGY!

### 8. Очень полезная штука: "definition of done" для AI

В конце каждого промпта:

```
Definition of Done:
- код компилируется;
- добавлены тесты;
- покрыты positive и negative cases;
- нет изменений вне заявленных файлов;
- public API не изменён;
- нет новых зависимостей;
- diagnostic message понятный;
- есть пример bad/good code;
- описаны known limitations.
```

Это не гарантия качества. Это забор. AI всё ещё может перелезть, но хотя бы будет видно, где он испачкал штаны.

### 9. Для твоего Own.NET я бы начал с таких модулей

**Async module**

Самый жирный кандидат.

```
OWNASYNC001: async void outside event handlers
OWNASYNC002: blocking wait on Task: .Wait(), .Result, GetAwaiter().GetResult()
OWNASYNC003: fire-and-forget Task without observation/logging
OWNASYNC004: Task.Run used to hide sync IO
OWNASYNC005: async method without CancellationToken in service boundary
OWNASYNC006: ConfigureAwait policy violation
```

Особенно интересно для WPF: ловить `.Result`/`.Wait()` в UI-пути. Это прям классика "почему окно умерло, хотя процесс живой".

**IDisposable / lifetime module**

```
OWNLIFE001: IDisposable field not disposed
OWNLIFE002: event subscription not unsubscribed
OWNLIFE003: IDisposable created but not owned
OWNLIFE004: CancellationTokenSource not disposed
OWNLIFE005: Stream/SqlConnection/DbCommand lifetime leak
```

Для legacy desktop это золото. Там утечки обычно не "одна большая ошибка", а тысяча мелких "ну оно же работает".

**SQL/data-access module**

```
OWNDATA001: string interpolation in SQL
OWNDATA002: concatenated SQL with user/domain input
OWNDATA003: SELECT * in repository/query object
OWNDATA004: missing transaction boundary
OWNDATA005: provider-specific SQL without abstraction marker
OWNDATA006: temp table incompatibility SQL Server/SQLite
```

С учётом твоей боли SQL Server/SQLite — прям вкусно. Можно делать analyzer + test corpus на query builder.

**WPF module**

```
OWNWPF001: ObservableCollection modified outside UI thread
OWNWPF002: event subscription leak in View/ViewModel/Presenter
OWNWPF003: long-running operation in command handler
OWNWPF004: Dispatcher.Invoke instead of BeginInvoke/async path
OWNWPF005: direct View reference from ViewModel
OWNWPF006: Bitmap/Image resource not released
```

Вот тут надо аккуратно: WPF-анализ легко даёт false positive. Но даже advisory diagnostics уже полезны.

### 10. Самый ценный формат промпта для тебя

Вот шаблон, который можно реально использовать:

```
Ты работаешь как senior .NET/Roslyn developer.

Контекст:
- проект: Own.NET
- цель: analyzer для legacy .NET/WPF проектов
- стиль: маленькие независимые rules
- тесты обязательны

Задача:
Реализовать rule OWNASYNC001: async void outside event handlers.

Требования:
- diagnostic для async void методов;
- не репортить event handlers вида void Handler(object sender, EventArgs e);
- не репортить override методов, если сигнатура навязана базовым API;
- diagnostic message должен объяснять риск;
- severity: Warning;
- code fix не делать.

Ограничения:
- не добавлять NuGet dependencies;
- не менять public API существующих rules;
- не делать unrelated refactoring;
- не менять build scripts.

Сначала дай план:
- какие файлы создашь/изменишь;
- какие тесты добавишь;
- какие false positives возможны;
- где нужна осторожность.

После плана остановись.
```

А после утверждения плана:

```
Реализуй только согласованный план.
После кода дай:
1. список изменённых файлов;
2. краткое объяснение;
3. тестовые сценарии;
4. known limitations.
```

Вот это уже не "vibe". Это нормальный рабочий протокол.

### 11. Для PR-review можно сделать отдельный "злой режим"

Например:

```
Review this PR for Own.NET.

Be strict. Assume the code is wrong until proven otherwise.

Check:
- analyzer correctness;
- false positives;
- false negatives;
- Roslyn performance;
- allocations;
- cancellation support;
- concurrency safety;
- deterministic diagnostics;
- tests quality;
- public API compatibility.

Do not praise. Find risks.
```

Это очень подходит под твой стиль "код должен заработать право существовать". И да, тут "не хвали" важно. AI по дефолту ведёт себя как HR на корпоративе: всё "promising", "solid foundation", "nice work". А тебе нужен maintainer, который скажет: "WHERE'S THE ERROR HANDLING?!"

### 12. Что реально можно протащить в твой процесс

Я бы внедрял так:

1. `.ai/` папка с правилами проекта — чтобы каждый агент не начинал с нуля и не изобретал очередной "чистый" ад.
2. Task template — одинаковый формат задач для analyzer/rule/refactor/test.
3. Review template — отдельный промпт для проверки diff'а.
4. Negative constraints — запреты на side effects, новые зависимости, public API changes.
5. Rule skeleton generator — агент генерит каркас analyzer rule, тесты, examples, docs.
6. Golden test corpus — папка с bad/good examples, чтобы AI не спорил с реальностью.
7. Regression checklist — особенно для графы 47, SQL builder, WPF lifecycle, async/threading.

### 13. Самая важная мысль

AI полезен не как "разработчик вместо тебя", а как ускоритель конкретных операций:

- накидать Roslyn analyzer skeleton;
- придумать negative test cases;
- проверить diff на риски;
- объяснить чужой код;
- сгенерить documentation examples;
- составить migration plan;
- найти edge cases;
- сделать boring code.

Но архитектурные инварианты, границы модулей, совместимость, lifecycle, перформанс и "а не превратится ли это в болото через 3 месяца" — это всё ещё на тебе. Несправедливо, конечно. Но зато без иллюзии, что "vibe" заменяет engineering. Вайб не ловит memory leak. Тесты ловят. Анализаторы ловят. Review ловит. Иногда senior с кофеином ловит.

Да. Более того, 007 — это как раз место, где такие подходы надо превращать из "хороших советов" в исполняемый протокол.

Для Own.NET это выглядело как:

> "AI, напиши analyzer rule, но вот инварианты, тесты, запреты, review."

А для 007 это должно выглядеть так:

> "007, запусти агента только внутри заданного контракта, собери diff, прогоняй gates, зафиксируй evidence, потом отдельный judge/reviewer решает, можно ли это вообще считать работой."

То есть Own.NET — пациент, а 007 — хирургическая операционная. Если операционная не стерильная, пациенту кирдык, даже если врач в белом халате и с Claude Max.

#### Что уже в 007 идеально подходит

Судя по README, 007 уже задуман как harness: `o7 run` делает worktree, запускает claude/codex, прогоняет gate steps и складывает canonical record: `task.md`, `meta.json`, `agent.stdout`, `diff.patch`, `gate/*.log`, `verdict.json`. Это прям база для disciplined agentic coding, а не "AI, сделай красиво, я отвернусь".

То есть NoBootCamp-идею надо не "применить к 007", а закодировать в 007 как режимы работы:

```
task contract → isolated run → gates → harvest → judge/review → verdict
```

И вот тут начинается мясо.

---

### 1. Для 007 нужен не "prompt template", а Task Contract

В Own.NET можно было держать `.ai/task-template.md`.

В 007 лучше сделать машиночитаемый task contract, например:

```toml
# task.o7.toml

[target]
repo = "../Own.NET"
base = "main"

[agent]
provider = "claude"
mode = "full-auto"

[scope]
allowed_paths = [
  "src/OwnNet.Analyzers/**",
  "tests/OwnNet.Analyzers.Tests/**"
]

forbidden_paths = [
  "*.csproj",
  "Directory.Build.props",
  ".github/**"
]

[change_policy]
allow_new_dependencies = false
allow_public_api_changes = false
allow_unrelated_refactoring = false
require_tests = true

[task]
kind = "roslyn-analyzer"
summary = "Implement OWNASYNC001: async void outside event handlers"

[done]
commands = [
  "dotnet test",
  "dotnet build -warnaserror"
]
```

Почему это лучше обычного `task.md`? Потому что обычный markdown — это просьба. А `.toml`/schema — это контракт. Компьютер хотя бы может проверить, что агент не полез в `.csproj`, вместо того чтобы потом человек руками обнаруживал "маленький рефакторинг" на 1800 строк. Технический долг, но с бантиком.

Что добавить в 007:

```
o7 validate-task --task task.o7.toml
o7 run --task task.o7.toml
o7 inspect-run runs/<id>
o7 judge-run runs/<id>
```

Минимальный MVP:

```
task.md          # человеческое описание
task.o7.toml     # машинный контракт
gate.toml        # команды проверки
policy.toml      # запреты / scope / allowlist
```

### 2. plan-then-build в 007 должен стать отдельной фазой

Сейчас README описывает один цикл: isolate → run → gate → harvest.

Но для coding-agent задач я бы разделил:

```
o7 plan
o7 run
o7 judge
```

То есть агент сначала не имеет права менять код. Он должен сгенерировать план:

```
runs/<target>/<run-id>/
  plan.md
  plan.meta.json
  plan.verdict.json
```

Потом отдельный gate проверяет план:

```
- план не трогает запрещённые файлы;
- план не добавляет зависимости;
- план перечисляет тесты;
- план содержит rollback/check strategy;
- план не предлагает глобальный рефакторинг.
```

И только потом:

```
o7 run --from-plan runs/.../plan.md
```

Это сильно лучше, чем давать агенту full-auto сразу. Потому что full-auto без предварительного плана — это как дать экскаватор человеку, который "примерно понял задачу". Земля, конечно, будет двигаться. Вопрос только, чья.

### 3. Negative prompts в 007 должны стать policy/gate, а не текстом

В Own.NET мы могли писать:

```
Не меняй public API.
Не добавляй зависимости.
Не трогай build scripts.
```

В 007 это надо превратить в проверяемые правила:

```toml
[diff_policy]
max_changed_files = 8
max_added_lines = 500
forbid_paths = [
  "Cargo.toml",
  "flake.nix",
  ".github/**",
  "**/*.sln",
  "**/*.csproj"
]

[dependency_policy]
allow_new_nuget = false
allow_new_npm = false
allow_new_cargo = false

[api_policy]
require_public_api_report = true
```

И gate после diff должен проверять:

```
diff.patch против policy.toml
```

Если агент полез куда не просили:

```
FAIL: touched forbidden file Directory.Build.props
FAIL: added dependency Microsoft.Extensions.DependencyInjection
FAIL: changed public API without approval
```

Вот это уже нормальная инженерия. Не "агент, пожалуйста, будь хорошим мальчиком", а "вышел за пределы клетки — run failed". WHERE'S THE ERROR HANDLING?! Вот оно, наконец-то.

### 4. 007 должен собирать не просто diff, а evidence pack

README уже говорит, что 007 harvest'ит `meta.json`, `agent.stdout`, `diff.patch`, gate logs и verdict.

Я бы расширил canonical record:

```
runs/<target>/<run-id>/
  task.md
  task.o7.toml
  plan.md
  meta.json

  diff.patch
  changed-files.json
  forbidden-touches.json

  agent/
    stdout.log
    stderr.log
    tool-calls.json

  gate/
    build.log
    test.log
    lint.log
    policy.log
    verdict.json

  judge/
    review.md
    verdict.json
    risks.json

  replay/
    base_commit.txt
    head_commit.txt
    commands.sh
```

Зачем: 007 должен быть не просто "запустил агента", а черный ящик самолёта после падения. Агент внёс diff? Докажи:

```
что он запускался в правильном repo;
от какого base commit;
какие файлы поменял;
какие gates прошли;
какие упали;
что judge сказал;
где логи;
какой prompt был;
чем run воспроизводится.
```

Иначе это не automation harness, а "скрипт, который доверяет LLM". А это уже почти религиозная практика.

### 5. judge в 007 — прямое продолжение self-review

У тебя уже есть `o7 judge`, и TODO говорит, что он проверен на read-only FP-triage и выдавал contract-conforming `fp-verdicts.json`; дальше запланирован FP-control и реальный STS-run на 156 FP-suspects.

Это очень важная часть. В терминах NoBootCamp:

```
self-correction / review prompt
```

В терминах 007:

```
judge command + rubric + schema + verdict contract
```

То есть не "Claude сам себя проверил, ну значит норм". Нет. Отдельный режим:

```
agent делает diff
judge смотрит diff + task + gate logs
judge возвращает machine-readable verdict
```

Например:

```json
{
  "verdict": "fail",
  "blocking": [
    {
      "kind": "scope_violation",
      "file": "Directory.Build.props",
      "reason": "Task did not permit build infrastructure changes"
    }
  ],
  "missing_tests": [
    "No negative test for event handler async void exception"
  ],
  "risk": "high"
}
```

Вот это годно.

### 6. Для 007 особенно важна безопасность, потому что сейчас worktree не sandbox

Вот тут надо быть неприятно честным, а не гладить 007 по README. Документ `security-layers.md` прямо говорит: `run` использует deny-list, а это не sandbox, потому что command obfuscation может проскочить. Там же указано, что worktree isolation — это cleanup/convention, но не security boundary: процесс всё равно может читать/писать вне worktree через абсолютные или `..` пути и ходить в сеть.

Ещё хуже: `.007/gate.toml` запускает произвольный `bash -lc <cmd>` из target repo. Для недоверенного repo это attacker-controlled code execution. Документ прямо фиксирует, что `current_dir` не ограничивает ни writes, ни reads, ни egress.

Что это значит для применения NoBootCamp-идей:

```
Для доверенных своих реп:
Можно начинать с policy/gates/worktree/evidence.

Для чужих или полудоверенных реп:
Без container/WASI/egress hardening это рискованно. Агентный harness без
настоящей песочницы — это "изоляция" уровня таблички "не входить" на двери
без замка.
```

Практический вывод

В 007 надо добавить `trust_level`:

```toml
[target]
trust = "trusted-local"
# trusted-local | semi-trusted | untrusted
```

И правила:

```
trusted-local:
  worktree + gates ok

semi-trusted:
  container required
  network off by default
  write mount only to worktree

untrusted:
  no agent full-auto
  judge/read-only only
  no bash gates unless sandboxed
```

Это прям должно быть в 007, иначе someday someone will run `o7 run` на "интересном" репозитории, и будет цирк с логами.

### 7. Верификация в 007 уже ближе к правильной, но её надо встроить в агентный workflow

`docs/verification.md` говорит, что проект уже использует/планирует несколько уровней: proptest для pure functions, cargo-fuzz для парсеров model stdout / findings.json / gate.toml, Kani для bounded no-panic proofs, плюс строгие lints и cargo deny.

Это отлично подходит к 007, потому что 007 — glue/orchestration, а самые опасные поверхности там:

```
- model output parsing;
- gate.toml parsing;
- findings.json parsing;
- path handling;
- command execution;
- harvest/replay correctness.
```

Я бы добавил gate profile:

```toml
[gate.profiles.fast]
steps = [
  "cargo test",
  "cargo clippy --all-targets -- -D warnings"
]

[gate.profiles.security]
steps = [
  "cargo test",
  "cargo deny check",
  "cargo +nightly fuzz run extract_json_array -- -max_total_time=60"
]

[gate.profiles.release]
steps = [
  "nix flake check",
  "cargo deny check"
]
```

И тогда task может сказать:

```toml
[required_gates]
profile = "fast"
```

А security-sensitive change:

```toml
[required_gates]
profile = "security"
```

Без этого агент может менять parser, а ты потом такой: "ну вроде тесты прошли". Какие тесты? Один happy path и молитва? IT'S FUCKING BUGGY!

### 8. Перформанс-часть: NoBootCamp тут почти не нужен, но 007 уже знает правильный рычаг

`docs/performance.md` правильно фиксирует, что 007 subprocess/LLM-bound, а не compute-bound: почти всё время уходит в ожидание claude, git, bash, а Rust glue занимает микросекунды. Единственный реальный рычаг — параллелить независимые per-file judge calls через bounded worker pool.

И TODO это подтверждает: для STS-run уже указано, что per-file claude calls независимы, sequential = сумма latency, а bounded `--jobs N` даст near-linear speedup без изменения логики pairing.

То есть для 007 я бы не тратил время на микротюнинг Rust. Никаких "давайте SmallVec", "давайте inline", "давайте cache locality". Это всё косметика на человеке, который опаздывает потому что ждёт поезд.

Что делать:

```
o7 judge --jobs 4
o7 judge --jobs 8
```

Но обязательно:

```
- bounded concurrency;
- retry/backoff;
- per-file error isolation;
- deterministic output ordering;
- rate-limit aware logs.
```

### 9. Как бы я разложил NoBootCamp-подход именно по 007

**A. `o7 plan`**

Новый режим:

```
o7 plan --repo ../Own.NET --base main --task ./task.md --out ./runs/...
```

Выход:

```
plan.md
plan.json
plan-verdict.json
```

Проверяет:

```
- scope;
- forbidden files;
- required tests;
- risk level;
- estimated gates.
```

**B. `o7 run`**

Текущий MVP, но с policy:

```
o7 run --task task.o7.toml --gate ../Own.NET/.007/gate.toml
```

Обязательно собирает:

```
- diff.patch;
- changed files;
- touched forbidden paths;
- dependency changes;
- gate logs.
```

**C. `o7 judge-run`**

Отдельная проверка результата:

```
o7 judge-run runs/Own.NET/<run-id>
```

Judge получает:

```
- original task;
- plan;
- diff;
- gate verdict;
- changed files;
- logs;
- policy violations.
```

Возвращает:

```
PASS | FAIL | NEEDS_HUMAN
```

**D. `o7 replay`**

Суперважно:

```
o7 replay runs/Own.NET/<run-id>
```

Если нельзя воспроизвести, значит evidence pack неполный. А неполный evidence pack — это как тест без assert. Красиво, бесполезно, пахнет обманом.

### 10. Самая сильная идея: 007 как "CI для AI-агентов"

Вот как я бы сформулировал роль 007:

```
007 is not an AI coding assistant.
007 is a reproducible, gated, auditable execution harness for AI coding assistants.
```

По-русски:

> 007 не должен быть "ещё одним агентом". 007 должен быть судьёй, клеткой, журналом и турникетом для агентов.

Claude/Codex могут генерировать код. 007 должен отвечать за:

```
- изоляцию;
- scope;
- запреты;
- gates;
- diff capture;
- evidence;
- judge;
- воспроизводимость;
- policy failure;
- human handoff.
```

И вот это уже реально применимо ко всем твоим штукам:

```
Own.NET       → агент пишет analyzer/rule/docs/tests
OwnAudit      → агент triage'ит findings / FP / отчёты
legacy WPF    → агент делает маленькие refactor tasks
STS           → judge по findings и false positives
sandboy       → будущая sandbox/plugin boundary
```

### 11. Что я бы сделал ближайшим шагом в 007

Не sandbox. Не Cedar. Не Verus. Не "consensus multi-agent tournament", как бы ни чесались руки построить роботизированный цирк.

Ближайший полезный шаг:

```
Task Contract + Diff Policy Gate
```

Минимально:

```
src/task_contract.rs
src/diff_policy.rs
schemas/task.o7.schema.json
examples/task.ownnet.analyzer.o7.toml
examples/policy.safe-defaults.toml
```

Первый gate:

```
- changed files are inside allowed_paths;
- forbidden_paths untouched;
- max files/lines not exceeded;
- dependency manifests unchanged unless allowed;
- task/gate/meta copied into run record.
```

Это даст 007 реальную ценность как harness, а не просто runner.

MVP формата

```toml
version = 1

[target]
repo = "../Own.NET"
base = "main"

[scope]
allowed_paths = [
  "src/**",
  "tests/**"
]
forbidden_paths = [
  ".github/**",
  "*.sln",
  "*.csproj",
  "Directory.Build.props"
]

[limits]
max_changed_files = 10
max_added_lines = 700
max_deleted_lines = 300

[policy]
allow_dependencies = false
allow_public_api_changes = false
require_tests = true
```

И после run:

```
o7 policy-check runs/<id>/diff.patch --policy task.o7.toml
```

Вердикт:

```json
{
  "verdict": "FAIL",
  "violations": [
    {
      "kind": "forbidden_path",
      "path": "Directory.Build.props"
    }
  ]
}
```

Вот это прям вкусно. Маленько, полезно, проверяемо.

---

## Итог

Да, применимо. Но для 007 это не "как писать промпты".

Для 007 правильная версия такая:

```
NoBootCamp principles → executable agent harness protocol
```

Грубо:

```
prompt discipline       → task contract
negative prompts        → diff policy
plan-then-build         → o7 plan + o7 run
self-review             → o7 judge-run
testing checklist       → gate profiles
AI output history       → evidence pack
security advice         → trust levels + sandbox triggers
```

Own.NET использует эти идеи внутри задач.

007 должен использовать эти идеи как инфраструктуру, которая не даёт задачам превратиться в агентный мусорный пожар.
