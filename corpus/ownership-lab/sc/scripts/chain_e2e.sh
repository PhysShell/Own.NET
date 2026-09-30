#!/usr/bin/env bash
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
for i in $(seq 1 720); do grep -q "^E2C_DONE" $S/lab/sc/e2c.log 2>/dev/null && break; sleep 10; done
repo=npgsql/efcore.pg; tag=${repo//\//__}; mv $S/lab/sc/e2/$tag.e2.json $S/lab/sc/e2/$tag.e2.sdk-pinned.json 2>/dev/null
echo "=== $repo (SDK pin set aside) $(date -u +%H:%M:%S)"; timeout 3600 python3 $S/lab/sc/e2.py "$repo" 2>&1 | tail -3; rm -rf "$S/lab/sc/e2/$tag"
cd $S/lab/sc && python3 e2floor.py
echo E2E_DONE
