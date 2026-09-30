#!/usr/bin/env bash
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 OWEN_LAB_THROWEXIT=1
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad; cd $S/lab/disc
for p in ZstdSharp.Port Google.Protobuf Serilog K4os.Compression.LZ4.Streams NLog Microsoft.Data.Sqlite.Core; do
  extra=""; [ "$p" = "Microsoft.Data.Sqlite.Core" ] && extra=$(ls -d $S/lab/disc/deps/SQLitePCLRaw.core/lib/netstandard2.0 2>/dev/null)
  OWN_EXTRA_REF_DIRS="$extra" python3 derive.py $p 2>&1 | head -1 | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d['package'],'rows',d['public_rows'],'fresh_all',d['fresh_all'],'release_all',d['release_all'])"
done; echo DERIVE_TIER2_DONE
