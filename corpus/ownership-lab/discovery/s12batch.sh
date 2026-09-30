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
MySqlConnector 2.6.2
StackExchange.Redis 3.3.1
RabbitMQ.Client 7.2.2
MQTTnet 5.2.0.1603
SSH.NET 2026.0.0
MailKit 4.18.1
SharpZipLib 1.4.2
SharpCompress 1.0.0
SixLabors.ImageSharp 4.1.2
BouncyCastle.Cryptography 2.7.0
NSec.Cryptography 26.4.0
SkiaSharp 4.153.1
LibGit2Sharp 0.32.0
CsvHelper 33.1.0
Newtonsoft.Json 13.0.4
LIST
echo S12_DONE
