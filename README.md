# OwnLang — PoC

Рабочий прототип того, о чём шла речь в твоих документах: маленький
ownership-язык со строгой дисциплиной владения в духе Rust, который
компилируется в C#. Это **передняя половина** всей задумки — ровно тот слой,
который документ №2 советовал строить первым (annotations/subset → analyzer →
IR), и сознательно **до** backend'а на Boogie/Dafny/F\*.

Не «Rust для C#». Честнее так:

> Статический ownership-checker для маленького ресурсного подмножества,
> с flow-sensitive анализом, моделью loans/permissions, строгой границей вызовов
> и кодогенерацией в C#.

Эта ревизия — переработка по ревью. Что изменилось: явная модель
**loans + permissions** (владелец остаётся `Owned`, borrow'ы — отдельные факты),
**`extern fn`** с запретом неизвестных вызовов, разделение диагностик на точные
коды (в т.ч. «definite» против «maybe»), и один golden-пример, лоуэрящийся в
**настоящий `ArrayPool<byte>`-код**. Маппинг старых кодов на новые — в разделе
[Changelog](#changelog-перенумерация-кодов).

---

## Что оно реально делает сегодня

```
.own файл
   ↓  lexer + recursive-descent parser
AST  (resource + extern fn + fn)
   ↓  scope/kind resolver  (имена → Symbol, классификация OWNED/BORROW/PLAIN)
   ↓  collect_signatures   (extern + локальные fn → таблица ownership-эффектов)
   ↓  lowering
CFG  (настоящие basic blocks, ветвления, merge, terminal на return, Invoke на вызов)
   ↓  flow-sensitive dataflow  (var-states + active loans; union на слиянии)
диагностики OWN0xx
   ↓  codegen
C#  (шаблоны emit_* → реальный .NET; try/finally на straight-line случае)
```

Всё запускается без зависимостей, на голом Python 3.11+. Никакого `rustc`,
никакого `dotnet` — C# только **генерируется**, не компилируется (компилятора в
песочнице нет). Golden-пример проверен *по построению* + чекером; запустить его
ты можешь у себя через `dotnet run` (см. ниже).

### Запуск

```bash
cd ownlang
python -m ownlang check  examples/ok_extern_calls.own        # проверка
python -m ownlang emit   examples/golden_arraypool/buffer.own # проверка + печать C#
python -m ownlang cfg    examples/bad_maybe_release.own       # дамп CFG
python -m ownlang report examples/buffer_scratch.own          # buffer-отчёт + .ownreport.json

python tests/run_tests.py                                     # кейсы + codegen + golden + buffer smoke
```

`check` возвращает ненулевой код при наличии ошибок — годится для CI.
`emit` **отказывается** генерировать C#, если в `.own` есть хоть одна ошибка.

### Golden-пример: настоящий ArrayPool

```bash
cd examples/golden_arraypool
dotnet run          # требует .NET SDK; в песочнице PoC его нет
```

`buffer.own` объявляет ресурс `Buffer` с шаблонами `emit_*`, отображающими его на
`System.Buffers.ArrayPool<byte>`. `python -m ownlang emit` выдаёт метод
`process` дословно так, как он вклеен в `Program.cs`:

```csharp
public static void process(int size)
{
    byte[] buf = ArrayPool<byte>.Shared.Rent(size);
    try
    {
        { // mutable borrow of buf as bytes
            var bytes = buf.AsSpan();
            Fill(bytes);
        }
        { // shared borrow of buf as view
            var view = buf.AsSpan();
            Hash(view);
        }
    }
    finally
    {
        ArrayPool<byte>.Shared.Return(buf);
    }
}
```

`Main` и заглушки `Fill`/`Hash` в `Program.cs` — это host-код, написанный руками
(`extern fn` — обещание хоста, тело даёт хост). Нюанс: `AsSpan()` берёт весь
арендованный массив (Rent может вернуть длиннее запрошенного); честная версия
писала бы `AsSpan(0, size)`, но шаблону borrow'а длина недоступна — это
сознательное упрощение для smoke-теста.

---

## Язык

Сознательно крошечный. Вся грамматика — в docstring `parser.py`.

```
module Demo

resource Buffer {        // ресурс с методами acquire/release
  acquire rent           //   -> в C#: Buffer.rent(...)   (или шаблон emit_acquire)
  release give           //   -> в C#: x.give()           (или шаблон emit_release)
  emit_type    "byte[]"                                   // опционально:
  emit_acquire "ArrayPool<byte>.Shared.Rent({args})"      //   реальное лоуэрение
  emit_release "ArrayPool<byte>.Shared.Return({0})"       //   вместо схематичного
  emit_borrow  "{0}.AsSpan()"
}

extern fn Fill(borrow_mut Buffer);   // обещание хоста: эффект каждого аргумента
extern fn Hash(borrow Buffer);
extern fn Store(consume Buffer);     // единственный способ «выпустить» владение

fn process(size: int) {
  let buf = acquire Buffer(size);    // buf: Owned<Buffer>
  borrow_mut buf as bytes {          // эксклюзивный borrow на время блока
    Fill(bytes);
  }
  Hash(buf);                         // временный shared borrow на время вызова
  release buf;                       // consume; после этого buf мёртв
}
```

Операции владения: `acquire`, `let y = move x`, `borrow x as y { }`,
`borrow_mut x as y { }`, `release x`, `use x`, `callee(args)`, `return x`.
Параметры бывают владеющие (`x: Buffer`) и заимствованные
(`x: &Buffer`, `x: &mut Buffer`).

---

## Модель: loans + permissions

Это ключевая поправка по ревью. Раньше описание состояния выглядело как
`Owned → SharedBorrowed(n) → …`, будто borrow *заменяет* `Owned`. Ревьюер
справедливо назвал это костылём. Важная деталь: **сам код и в прошлой версии**
держал счётчики borrow'ов отдельно от линейного состояния владельца — то есть
владелец и так не «терял» `Owned`. Здесь это сделано **явным** и поименованным.

**Variable state** (на каждый owned-символ) — множество из
`{OWNED, MOVED, RELEASED, ESCAPED}`. `ESCAPED` = владение покинуло функцию
(вернули через `return` или отдали в `consume`-вызов). Владелец остаётся `OWNED`
всё время, пока его одолжили — borrow никогда не перезаписывает состояние
владельца.

**Active loans** — borrow это объект первого класса `Loan(owner, binding, kind)`,
который **добавляется** при открытии и **удаляется** при закрытии. Loans живут
рядом с состояниями переменных, а не внутри них.

**Permissions** выводятся на лету из (variable-state + active loans):

| Состояние владельца | Permissions |
|---|---|
| `Owned`, нет loans | Own + Read + Write + Drop |
| `Owned`, есть shared loan | Read (Own/Write/Drop подвешены) |
| `Owned`, есть mutable loan | — (эксклюзив: владелец недоступен) |
| `Moved` / `Released` / `Escaped` | — |

Каждая операция проверяет нужное ей право и репортит точный код: `move`/`consume`
требуют Own (подвешивается *любым* loan'ом → OWN007), `release` требует Drop
(→ OWN008), `use` владельца требует Read (подвешивается mutable loan'ом → OWN013),
`borrow_mut` требует эксклюзива (живой shared → OWN006, живой mut → OWN011),
`borrow` несовместим с живым mut (→ OWN012).

Поскольку язык без циклов и borrow'ы блок-скоупные, множество активных loans
**одинаково** на всех предшественниках любого merge. Это инвариант, который
`join()` **проверяет ассертом**, а не предполагает (см. ниже про OWN010-ревьюера).

---

## Граница вызовов: `extern fn` и строгая escape-политика

Вторая большая поправка. Ревью: «неизвестный вызов — дыра размером с автобус».
Согласен полностью. Теперь:

* **Любой вызов обязан резолвиться** в объявленный `extern fn` или локальный `fn`.
  Неизвестный вызов — жёсткая ошибка **OWN040**. Протуннелить чекер через
  `SomeCSharpCall(x)` больше нельзя.
* Каждый параметр несёт **ownership-эффект**: `borrow` (временный shared loan на
  время вызова), `borrow_mut` (временный эксклюзив), `consume` (забирает владение
  → владелец становится `ESCAPED`), либо plain (например `int`).
* **Строгая escape-политика (MVP):** `borrow`/`borrow_mut`-параметры всегда
  *noescape* — у языка просто нет способа выразить «сохранить borrow». Выпустить
  значение наружу можно **только** через `consume`/Owned. Никаких `escapes`-
  аннотаций: borrow по определению безопасен.

Локальные `fn` тоже дают сигнатуру: `&mut`-параметр → `borrow_mut`,
`&` → `borrow`, owned-ресурс → `consume`, прочее → plain. Несовместимость
аргумента (shared туда, где нужен `&mut`; plain туда, где нужен ресурс; consume
через borrow; неверная арность) → **OWN041**.

---

## Правила, которые проверяются

### Поток владения / loans / permissions

| Код | Что ловит |
|-----|-----------|
| **OWN001** | owned-ресурс не освобождён на каком-то пути (утечка) |
| **OWN002** | use/… после release или consume (**definite** — на всех путях) |
| **OWN003** | двойной release |
| **OWN004** | borrow убегает из своей области (например, `return` borrow'а) |
| **OWN005** | use/… после move (**definite**) |
| **OWN006** | `borrow_mut` при живом shared borrow |
| **OWN007** | move/consume владельца под живым borrow'ом |
| **OWN008** | release владельца под живым borrow'ом |
| **OWN009** | операция над ресурсом, который **мог** быть освобождён на каком-то пути (**maybe**) |
| **OWN010** | операция над ресурсом, который **мог** быть перемещён на каком-то пути (**maybe**) |
| **OWN011** | `borrow_mut` при живом `borrow_mut` (два эксклюзива) |
| **OWN012** | shared borrow при живом `borrow_mut` |
| **OWN013** | прямое обращение к владельцу, пока он `borrow_mut` |

### Буферы: storage policies

| Код | Что ловит |
|-----|-----------|
| OWN015 | stack-backed буфер (`stack`/`scratch`/`inline`) пытается убежать из функции (`return`) |
| OWN016 | stack-backed буфер отдан в `consume`-вызов (move в более долгоживущего владельца) |
| OWN017 | movable-буфер (`pooled`/`native`) escape'ит — модель это разрешает, но PoC-codegen пока не умеет честно лоуэрить escape (см. ниже) |
| OWN019 | inline-ёмкость слишком велика для stack-backed политики (выше потолка стека) |
| OWN021 | `stack`/`inline` динамического размера без статической границы (нет `max =`) |
| OWN023 | `scratch` с `fallback = forbidden`, но размер может превысить inline-лимит |

### Неподдерживаемое / структурное / граница

| Код | Что ловит |
|-----|-----------|
| OWN020 | неподдерживаемая конструкция (цикл/async) |
| OWN030 | неизвестное имя |
| OWN031 | переопределение в области видимости |
| OWN032 | owned-ресурс скопирован без `move` |
| OWN033 | функция с типом возврата может дойти до конца без `return` |
| OWN034 | операция применена не к owned-ресурсу |
| OWN040 | вызов необъявленной функции (неизвестные вызовы запрещены) |
| OWN041 | несовместимость аргумента вызова (арность / kind / plain-vs-resource) |

Разделение **definite (002/005)** против **maybe (009/010)** — прямо по ревью:
ошибка на *всех* путях и ошибка на *каком-то* пути — это разные по резкости
сообщения, и это разделение естественно выпадает из решётки множеств состояний.
Каждый код покрыт тестом и примером в `examples/`.

---

## Где живёт настоящая работа: слияние ветвей

Документ №4 правильно показывал пальцем: вся сложность не в парсере, а в **join
состояний на merge control-flow**.

Состояние каждого owned-символа — **множество** из
`{OWNED, MOVED, RELEASED, ESCAPED}`: «что *может* быть истинно здесь по всем
путям». На слиянии берётся **объединение**:

```
let c = acquire Conn(flag);
if (flag) { release c; }     // then: c -> {RELEASED}
                             // else: (пусто) c -> {OWNED}
// merge: {RELEASED} ∪ {OWNED} = {RELEASED, OWNED}
// use c здесь            =>  OWN009 (мог быть освобождён по then-пути)
// конец функции          =>  OWN001 (утечка по else-пути)
```

Проверки на каждой операции спрашивают «безопасно ли это **на всех** путях»:
- `OWNED ∉` состояния → **definite** (OWN002/OWN005);
- `OWNED ∈`, но рядом `RELEASED`/`ESCAPED` → **maybe** (OWN009);
- `OWNED ∈`, но рядом `MOVED` → **maybe** (OWN010);
- на выходе `OWNED ∈` → OWN001.

Обход — один топологический проход по DAG (циклов нет → fixpoint не нужен).

### Важный разворот про false positives

В Snipper твоя прайм-директива была «ложное срабатывание хуже пропуска». Здесь
она **сознательно переворачивается**. Это checker безопасности: пропущенный
use-after-release — реальный баг в проде, а лишний OWN001 — просто отвергнутая
валидная программа. Поэтому анализ намеренно консервативен. Ровно так же ведёт
себя borrow checker в Rust.

---

## Кодоген в C#

Две стратегии, выбираются автоматически.

**try/finally hoist** — для функций без ветвлений, без `move` и без owned-`return`.
Каждый ресурс освобождается ровно один раз, поэтому release поднимается в
`finally` (см. golden-пример выше). Чекер **уже доказал** release-ровно-один-раз;
`finally` вдобавок держит это при исключениях.

**Почему нет runtime-флага `bReleased`.** Ревью предлагало на случай явного
`release` в середине плюс auto-`finally` завести рантайм-флаг. Я с этим **не
согласен для PoC**. Если чекер доказал release-ровно-один-раз на каждом пути
(а он доказал), то release поднимается *из* `try` — он не дублируется в теле, —
и `finally` срабатывает ровно один раз без всякого охранника. Рантайм-флаг имеет
смысл, только если мы не доверяем статическому результату; а если не доверяем —
не надо его шипать. Поэтому в PoC сознательно выбран **explicit release required**
(не RAII auto-release), а `finally` — только защита от исключений.

**faithful inline** — для функций с ветвлениями/передачей владения releases
эмитятся ровно там, где они в исходнике. Автоподъём releases из произвольного
control-flow в `finally` — настоящая работа, она в roadmap, а не подделана.

Шаблоны `emit_*` на ресурсе превращают схематичный `Resource.method()` в
реальный .NET (`ArrayPool<byte>.Shared.Rent/Return`, `byte[]`, `.AsSpan()`).

---

## Буферы: storage policies + логирование

`stackalloc` — это не оптимизация сама по себе. Это **storage strategy с жёстким
lifetime-контрактом**. Поэтому буфер в OwnLang — это owned-ресурс (release ровно
один раз, escape-проверки, конфликты borrow'ов — всё как обычно), но с явной
**политикой хранения**. Модель: *пользователь задаёт intent → checker проверяет
lifetime/ownership → backend выбирает или строго соблюдает storage → codegen
генерит безопасный C# → логи показывают фактический выбор → benchmark доказывает
выигрыш*. Не «компилятор молча решил за тебя» — а «ты задал политику, компилятор
её соблюл, runtime показал, что реально выбралось».

### Режимы

```
let a = Buffer.stack(256);                              // только stackalloc, fallback запрещён
let b = Buffer.stack(size, max = 1024);                 // динамика, но с забором (guard)
let c = Buffer.scratch(size, inline = 1024, fallback = pool);  // стек, иначе ArrayPool
let d = Buffer.pooled(size);                            // только ArrayPool; movable, Return обязателен
let e = Buffer.native(size);                            // NativeMemory; unsafe, Free обязателен
let f = Buffer.inline(128);                             // фиксированный compile-time стековый буфер
```

Главное правило: **`stack` никогда не падает в heap**; **`scratch` может**, потому
что пользователь явно разрешил fallback. API, который врёт про память, — это не
абстракция. `stack`/`scratch`/`inline` — stack-backed → не могут escape (OWN015/016).

Буфер можно `move` внутри функции — владение и storage-политика переходят на
нового владельца, и `release` нового имени освобождает исходный backing. Namespace
обязан быть `Buffer`: `Foo.stack(...)` (опечатка/чужой идентификатор) — это
**OWN030**, а не тихая аллокация.

`pooled`/`native` в **ownership-модели** movable (теоретически их можно
`return`/`consume`). Но **deliverable здесь — checker, а codegen лишь доказывает,
что модель лоуэрится в настоящий .NET**, и не раздувается в самоцель. Честно
лоуэрить *escaping* буфер нечем: значение внутри функции — это `Span<byte>`, а
отдавать наружу надо handle (`byte[]`/`byte*`+длина), которым вызывающий сделает
`Return`/`Free`. Поэтому PoC **отвергает** escape movable-буфера (**OWN017**), а не
шипает C#, который течёт или не компилируется. Локально `pooled`/`native` работают
полноценно (rent→borrow→release с реальным `ArrayPool.Return`/`NativeMemory.Free`).
Полноценный movable-lowering (через `byte[]`-handle или обёртку
`IMemoryOwner<byte>`) — **roadmap**.

### `scratch` лоуэрится так (это и есть golden buffer-пример)

```csharp
byte[]? tmp_rented = null;
Span<byte> tmp_backing = stackalloc byte[1024];
Span<byte> tmp;
if (size <= 1024)
{
    OwnTrace.ScratchSelected("parse", "tmp", size, 1024, "stackalloc");
    OwnCounters.StackHit();
    tmp = tmp_backing[..size];
}
else
{
    OwnTrace.ScratchSelected("parse", "tmp", size, 1024, "ArrayPool");
    OwnCounters.PoolFallback(size);
    tmp_rented = ArrayPool<byte>.Shared.Rent(size);
    tmp = tmp_rented.AsSpan(0, size);
}
try { /* ... */ }
finally
{
    OwnCounters.Release();
    if (tmp_rented is not null)
        ArrayPool<byte>.Shared.Return(tmp_rented);
}
```

### Логирование — обязательная часть, а не опция

Без логов `scratch` стал бы той самой «умной» абстракцией, которая молча выбрала
pool, а ты три часа смотришь на GC-график. Поэтому логи — в трёх местах:

1. **Compile-time report** (`python -m ownlang report file.own`): что checker/codegen
   решил по каждому буферу — mode, inline-лимит, fallback, escape-policy, clear,
   сгенерированные ветки и какие проверки прошли. Выводится текстом и пишется в
   `file.ownreport.json` (удобно для ревью/CI).

2. **Runtime trace** — хук `OwnTrace.*` в сгенерированном C#: какой backend реально
   выбран при конкретном `size`. Под `[Conditional("OWNSHARP_TRACE")]` — в обычном
   Release вызовы вырезаются, логирование не становится новым bottleneck'ом.

3. **Runtime counters** — `OwnCounters` (`ScratchStackHits`, `ScratchPoolFallbacks`,
   `ScratchPoolBytesRented`, `ScratchReleaseCount`) под `[Conditional("OWNSHARP_COUNTERS")]`.
   Отвечают на главный вопрос: мы реально часто попадаем в стек, или inline-лимит
   подобран мимо?

### Политики

`policy`-блок — это переиспользуемый набор дефолтов; буфер ссылается на него через
`policy =`, инлайновые опции перекрывают:

```
policy SensitiveScratch {
    inline_bytes     = 512;
    fallback         = pool;
    counters         = true;
    clear_on_release = true;       // занулить байты перед возвратом в пул
}

fn handle(size: int) {
    let secret = Buffer.scratch(size, policy = SensitiveScratch);
    borrow_mut secret as m { Fill(m); }
    release secret;                 // codegen: secret.Clear(); затем Return
}
```

### Runnable golden

`buffer_scratch_program.cs.txt` — запускаемый пример: метод `parse` и классы
`OwnTrace`/`OwnCounters` вклеены **дословно** из `python -m ownlang emit
buffer_scratch.own`, а `Fill`/`Hash`/`Main` — host-код. Доказывает, что
buffer-модель лоуэрится в настоящий .NET с реальным `ArrayPool.Rent/Return`:

```bash
dotnet run -p:DefineConstants="OWNSHARP_TRACE;OWNSHARP_COUNTERS"
# parse(64)   -> stackalloc-ветка (heap не трогаем)
# parse(4096) -> ArrayPool-ветка  (реальные Rent/Return), trace + counters в выводе
```

### Где это жульничает

Элемент буфера зафиксирован как `byte` (как во всех примерах). В straight-line
функции (без `if`/`move`/owned-return) буферы и обычные ресурсы лоуэрятся в порядке
исходника, каждый в свой exception-safe `try/finally` со split'ом по точке
`release` — **но только если времена жизни laminar** (любая пара вложена или
раздельна): непересекающиеся остаются раздельными (a возвращается до аренды b),
вложенные — нестятся (LIFO). Частичное пересечение (`let a; let b; release a; …
release b;`) hoist'ить нельзя без искажения lifetime'а, поэтому такие функции
лоуэрятся faithful-inline (release ровно там, где написан; без `try/finally`).
`scratch`/`stack`/`native` динамического размера guard'ят некорректный (в т.ч.
отрицательный) запрос **до** любого trace/counter, чтобы битый ввод не портил
метрики. Размер буфера обязан быть целым числом — `Buffer.pooled(flag: bool)` или
owned-ресурс как размер это **OWN018**; а `inline` требует compile-time
литерала — `Buffer.inline(n, max = …)` это **OWN021** (для динамики есть `stack`). `native` хранит `byte*` (backing, освобождается на release), но наружу
отдаёт `Span<byte>`-view — borrow/call видят тот же логический тип, что и
pooled/stack/scratch, так что один `extern fn Fill(borrow_mut Buffer)` лоуэрится в
одну C#-сигнатуру (`Span<byte>`) для всех storage-режимов.
В ветвистой функции (есть `if`/`move`/owned-return) используется inline-режим:
буфер с чистым вложением получает `try/finally`, а перекрывающиеся времена жизни,
ветвистый release и moved-алиасы — inline-release (реальный cleanup в местах
release'ов, без подъёма в `finally`; обычные ресурсы там тоже inline — подъём из
произвольного control-flow это roadmap). `native` динамического размера
guard'ит отрицательный запрос перед `NativeMemory.Alloc`. Escaping movable-буферы
отвергаются (OWN017), полноценный movable-lowering — roadmap. Неизвестные значения
**и имена** настроек (mode, namespace, policy, fallback, а также сами имена опций
буфера и ключей policy-блока) ловятся как **OWN030** — опечатка в
`fallback = forbidden`, `fallback = 0` или `fallbak = forbidden` не «протечёт» в
heap, а будет отвергнута. Бенчмарк-матрица из дизайн-дока
(safe vs unsafe, stack vs pool на размерах 32 B … 1 MB) — **следующий слой**:
правило «unsafe-backend разрешён только при выигрыше ≥ 10-15 % с disassembly-
обоснованием» задаёт дисциплину, но прогон бенчей вне песочницы. Unsafe-контракты
(`UNS0xx`) пока не реализованы: `native` лоуэрится в `NativeMemory.Alloc/Free` в
`unsafe`-блоке, но pointer-escape проверки — roadmap.

---

## Changelog: перенумерация кодов

Коды переразложены в связную схему. Если ты смотришь вывод прошлой версии:

| Было | Стало | Заметка |
|------|-------|---------|
| OWN006 (catch-all borrow) | OWN006 / 007 / 008 / 011 / 012 / 013 | расщеплён на конкретные нарушения |
| OWN002 (любой use-after-release) | OWN002 (definite) + OWN009 (maybe) | разделено definite/maybe |
| OWN005 (любой use-after-move) | OWN005 (definite) + OWN010 (maybe) | разделено definite/maybe |
| OWN007 (operation-requires-owned) | OWN034 | освобождён номер под loans |
| OWN010 (undefined name) | OWN030 | |
| OWN011 (redefinition) | OWN031 | |
| OWN012 (copy-owned) | OWN032 | |
| OWN013 (missing-return) | OWN033 | |
| — | OWN040 / OWN041 | новая граница вызовов |

Про **OWN010-ревьюера «incompatible-state-at-join»**: в блок-скоупном языке без
циклов несовместимых loans на merge быть не может (borrow всегда сбалансирован
внутри ветки). Поэтому это не user-facing код, а **ассерт-инвариант** в `join()`.
Добавлять диагностику, которая структурно никогда не сработает, — это та самая
декорация, против которой вся затея. Когда появятся циклы/ранний выход из borrow'а,
ассерт превратится в реальный код. (Номер OWN010 в новой схеме занят «maybe-move».)

---

## Где оно жульничает (читать обязательно)

Это PoC. Список дырок — намеренно явный.

1. **Граница вызовов закрыта, граница полей — нет.** `extern fn` + запрет
   неизвестных вызовов (OWN040) закрывают ту самую «дыру размером с автобус»:
   протуннелить владение через анонимный C#-вызов больше нельзя. Но **полей всё
   ещё нет**, поэтому «borrow сохранён в поле/замыкании/таймере» не моделируется —
   а в реальном C# это главный источник утечек (ViewModel, события). Это
   следующий шаг escape-анализа.

2. **Нет доказательств.** Это checker, не verifier. Никакого Boogie/Dafny/F\*.
   Soundness не доказан — он аргументирован и протестирован. Трансляция в Dafny/F\*
   и доказательство — **следующий слой**, не этот.

3. **Циклы и async отвергаются, а не анализируются** (OWN020). Нужен worklist с
   fixpoint и loop-инварианты владения; CFG к этому готов (DAG-проход → worklist).

4. **C# в песочнице не запускается.** Компилятора нет, поэтому golden-пример
   проверен *по построению* и чекером, **не исполнен**. У себя: `dotnet run`
   в `examples/golden_arraypool`.

5. **Нет настоящей системы типов.** Ресурсы номинальные, аргументы `acquire` не
   типизируются, арифметики нет. Условие в `if` — непрозрачный текст: моделируется
   control-flow, а не значения. Возвращаемое значение вызова не отслеживается
   (вызов как statement; если локальный `fn` возвращает ресурс — он не трекается).

6. **Запрещено shadowing** (OWN031). Rust разрешает; для PoC запрет проще.

---

## Как это ложится на твои документы

| Слой из документов | Статус в PoC |
|--------------------|--------------|
| OwnLang v0: ownership-ядро, borrow-блоки, must-release, C# codegen (док №4) | **сделано** |
| OwnSharp IR: CFG + ownership facts (док №2, Phase 2) | **сделано** (CFG + dataflow + loans/permissions) |
| Явная граница interop / escape-policy (док №2/3) | **частично** — вызовы закрыты (OWN040/041), поля нет |
| Roslyn analyzer для C# с аннотациями (док №2, Phase 1; док №1, Option 1) | не здесь — альтернативный фронтенд |
| Boogie backend / proof obligations (док №2, Phase 3) | roadmap |
| Dafny backend (док №2, Phase 4) | roadmap |
| F\* soundness ядра (док №2, Phase 6) | roadmap |
| IDE-визуализация в стиле RustOwl (док №1; док №4) | roadmap — CFG-дамп это зачаток |

Ближайший следующий шаг: **escape через поля** (пункт 1), потом **Boogie backend** —
генерить из той же CFG proof obligations и гонять через Z3.

---

## Структура

```
ownlang/
  ownlang/
    lexer.py        # токенизатор; цикл/async лексятся как REJECTED; строки для emit_*
    ast_nodes.py    # dataclass-узлы AST (resource, extern, call, эффекты, buffer, policy)
    parser.py       # recursive descent; грамматика в docstring
    buffers.py      # storage policies: режимы, резолв policy+intent, валидация
    cfg.py          # resolver (Symbol/Kind) + collect_signatures + lowering, Invoke
    analysis.py     # flow-sensitive dataflow: var-states + active loans + permissions
    diagnostics.py  # коды OWN0xx в одном месте
    codegen.py      # C# codegen (emit_* шаблоны, try/finally hoist + inline, буферы)
    report.py       # compile-time buffer report -> stdout + .ownreport.json
    __main__.py     # CLI: check / emit / cfg / report
  examples/
    ok_*.own                  # проходят
    bad_*.own                 # падают с конкретным кодом
    golden_arraypool/         # buffer.own + Program.cs + demo.csproj (dotnet run)
  tests/run_tests.py          # 42 кейса анализа + codegen smoke + golden smoke
```
