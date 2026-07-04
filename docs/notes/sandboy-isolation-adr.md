# ADR: Sandboy — изоляция агентов (design-readiness)

> ADR + design note для **Sandboy** — припаркованного sibling'а `007`.
> Sibling-проект, не Own.NET-core: живёт в неймспейсе Own.NET (как зафиксировано
> в `007/README.md` и `docs/notes/strictness-and-fitness.md`), но решает задачу
> **`007`** — см. `007/docs/security-layers.md`. Не Own.NET-фича; в `docs/proposals/`
> (`P-NNN`) не заводится намеренно.
>
> Статус: **accepted (направление)** · draft (design). Итог аудита: «хватает ли
> информации, чтобы проектировать Sandboy». Ответ: по **изоляции** — да,
> направление ясное; по **WIT-плагинам** — паркуем.

---

## 0. Решение (ADR)

**ADOPT** — Sandboy как **механизм изоляции агентов**, а не расширяемости:

- OS-level граница вокруг агента, который запускает **нативные** тулы
  (`bash`, `git`, `claude`/`codex` CLI, компиляторы, пакетные менеджеры) и
  исполняет недоверенные `bash -lc`-шаги из репо-конфига (`.007/gate.toml`);
- цель — дать агенту **широкую свободу внутри коробки**, из которой он не может
  повредить хост или утечь данными;
- архитектура — **defense-in-depth** (три слоя, § 4), а не «выбрать один рантайм».

**PARK** — WASM/WIT plugin surface (custom rules «на любом языке»):

- реального спроса нет (в т.ч. у автора); рынок такого не просит — победившая
  расширяемость анализаторов это **декларативный rule-DSL** (Semgrep, CodeQL) либо
  **same-language in-process** плагины (ESLint, Roslyn), но не кросс-языковой
  WASM-ABI;
- конфликтует с уже принятым `AGENTS.execution-surfaces.md` (rule-DSL/интерпретатор
  **отклонён** в пользу typed primitive registry);
- остаётся строкой в trigger-table (§ 6) — «сделать при появлении внешних авторов
  правил, упёршихся в один язык».

**REJECT (для этого workload'а)** — WASM/Wasmtime/WASI как механизм изоляции
**агента**: агент гоняет нативные бинари, а не WASM-модули; WASI-capability-песочница
к ним неприменима. WASM годен только для plugin-кейса выше, не для изоляции агента.

---

## 1. Motivation — реальная боль

Из `007/docs/security-layers.md` (ADR, accepted): острейшая present-day граница
`007` — **`o7 run`/gate**. `gate.rs` исполняет **произвольный `bash -lc <cmd>` из
`.007/gate.toml` целевого репозитория**, агент бежит под `bypassPermissions`, а
`current_dir(worktree)` — **не** confinement:

- пишет вне дерева через абсолютные пути / `..`;
- читает всё, что может пользователь;
- ходит в сеть (egress не закрыт).

worktree — это cleanup-convenience, а не sandbox. «Слот под песочницу» — здесь, в
`run`/gate, **не** в `judge` (тот уже closed-world). Sandboy — это заполнение
этого слота.

Личный триггер (для-души-проект, self-use): автор сам гоняет агентов и хочет
**смело давать фулл-пермишен**, не боясь жёстко сломать машину. Боль настоящая и
своя — валидация N=1 достаточна для крафтового проекта.

---

## 2. Scope / Non-goals

**Scope:**

- изоляция process-tree агента + gate-шагов на **Linux**;
- четыре оси угроз: (a) egress/exfil, (b) защита ФС хоста от абсолютных/`..` путей,
  (c) host-escape resistance против враждебного кода, (d) runaway-лимиты (CPU/RAM/диск/время);
- эфемерность: коробка на задачу, teardown дёшев.

**Non-goals (важнейший раздел — отказ от soul-eating версии):**

- **НЕ** мульти-tenant hosting-платформа. Один tenant (сам автор). Side-channel
  (Spectre/MDS) вне модели угроз (§ 5) — при N=1 он неактуален.
- **НЕ** WASM plugin runtime (§ 0, PARK).
- **НЕ** свой гипервизор / свой LSM. Берём готовое (Firecracker/gVisor/Landlock),
  Sandboy — это **интеграция + policy**, не новый изоляционный примитив.
- **НЕ** «универсальный» кросс-OS. macOS-хост обслуживается только через Linux-VM
  (Lima/Colima) или managed-сервис; нативной macOS-песочницы не строим.

---

## 3. Модель угроз — что внутри границы

| | Trust |
|---|---|
| Хост-ОС/ядро, бинарь Sandboy | **доверенные** |
| Агент + все тулы, которые он спавнит | **недоверенные** (враждебны с момента старта) |
| `.007/gate.toml` целевого репо | **недоверенный** (attacker-controlled code execution) |
| Сеть наружу | **недоверенная** (потенциальный exfil-канал) |

Что защищаем: главный checkout и файлы вне рабочей директории; секреты/код от
утечки; сам хост от поломки; машину от runaway-нагрузки. Остаточный **TOCTOU**
между `canonicalize` и `open` (который строковые проверки `judge` не закрывают) —
закрывает именно реальный sandbox-слой, т.е. Sandboy.

---

## 4. Решение: defense-in-depth (3 слоя)

Не «выбрать один рантайм», а слои — каждый закрывает свою угрозу:

```
┌─ Слой 1: внешняя граница (host-escape) ────────────────┐
│  Firecracker microVM вокруг всего агента.              │
│  VM-grade изоляция; свой kernel на sandbox.            │
│  ⚠ держать VMM пропатченным (§ 5 — 2026 escape-CVE).   │
│                                                         │
│  ┌─ Слой 2: least-privilege на команду ─────────────┐  │
│  │  Sandlock-style «wrap-the-child»:                 │  │
│  │  каждый bash -lc из gate.toml форкается →         │  │
│  │  конфайнится (Landlock FS/TCP + seccomp) → exec.  │  │
│  │  Ложится 1:1 на gate.rs. ~5-6 мс на шаг.          │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  Слой 3: egress — netns + фильтрующий proxy,           │
│  UDP заблокирован, домены по allowlist (§ 4.1).        │
└─────────────────────────────────────────────────────────┘
```

**Ведущие кандидаты по слоям:**

- Слой 1 — **Firecracker** (VM-grade, ~100–125 мс старт, ~5 МБ overhead; нужен KVM).
  Альтернатива — **gVisor/systrap** (меньшая attack-surface без управления образами
  ядра, работает **без** KVM), но у него **пробелы совместимости сисколлов** —
  риск для агента с произвольным toolchain (открытый вопрос № 1). Под «широкую
  свободу» Firecracker безопаснее.
- Слой 2 — **Sandlock** (`arXiv:2605.26298`, `github.com/multikernel/sandlock`):
  непривилегированные примитивы (Landlock + seccomp-bpf + seccomp-notify),
  **без root / mount-ns / cgroups**, ~5–6 мс старт. Прямое попадание в `gate.toml`-слот.
- Слой 3 — netns + `nftables`/proxy (см. § 4.1).

**Минимальная жизнеспособная версия (MVP):** если KVM нет или хочется портабельно —
**начать только со Слоя 2** (Sandlock/Landlock): ~80 % ценности за ~20 % усилий,
законченный самостоятельный проект. Слой 1 (VM-граница) добавляется, когда в скоуп
попадёт недоверенный target-репо (триггер из `security-layers.md`).

### 4.1 Egress — единственная универсально слабая ось

Ни один механизм не даёт default-deny egress «бесплатно». Даже лучшие доменные
allowlist'ы инспектируют **только HTTP Host-header и TLS-SNI** — зашифрованный
**UDP/QUIC/HTTP3 обходит L7-политику везде** (E2B, Daytona, Sandlock).

Решение Sandboy: **блокировать UDP целиком + CIDR-фильтрация** на netns, домены —
через L7-proxy на allowlist. QUIC-обход агентам, как правило, не нужен (открытый
вопрос № 3).

---

## 5. Чего НЕ защищает никакой из вариантов

- **Микроархитектурные side-channels** (Spectre-PHT/MDS): Firecracker даёт
  «пренебрежимо малую защиту» (peer-reviewed `10.1007/978-3-031-80020-7_1`);
  Medusa/MDS-вариант работает в Firecracker-VM (не на bare-metal), Spectre-PHT жив
  даже при выключенном SMT, если жертва и атакующий делят ядро. **Вне модели угроз
  Sandboy** (single-tenant, § 2).
- **«Неломаемых» microVM больше нет.** 2026 принёс первые опубликованные
  escape-class CVE: Firecracker `CVE-2026-5747` (virtio-pci OOB write, CVSS 8.7),
  `CVE-2026-1386` (jailer symlink overwrite, 6.0); Cloud Hypervisor `CVE-2026-45782`
  (virtio-block async-I/O UAF, 8.9, полный guest→host escape). **Патч-currency VMM —
  часть модели безопасности.**
- **Голые контейнеры — не граница** против враждебного кода: делят хост-ядро
  дословно, runc набрал 4 escape-CVE за 24 мес (procfs/mount-races, вкл. ноябрь-2025
  `CVE-2025-52565/52881/31133`). Слой 2 в одиночку (общее ядро) escape-resistance
  **не даёт** — отсюда и нужен Слой 1 при недоверенном target.

---

## 6. Trigger table

| Отклонено / отложено | Пересмотреть, если | Кандидат |
|---|---|---|
| Слой 1 (VM-граница) в MVP | В скоуп попал **недоверенный target-репо** | Firecracker (KVM) / gVisor (без KVM) |
| WASM/WIT rule-плагины | Появились **внешние авторы правил**, упёршиеся в один язык; ИЛИ строю ради удовольствия от component-model (для-души — валидный триггер, назвать честно) | Wasmtime + WIT, in-process, capability-scoped |
| Side-channel mitigations | Проект стал **мульти-tenant** (чужой код на общем хосте) | CPU microcode + `mds`/SMT-off + core-scheduling |
| Managed-сервис вместо self-host | TCO self-host стека превысил посекундную оплату | E2B (Apache-2.0, self-host на KVM) / Daytona |

Правило (из `execution-surfaces.md`): `trigger = реальная боль / цифры`, не
«красиво звучит в ADR».

---

## 7. Open questions (решить до полного дизайна)

1. **gVisor × наш toolchain** — ломаются ли `git` / компиляторы / `claude`/`codex`
   CLI под Sentry (пробелы совместимости сисколлов)? Если да — «широкая свобода»
   под угрозой, и Слой 1 = Firecracker, не gVisor.
2. **Kata Containers 2026** — ресёрч не дал ни одного выжившего Kata-specific факта;
   пробел против Firecracker/gVisor по boot/CVE/egress для VM-backed-container опции.
3. **QUIC/HTTP3 egress** — нужен ли агентам QUIC? Если нет — blanket-UDP-block
   достаточно; если да — нужен MITM-CA / L7-proxy (Sandlock opt-in HTTPS-inspection).
4. **TCO self-host vs managed** — инженерное время на rootfs/snapshot/teardown/egress
   против посекундной оплаты E2B (~$0.000028/с при 2 vCPU по умолчанию; Pro $150/мес).

---

## 8. Placement

Канонический файл:

```
PhysShell/Own.NET/docs/notes/sandboy-isolation-adr.md
```

Sandboy — sibling-проект (живёт в неймспейсе Own.NET), но НЕ Own.NET-core фича:
в `docs/proposals/` (`P-NNN`, фичи анализатора) не заводится. Задачу решает `007`
(`run`/gate-слот) — этот ADR перекрёстно ссылается на `007/docs/security-layers.md`.
Дисциплина границ проектов — как в `AGENTS.execution-surfaces.md` § 10.

---

## Appendix. Провенанс ресёрча

Источник фактов § 4–5 — deep-research прогон (2026-07-04): 6 углов, 27 источников,
129 claim'ов → 25 верифицированы адверсариально (3–0 единогласно, 0 опровергнуто).

Ключевые источники (приоритет — первоисточники):

- gVisor security/platforms — `gvisor.dev/docs/architecture_guide/{security,platforms}`
- Comparative escape-reachability study (2026, medium-conf, non-peer-reviewed
  preprint; reachability ≠ exploitability) — `arXiv:2606.08433`
- Sandlock (2026, medium-conf, self-reported бенчи) — `arXiv:2605.26298` +
  `github.com/multikernel/sandlock`
- Firecracker threat model — `github.com/firecracker-microvm/firecracker/blob/main/docs/design.md`
- Firecracker microarch security (peer-reviewed) — `10.1007/978-3-031-80020-7_1`
- 2026 escape-CVE — NVD `CVE-2026-5747`, `CVE-2026-45782`; runc advisories
- Egress/pricing — `e2b.dev/docs/sandbox/internet-access`, `daytona.io/docs/en/network-limits`,
  `e2b.dev/pricing`
- nsjail — `github.com/google/nsjail`

Caveats: пространство активно движется; escape-CVE 2026 означают, что VMM-патчи —
живое операционное требование; «0 gVisor escapes» ограничено 24-месячным окном (не
доказательство immunity — историческая `CVE-2018-16359` вне окна); E2B-цены дрейфуют.
