# Real-world corpus

Не «Damn Vulnerable .NET app», а **Damn Leaky Resource Corpus**: настоящие
паттерны багов владения ресурсами из реального .NET-кода (ArrayPool, `Dispose`,
pooled buffers), сведённые к минимальной OwnLang-модели, на которой видно, как
checker их ловит.

Каждый кейс — папка с пятью файлами:

| Файл | Что это |
|------|---------|
| `before.cs` | багованный C#-фрагмент (паттерн как в реальном коде) |
| `after.cs` | исправленная версия |
| `case.own` | минимальная OwnLang-модель того же владения |
| `expected-diagnostics.txt` | коды, которые checker обязан выдать на `case.own` |
| `notes.md` | паттерн, источник и честная рамка |

Прогон (часть общего сьюта — `tests/test_corpus.py`):

```bash
python tests/test_corpus.py
```

## Честная рамка (читать обязательно)

`case.own` — это **ручная редукция** C#-паттерна, а **не** C#, который checker
прочитал: у OwnLang нет фронтенда по C#. Корпус доказывает, что **логика
владения ложится на настоящие баги** — будь это написано на OwnLang, checker бы
отверг. `before.cs`/`after.cs` репрезентативны для паттерна, это не дословный
дифф одного PR.

## Что выразимо, а что нет

Сейчас checker берёт «голый borrow»: leak / use-after-return / double-return /
escape / release-while-borrowed. **Не** выразимо (нужны новые модели — roadmap):
over-clear по границе `Span` (нет region/length-анализа), утечка только на
exception-path (анализ не моделирует исключения), concurrent `Dispose` (нет
конкурентности), async.

## Кейсы

| Кейс | Код | Реальный паттерн |
|------|-----|------------------|
| `arraypool-use-after-return` | OWN002 | rented-буфер вернули в пул, потом ещё читали slice |
| `arraypool-double-return` | OWN003 | один и тот же массив вернули в ArrayPool дважды ([#33767](https://github.com/dotnet/runtime/issues/33767)) |
| `ownership-handoff-use` | OWN002 | поток отдали потребителю (он его закрыл), потом ещё читали — use-after-handoff |
| `ownership-handoff-use-transitive` | OWN002 | то же, но потребитель не закрывает сам, а **пробрасывает** владение дальше (transitive consume) |
