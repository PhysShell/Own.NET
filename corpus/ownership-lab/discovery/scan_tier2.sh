#!/usr/bin/env bash
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad; cd $S/lab/disc
for p in ZstdSharp.Port Google.Protobuf Serilog K4os.Compression.LZ4.Streams NLog Microsoft.Data.Sqlite.Core; do
  extra=""; [ "$p" = "Microsoft.Data.Sqlite.Core" ] && extra=$(ls -d $S/lab/disc/deps/SQLitePCLRaw.core/lib/netstandard2.0 2>/dev/null)
  OWN_EXTRA_REF_DIRS="$extra" python3 scan.py $p tests 2>&1; done; echo SCAN_TIER2_DONE
