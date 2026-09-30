#!/usr/bin/env bash
# pool entries 15-18 after the disk-allowance incident (ProGPU's first attempt died on ENOSPC), then the floor
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
for repo in wieslawsoltes/ProGPU KrisTHL181/Break-This-Repo npgsql/efcore.pg victor-wiki/DatabaseManager; do
  tag=${repo//\//__}; echo "=== $repo $(date -u +%H:%M:%S)"; timeout 3600 python3 $S/lab/sc/e2.py "$repo" 2>&1 | tail -3; rm -rf "$S/lab/sc/e2/$tag"; df -h / | tail -1 | awk '{print "avail",$4}'
done
cd $S/lab/sc && python3 e2floor.py
echo E2C_DONE
