#!/usr/bin/env bash
# Stage E2: after the E1 pool census, freeze the pool (copy into paperwork), then run e2.py over the first 12 nominated
# repositories in pool order; each clone is deleted after its census to keep the disk bounded. No OFF/ON here.
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad; P=/home/user/Own.NET-paperwork
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
for i in $(seq 1 300); do grep -q E1POOL_DONE $S/lab/sc/e1pool.log && break; sleep 15; done
for i in $(seq 1 300); do grep -q WITNESS_DONE $S/lab/sc/witness3.log && break; sleep 15; done
cp $S/lab/sc/e1pool.json $P/paper-eval/semantic-coverage/e1-pool-frozen-v1.json
python3 - <<'PY'
import json; S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
pool=json.load(open(f'{S}/lab/sc/e1pool.json'))['frozen_pool_top30']; open(f'{S}/lab/sc/e2-order.txt','w').write('\n'.join(x['repo'].replace('github.com/','') for x in pool[:12]))
PY
while read -r repo; do [ -z "$repo" ] && continue; echo "=== $repo $(date -u +%H:%M:%S)"; timeout 3600 python3 $S/lab/sc/e2.py "$repo" 2>&1 | tail -3; rm -rf "$S/lab/sc/e2/${repo//\//__}"; df -h / | tail -1 | awk '{print "avail",$4}'; done < $S/lab/sc/e2-order.txt
echo E2_DONE
