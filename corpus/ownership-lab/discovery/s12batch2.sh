#!/usr/bin/env bash
# discovery S1+S2 for a list of "Package version" pairs
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad; cd $S/lab/disc
while read -r pid ver; do
  [ -z "$pid" ] && continue
  python3 fetch.py "$pid" "$ver" 2>&1 | tail -1
  main=$(python3 -c "import json;print(json.load(open('libs/$pid/acquire.json')).get('main_assembly') or '')")
  if [ -n "$main" ]; then dotnet /home/user/Own.NET/frontend/roslyn/OwnSharp.ApiList/bin/Release/net8.0/ownsharp-apilist.dll "$main" > libs/$pid/api.json 2> libs/$pid/api.err
    python3 -c "import json;a=json.load(open('libs/$pid/api.json'));print('  API $pid: types',a['disposable_types'],'factories',len(a['factories']),'adopting ctors',len(a['adopting_ctors']),'release names',len(a['release_name_candidates']))" || echo "  API $pid: FAILED $(head -c 200 libs/$pid/api.err)"
  else echo "  $pid: no main assembly"; fi
done <<'LIST'
K4os.Compression.LZ4.Streams 1.3.8
ZstdSharp.Port 0.8.8
Google.Protobuf 3.36.2
Serilog 4.4.0
Microsoft.Data.Sqlite 10.0.12
NLog 6.2.1
LIST
echo S12_DONE
