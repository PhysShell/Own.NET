#!/usr/bin/env bash
# after the re-run pass and the SkiaSharp 4.148.0 derivation/witnesses: FeatherQR again, then pool entries 13-18 in order
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
for i in $(seq 1 720); do grep -q "^E2B_DONE" $S/lab/sc/e2b.log 2>/dev/null && grep -q "^SKIA_DONE" $S/lab/sc/skia.log 2>/dev/null && break; sleep 10; done
for repo in guitarrapc/FeatherQR potatobeanradio/circuitRF seiggy/lucia-dotnet wieslawsoltes/ProGPU KrisTHL181/Break-This-Repo npgsql/efcore.pg victor-wiki/DatabaseManager; do
  tag=${repo//\//__}; [ -f $S/lab/sc/e2/$tag.e2.json ] && mv $S/lab/sc/e2/$tag.e2.json $S/lab/sc/e2/$tag.e2.pre-skia.json
  echo "=== $repo $(date -u +%H:%M:%S)"; timeout 3600 python3 $S/lab/sc/e2.py "$repo" 2>&1 | tail -3; rm -rf "$S/lab/sc/e2/$tag"; df -h / | tail -1 | awk '{print "avail",$4}'
done
cd $S/lab/sc && python3 e2floor.py
echo E2C_DONE
