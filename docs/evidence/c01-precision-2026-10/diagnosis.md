# Phase 1 — причины ложных C01 на H1 и OpenSilver

Дата: 2026-10-23. Own.NET `1750769`. Источники прочитаны: `runs/H1/` (STATUS, 02-all-findings.jsonl, frozen facts/SARIF,
run.sh), `runs/H1-annotation/` (STATUS, metrics, recall, unresolved-register, labels-table.csv, basis.json,
disagreement-review, primary/A-labels.jsonl), `runs/DECISIONS.md`, `runs/SYNTHESIS-R-K.md`, `runs/R/delta-vs-prior.md`,
прежнее исследование `D13-validation-gate.md` §G2 и `evidence/gate/c01-fp/README.md`, `D10` (R5), OpenSilver
`REPORT.md`, `triage/TRIAGE.md`, `triage/triage.jsonl`; в Own.NET — `frontend/roslyn/OwnSharp.Extractor/Program.cs`
(подписки, teardown, provenance), `docs/notes/teardown-predicate-adversarial-audit.md`, `corpus/wpf/*/notes.md`.
`spec/OwnIR.md`, `docs/notes/subscription-leaks-and-profiles.md`, `field-notes-patterns.md` просмотрены только в
нужных местах (поля подписки, политика static/injected); полностью не читались.
Отсутствующих артефактов из списка владельца нет.

Обозначения: **[Ф]** — факт (код/данные, указан источник), **[В]** — вывод, **[?]** — открытый вопрос.

## 0. Где решается C01 (общая часть)
- [Ф] Решение «отпущено / не отпущено» принимает **extractor**, а не ядро: факт подписки в OwnIR — это
  `{event, handler, line, column, released, resource, source, lambda}` (+ `source_provenance` для #146).
  В замороженных фактах H1: 1 046 мест, `released=false` 415, `true` 83, `source` ∈ {injected 450, static 28}.
  Ядро превращает `released=false` + `source=injected` в OWN001 «never unsubscribed; its source is an injected
  dependency whose lifetime is unknown» (Program.cs:6155–6377; `ownlang/ownir.py`).
- [Ф] `released` = (a) `-=` с **тем же текстом** левой части и обработчика (`unsub.Contains($"{a.Left}|…")`,
  Program.cs:6275) в **доказанном teardown-контексте** (#278: `Dispose`/`DisposeAsync`/`OnClosed`/`OnClosing`/
  `OnUnloaded`/`OnFormClosed`/`OnFormClosing`, обработчик собственного `Closed`/`Unloaded`-события, и замыкание по
  вызовам `M()`/`this.M()`, разрешённым в метод этого же класса, Program.cs:1038–1132) и не под guard'ом параметра;
  или (b) самоотписка (#224); или (c) ротация old→new (#218, только `e.OldValue/NewValue` и пара параметров);
  или (d) остановка таймера.
- [Ф] Происхождение издателя — двухуровневое `SubscriptionSourceKind`: `static` / `local`(отбрасывается) / всё
  остальное `injected`. Исключения P-004: `this`, поле/локал, созданный `new` в классе, template part
  (`GetTemplateChild`/`FindName` по имени метода), `Behavior.AssociatedObject`, элемент собственной коллекции (#229),
  статический или не захватывающий обработчик, #146 `returned_fresh`.

## 1. Что говорят метки H1 (102 размеченных записи A)
[Ф] `basis.json` + `labels-table.csv` (после раскрытия):

| основание метки (аудитор H1) | всего | ACTIONABLE после раскрытия |
|---|---:|---:|
| APP — издателя задаёт приложение | 25 | 17 |
| OWN — издатель «свой» (ребёнок, тот же граф) | 31 | **8** (общие дочерние Geometry/PathFigure/Transform/Span) |
| REL — есть отписка/освобождение на реальном пути | 37 | 0 |
| WEAK/FWD/FP — слабое событие, пересылающий аксессор | 9 | 0 |

[Ф] Текстовый разбор всех 405 C01 (`work/classify_minus.py` → `work/minus-triage.json`; эвристика по тексту, не вердикт):
для какой доли предупреждений в том же файле есть `-=` того же члена события и того же обработчика.

| | `-=` с тем же текстом получателя | `-=` с другим получателем | `-=` нет |
|---|---:|---:|---:|
| C01-U (335 OWN001) | 217 | 88 | 43 (+12 не разобраны) |
| C01-K (41) | 22 | 16 | 3 |
| **ACTIONABLE после раскрытия (25 размеченных)** | **7** | **14** | 4 |

Методы, где стоят «одинаковые» `-=` (топ): `DisconnectHandler` 21, `Disconnect` 17, `Dispose` 13 (Dispose не прошёл
по другим причинам), `OnParentChangedCore` 9, `UntrackTarget` 8, `OnElementChanged` 5, `IDisconnectable.Disconnect` 5, …

[В] **Главный вывод диагностики:** у 21 из 25 подтверждённых ACTIONABLE тоже есть парный `-=`. Отписка при смене
значения, в `DisconnectHandler`, в `OnXChanged` у MAUI есть почти везде — дефекты как раз в том, что этот путь не
выполняется при уничтожении владельца или снимает не тот экземпляр (`Clear()`→`Reset`, новое замыкание, общий
ребёнок). Поэтому «есть `-=`» и «расширить список teardown-имён» (D13 G2 R3 «small») — запрещённые shortcut'ы и на
этих данных они **съели бы TP**.

## 2. Четыре механизма

### A. Publisher provenance
- Конкретные ложные: H1 OWN 23 BENIGN (IndicatorStackLayout ← собственный IndicatorView, FormattedString ← свои Span и
  т. д.); OpenSilver: «собственный ребёнок / тот же срок» 3, template-part-сеттеры 11 (T048–T051, T054, T057–T060,
  T062, T069).
- Нужные данные: как получен приёмник (создан владельцем, передан приложением, общий ресурс). [Ф] В OwnIR есть только
  уровень `source`; `source_provenance` — только `returned_fresh` (#146).
- Есть ли в Roslyn: частично (синтаксис присваиваний), но **различие «свой ребёнок» / «общий ребёнок из
  ресурса или стиля» по коду фреймворка не устанавливается**: 8 из 31 OWN после раскрытия — измеренные людьми утечки
  на общих дочерних объектах (H1 unresolved-register §2). Это и есть R5 (закрыт `KILL`).
- OpenSilver template part через сеттер: `HeaderButton = GetElementHeaderButton(isWpf)` → сеттер → `_headerButton =
  value` (CalendarItem.cs:101, :409) — цепочка из 3 звеньев (вспомогательный метод → свойство → поле) поверх
  уже **именного** признака `GetTemplateChild` (Program.cs:1507–1522, сравнение по имени метода). Расширение
  означало бы межпроцедурный value-flow поверх имени — против запрета «доверять названиям без symbol
  resolution» и с эффектом ≈ 0 на MAUI.
- Затронутые TP: для «свой ребёнок» — до 8 размеченных ACTIONABLE (H1-017, 038, 039, 041, 055, 061, 086, 099).
- Минимальный тест: формы 1 и 2 `controls/`; отличие «свой» vs «общий» требует знания приложения.
- Известное ограничение: да (R5, D13 G2 R1, R `delta-vs-prior.md`).
- **Вердикт: не выбирать** (риск TP, R5, нужен value-flow).

### B. Subscription lifecycle (модель release)
- Конкретные ложные: H1 REL 37 BENIGN (из них 29 в C01-U, т. е. 58% выборки C01-U); OpenSilver: переподписка в
  сеттере 16/30, отписка в не-teardown методе 10.
- Разбор REL C01-U по тому, **почему** `released=false` (по коду MAUI, `work/maui-src`, H1 A-labels):
  - `-=` в методах, вызов которых при уничтожении владельца не доказан: `DisconnectHandler`, `Disconnect`,
    `OnParentChangedCore`, `UntrackTarget`, `TearDownOldElement`, `OnDetachingFrom`, `UnregisterChildPage` и т. п.
    (большинство). [Ф] В MAUI `DisconnectHandler` не вызывается автоматически; «нет отключения хендлеров» — один
    из классов дефектов K (`01-eligibility-report.md`, OUT_OF_SCOPE). Признать эти методы teardown по имени —
    запрещено и опасно (H1-076 PolygonHandler: ACTIONABLE с `-=` именно в `DisconnectHandler`).
  - `-=` на другом выражении-получателе (параметр vs поле/свойство: `searchHandler` vs `SearchHandler`,
    `listView` vs `_listView`; pattern-переменная `scc`) — нужен alias-анализ; среди 88 DIFF_TEXT только **1**
    отличается одной лишь записью (каст/`this.`) — PhoneFlyoutPageRenderer.cs:170.
  - самоотписка (#224 уже есть; H1-056/090 — лямбда в локале и `sender`-форма), `-=` перед `+=` (не освобождение).
  - **`-=` в явной реализации интерфейса, вызванной из `Dispose(bool)` через приведение `this` к интерфейсу:**
    `protected override void Dispose(bool disposing) { if (disposing …) (this as IDisconnectable).Disconnect(); }`
    и `void IDisconnectable.Disconnect() { … _shellSection.PropertyChanged -= HandlePropertyChanged; }`
    (ShellSectionRenderer.cs:270–306, ShellSectionRootRenderer.cs:154–185, ShellItemRenderer.cs:135–173).
    [Ф] Замыкание #278 идёт только по `M()`/`this.M()` (Program.cs:1119–1121): выражение `(this as I).M()` — это
    `MemberAccess` на скобочном приведении, и разрешённый символ — **метод интерфейса**, у которого
    `ContainingType` — интерфейс, а не класс (Program.cs:1124–1127). Поэтому реализация этого же класса в teardown
    не попадает, хотя Roslyn точно знает, какая реализация будет вызвана (`FindImplementationForInterfaceMember`).
    Затронуто (текстовый прогноз): **5** предупреждений C01-U, из них размечены 2 — H1-024 (ShellSectionRenderer:32)
    и H1-065 (ShellSectionRootRenderer:101), обе BENIGN/REL; ни одного C01-K, ни одного ACTIONABLE.
- Нужные данные: символ вызываемого метода и его реализация в классе — **есть в Roslyn SemanticModel**; OwnIR менять
  не нужно (меняется только вычисление `released`).
- Затронутые TP: 0 по прогнозу (проверяется на MAUI и контролях).
- Минимальный тест: `Dispose → (this as I).M()` с `-=` (должно стать released) против: тот же вызов из не-teardown,
  реализация в базовом классе, вызов под guard'ом параметра, приведение другого объекта, вызов другого члена.
- Известное ограничение: [Ф] D13 G2 упоминает «interface dispatch» как medium-элемент (для фабрики, не для teardown) и
  «teardown not recognised» R3; никакой реализации или отрицательного эксперимента по этому ребру нет
  (`D11-negative-results.md`, `oracle-known-fps.md`, `teardown-predicate-adversarial-audit.md` — проверено поиском).

### C. Ownership/aliasing дочерних объектов
- Пересекается с A. [Ф] 8 «своих» детей оказались общими (H1). Alias-случаи из B (параметр → поле) — 10–15 мест
  по тексту, требуют доказательства, что поле не переприсваивается между `+=` и teardown (иначе снимается
  подписка с другого объекта; #163 «rebinding setter gap» уже признан для текстового сопоставления).
- **Вердикт: не выбирать** (риск TP, нужен alias/value-flow, ≥ medium).

### D. Weak subscriptions и custom event accessors
- Конкретные ложные: H1 WEAK/FWD 7 в C01-U (Application.RequestedThemeChanged через `_weakEventManager`, пересылающие
  `add => Default.X += value` у Battery/AppActions/Geolocation); OpenSilver — `KeyboardNavigation.FocusChanged` со
  слабым списком, `handler 'value'` 2.
- Нужные данные: тело `add`/`remove` издателя и семантика хранения (слабая ссылка) — есть в компиляции, если
  издатель в исходниках. Доказать «слабость» без доверия имени `WeakEventManager` нужно разбором реализации
  менеджера — межпроцедурно и по чужому типу.
- Пересылающий аксессор: [Ф] D36 (AppActions.OnAppAction, реальный дефект K) сейчас **PARTIAL** именно через OWN014
  на пересылающем `add` (`recall.md`). Подавление пересылки (D13 G2 R2) превратило бы его в MISS; правильнее
  переносить предупреждение на подписчика-вызывающего, а это новый механизм.
- **Вердикт: не выбирать** в этой итерации.

## 3. Выбор (подробно — `hypothesis-preregistration.md`)
Выбран один механизм из B: **ребро «teardown → собственная реализация интерфейса, вызванная через приведение `this`»
в существующем замыкании #278.** Это не R5 (не про время жизни издателя, а про доказательство выполнения уже
найденного `-=`), не «любой Dispose — teardown» (корни teardown не расширяются), не доверие имени
(`IDisconnectable`/`Disconnect` нигде не упоминаются; решает символ реализации).

[В] Ожидаемый эффект мал: 5 из 405 C01 на MAUI (1,2%), около 0 на OpenSilver (в области 13 вызовов
`(this as I).M()`/`((I)this).M()`, ни одного похожего на teardown-вызов, по `grep`). Основная масса ложных C01-U
этим и любым другим «доказательным» механизмом в бюджете не снимается: их отписка стоит на путях, выполнение которых
при уничтожении владельца по коду фреймворка не доказывается.
