#!/usr/bin/env bash
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad; cd $S/lab/sc
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
python3 idispcheck.py e3/JasperFx__weasel/src/DocSamples/DocSamples.csproj e3/idisp-JasperFx__weasel-DocSamples.json
python3 idispcheck.py e3/victor-wiki__DatabaseManager/DatabaseInterpreter/DatabaseInterpreter.Core/DatabaseInterpreter.Core.csproj e3/idisp-victor-wiki__DatabaseManager-DatabaseInterpreter.Core.json
python3 idispcheck.py e3/NpgsqlRest__NpgsqlRest/NpgsqlRestClient/NpgsqlRestClient.csproj e3/idisp-NpgsqlRest__NpgsqlRest-NpgsqlRestClient.json
echo IDISP_CHAIN_DONE
