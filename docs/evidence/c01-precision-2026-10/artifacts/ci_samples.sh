#!/usr/bin/env bash
set -u
RUNNER_TEMP="$1"
cd ~/Documents/ownnet-eng/Own.NET
set -e
# --- Extract OwnIR facts from sample C# (ci.yml) ---
dotnet run --project frontend/roslyn/OwnSharp.Extractor -- \
  frontend/roslyn/samples/CustomerViewModel.cs \
  frontend/roslyn/samples/LambdaHandlerViewModel.cs \
  frontend/roslyn/samples/AliasedSourceViewModel.cs \
  frontend/roslyn/samples/OrdersViewModel.cs \
  frontend/roslyn/samples/TimerViewModel.cs \
  frontend/roslyn/samples/DisposableFieldViewModel.cs \
  frontend/roslyn/samples/MessengerViewModel.cs \
  frontend/roslyn/samples/PooledBufferSample.cs \
  frontend/roslyn/samples/LocalDisposableSample.cs \
  frontend/roslyn/samples/SelfOwnedViewModel.cs \
  frontend/roslyn/samples/SelfOwnedControlParts.cs \
  frontend/roslyn/samples/ExternalRefSubscription.cs \
  frontend/roslyn/samples/StaticHandlerViewModel.cs \
  frontend/roslyn/samples/StaticEventEscapeViewModel.cs \
  frontend/roslyn/samples/WhenAnyValueViewModel.cs \
  frontend/roslyn/samples/DiCaptiveSample.cs \
  frontend/roslyn/samples/SampleTypes.cs \
  frontend/roslyn/samples/PipeFieldsSample.cs \
  frontend/roslyn/samples/AppLifetimeSample.cs \
  frontend/roslyn/samples/ViewOwnsVmSample.xaml.cs \
  frontend/roslyn/samples/InjectedDcViewSample.xaml.cs \
  frontend/roslyn/samples/ResolvedDisposableSample.cs \
  frontend/roslyn/samples/FieldReleaseSample.cs \
  frontend/roslyn/samples/StaticClassEscapeSample.cs \
  frontend/roslyn/samples/EventSourceCountersSample.cs \
  frontend/roslyn/samples/AppDomainShutdownSample.cs \
  frontend/roslyn/samples/LambdaTiersSample.cs \
  frontend/roslyn/samples/AliasDisposeSample.cs \
  frontend/roslyn/samples/CloseReleaseSample.cs \
  frontend/roslyn/samples/SemaphoreFieldSample.cs \
  frontend/roslyn/samples/VoidSubscribeSample.cs \
  frontend/roslyn/samples/ReturnedPublisherSample.cs \
  frontend/roslyn/samples/OwnIgnoreSample.cs \
  frontend/roslyn/samples/DpRotationSample.cs \
  frontend/roslyn/samples/RequerySuggestedAllowlistSample.cs \
  frontend/roslyn/samples/SelfDetachingHandlerSample.cs \
  frontend/roslyn/samples/UsingFieldAcquisitionSample.cs \
  frontend/roslyn/samples/TemplatePartLocalCaptureSample.cs \
  frontend/roslyn/samples/EmptyDisposeSample.cs \
  frontend/roslyn/samples/AppScopedSourceSample.cs \
  frontend/roslyn/samples/WinFormsDisposalSample.cs \
  frontend/roslyn/samples/AssociatedObjectSourceSample.cs \
  frontend/roslyn/samples/OwnedCollectionElementSample.cs \
  -o "$RUNNER_TEMP/facts.json"
cat "$RUNNER_TEMP/facts.json"
# --- Check facts through the core (ci.yml) ---
out=$(python -m ownlang ownir "$RUNNER_TEMP/facts.json" || true)
echo "$out"
echo "$out" | grep -q "OWN001" \
  || { echo "FAIL: expected OWN001"; exit 1; }
# P-004 tiering: CustomerViewModel subscribes to an INJECTED bus (a ctor
# param of unknown lifetime). We cannot prove it outlives the view model,
# so the leak is reported at WARNING level (an honest "possible leak"),
# not a hard error — until lifetime/ownership modelling lands.
echo "$out" | grep -qE "CustomerViewModel\.cs:[0-9]+: warning: \[OWN001\]" \
  || { echo "FAIL: expected CustomerViewModel as a WARNING (injected source)"; exit 1; }
echo "$out" | grep -q "injected dependency whose lifetime is unknown" \
  || { echo "FAIL: expected the injected-source wording"; exit 1; }
if echo "$out" | grep -q "OrdersViewModel.cs"; then
  echo "FAIL: disposed subscription wrongly reported"; exit 1
fi
# Mined FP regression (Pipelines.Sockets.Unofficial): System.IO.Pipelines PipeReader/PipeWriter
# END WITH Reader/Writer but are NOT IDisposable (they finish via Complete(), not Dispose()), so
# an undisposed PipeReader/PipeWriter FIELD must NOT be flagged as a leak —
# IsNonDisposableReaderWriter excludes them from the field-disposable name heuristic.
if echo "$out" | grep -q "PipeFieldsSample.cs"; then
  echo "FAIL: PipeReader/PipeWriter field wrongly reported as an undisposed-disposable leak"; exit 1
fi
# a lambda handler has no stored delegate, so it can NEVER be `-=`'d — the
# finding says so. (Same injected source as Customer -> also a warning.)
echo "$out" | grep -qE "LambdaHandlerViewModel\.cs:[0-9]+: warning: \[OWN001\]" \
  || { echo "FAIL: expected the lambda-handler subscription leak (warning)"; exit 1; }
echo "$out" | grep -q "inline lambda it has no '-=' handle" \
  || { echo "FAIL: expected the lambda no-handle wording"; exit 1; }
# #146 interprocedural publisher provenance (the Newtonsoft
# Create->ApplySerializerSettings shape): every caller of ApplyBounded
# constructs the publisher and returns it, so the param-publisher
# subscription is bounded -> the extractor stamps
# `source_provenance: "returned_fresh"` and the bridge drops it (SILENT).
grep -q '"source_provenance": "returned_fresh"' "$RUNNER_TEMP/facts.json" \
  || { echo "FAIL: expected the returned_fresh provenance stamp in the facts"; exit 1; }
if echo "$out" | grep -q "publisher.Error"; then
  echo "FAIL: the proven returned-fresh publisher subscription must be silent"; exit 1
fi
# ...and every denial case KEEPS the honest OWN001 warning — public
# candidate, mixed callers, field-stored fresh local, the param->param
# DI dual this feature must never silence, and the two local-function
# closure escapes (callee-side capture / caller-side capture, Codex P2).
for ev in "pub.Faulted" "target.Mixed" "stored.Stored" "bus.Changed" \
          "deferred.Deferred" "later.Later"; do
  echo "$out" | grep -qE "ReturnedPublisherSample\.cs:[0-9]+: warning: \[OWN001\].*'$ev'" \
    || { echo "FAIL: expected the OWN001 warning to survive for '$ev' (provenance must deny)"; exit 1; }
done
# P-004 provenance: a local that ALIASES an injected source (var src =
# _bus) is NOT method-bounded — it must warn, not be silently dropped. A
# local the scope CONSTRUCTS (var owned = new Calc()) IS bounded -> silent.
echo "$out" | grep -qE "AliasedSourceViewModel\.cs:[0-9]+: warning: \[OWN001\]" \
  || { echo "FAIL: aliased-injected local should warn, not be dropped"; exit 1; }
if echo "$out" | grep -q "owned.Changed"; then
  echo "FAIL: a locally-constructed publisher must be dropped"; exit 1
fi
# WPF002: the started, never-stopped timer leaks with a [resource: timer]
# tag; the timer stopped in Dispose stays silent.
echo "$out" | grep -q "TimerViewModel.cs" \
  || { echo "FAIL: expected the TimerViewModel timer leak"; exit 1; }
echo "$out" | grep -q "resource: timer" \
  || { echo "FAIL: expected a [resource: timer] tag"; exit 1; }
if echo "$out" | grep -q "CleanTimerViewModel"; then
  echo "FAIL: stopped timer wrongly reported"; exit 1
fi
# WPF003: the IDisposable field the class new's but never disposes leaks
# with a [resource: disposable field] tag; the one disposed in Dispose
# stays silent.
echo "$out" | grep -q "DisposableFieldViewModel.cs" \
  || { echo "FAIL: expected the ReportViewModel field leak"; exit 1; }
echo "$out" | grep -q "resource: disposable field" \
  || { echo "FAIL: expected a [resource: disposable field] tag"; exit 1; }
if echo "$out" | grep -q "CleanReportViewModel"; then
  echo "FAIL: disposed field wrongly reported"; exit 1
fi
# a static IDisposable field is a process-lifetime singleton (Dapper's
# DisposedReader.Instance) — never an owned leak, so it stays silent.
if echo "$out" | grep -q "SharedTokenHolder"; then
  echo "FAIL: a static singleton IDisposable field was wrongly reported"; exit 1
fi
# P-004 resolve-aware disposability (mined: ImageSharp Vp8BitWriter/JpegBitReader):
# a field whose type NAME ends in Writer/Reader/Stream but is NOT IDisposable (and
# RESOLVES) must NOT be flagged — IsOwnedDisposableType asks the real interface.
if echo "$out" | grep -q "EncoderWithNonDisposableWriter"; then
  echo "FAIL: a resolved non-IDisposable Writer/Reader field was wrongly flagged"; exit 1
fi
# control: resolved IDisposable fields (MemoryStream / CancellationTokenSource) the
# class new's but never disposes must STILL warn — real detection intact. (CodeRabbit:
# tie the assertion to OWN001 + the disposable-field resource, not just the class name.
# Severity-agnostic on purpose — the disposable-field leak renders as error, not warning.)
echo "$out" | grep -qE "ResolvedDisposableSample\.cs:[0-9]+:.*\[OWN001\].*resource: disposable field" \
  || { echo "FAIL: expected the OWN001 disposable-field finding on the resolved IDisposable control"; exit 1; }
echo "$out" | grep -q "HolderWithRealDisposable" \
  || { echo "FAIL: the resolved IDisposable control (MemoryStream/CTS) must be flagged by owner name"; exit 1; }
# dispose-optional control (Codex): Task / DataTable ARE IDisposable but disposal is
# optional (IsDisposeOptional) — a new'd, undisposed field of these must stay SILENT.
if echo "$out" | grep -q "HolderWithDisposeOptional"; then
  echo "FAIL: a dispose-optional (Task/DataTable) field was wrongly flagged"; exit 1
fi
# the same rule for string-backed reader/writer fields (field-notes #8, Newtonsoft
# TraceJsonReader/Writer): a new'd, undisposed StringWriter/StringReader holds no
# unmanaged resource -> must stay SILENT (IsDisposeOptional, System.IO).
if echo "$out" | grep -q "HolderWithStringWriter"; then
  echo "FAIL: a dispose-optional (StringWriter/StringReader) field was wrongly flagged"; exit 1
fi
# field release recognition (mined: ImageSharp). #2 null-conditional dispose
# `field?.Dispose()` must be recognized -> silent; the undisposed control still warns.
if echo "$out" | grep -q "DisposesViaConditional"; then
  echo "FAIL: a field disposed via null-conditional field?.Dispose() was wrongly flagged"; exit 1
fi
echo "$out" | grep -q "NeverDisposesField" \
  || { echo "FAIL: an undisposed IDisposable field control must still warn"; exit 1; }
# #3 a pooled FIELD released cross-member (ctor rent + Dispose Return) must be silent;
# the rented-never-returned control still warns.
if echo "$out" | grep -q "pooled buffer 'returnedBuf'"; then
  echo "FAIL: a pooled field returned in Dispose was wrongly flagged"; exit 1
fi
echo "$out" | grep -q "pooled buffer 'leakedBuf'" \
  || { echo "FAIL: a pooled field rented but never returned must still warn"; exit 1; }
# field disposed through a local ALIAS (mined: Npgsql NpgsqlDataSource): `var cts = _cts;
# cts.Dispose();` (and the `this._f` / `cts?.Dispose()` shapes) releases the field -> the
# aliased fields must be SILENT.
if echo "$out" | grep -qE "'_aliased'|'_aliasedQ'"; then
  echo "FAIL: a field disposed through a local alias was wrongly reported as undisposed"; exit 1
fi
# controls: an alias that is never disposed, and an alias REBOUND to a new object, must
# both STILL leak (the recognition needs an actual dispose on an un-reassigned alias).
echo "$out" | grep -qE "AliasDisposeSample\.cs:[0-9]+:.*\[OWN001\].*'_neverDisposed'" \
  || { echo "FAIL: a field aliased but never disposed must still warn"; exit 1; }
echo "$out" | grep -qE "AliasDisposeSample\.cs:[0-9]+:.*\[OWN001\].*'_rebound'" \
  || { echo "FAIL: a field whose alias was rebound to a new object must still warn"; exit 1; }
# Codex control: an alias rebound through a ref/out ARGUMENT must still leak.
echo "$out" | grep -qE "AliasDisposeSample\.cs:[0-9]+:.*\[OWN001\].*'_refRebound'" \
  || { echo "FAIL: a field whose alias was rebound via a ref/out argument must still warn"; exit 1; }
# Codex/CodeRabbit control: aliases are symbol-scoped, not name-keyed — an unrelated
# same-named local disposed in another method must NOT credit the field, so it still leaks.
echo "$out" | grep -qE "AliasDisposeSample\.cs:[0-9]+:.*\[OWN001\].*'_scopedLeak'" \
  || { echo "FAIL: a same-named local in another scope must not be miscredited (symbol-scoped aliases)"; exit 1; }
# a field released via `.Close()` (direct and null-conditional) must be SILENT — mirrors the
# local detector's Dispose/Close/DisposeAsync set (mined: Npgsql ReplicationConnection._npgsqlConnection).
if echo "$out" | grep -qE "'_closedConn'|'_closedConnQ'"; then
  echo "FAIL: a field released via .Close() was wrongly reported as undisposed"; exit 1
fi
# control: a connection-like field NEITHER closed NOR disposed must STILL warn.
echo "$out" | grep -qE "CloseReleaseSample\.cs:[0-9]+:.*\[OWN001\].*'_leakedConn'" \
  || { echo "FAIL: a field that is never closed/disposed must still warn (Close-as-release stays scoped to an actual Close call)"; exit 1; }
# Codex/CodeRabbit control: Close() credits THIS instance's field only — closing ANOTHER instance
# of the same class's same-named field must NOT suppress this object's leak (ThisFieldName, not a
# receiver-stripping name match that a same-class ContainingType check would also miss).
echo "$out" | grep -qE "CloseReleaseSample\.cs:[0-9]+:.*\[OWN001\].*'_xconn'" \
  || { echo "FAIL: other-instance .Close() must not credit this field (receiver-scoped to this/alias)"; exit 1; }
# P-004 SemaphoreSlim FIELD dispose-optional (mined: Npgsql NpgsqlDataSource._setupMappingsSemaphore):
# a SemaphoreSlim field used only for Wait/Release (AvailableWaitHandle never read) frees nothing on
# Dispose -> must be SILENT.
if echo "$out" | grep -q "'_optionalSem'"; then
  echo "FAIL: a SemaphoreSlim field whose AvailableWaitHandle is never read was wrongly reported (dispose-optional)"; exit 1
fi
# gate control: a SemaphoreSlim field whose AvailableWaitHandle IS read allocates a handle Dispose
# must release -> it must STILL warn (proves the exemption is gated, not blanket — Codex).
echo "$out" | grep -qE "SemaphoreFieldSample\.cs:[0-9]+:.*\[OWN001\].*'_handleSem'" \
  || { echo "FAIL: a SemaphoreSlim field whose AvailableWaitHandle is read must still warn"; exit 1; }
# Codex control: an AvailableWaitHandle read THROUGH A FIELD ALIAS must credit the field -> still warn.
echo "$out" | grep -qE "SemaphoreFieldSample\.cs:[0-9]+:.*\[OWN001\].*'_aliasedSem'" \
  || { echo "FAIL: an aliased AvailableWaitHandle read must keep the field tracked (alias-aware gate)"; exit 1; }
# type-scope control: a non-SemaphoreSlim owned IDisposable (CTS) never disposed must STILL warn.
echo "$out" | grep -qE "SemaphoreFieldSample\.cs:[0-9]+:.*\[OWN001\].*'_ctsControl'" \
  || { echo "FAIL: a non-SemaphoreSlim owned IDisposable field must still warn (exemption stays SemaphoreSlim-scoped)"; exit 1; }
# field-scoped: the existing method-bounded LOCAL SemaphoreSlim leak (FlowLocalsSample.semLeak) must
# be UNAFFECTED — checked in the --flow-locals step below; this exemption never touches IsDisposeOptional.
# WPF004: an ignored `X.Subscribe(...)` result leaks; the captured+
# disposed one stays silent. "ignored" is unique to the WPF004 message.
echo "$out" | grep -q "MessengerViewModel.cs" \
  || { echo "FAIL: expected the InboxViewModel ignored-Subscribe leak"; exit 1; }
echo "$out" | grep -q "is ignored" \
  || { echo "FAIL: expected the ignored-Subscribe message"; exit 1; }
# P-004 resolve-aware ignored-Subscribe (mined: StackExchange.Redis): a bare `x.Subscribe(...)`
# whose call returns VOID (the Redis `ISubscriber.Subscribe(channel, handler, flags)` shape) has
# no IDisposable token -> must be SILENT; the IDisposable-returning Subscribe still WARNs.
if echo "$out" | grep -q "leaking 'VoidSubscriber'"; then
  echo "FAIL: a void-returning .Subscribe(...) was wrongly flagged as an ignored IDisposable subscription"; exit 1
fi
echo "$out" | grep -q "leaking 'DisposableSubscriber'" \
  || { echo "FAIL: an ignored IDisposable-returning .Subscribe(...) must still warn (resolve-aware stays scoped)"; exit 1; }
# Codex control: a `dynamic` receiver's Subscribe has a dynamic return -> unprovable -> still WARN.
echo "$out" | grep -q "leaking 'DynamicSubscriber'" \
  || { echo "FAIL: an ignored dynamic .Subscribe(...) must still warn (dynamic return is unknown, not silenced)"; exit 1; }
if echo "$out" | grep -q "CleanInboxViewModel"; then
  echo "FAIL: captured+disposed subscription wrongly reported"; exit 1
fi
# POOL001: a Rent'd-but-never-Return'd buffer leaks; the rent+return
# (finally) one stays silent.
echo "$out" | grep -q "pooled buffer 'leaky'" \
  || { echo "FAIL: expected the rented-not-returned buffer leak"; exit 1; }
if echo "$out" | grep -q "pooled buffer 'ok'"; then
  echo "FAIL: returned buffer wrongly reported"; exit 1
fi
# P-005 D1: a `new`'d local IDisposable never disposed leaks; a `using`
# one and a returned (transferred) one stay silent.
echo "$out" | grep -q "local IDisposable 'leaky'" \
  || { echo "FAIL: expected the undisposed-local leak"; exit 1; }
echo "$out" | grep -q "LocalDisposableSample.cs" \
  || { echo "FAIL: expected LocalDisposableSample.cs in the local-disposable finding"; exit 1; }
echo "$out" | grep -q "resource: disposable]" \
  || { echo "FAIL: expected a [resource: disposable] tag"; exit 1; }
if echo "$out" | grep -qE "'guarded'|'moved'"; then
  echo "FAIL: using/returned local wrongly reported"; exit 1
fi
# P-004 self-owned exemption: a subscription whose source is a field the
# class constructs (owns) is a GC-collectable cycle, not a leak — silent.
if echo "$out" | grep -q "SelfOwnedViewModel.cs"; then
  echo "FAIL: a self-owned subscription was wrongly reported"; exit 1
fi
# P-004 self-owned (extended): a field built indirectly via a `ref`/`out`
# helper, or fetched as one of the control's own template parts
# (GetTemplateChild), is owned just like a `new`'d field — both
# subscriptions in SelfOwnedControlParts are collectable cycles -> silent.
if echo "$out" | grep -q "SelfOwnedControlParts.cs"; then
  echo "FAIL: a self-owned (ref-built / template-part) subscription was wrongly reported"; exit 1
fi
# P-004 (ref/out narrowing, Codex P2): a field populated by an EXTERNAL
# class's ref method (not this class's own helper) is NOT self-owned — the
# subscription must still be reported, not silently suppressed.
echo "$out" | grep -qE "ExternalRefSubscription\.cs:[0-9]+: warning: \[OWN001\]" \
  || { echo "FAIL: expected OWN001 on the external-ref subscription (must not be exempted)"; exit 1; }
# P-004 self-WhenAnyValue classifier (docs/notes/self-whenany-precision.md):
# `this.WhenAnyValue(p => p.SelfProp[, q => q.Other]).Subscribe` over the
# component's OWN single-hop properties is a collectable self-cycle ->
# silent; a nested path through an INJECTED object, or a combinator that
# mixes in an EXTERNAL observable, stays a flagged leak (OWN001).
echo "$out" | grep -q "x.Svc.Name" \
  || { echo "FAIL: nested-path WhenAnyValue (injected Svc) must leak"; exit 1; }
echo "$out" | grep -q "CombineLatest" \
  || { echo "FAIL: combinator WhenAnyValue (external observable) must leak"; exit 1; }
# the multi-arg single-hop self chain must be SILENCED (the fix): `x => x.B`
# appears only in that chain, so it must not surface anywhere.
if echo "$out" | grep -q "x => x.B"; then
  echo "FAIL: multi-arg single-hop self WhenAnyValue must be silenced"; exit 1
fi
# exactly two WhenAnyValueViewModel leaks (nested + combinator) — the three
# self-rooted chains produce nothing.
n=$(echo "$out" | grep -cE "WhenAnyValueViewModel\.cs:[0-9]+:.*\[OWN001\]")
[ "$n" = "2" ] \
  || { echo "FAIL: expected exactly 2 WhenAnyValueViewModel leaks, got $n"; exit 1; }
# P-004 static-handler exemption: a static-method handler has a null
# delegate target — no instance retained, so not a leak — silent.
if echo "$out" | grep -q "StaticHandlerViewModel.cs"; then
  echo "FAIL: a static-handler subscription was wrongly reported"; exit 1
fi
# P-004 WPF005 region escape: an INSTANCE handler subscribed to a
# process-lived STATIC event (Calc.GlobalPing) with no `-=` is a region
# escape, NOT a token leak. The extractor lowers the static-source `+=` to
# a `capture` fact and the core's region engine reports OWN014 (the
# view-model is promoted to process lifetime), an error — proving real C#
# static-event subscriptions reach the region core, not only OWN001.
echo "$out" | grep -qE "StaticEventEscapeViewModel\.cs:[0-9]+: error: \[OWN014\]" \
  || { echo "FAIL: expected OWN014 region escape on the static-event instance subscription"; exit 1; }
echo "$out" | grep -q "region escape" \
  || { echo "FAIL: expected the region-escape wording on the static-event capture"; exit 1; }
# P-004 process-lifetime AppDomain-event exemption (mined: Npgsql PoolManager): a
# NON-CAPTURING handler on a process-host AppDomain event (ProcessExit/DomainUnload/
# UnhandledException/FirstChanceException) is a shutdown/diagnostics hook meant to live
# for the process -> NOT a region escape -> silent. (Scoped to ShutdownCleanup, the
# exempt class — CapturingShutdownSubscriber in the same file MUST still raise OWN014.)
if echo "$out" | grep -qE "OWN014.*'ShutdownCleanup'"; then
  echo "FAIL: ShutdownCleanup's non-capturing AppDomain subscriptions were wrongly reported as OWN014"; exit 1
fi
# issue #199 — capture-aware static tier: the region escape keys off whether the handler
# RETAINS an instance. A CAPTURING lambda on a non-AppDomain static event (NonAppDomain-
# Subscriber captures the ctor's `cts` — the CsvHelper cts/resetEvent shape Codex defended)
# still pins it -> OWN014; an AppDomain handler that captures instance state (Capturing-
# ShutdownSubscriber) is still pinned -> OWN014. Both must stay flagged.
echo "$out" | grep -qE "\[OWN014\].*NonAppDomainSubscriber" \
  || { echo "FAIL: a CAPTURING lambda on a non-AppDomain static event must still raise OWN014"; exit 1; }
echo "$out" | grep -qE "\[OWN014\].*CapturingShutdownSubscriber" \
  || { echo "FAIL: an instance-capturing AppDomain handler must still raise OWN014 (exemption is non-capturing only)"; exit 1; }
# issue #199 FP FIX: a NON-CAPTURING lambda on a static event retains no instance (the
# closure analog of the static-METHOD exemption / StaticHandlerViewModel) -> OWN014's
# premise ("subscriber pinned") fails -> SILENT. Reverses the prior false positive where a
# non-capturing static lambda was flagged (policy: docs/notes/subscription-leaks-and-
# profiles.md — "static + non-retaining handler -> silent; static + retaining -> OWN014").
if echo "$out" | grep -q "NonCapturingStaticSubscriber"; then
  echo "FAIL: a NON-capturing lambda on a static event must be SILENT (retains no instance)"; exit 1
fi
# issue #199 cosmetic: a LAMBDA handler's OWN014 message spells out the no-'-=' handle,
# like OWN001 does (extractor stamps lambda:true; the bridge folds in the note).
echo "$out" | grep -qE "\[OWN014\].*NonAppDomainSubscriber.*inline lambda it has no" \
  || { echo "FAIL: OWN014 on a lambda handler must carry the inline-lambda no-'-=' note"; exit 1; }
# issue #199 — POSITIVE anchor for LambdaTiersSample.cs: an INJECTED-source lambda
# (publisher handed in as a ctor param, lifetime unknown) is the honest hedge -> OWN001
# WARNING, and it carries the inline-lambda no-'-=' note like OWN014 does. This is the ONLY
# component the extractor emits from LambdaTiersSample.cs, so it proves the file is actually
# extracted — without it the two silent negatives below would pass VACUOUSLY (CodeRabbit).
echo "$out" | grep -qE "LambdaTiersSample\.cs:[0-9]+: warning: \[OWN001\].*injected dependency.*'InjectedSourceLambda'" \
  || { echo "FAIL: expected OWN001 warning on the injected-source lambda (also the file's extraction anchor)"; exit 1; }
echo "$out" | grep -qE "\[OWN001\].*InjectedSourceLambda.*inline lambda it has no" \
  || { echo "FAIL: OWN001 on a lambda handler must also carry the inline-lambda no-'-=' note"; exit 1; }
# issue #199 — the SILENT lambda tiers (bounded/local + self-owned): a lambda on a
# method-bounded local source, or on a field the class constructs, is not a heap leak
# (the '-=-impossible-but-bounded' shape) -> must be silent. These negatives are NOT
# vacuous: the InjectedSourceLambda anchor above proves the file reached the extractor.
if echo "$out" | grep -qE "LocalBoundedLambda|SelfOwnedFieldLambda"; then
  echo "FAIL: a lambda on a bounded/local or self-owned source must stay SILENT"; exit 1
fi
# the unsubscribed variant (a matching `-=`, released capture) is mitigated
# -> silent. Must NOT be reported.
if echo "$out" | grep -q "CleanStaticEventViewModel"; then
  echo "FAIL: an unsubscribed (released) static-event subscription was wrongly reported"; exit 1
fi
# P-004 robust static-handler exemption (mined: ImageSharp MemoryAllocatorValidator): a
# static-METHOD handler on a static event stores a null-target delegate -> no instance is
# retained -> OWN014 must NOT fire, even when the method-group symbol surfaces as a member
# group (now resolved via CandidateSymbols). (StaticEventEscapeViewModel above proves an
# INSTANCE handler on the same static event still escapes, so this stays scoped.)
if echo "$out" | grep -q "StaticAllocationCounter"; then
  echo "FAIL: a static-method handler on a static event was wrongly reported as a region escape"; exit 1
fi
# P-004 EventSource diagnostic-counter exemption (mined: Npgsql NpgsqlEventSource): a
# DiagnosticCounter (EventCounter / PollingCounter / Incrementing{Event,Polling}Counter)
# built with `this` is registered to the parent EventSource and shares its process
# lifetime -> idiomatically never field-disposed -> must NOT be flagged as an undisposed leak.
if echo "$out" | grep -qE "'_bytesPerSecond'|'_totalBytes'|'_commandDuration'|'_totalCommands'"; then
  echo "FAIL: an EventSource-owned DiagnosticCounter field was wrongly reported as an undisposed leak"; exit 1
fi
# scope control (Codex): the exemption keys off the DiagnosticCounter type handed to
# `this`, NOT the EventSource class — so a plain owned IDisposable field in the same
# EventSource (`_scratch`) must STILL raise the OWN001 disposable-field leak.
echo "$out" | grep -qE "EventSourceCountersSample\.cs:[0-9]+:.*\[OWN001\].*'_scratch'" \
  || { echo "FAIL: a non-counter owned IDisposable field in an EventSource must still warn (exemption stays counter-type-scoped)"; exit 1; }
# declared-type control (Codex): a field DECLARED as a plain IDisposable that is ALSO
# assigned a counter once (`_mixed = new EventCounter(..., this)`) must STILL leak its
# earlier `new MemoryStream()` — the exemption requires the DECLARED field type to be a
# DiagnosticCounter, so a name-only skip cannot hide the non-counter resource.
echo "$out" | grep -qE "EventSourceCountersSample\.cs:[0-9]+:.*\[OWN001\].*'_mixed'" \
  || { echo "FAIL: a field declared as a non-counter IDisposable that is later assigned a counter must still leak (exemption requires the DECLARED type to be a DiagnosticCounter)"; exit 1; }
# P-004 process-lived-subscriber exemption (mined: ScreenToGif App +
# Translator): the WPF `App` singleton hooking the process-lived
# AppDomain.UnhandledException promotes nothing, so the static-source region
# escape (OWN014) must NOT fire — for both the name-based (`partial class
# App`) and base-based (`: Application`) shapes.
if echo "$out" | grep -q "AppLifetimeSample.cs"; then
  echo "FAIL: a process-lived App static-event subscription was wrongly reported (OWN014 FP)"; exit 1
fi
# P-004 WPF MVVM ownership (mined: ScreenToGif VideoSource): a view that
# CONSTRUCTS its view-model in its own XAML (`<X.DataContext><VM/>` — read from
# the sibling .xaml) owns it, so a field assigned from `DataContext` is
# self-owned and subscribing to its events is a collectable cycle -> SILENT.
if echo "$out" | grep -q "ViewOwnsVmSample"; then
  echo "FAIL: a view that owns its VM via its own XAML DataContext was wrongly reported"; exit 1
fi
# negative control: a view whose XAML BINDS its DataContext (`<Binding/>`) does
# NOT own the VM (it may be externally supplied), so the subscription must
# still WARN — proving the gate keys off proven construction, not every cast.
echo "$out" | grep -qE "InjectedDcViewSample\.xaml\.cs:[0-9]+: warning: \[OWN001\].*injected dependency whose lifetime is unknown" \
  || { echo "FAIL: a bound (unowned) DataContext subscription must still warn with the injected-source wording"; exit 1; }
# P-006 DI001 (captive dependency): the registration + constructor graph
# extracted from DiCaptiveSample.cs feeds ownlang/di.py. A singleton that
# captures a scoped service — directly, transitively through a transient,
# or through an interface registration — is flagged at the registration
# site; a singleton->singleton edge and the clean registrations stay silent.
echo "$out" | grep -q "DI001" \
  || { echo "FAIL: expected DI001 captive-dependency findings"; exit 1; }
echo "$out" | grep -q "singleton 'EmailSender' captures scoped service 'AppDbContext'" \
  || { echo "FAIL: expected the direct captive (singleton EmailSender -> scoped AppDbContext)"; exit 1; }
# the transitive capture must thread through the transient UnitOfWork.
echo "$out" | grep -q "ReportService -> UnitOfWork -> AppDbContext" \
  || { echo "FAIL: expected the transitive captive path via the transient UnitOfWork"; exit 1; }
# the interface registration (AddScoped<IRepo, Repo>) must map so the
# singleton consuming IRepo is caught.
echo "$out" | grep -q "singleton 'CacheService' captures scoped service 'IRepo'" \
  || { echo "FAIL: expected the interface-registration captive (CacheService -> IRepo)"; exit 1; }
# C# 12 primary-constructor injection (deps on the class declaration, not a
# ctor member) must be read too.
echo "$out" | grep -q "singleton 'PrimaryCtorService' captures scoped service 'AppDbContext'" \
  || { echo "FAIL: expected the primary-constructor captive (PrimaryCtorService -> AppDbContext)"; exit 1; }
echo "$out" | grep -q "DiCaptiveSample.cs" \
  || { echo "FAIL: expected the DI001 findings at the DiCaptiveSample.cs registration site"; exit 1; }
# NOT captive: singleton->singleton (Metrics->Clock), and PublicCtorOnly —
# DI resolves its public parameterless ctor, so the wider PRIVATE ctor's
# scoped dependency is never used. None of these may be flagged.
if echo "$out" | grep -qE "captures scoped service '(Clock|Metrics)'" \
   || echo "$out" | grep -q "'PublicCtorOnly'"; then
  echo "FAIL: a singleton->singleton, public-ctor-only, or clean registration was wrongly flagged captive"; exit 1
fi
# exactly four captive dependencies (direct + transitive + interface + primary-ctor).
nd=$(echo "$out" | grep -cE "DiCaptiveSample\.cs:[0-9]+:.*\[DI001\]")
[ "$nd" = "4" ] \
  || { echo "FAIL: expected exactly 4 DI001 captive findings, got $nd"; exit 1; }
# P-006 Q#1: each captive finding anchors at the registration site but ALSO names its
# CONSUMING CONSTRUCTOR (where the capture is injected) — the explicit ctor line for
# EmailSender, and the class-declaration line for the C# 12 primary ctor.
echo "$out" | grep -qE "consumed by the 'EmailSender' constructor at .*DiCaptiveSample\.cs:25\]" \
  || { echo "FAIL: expected the consuming-constructor anchor (EmailSender ctor, line 25)"; exit 1; }
echo "$out" | grep -qE "consumed by the 'PrimaryCtorService' constructor at .*DiCaptiveSample\.cs:33\]" \
  || { echo "FAIL: expected the primary-constructor consuming anchor (PrimaryCtorService, line 33)"; exit 1; }
# P-006 DI003 (transient IDisposable captured by a singleton, WARNING): the
# singleton ConnectionWarmer holds the transient IDisposable PooledConnection
# for the app lifetime (disposed only at root disposal). A warning, distinct
# from a DI001 — the "exactly 4 DI001" count above proves it is not miscounted.
echo "$out" | grep -qE "\[DI003\].*'ConnectionWarmer' captures transient IDisposable 'PooledConnection'" \
  || { echo "FAIL: expected DI003 (ConnectionWarmer captures transient IDisposable PooledConnection)"; exit 1; }
nw=$(echo "$out" | grep -cE "DiCaptiveSample\.cs:[0-9]+:.*\[DI003\]")
[ "$nw" = "1" ] \
  || { echo "FAIL: expected exactly 1 DI003 finding, got $nw"; exit 1; }
# DI003 carries the consuming-constructor anchor too (ConnectionWarmer's ctor, line 50).
echo "$out" | grep -qE "consumed by the 'ConnectionWarmer' constructor at .*DiCaptiveSample\.cs:50\]" \
  || { echo "FAIL: expected the DI003 consuming-constructor anchor (ConnectionWarmer, line 50)"; exit 1; }
# P-006 DI002 (scoped service held by a singleton via WeakReference<T>, WARNING):
# the weak ref is the usual "fix" for a DI001 captive, but scoped AppDbContext is
# still root-resolved and app-lived — the lifetime contract is still violated. The
# weak edge is OFF the strong graph, so WeakCache is a DI002, NOT a 5th DI001 (the
# "exactly 4 DI001" count above proves it). A weak ref to a SINGLETON
# (WeakClockHolder -> Clock) is no mismatch -> silent.
echo "$out" | grep -qE "\[DI002\].*'WeakCache' weakly captures scoped service 'AppDbContext'" \
  || { echo "FAIL: expected DI002 (WeakCache weakly captures scoped AppDbContext)"; exit 1; }
# a NULLABLE WeakReference<AppDbContext>? is the same weak captive — the `?` annotation
# is unwrapped, so the scoped service is still seen (CodeRabbit review on #63).
echo "$out" | grep -qE "\[DI002\].*'WeakCacheOpt' weakly captures scoped service 'AppDbContext'" \
  || { echo "FAIL: expected DI002 on the nullable WeakReference (WeakCacheOpt)"; exit 1; }
# transitive DI002: a singleton weakly holds the transient UnitOfWork, which strongly
# drags in scoped AppDbContext (WeakReport -> UnitOfWork -> AppDbContext). The weak DFS
# follows the transient's strong edges like DI001 does.
echo "$out" | grep -qE "\[DI002\].*'WeakReport' weakly captures scoped service 'AppDbContext'" \
  || { echo "FAIL: expected transitive DI002 (WeakReport -> UnitOfWork -> AppDbContext)"; exit 1; }
# pin the rendered transitive PATH (not just the finding), so a path-rendering
# regression fails CI (CodeRabbit review on #64).
echo "$out" | grep -q "WeakReport -> UnitOfWork -> AppDbContext" \
  || { echo "FAIL: expected the transitive DI002 path text"; exit 1; }
nwk=$(echo "$out" | grep -cE "DiCaptiveSample\.cs:[0-9]+:.*\[DI002\]")
[ "$nwk" = "3" ] \
  || { echo "FAIL: expected exactly 3 DI002 findings, got $nwk"; exit 1; }
# DI002 carries the consuming-constructor anchor too (WeakCache's ctor, line 57).
echo "$out" | grep -qE "consumed by the 'WeakCache' constructor at .*DiCaptiveSample\.cs:57\]" \
  || { echo "FAIL: expected the DI002 consuming-constructor anchor (WeakCache, line 57)"; exit 1; }
if echo "$out" | grep -q "WeakClockHolder"; then
  echo "FAIL: a weak ref to a singleton (WeakClockHolder) was wrongly flagged"; exit 1
fi
# P-006 DI004 (transient IDisposable resolved BY HAND from the root IServiceProvider,
# WARNING): a singleton that service-locates a transient IDisposable off its injected
# root provider — tracked to app shutdown. This is a CALL SITE the registration graph
# (DI001/2/3) cannot see, so it is the unique slice. Three flagged shapes:
#   - ConnectionResolver  -> PooledConnection            (block-bodied ctor, direct)
#   - ExprBodiedResolver  -> PooledConnection            (EXPRESSION-bodied ctor; Codex)
#   - WrapperResolver -> MidConnection -> PooledConnection (TRANSITIVE: the root builds
#     the non-disposable wrapper's transient subtree; the DFS mirrors DI003; Codex)
echo "$out" | grep -qE "\[DI004\].*'ConnectionResolver' resolves transient IDisposable 'PooledConnection'" \
  || { echo "FAIL: expected DI004 (ConnectionResolver service-locates PooledConnection)"; exit 1; }
echo "$out" | grep -qE "\[DI004\].*'ExprBodiedResolver' resolves transient IDisposable 'PooledConnection'" \
  || { echo "FAIL: expected DI004 on the expression-bodied ctor (ExprBodiedResolver)"; exit 1; }
echo "$out" | grep -qE "\[DI004\].*'WrapperResolver' resolves transient IDisposable 'PooledConnection'" \
  || { echo "FAIL: expected transitive DI004 (WrapperResolver -> MidConnection -> PooledConnection)"; exit 1; }
# pin the rendered transitive PATH (not just the finding), like the DI002 transitive case.
echo "$out" | grep -q "WrapperResolver -> MidConnection -> PooledConnection" \
  || { echo "FAIL: expected the transitive DI004 path text"; exit 1; }
n4=$(echo "$out" | grep -cE "DiCaptiveSample\.cs:[0-9]+:.*\[DI004\]")
[ "$n4" = "3" ] \
  || { echo "FAIL: expected exactly 3 DI004 findings, got $n4"; exit 1; }
# DI004's consumer is the GetRequiredService CALL SITE (not a ctor) — and the leak IS
# that call, so it is the PRIMARY anchor (the line prefix), not the registration site
# (Codex review): ConnectionResolver:79, ExprBodiedResolver:123, transitive
# WrapperResolver:137 (the entry MidConnection's call, not the dragged-in disposable).
echo "$out" | grep -qE "DiCaptiveSample\.cs:79: warning: \[DI004\].*'ConnectionResolver'" \
  || { echo "FAIL: expected DI004 ConnectionResolver ANCHORED at its call site (line 79)"; exit 1; }
echo "$out" | grep -qE "DiCaptiveSample\.cs:123: warning: \[DI004\].*'ExprBodiedResolver'" \
  || { echo "FAIL: expected DI004 ExprBodiedResolver anchored at its call site (line 123)"; exit 1; }
echo "$out" | grep -qE "DiCaptiveSample\.cs:137: warning: \[DI004\].*'WrapperResolver'" \
  || { echo "FAIL: expected transitive DI004 WrapperResolver anchored at the entry call site (line 137)"; exit 1; }
# the registration site rides along as the SECONDARY anchor (named in EACH DI004
# message tail) — exactly 3, one per finding, so a partial-suffix regression (the tail
# on some findings but not all) fails CI too (CodeRabbit review; mirrors the counts above).
nreg=$(echo "$out" | grep -cE "\[DI004\].*singleton registered at ")
[ "$nreg" = "3" ] \
  || { echo "FAIL: expected exactly 3 DI004 registration-site suffixes, got $nreg"; exit 1; }
# the three controls each pin one precision guard and must stay SILENT: ScopedResolver
# resolves from a SCOPE it creates (scope.ServiceProvider — the correct shape);
# PlainResolver resolves a NON-disposable transient whose only dep is scoped (the root
# does not track it); RequestResolver is SCOPED (its injected provider is the request
# scope, not the root). MidConnection itself (a transient wrapper) is not a singleton.
if echo "$out" | grep -qE "(ScopedResolver|PlainResolver|RequestResolver)"; then
  echo "FAIL: a correct/non-leaking resolver (scope-resolved, non-disposable, or scoped) was wrongly flagged DI004"; exit 1
fi
# P-006 DI005 (scope-cached captive, WARNING): a singleton that resolves a SCOPED service
# from a scope it CREATES (the correct IServiceScopeFactory pattern) but CACHES it into a
# field — the scope is disposed when the operation ends, so the cached instance dangles
# and is promoted to application lifetime (the captive returns, hidden behind the fix).
echo "$out" | grep -qE "\[DI005\].*'ScopeCachingService' caches scoped service 'AppDbContext'" \
  || { echo "FAIL: expected DI005 (ScopeCachingService caches scope-resolved scoped AppDbContext)"; exit 1; }
# transitive DI005: a singleton caches the TRANSIENT UnitOfWork (which ctor-injects scoped
# AppDbContext) from a created scope — the DFS follows the cached transient's strong edges
# like DI001, so the dragged-in scoped service is found. A captive DI001/3/4 cannot see.
echo "$out" | grep -qE "\[DI005\].*'UnitOfWorkCachingService' caches scoped service 'AppDbContext'" \
  || { echo "FAIL: expected transitive DI005 (UnitOfWorkCachingService -> UnitOfWork -> AppDbContext)"; exit 1; }
echo "$out" | grep -q "UnitOfWorkCachingService -> UnitOfWork -> AppDbContext" \
  || { echo "FAIL: expected the transitive DI005 path text"; exit 1; }
n5=$(echo "$out" | grep -cE "DiCaptiveSample\.cs:[0-9]+:.*\[DI005\]")
[ "$n5" = "2" ] \
  || { echo "FAIL: expected exactly 2 DI005 findings (direct + transitive), got $n5"; exit 1; }
# DI005's consumer is the field-STORE site (not a ctor), the PRIMARY anchor — the direct
# case at line 154 (`_db = ...AppDbContext`), the transitive case at the cached ENTRY's
# store (line 201, `_uow = ...UnitOfWork`, NOT the dragged-in AppDbContext) — with the
# registration as the secondary suffix.
echo "$out" | grep -qE "DiCaptiveSample\.cs:154: warning: \[DI005\].*'ScopeCachingService'" \
  || { echo "FAIL: expected DI005 anchored at the field-store site (line 154)"; exit 1; }
echo "$out" | grep -qE "DiCaptiveSample\.cs:201: warning: \[DI005\].*'UnitOfWorkCachingService'" \
  || { echo "FAIL: expected transitive DI005 anchored at the cached-entry store site (line 201)"; exit 1; }
# the registration site rides along as the SECONDARY anchor in EACH DI005 message tail —
# exactly 2 (one per finding), so a partial-suffix regression fails CI (like DI004's nreg).
nreg5=$(echo "$out" | grep -cE "\[DI005\].*singleton registered at ")
[ "$nreg5" = "2" ] \
  || { echo "FAIL: expected exactly 2 DI005 registration-site suffixes, got $nreg5"; exit 1; }
# two controls stay SILENT: ScopeUsingService USES the scope-resolved service within the
# scope (a local, not a field store); ClockCachingService caches a SINGLETON (shareable,
# not a scoped service). Neither is a captive.
if echo "$out" | grep -qE "(ScopeUsingService|ClockCachingService)"; then
  echo "FAIL: a correct scope use (used-in-scope, or a cached singleton) was wrongly flagged DI005"; exit 1
fi
# issue #209 — inline [OwnIgnore("reason")] per-site suppression (P-004), on an
# IDisposable field. Four contrasting shapes in OwnIgnoreSample.cs: the un-annotated
# leak, a reason-less [OwnIgnore], and an empty [OwnIgnore("")] all FIRE OWN001; only
# [OwnIgnore("reason")] is silent-but-COUNTED (SARIF suppressions), never failing the run.
echo "$out" | grep -qE "OwnIgnoreSample\.cs:[0-9]+: error: \[OWN001\].*'UnsuppressedLeak'" \
  || { echo "FAIL: an un-annotated IDisposable field must raise OWN001"; exit 1; }
echo "$out" | grep -qE "\[OWN001\].*'ReasonlessLeak'" \
  || { echo "FAIL: a reason-less [OwnIgnore] must NOT suppress (OWN001 must still fire)"; exit 1; }
echo "$out" | grep -qE "\[OWN001\].*'EmptyReasonLeak'" \
  || { echo "FAIL: an empty [OwnIgnore(\"\")] reason must NOT suppress (OWN001 must still fire)"; exit 1; }
# the suppressed leak is SILENT in the human findings stream...
if echo "$out" | grep -q "'SuppressedLeak'"; then
  echo "FAIL: a [OwnIgnore(\"reason\")] finding must be silent in the human output"; exit 1
fi
# ...but COUNTED in the run summary (visibility over silence).
echo "$out" | grep -qE "[0-9]+ suppressed \(\[OwnIgnore\]\)" \
  || { echo "FAIL: the suppressed finding must be counted in the summary tally"; exit 1; }
# SARIF carries it as a result WITH a `suppressions` array (kind inSource + the
# mandatory reason as justification) — a consumer counts it, GitHub shows it
# suppressed rather than an open alert, and it never fails the run.
rc=0; python -m ownlang ownir "$RUNNER_TEMP/facts.json" --format sarif > "$RUNNER_TEMP/own.sarif" || rc=$?
[ "$rc" -le 1 ] || { echo "FAIL: SARIF generation errored (rc=$rc)"; exit 1; }
jq -e '[.runs[0].results[] | select(.properties.component == "SuppressedLeak")] as $s
       | ($s | length) == 1
         and ($s[0].suppressions[0].kind == "inSource")
         and ($s[0].suppressions[0].justification | contains("owned and disposed by the DI container"))' \
  "$RUNNER_TEMP/own.sarif" >/dev/null \
  || { echo "FAIL: SARIF must carry SuppressedLeak once, with an inSource suppressions justification"; \
       jq '.runs[0].results[]|{ruleId,component:.properties.component,suppressions}' "$RUNNER_TEMP/own.sarif"; exit 1; }
# issue #218 — DP/property-changed old->new subscription ROTATION (unsub OLD, sub NEW, same
# handler = one paired lifecycle) must be SILENT. Two recognised forms: a DP callback reading
# e.OldValue/e.NewValue (CommandTriggerAction), and a plain virtual OnXChanged(old, new)
# override with two same-type params (AbstractMargin). Confirmed FP in 3 real repos, 6+ sites.
# InlineCastRotation covers the direct inline-cast receiver `((ICommand)e.NewValue!).Event +=`
# (OldValue/NewValue are object-typed, so the cast is mandatory) — Codex review catch.
if echo "$out" | grep -qE "'CommandTriggerAction'|'AbstractMargin'|'InlineCastRotation'"; then
  echo "FAIL: a DP old->new subscription rotation was wrongly flagged as a leak (#218)"; exit 1
fi
# ...and it must NOT over-widen — three controls STAY flagged: (a) the += uses a DIFFERENT
# handler than the -= (a genuine unpaired subscription); (b) two UNRELATED, differently-typed
# params (not the old/new halves of one change); (c) `-=` on one class FIELD, `+=` on another.
echo "$out" | grep -qE "\[OWN001\].*'MismatchedHandlerRotation'" \
  || { echo "FAIL: a rotation with a DIFFERENT += handler must stay flagged (no over-widen)"; exit 1; }
echo "$out" | grep -qE "\[OWN001\].*'UnrelatedPairRotation'" \
  || { echo "FAIL: a -=/+= pair on differently-typed params must stay flagged (not old/new halves)"; exit 1; }
echo "$out" | grep -qE "\[OWN001\].*'TwoFieldsRotation'" \
  || { echo "FAIL: a -=/+= pair across two class fields must stay flagged (not a rotation)"; exit 1; }
# issue #223 — curated allowlist: CommandManager.RequerySuggested is implemented
# over weak references (see docs/notes/field-notes-patterns.md entry 17), so an
# ordinary instance-bound handler that never `-=`s it must NOT raise OWN014.
if echo "$out" | grep -q "ImeSupportLike"; then
  echo "FAIL: an allowlisted CommandManager.RequerySuggested subscription was wrongly reported"; exit 1
fi
# control: an ORDINARY (non-allowlisted) static event, same never-detached
# instance-handler shape, must STILL raise OWN014 — the allowlist must not
# weaken the general static-source tier.
echo "$out" | grep -qE "RequerySuggestedAllowlistSample\.cs:[0-9]+: error: \[OWN014\].*'OrdinaryStaticSubscriber'" \
  || { echo "FAIL: expected OWN014 on the non-allowlisted static-event subscriber"; exit 1; }
# issue #224 — a handler that unsubscribes ITSELF inside its own body (a
# self-detaching one-shot handler) is bounded -> must be SILENT.
if echo "$out" | grep -q "DropDownButtonLike"; then
  echo "FAIL: a self-detaching handler subscription was wrongly reported"; exit 1
fi
# control 1: the SAME shape but the handler does NOT self-detach -> must STILL warn.
echo "$out" | grep -qE "SelfDetachingHandlerSample\.cs:[0-9]+: warning: \[OWN001\].*'NonDetachingSubscriber'" \
  || { echo "FAIL: expected OWN001 on the non-self-detaching subscriber"; exit 1; }
# control 2: the handler detaches a DIFFERENT event name -> must NOT be credited
# as releasing the subscribed event -> must STILL warn.
echo "$out" | grep -qE "SelfDetachingHandlerSample\.cs:[0-9]+: warning: \[OWN001\].*'WrongEventDetachSubscriber'" \
  || { echo "FAIL: expected OWN001 when the self-detach targets the wrong event name"; exit 1; }
# control 3 (Codex P2 on PR #231): the handler detaches the CORRECT event name
# but off an UNRELATED receiver, not its own `sender` parameter -> the actual
# subscribed source is never released -> must STILL warn.
echo "$out" | grep -qE "SelfDetachingHandlerSample\.cs:[0-9]+: warning: \[OWN001\].*'WrongReceiverDetachSubscriber'" \
  || { echo "FAIL: expected OWN001 when the self-detach targets the wrong receiver (not sender)"; exit 1; }
# issue #220 — `using (field = new T())`: the field IS the `using` acquisition
# target, disposed at scope exit -> must be SILENT.
if echo "$out" | grep -q "HashCheckerLike"; then
  echo "FAIL: a field disposed via using (field = new T()) was wrongly reported"; exit 1
fi
# control: the SAME field, constructed the same way, but OUTSIDE any `using` and
# never disposed -> must STILL warn (the recognition is using-scoped, not "any
# field assignment from new is a release").
echo "$out" | grep -qE "UsingFieldAcquisitionSample\.cs:[0-9]+: error: \[OWN001\].*'LeakyAssignerLike'" \
  || { echo "FAIL: expected OWN001 on the field assigned outside any using block"; exit 1; }
# issue #222 — a template part captured as a LOCAL (plain variable, via
# Template.FindName) or an `is T x` PATTERN variable (via GetTemplateChild), not
# only a field, is self-owned -> both must be SILENT.
if echo "$out" | grep -qE "MetroWindowLike|OverloadViewerLike"; then
  echo "FAIL: a template part captured as a local/pattern variable was wrongly reported"; exit 1
fi
# control: a local variable that merely ALIASES an INJECTED field (not a
# GetTemplateChild/FindName fetch) must STILL warn — the exemption is scoped to
# an actual template-part fetch, not "any local-variable subscription is self-owned."
echo "$out" | grep -qE "TemplatePartLocalCaptureSample\.cs:[0-9]+: warning: \[OWN001\].*'InjectedLocalSubscriber'" \
  || { echo "FAIL: expected OWN001 on the injected-local (non-template-part) subscriber"; exit 1; }
# control (Codex P2 on PR #231): a template-part local in one method must NOT
# exempt an UNRELATED same-named local (aliasing an injected source) in a
# DIFFERENT method of the same class — locals are self-owned by SYMBOL, not
# name. The template-part method's own subscription must stay silent...
if echo "$out" | grep -q "OnTemplateClick"; then
  echo "FAIL: the legitimate template-part-local subscription was wrongly reported"; exit 1
fi
# ...while the same-named local in the OTHER method must still warn.
echo "$out" | grep -qE "TemplatePartLocalCaptureSample\.cs:[0-9]+: warning: \[OWN001\].*'SameNameDifferentScopeSubscriber'" \
  || { echo "FAIL: expected OWN001 on the same-named-but-unrelated local in a different method"; exit 1; }
# issue #225 (narrowed by #238) — the empty-Dispose exemption is confined to ENUMERATOR
# types: source emptiness proves nothing about the COMPILED body once an IL weaver is in
# play (Janitor.Fody wove real cleanup into ClosedXML's XLWorkbook.Dispose — 263 silently
# swallowed findings). ScratchReader (empty source Dispose, NOT an enumerator — the
# XLWorkbook shape) must therefore STAY flagged on the flat name path...
echo "$out" | grep -qE "EmptyDisposeSample\.cs:[0-9]+:.*\[OWN001\].*'s'.*'ScratchReader'" \
  || { echo "FAIL: #238: a NON-enumerator empty-source-Dispose local must stay flagged (weaver soundness)"; exit 1; }
echo "$out" | grep -qE "EmptyDisposeSample\.cs:[0-9]+:.*\[OWN001\].*'lr'.*'LeakyReader'" \
  || { echo "FAIL: a non-empty-Dispose local (LeakyReader) must still leak (#225 stays scoped)"; exit 1; }
# Codex P2: an empty SYNC Dispose but a real DisposeAsync (a `*Reader` here) must still leak.
echo "$out" | grep -qE "EmptyDisposeSample\.cs:[0-9]+:.*\[OWN001\].*'ar'.*'AsyncReader'" \
  || { echo "FAIL: a type with a real DisposeAsync (empty sync Dispose) must still leak (#225)"; exit 1; }
# issue #228 — an Application-derived subscriber on a CURATED app-scoped
# resolver result (PaletteHelper.GetThemeManager) with a method-group handler
# of the App class itself must be SILENT: the source is process-lived (bound
# to the app's own state), so nothing is promoted. Both receiver forms — an
# `is`-pattern local (App) and the direct invocation (DirectApp).
if echo "$out" | grep -qE "AppScopedSourceSample\.cs:[0-9]+:.*('App'|'DirectApp')"; then
  echo "FAIL: a curated app-scoped subscription inside the Application was wrongly reported (#228)"; exit 1
fi
# ...and the exemption must NOT over-widen — three controls STAY flagged:
# (1) the SAME curated shape from a NON-Application class (the subscriber
# gate stays clsIsApp, byte-for-byte);
echo "$out" | grep -qE "AppScopedSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'NotAnApp'" \
  || { echo "FAIL: expected OWN001 on the non-Application subscriber (curated source alone must not exempt)"; exit 1; }
# (2) App + curated source, but a LAMBDA handler capturing a local — the
# exact hole that sank the rejected clsIsStatic broadening;
echo "$out" | grep -qE "AppScopedSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'LambdaApp'" \
  || { echo "FAIL: expected OWN001 on the lambda-handler subscription inside the App (capture hole)"; exit 1; }
# (3) App + method-group handler, but a NON-curated resolver;
echo "$out" | grep -qE "AppScopedSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'CuratedOnlyApp'" \
  || { echo "FAIL: expected OWN001 on the non-curated resolver source inside the App"; exit 1; }
# (4, Codex P2) the method group is qualified with ANOTHER instance of the
# same App type — right ContainingType, wrong delegate target;
echo "$out" | grep -qE "AppScopedSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'TwinApp'" \
  || { echo "FAIL: expected OWN001 when the handler target is another instance, not this"; exit 1; }
# (5, Codex P2) the local is REASSIGNED to an injected publisher after the
# curated initializer — the stale declaration binding must not exempt.
echo "$out" | grep -qE "AppScopedSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'ReassignApp'" \
  || { echo "FAIL: expected OWN001 when the resolver-bound local is reassigned before the +="; exit 1; }
# issue #219 — WinForms disposal CHANNELS: (a) a Control/ToolStripItem field added to THIS's
# own Controls/Items collection is disposed transitively by base.Dispose(disposing); (b) a
# component built with `new T(components)` / registered via `components.Add(x)` is disposed by
# components.Dispose(). ~30 ShareX FPs. Both require the class to reach a disposal root.
# SILENT: (a) direct Controls.Add, AddRange, a transitive ToolStrip Items add, a ComboBox
# added to Controls; (b) both IContainer-registration shapes incl. the named Add(x,"name").
if echo "$out" | grep -qE "WinFormsDisposalSample\.cs.*'(lblStatus|btnOk|menu|menuItem|trayIcon|icon|namedIcon|combo)'"; then
  echo "FAIL: a WinForms Controls/Items-membership or IContainer-registered field was wrongly flagged (#219)"; exit 1
fi
# ...and the negative controls MUST stay flagged: an add into a FOREIGN (param) container;
# a plain owner with NO Dispose at all (owned container never disposed); a component NOT
# container-registered; and a real disposable stored as a ComboBox item (ObjectCollection
# does not dispose its items — Codex).
echo "$out" | grep -qE "WinFormsDisposalSample\.cs:[0-9]+:.*\[OWN001\].*'lblForeign'" \
  || { echo "FAIL: #219 (a): a control added to a FOREIGN container must stay flagged"; exit 1; }
echo "$out" | grep -qE "WinFormsDisposalSample\.cs:[0-9]+:.*\[OWN001\].*'item'" \
  || { echo "FAIL: #219 (a): a control in an owned container with NO Dispose must stay flagged"; exit 1; }
echo "$out" | grep -qE "WinFormsDisposalSample\.cs:[0-9]+:.*\[OWN001\].*'unregisteredIcon'" \
  || { echo "FAIL: #219 (b): a component NOT registered in the IContainer must stay flagged"; exit 1; }
echo "$out" | grep -qE "WinFormsDisposalSample\.cs:[0-9]+:.*\[OWN001\].*'comboItem'" \
  || { echo "FAIL: #219 (a): a disposable stored as a ComboBox item (ObjectCollection) must stay flagged"; exit 1; }
# exactly 5 WinFormsDisposalSample findings (lblForeign, cms, item, unregisteredIcon,
# comboItem) — the eight channel-disposed fields are all silent; any leak pushes it past 5.
nwf=$(echo "$out" | grep -cE "WinFormsDisposalSample\.cs:[0-9]+:.*\[OWN001\]")
[ "$nwf" = "5" ] \
  || { echo "FAIL: #219 expected exactly 5 WinFormsDisposalSample findings (controls only), got $nwf"; exit 1; }
# issue #227 — a `Behavior`-derived subscriber whose event source is (an element
# reached from) its own base-class `AssociatedObject` must be SILENT: the
# behavior cannot outlive being attached, so the source is co-lifetimed with the
# subscriber (a collectable self-cycle, not a leak). Three receiver forms:
# an `is`-pattern local off a field assigned from AssociatedObject (TiltLikeBehavior),
# the direct `this.AssociatedObject.Event` (DirectAssociatedBehavior), and a
# bare-identifier local bound from AssociatedObject (LocalAssociatedBehavior).
if echo "$out" | grep -qE "AssociatedObjectSourceSample\.cs:[0-9]+:.*'panel\.Loaded'.*'TiltLikeBehavior'"; then
  echo "FAIL: the AssociatedObject-derived subscription in the Behavior was wrongly reported (#227)"; exit 1
fi
if echo "$out" | grep -qE "AssociatedObjectSourceSample\.cs:[0-9]+:.*('DirectAssociatedBehavior'|'LocalAssociatedBehavior')"; then
  echo "FAIL: a direct/local AssociatedObject subscription in the Behavior was wrongly reported (#227)"; exit 1
fi
# ...and the required negative control: an UNRELATED injected source subscribed
# in the SAME OnAttached stays flagged.
echo "$out" | grep -qE "AssociatedObjectSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'_bus\.Changed'.*'TiltLikeBehavior'" \
  || { echo "FAIL: expected OWN001 on the unrelated injected source in the same OnAttached (#227)"; exit 1; }
# ...and the exemption must NOT over-widen — three controls STAY flagged:
# (1) the same AssociatedObject shape from a NON-Behavior subscriber (the gate
# is the `Behavior` base, not the member name);
echo "$out" | grep -qE "AssociatedObjectSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'NotABehavior'" \
  || { echo "FAIL: expected OWN001 on the non-Behavior subscriber (AssociatedObject name alone must not exempt)"; exit 1; }
# (2) a field assigned from AssociatedObject AND from an injected value elsewhere
# — every assignment must resolve to AssociatedObject;
echo "$out" | grep -qE "AssociatedObjectSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'MixedFieldBehavior'" \
  || { echo "FAIL: expected OWN001 when the field is also assigned an injected value (#227)"; exit 1; }
# (3) the local starts as AssociatedObject but is REASSIGNED to an injected
# source before the `+=` — the stale declaration binding must not exempt.
echo "$out" | grep -qE "AssociatedObjectSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'ReassignedLocalBehavior'" \
  || { echo "FAIL: expected OWN001 when the AssociatedObject-bound local is reassigned before the +="; exit 1; }
# (4, Codex P2) a PARAMETER named `AssociatedObject` SHADOWS the inherited base
# accessor — the name matches by text, but the symbol is an injected parameter,
# so the exemption must resolve the binding, not just the name.
echo "$out" | grep -qE "AssociatedObjectSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'ShadowParamBehavior'" \
  || { echo "FAIL: expected OWN001 when a shadowing parameter is named AssociatedObject (#227)"; exit 1; }
# (5) a PARTIAL behavior whose field is assigned from AssociatedObject in one
# declaration but from an injected value in the sibling partial — the field-
# population scan must span every partial of the type.
echo "$out" | grep -qE "AssociatedObjectSourceSample\.cs:[0-9]+: warning: \[OWN001\].*'PartialFieldBehavior'" \
  || { echo "FAIL: expected OWN001 when a sibling partial injects the AssociatedObject field (#227)"; exit 1; }
# issue #229 — subscribing to an element of a collection the class itself
# populated (a `foreach` over a this-owned field/property assigned from the
# class's OWN construction/factory) must be SILENT: the collection and its
# elements share the constructing object's lifetime (a collectable self-cycle,
# not a leak). Three population forms: an own factory into a property
# (OwnedFactoryViewModel), a collection-initializer field (InlineNewViewModel),
# and a `new` assigned in the ctor (DirectNewViewModel).
if echo "$out" | grep -qE "OwnedCollectionElementSample\.cs:[0-9]+:.*('OwnedFactoryViewModel'|'InlineNewViewModel'|'DirectNewViewModel')"; then
  echo "FAIL: a self-populated owned-collection element subscription was wrongly reported (#229)"; exit 1
fi
# ...and the exemption must NOT over-widen — four controls STAY flagged:
# (1, REQUIRED) the collection is a FIELD assigned from a ctor PARAMETER;
echo "$out" | grep -qE "OwnedCollectionElementSample\.cs:[0-9]+: warning: \[OWN001\].*'InjectedCollectionViewModel'" \
  || { echo "FAIL: expected OWN001 on the injected-collection field (#229)"; exit 1; }
# (2, REQUIRED) the `foreach` iterates a ctor PARAMETER collection directly;
echo "$out" | grep -qE "OwnedCollectionElementSample\.cs:[0-9]+: warning: \[OWN001\].*'ParamCollectionViewModel'" \
  || { echo "FAIL: expected OWN001 on the parameter-collection foreach (#229)"; exit 1; }
# (3) the member is populated from a SERVICE-LOCATED call (injected receiver);
echo "$out" | grep -qE "OwnedCollectionElementSample\.cs:[0-9]+: warning: \[OWN001\].*'ServiceLocatedViewModel'" \
  || { echo "FAIL: expected OWN001 on the service-located collection source (#229)"; exit 1; }
# (4) the member is own-populated in the ctor but ALSO reassigned an injected
# value elsewhere — every population site must be own-produced.
echo "$out" | grep -qE "OwnedCollectionElementSample\.cs:[0-9]+: warning: \[OWN001\].*'MixedCollectionViewModel'" \
  || { echo "FAIL: expected OWN001 when the collection is also assigned an injected value (#229)"; exit 1; }
# (5, Codex P1) a freshly-`new`d collection SEEDED from an injected parameter —
# the elements (which carry the events) are injected, so it is not owned;
echo "$out" | grep -qE "OwnedCollectionElementSample\.cs:[0-9]+: warning: \[OWN001\].*'SeededNewViewModel'" \
  || { echo "FAIL: expected OWN001 on a new collection seeded from injected elements (#229)"; exit 1; }
# (6, Codex P1) an own-class factory that FORWARDS a service-located collection;
echo "$out" | grep -qE "OwnedCollectionElementSample\.cs:[0-9]+: warning: \[OWN001\].*'ForwardingFactoryViewModel'" \
  || { echo "FAIL: expected OWN001 when the own factory forwards injected data (#229)"; exit 1; }
# (7, CodeRabbit) a PARTIAL class with a disqualifying injected assignment in a
# sibling partial — the population scan must span every partial of the type.
echo "$out" | grep -qE "OwnedCollectionElementSample\.cs:[0-9]+: warning: \[OWN001\].*'PartialInjectedViewModel'" \
  || { echo "FAIL: expected OWN001 when a sibling partial injects the collection (#229)"; exit 1; }
echo "OK: real C# -> facts -> OWN001 (subscription + timer + field + Subscribe + pool + local) + OWN014 (static-event region escape) + DI001 (captive dependency) + DI002 (scoped captured weakly) + DI003 (transient IDisposable captured by a singleton) + DI004 (transient IDisposable service-located from the root provider) + DI005 (scoped service cached from a created scope) + [OwnIgnore] suppression (silent-but-counted, SARIF suppressions) + #218 DP old->new subscription rotation (silent; controls flagged) + #225 empty-Dispose local exemption (silent; controls flagged) + #228 curated app-scoped source in App (silent; controls flagged) + #227 self-owned Behavior.AssociatedObject source (silent; controls flagged) + #219 WinForms Controls/IContainer disposal channels (silent; controls flagged) + #229 self-populated owned-collection element (silent; controls flagged) at the C# location"
echo "CI_SAMPLES_ALL_ASSERTIONS_PASSED"
