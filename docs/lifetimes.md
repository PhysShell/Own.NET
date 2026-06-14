# OwnSharp Lifetimes — модуль `lifetimes` (design)

> Статус: **draft на согласование.** Описывает, куда растёт PoC после ownership/
> borrow-ядра. Код ещё не написан — это контракт на синтаксис и границы слайсов,
> чтобы не трогать парсер вслепую.

## 1. Зачем

Performance-профиль (`stackalloc`/`scratch`/pool) — это «игрушка для
performance-зоопарка». Бизнес-софт чаще умирает не от того, что `Span<byte>` на
7 нс медленнее, а от того, что `CustomerWindowViewModel` висит в памяти весь
день: кто-то подписался на singleton-event и не отписался. Окно закрыто, а
ViewModel жива — зомби с `INotifyPropertyChanged`. GC не телепат: объект
достижим из app-lifetime root через `EventBus -> delegate -> VM.OnChanged -> VM`,
значит он не мусор.

Цель модуля: **статический lifetime/ownership-чекер для .NET-ресурсов**, который
говорит «кто кого держит, кто обязан отпустить, и почему закрытое окно не
умирает» — с фокусом на WPF-утечки (подписки, таймеры, кэши, `IDisposable`).

Архитектура — **модульный монолит** с platform-agnostic ядром:

```
ownlang/
  core      states/lattice/dataflow/diagnostics  (= нынешние analysis/cfg/diagnostics)
  buffers   профиль OwnSharp.Performance          (есть)
  lifetimes профиль OwnSharp.Lifetimes            (этот док)
  frontend/csharp  Roslyn-ингест                  (далёкая фаза)
```

## 2. Ключевая идея: reachability → linear ownership

«VM стала достижима из AppLifetime через подписку» — это по-честному
escape/reachability-анализ через хранимые ссылки между объектами, тяжелее нашего
intra-procedural flow. Но есть сворачивание, и оно же — в самой модели WPF:

> `Subscribe` возвращает **`Owned<SubscriptionToken>`**, который **обязан быть
> released в `Dispose`**.

Эта формулировка переводит проблему достижимости обратно в **линейную
ownership-дисциплину**, которую ядро уже делает: «owned-ресурс не released на всех
путях» = `OWN001`. То есть бóльшая часть бизнес-ценности достаётся
**переиспользованием** проверенного движка, а не новой тяжёлой аналитикой.

## 3. Что УЖЕ выразимо сегодня (без изменений языка)

Моделируем ViewModel как **scope функции**: «поля» = owned-ресурсы, которые она
держит; «`Dispose`» = конец scope, где всё обязано быть отпущено. Тогда:

```ownlang
resource Subscription {       // токен подписки
    acquire Subscribe         // bus.Subscribe<T>(handler) -> token
    release Dispose           // token.Dispose()
}

fn CustomerViewModel_buggy(bus: int) {
    let token = acquire Subscription(bus);
    // нет Dispose -> bus держит VM живой
}
```

Сегодняшний вывод чекера, дословно:

```text
$ python -m ownlang check vm.own
vm.own:12:9: error: [OWN001] 'token' is owned but not released at end of function
  12 |     let token = acquire Subscription(bus);
               ^
```

Симметрично: использование после `Dispose` → `OWN002` (use-after-release),
двойной `Dispose` → `OWN003`. **Главный класс WPF-утечек ядро ловит уже сейчас.**
Это и делает slice #1 дешёвым: его задача — не новый анализ, а *доказать
корпусом*, что ownership-логика ложится на реальные WPF-баги, и дать
WPF-ориентированную подачу.

## 4. Что НОВОЕ (нужен дизайн): lifetime-регионы

Чего текущая модель не выражает — **порядок времён жизни** и утечку из короткого
региона в длинный. Предлагаемый синтаксис:

```ownlang
lifetime App;
lifetime Window < App;        // Window строго короче App
lifetime ViewModel < Window;
```

`<` задаёт строгий частичный порядок (DAG, без циклов — проверяется в
`__post_init__`/резолвере: вот первый *настоящий* меж-полевой инвариант, ради
которого post_init окупается). Объект из короткого региона, ставший достижимым из
длинного через strong-подписку, — это `WPF010` (lifetime promotion), если нет
owned-токена с гарантированным release. Это **slice #2**: тут появляется
региональная аннотация на параметрах (`[Lifetime("App")] bus`) и проверка
«source_lifetime > listener_lifetime ⇒ нужен токен».

## 5. Каталог кодов (OWN-WPF) и куда какой слайс

| Код | Смысл | Сводится к | Слайс |
|-----|-------|-----------|-------|
| WPF004 | `Subscribe` вернул owned-токен, результат проигнорирован → утечёт | `OWN001` | **#1** |
| WPF005 | `IDisposable`-поле требует `VM : IDisposable` + cascade `Dispose` | `OWN001`/`OWN002` | **#1** |
| WPF002 | `DispatcherTimer`/`Timer` в VM требует `Stop`+detach | `OWN001` | #1/#2 |
| WPF008 | `CollectionChanged`/`PropertyChanged` подписка без отписки | `OWN001` | #2 |
| WPF010 | объект ушёл из короткого lifetime в длинный (region escape) | новый region-анализ | **#2** |
| WPF003 | static-подписка запрещена без weak | region + policy | #2 |
| WPF001/006/007/009 | event+= / DataContext / lambda-capture / static cache | region + capture-анализ | позже |

MVP (slice #1) сознательно сводит WPF004/005/002 к уже-работающим OWN-кодам.
Региональная половина (WPF010 и зависящие) — slice #2.

## 6. Слайсы

- **slice #1 (сейчас):** WPF-корпус `corpus/wpf/` (zombie-VM, незакрытый таймер,
  disposable-поле) на текущем движке + WPF-галерея + self-checking тест. Опционально
  — тонкий WPF-флейвор слой над диагностиками (см. развилку B).
- **slice #2:** lifetime-регионы (`lifetime A < B;`), region-escape-анализ, WPF010.
- **slice #3 (далеко):** узкий Roslyn-frontend — pattern matcher (`event +=`,
  `Subscribe<T>`, `DispatcherTimer`, `IDisposable`-поля) → кормит это же ядро.
  Не «ингест всего C#» (это человеко-годы), а распознавание известных паттернов.

## 7. Открытые развилки (на согласование)

- **A. Синтаксис регионов:** `lifetime Window < App;` (короче-чем). Альтернатива —
  `lifetime Window inside App;`. Решает читаемость.
- **B. MVP-подача:** выдавать ли в slice #1 WPF-специфичные коды (`WPF004:
  subscription token never disposed`) или переиспользовать `OWN001/002` с
  WPF-формулировкой в корпусе/нотах. Первое — лучше UX и «продаваемость», стоит
  тонкого слоя «вид ресурса = subscription/timer». Второе — ноль нового кода.

## 8. Честность / scope

- `case.own` — **hand reduction** WPF-паттерна, не C#, который чекер съел: фронта
  C# нет (slice #3). Корпус показывает, что ownership-логика **ложится** на
  реальный баг, а не что инструмент просканировал реальный код.
- Финализаторы тут не лечат причину: объект, удерживаемый event/static-ссылкой,
  до финализации не доходит. Полезны только как debug-sentinel — вне scope ядра.
- Weak events — отдельная policy в slice #2, не серебряная пуля (таймеры,
  unmanaged, кэши всё равно требуют ownership).
