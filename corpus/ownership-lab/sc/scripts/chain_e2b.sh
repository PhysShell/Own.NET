#!/usr/bin/env bash
# after the main E2 chain: re-run the consumers censused before the version-specific Npgsql derivations (9.0.4 / 10.0.0)
# and the SkiaSharp/SSH.NET TFM witnesses existed, then evaluate the exposure floor
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
for i in $(seq 1 720); do [ "$(tail -1 $S/lab/sc/e2.log)" = "E2_DONE" ] && break; sleep 10; done
for i in $(seq 1 720); do grep -q WITNESS_DONE $S/lab/sc/witness-tfm3.log 2>/dev/null && break; sleep 10; done
for repo in JasperFx/wolverine JasperFx/marten WebVella/WebVella-ERP NpgsqlRest/NpgsqlRest guitarrapc/FeatherQR JasperFx/weasel quartznet/quartznet; do
  tag=${repo//\//__}; [ -f $S/lab/sc/e2/$tag.e2.json ] && mv $S/lab/sc/e2/$tag.e2.json $S/lab/sc/e2/$tag.e2.pre-rederive.json
  echo "=== rerun $repo $(date -u +%H:%M:%S)"; timeout 3600 python3 $S/lab/sc/e2.py "$repo" 2>&1 | tail -3; rm -rf "$S/lab/sc/e2/$tag"
done
cd $S/lab/sc && python3 e2floor.py
echo E2B_DONE
