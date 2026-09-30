#!/usr/bin/env bash
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad; T=/home/user/Own.NET/frontend/roslyn/OwnSharp.RelDump/bin/Release/net8.0/ownsharp-reldump.dll
for acq in $S/lab/disc/libs/*/acquire.json; do L=$(dirname $acq); pid=$(basename $L); main=$(python3 -c "import json;print(json.load(open('$acq')).get('main_assembly') or '')"); [ -z "$main" ] && continue
  extra=""; [ "$pid" = "Microsoft.Data.Sqlite.Core" ] && extra=$S/lab/disc/deps/SQLitePCLRaw.core/lib/netstandard2.0
  dotnet $T "$main" $extra > $S/lab/ct/rel-$pid.json 2> $S/lab/ct/rel-$pid.err; echo "$pid $(python3 -c "import json;d=json.load(open('$S/lab/ct/rel-$pid.json'));print('methods',d['methods'],'bodies',d['bodies'],'ret_disposable',sum(1 for r in d['records'] if r['ret_disposable']))" 2>&1 | tail -1)"
done
# the SkiaSharp version-holdout surfaces (net6.0 assets of the versions the v2 consumers resolved)
for v in 3.119.4 4.148.0 4.152.0; do dotnet $T $S/lab/ct/skia/$v/skiasharp/lib/net6.0/SkiaSharp.dll > $S/lab/ct/rel-SkiaSharp@$v.json 2> $S/lab/ct/rel-SkiaSharp@$v.err; echo "SkiaSharp@$v $(python3 -c "import json;d=json.load(open('$S/lab/ct/rel-SkiaSharp@$v.json'));print('methods',d['methods'],'mvid',d['mvid'])" 2>&1 | tail -1)"; done
echo RELDUMP_DONE
