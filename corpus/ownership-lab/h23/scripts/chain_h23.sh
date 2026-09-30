#!/usr/bin/env bash
# H-23A population census: the 17 frozen consumers at their frozen revisions, the frozen rows, the seam ON
# (OWEN_H23A_TREATMENT=1); outputs e2h23/<tag>.e2.json; disk guard: below 6G free the NuGet cache is wiped and the row
# packages restored again (pkgrestore projects); clones deleted per consumer
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 OWEN_H23A_TREATMENT=1
cd $S/lab/sc
while read -r repo sha || [ -n "$repo" ]; do
  [ -z "$repo" ] && continue; tag=${repo//\//__}
  avail=$(df -k / | tail -1 | awk '{print $4}')
  if [ "$avail" -lt 6000000 ]; then echo "PRUNE cache (avail ${avail}K)"; rm -rf ~/.nuget/packages/* ~/.local/share/NuGet/http-cache 2>/dev/null; for d in $S/pkgrestore/r_*; do dotnet restore $d/r.csproj -nologo -v q >/dev/null 2>&1; done; fi
  echo "=== H23 $repo $sha $(date -u +%H:%M:%S)"; timeout 3600 python3 e2.py "$repo" "$sha" 2>&1 | tail -2; rm -rf "$S/lab/sc/e2h23/$tag"; df -h / | tail -1 | awk '{print "avail",$4}'
done < h23-order.txt
echo H23_E2_DONE
