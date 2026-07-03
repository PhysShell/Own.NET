# AGENTS.execution-surfaces.md

> ADR + task spec. Итог аудита идеи «Forth-like stack VM как внутренний IR»
> для Own.NET.
>
> Документ агентно-ориентированный: можно скармливать Claude Code / Codex как
> контекст задачи целиком или по секциям.

---

## 0. Решение (ADR)

Статус: **accepted**.

**REJECT** — Forth-like stack VM как внутренний IR для Own.NET:

- universal stack bytecode как центральная модель исполнения;
- сырой stack-DSL (`DUP` / `SWAP` / `ROT`) для написания людьми;
- VM «на вырост» под спекулятивные workload'ы, которых сейчас нет;
- отдельный интерпретатор правил поверх уже существующего dataflow-ядра.

**ADOPT** — problem-oriented execution surface для Own.NET:

- typed operation/primitive registry;
- explicit typed signatures + композиционная проверка pipeline'ов через существующий mypy gate, не через runtime-VM;
- structured evidence/provenance как расширение существующего `diagnostics.Evidence`;
- small composable primitives;
- registry операций/детекторов вместо нового DSL;
- per-finding explain surface — отдельно и позже, после покрытия diagnostics evidence.

**RECONSIDER LATER** — generated stack bytecode допустим только при появлении
workload'а профиля AwkwardForth:

- машинно-генерируемые программы;
- линейная потоковая обработка;
- высокочастотное исполнение;
- нужен portable bytecode;
- человек этот язык руками не пишет.

Такого workload'а в Own.NET сейчас нет.

---

## 1. Обоснование

Ядро Own.NET — это не линейный pipeline вида:

```
input -> transform -> transform -> output
```

Текущая модель Own.NET:

```
parser
  -> CFG
  -> flow-sensitive dataflow
  -> worklist-fixpoint
  -> ActiveLoans
  -> union на merge
  -> diagnostics
```

Это graph/fixpoint-задача, а не задача для стекового байткода.

Стековая VM хорошо ложится на straight-line обработку потока данных. Own.NET же решает задачу распространения состояний по CFG:

- состояние owned-символа — множество `{OWNED, MOVED, RELEASED, ESCAPED}`;
- borrow — first-class `Loan`;
- active loans живут рядом с variable state;
- на merge происходит union состояний;
- циклы обрабатываются worklist-fixpoint;
- diagnostics эмитятся после схождения.

Стековый IR здесь создаст лишний слой, поверх которого всё равно придётся писать fixpoint-driver. То есть VM не заменит ядро анализа, а станет дополнительной accidental complexity.

Естественный декларативный target при росте — Datalog / реляционная модель / Ascent / Soufflé-подобный подход, но не сейчас. Текущий Python worklist остаётся рабочей моделью PoC.

Хорошие идеи Forth отделимы от стека:

```
dictionary      -> registry операций
stack effects   -> typed signatures
trace           -> structured evidence
REPL            -> query shell поверх registry
small words     -> small composable primitives
```

---

## 2. Target design: typed rule primitive registry

### 2.1 PrimitiveSpec

Каждый детектор-примитив регистрируется с метаданными.

```python
from dataclasses import dataclass
from enum import Enum

class Effect(Enum):
    PURE = "pure"           # только читит факты
    REPORTS = "reports"     # эмитит диагностику

@dataclass(frozen=True)
class PrimitiveSpec:
    name: str                        # "loan_active_at"
    input_types: tuple[type, ...]    # conceptual: (Loan, Location)
    output_type: type                # conceptual: bool / Sequence[Loan] / state enum
    effect: Effect
    required_facts: frozenset[str]   # {"loans", "cfg"}
    doc: str
```

Примитивы — обычные типизированные функции.

Registry:

```
dict name -> (PrimitiveSpec, function)
```

Композиционная корректность pipeline'ов проверяется существующим mypy gate репы:

```
ruff check .
mypy ownlang
```

Никакого runtime-bytecode, VM, отдельного parser DSL или Forth-like исполнения.

### 2.2 Концептуальный стартовый набор примитивов

Стартовый набор вытаскивается из текущего `analysis.py`, не меняя семантику:

```
state_at(Symbol, Location) -> OwnershipState
loan_active_at(Loan, Location) -> bool
loans_of(Symbol, Location) -> Sequence[Loan]
escapes_at(Symbol, Location) -> bool
moved_between(Symbol, Location, Location) -> bool
```

Важно: сигнатуры выше — целевая концептуальная форма API, не требование вводить новые доменные типы.

`Location` / `OwnershipState` в текущем коде не существуют. Текущая модель — это:

```
CFG
State
VarState
Loan
Block
Instr
line
RID
handle_rid
```

При реализации маппить концептуальные сигнатуры на существующие типы. Не плодить параллельную ownership-модель. Новые доменные типы — только отдельным PR с тестами и явным обоснованием.

---

## 3. Structured evidence: расширить существующий Evidence

В Own.NET уже есть каноническая модель structured evidence:

```
diagnostics.Evidence
Diagnostic.evidence
ownlang/evidence.py
```

`diagnostics.Evidence` / `Diagnostic.evidence` — structured successor текстовых riders: location, role, rendering.

`ownlang/evidence.py` — проекция reachability-slice evidence в SARIF:

```
relatedLocations
codeFlows
```

Это общий shape для OwnIR DI checker, ownership checker и будущих frontends.

### 3.1 Что делать

Расширить покрытие evidence, не заменять модель:

- `Evidence` остаётся каноническим per-diagnostic shape вторичных локаций;
- добавить недостающие evidence-продьюсеры в `analysis.py` для выбранных flow-диагностик;
- OwnIR/SARIF `codeFlows` потребляют тот же evidence-словарь;
- render evidence — только в presentation слоях: CLI / SARIF / human output;
- задокументировать, где merge-point evidence остаётся частичным.

### 3.2 Какие события покрывать evidence

Приоритетные события:

```
resource assigned/acquired
loan issued
loan killed
resource moved
resource released
resource consumed/escaped
return escape
merge-point union
```

Для merge-point evidence честно указывать ограничения. Не изображать точность, которой нет. Это статанализатор, а не гадалка в халате.

### 3.3 Что запрещено

Запрещено вводить параллельный provenance type:

```
ProvenanceFact
FactKind
FlowFact
Evidence2
```

Два стандарта provenance для борьбы с одним — это не архитектура, это «Utils2».

---

## 4. Per-finding explain: не перегружать существующую команду explain

Текущая команда:

```
python -m ownlang explain OWN001
python -m ownlang explain --json findings.json
```

— это каталог кодов диагностик: what / why / fix для diagnostic code.

Она не является трассой конкретного finding. Семантику не менять, provenance на неё не вешать.

Per-finding объяснение строится на `Diagnostic.evidence` и выносится в отдельную поверхность после появления покрытия evidence.

Кандидаты:

```
check --show-evidence
ownir --format human --show-evidence
trace <file.own>
```

В рамках текущей задачи обязательна только структурная часть: diagnostics должны нести evidence. Presentation surface едет следом.

---

## 5. Acceptance criteria

- [ ] Весь существующий тест-сьют зелёный.
- [ ] Семантика текущих проверок не менялась.
- [ ] Минимум 3 flow-диагностики несут непустой `Diagnostic.evidence`.
- [ ] Среди этих диагностик есть минимум одна из класса escape / lifetime / resource-leak.
- [ ] Среди этих диагностик есть минимум одна из класса use-after-move / use-after-release.
- [ ] Конкретные коды указаны в PR-описании, не спрятаны за словом «escape».
- [ ] Golden test на evidence в SARIF/codeFlows или human-render snapshot.
- [ ] `.ownreport.json` не перегружен.
- [ ] Новые/изменённые модули `ownlang` проходят существующий gate: `ruff check .` + `mypy ownlang`.
- [ ] Не добавлены новые `# type: ignore` ради прохождения gate.
- [ ] README обновлён: в «Where it cheats» честно описано, где merge-point evidence остаётся неполным.

### 5.1 Что считать escape / lifetime / resource-leak классом

В текущей модели слово «escape» многозначно. В PR-описании указывать конкретные коды.

Примеры:

```
OWN001       resource leak
OWN014       lifetime / region escape
OWN015       stack-backed buffer escapes current function
OWN016       stack-backed buffer moved to longer-lived owner
OWN017       movable buffer escape unsupported by codegen
ESCAPED      internal state
consume      call-boundary escape
return       return escape
```

---

## 6. Что НЕ делать

- НЕ переписывать worklist/dataflow на Datalog сейчас.
- НЕ строить stack VM.
- НЕ строить интерпретатор правил.
- НЕ делать свой parser rule-DSL.
- НЕ вводить второй provenance-тип параллельно `diagnostics.Evidence`.
- НЕ вводить строковые provenance-факты вместо structured evidence.
- НЕ перегружать существующую команду `explain`.
- НЕ перегружать `.ownreport.json`.
- НЕ материализовать `Location` / `OwnershipState` из conceptual signatures как новые типы.
- НЕ менять mypy-конфиг всего репозитория ради галочки.
- НЕ упрощать branches в `analysis.py` ради эстетики, если это ухудшает читаемость dataflow.

---

## 7. Лестница развития

Текущий порядок:

1. Python worklist жив, пока жив PoC.
2. Добавить evidence coverage.
3. Выделить facts/relations явно.
4. Только потом смотреть Datalog / Ascent / Soufflé.

Datalog пересматривать только при реальной боли:

- больше 30–50 правил с болезненными interdependencies;
- императивный код правил стал неуправляемым;
- есть измеримые проблемы с поддерживаемостью;
- ядро реально переезжает на Rust.

Не пересматривать потому что «было бы красиво». Это не критерий, это источник техдолга с поэтическим уклоном.

---

## 8. Trigger table

| Решение отклонено | Пересмотреть, если | Кандидат |
| --- | --- | --- |
| Datalog-ядро | >30–50 правил с болезненными interdependencies, либо переезд ядра на Rust | Ascent / Soufflé |
| Stack bytecode | Появился workload: машинно-генерируемые, линейные, высокочастотные программы, потоковая обработка, portable bytecode, человек язык не пишет | маленькая typed stack VM |
| Per-finding explain UI | У diagnostics уже есть стабильное evidence coverage | `check --show-evidence`, `ownir --format human --show-evidence`, `trace` |
| REPL/query shell | Registry уже существует и полезен вручную | `ownnet repl` |

Правило:

```
trigger = цифры из профилировщика или реальная боль в коде
```

Не:

```
trigger = красиво звучит в ADR
```

---

## 9. Порядок работ

1. Добавить evidence coverage для 3 flow-диагностик.
2. Добавить golden/snapshot test на evidence.
3. Убедиться, что SARIF/codeFlows или human-render поверхность показывает evidence.
4. Обновить README: «Where it cheats».
5. Только после этого думать про registry/query shell.
6. Никаких VM, Datalog rewrite и rule DSL в этом этапе.

---

## 10. Placement

Канонический файл:

```
PhysShell/Own.NET/AGENTS.execution-surfaces.md
```

Этот документ относится к Own.NET. Не добавлять сюда графу 47, 007 или другие проекты.
