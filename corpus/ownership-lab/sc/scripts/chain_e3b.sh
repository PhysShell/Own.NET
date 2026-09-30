#!/usr/bin/env bash
# after the E3 chain: RepoDB and wolverine scans (both aborted when the dumps cache was removed mid-run), then the
# context, textual recount and analyzer overlap steps over ALL scan outputs
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
for i in $(seq 1 720); do grep -q "^E3_DONE" $S/lab/sc/e3.log 2>/dev/null && break; sleep 10; done
cd $S/lab/sc
for rs in "mikependon/RepoDB edabfb2044cbbed70a37eb04488386835d202038" "JasperFx/wolverine 7ee3df905e8d852ba0b93e1c7c5b435e5fe0dac7"; do set -- $rs; echo "=== E3 $1 $2 $(date -u +%H:%M:%S)"; timeout 5400 python3 e3scan.py "$1" "$2" 2>&1 | tail -3; done
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
        if os.path.exists(out): print('have',out); continue
        print(subprocess.run(['python3',f'{S}/lab/sc/idispcheck.py',proj,out],capture_output=True,text=True,timeout=2400).stdout.strip()[-300:],flush=True)
PY
echo E3B_DONE
