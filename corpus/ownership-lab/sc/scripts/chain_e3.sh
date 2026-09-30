#!/usr/bin/env bash
# Stage E3 after the census re-runs and the floor: freeze = every consumer with >= 1 trusted opportunity (production or
# test project) in e2-floor.json; OFF vs ON scan per frozen consumer (clones kept for triage); source context of every
# new/lost finding; analyzer overlap (IDisposableAnalyzers + CA2000) for each project/TFM with new findings
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
for i in $(seq 1 720); do grep -q "^E2E_DONE" $S/lab/sc/e2e.log 2>/dev/null && break; sleep 10; done
cd $S/lab/sc
python3 write_freeze.py
python3 - <<'PY' > e3-order.txt
import json
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
f=json.load(open(f'{S}/lab/sc/e2-floor.json'))
for x in f['per_consumer']:
    if x['trusted_units']>=1: print(x['repo'], x['sha'])
PY
python3 - <<'PY'
import json,glob
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
full={}
for g in glob.glob(f'{S}/lab/sc/e2/*.e2.json'):
    d=json.load(open(g)); full[d['repo']]=d['sha']
open(f'{S}/lab/sc/e3-order.txt','w').write('\n'.join(f'{r} {full[r]}' for r,_ in [l.split() for l in open(f'{S}/lab/sc/e3-order.txt') if l.strip()]))
PY
while read -r repo sha || [ -n "$repo" ]; do [ -z "$repo" ] && continue; echo "=== E3 $repo $sha $(date -u +%H:%M:%S)"; timeout 5400 python3 $S/lab/sc/e3scan.py "$repo" "$sha" 2>&1 | tail -3; done < e3-order.txt
python3 e3context.py > e3-context.txt 2>&1
python3 textsites.py > textsites.log 2>&1
python3 - <<'PY'
import json,glob,os,subprocess
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3'
seen=set()
for g in sorted(glob.glob(f'{E}/*.e3.json')):
    d=json.load(open(g)); W=f'{E}/'+d['repo'].replace('/','__')
    for x in d['new_findings']:
        proj=os.path.join(W,x[0])
        if proj in seen: continue
        seen.add(proj); out=f'{E}/idisp-'+d['repo'].replace('/','__')+'-'+os.path.basename(x[0]).replace('.csproj','')+'.json'
        print(subprocess.run(['python3',f'{S}/lab/sc/idispcheck.py',proj,out],capture_output=True,text=True,timeout=2400).stdout.strip()[-300:],flush=True)
PY
echo E3_DONE
