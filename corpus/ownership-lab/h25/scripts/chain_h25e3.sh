#!/usr/bin/env bash
# H-25 probe: OFF (rows, no seam) versus ON (rows + OWEN_H25=1) on the 8 frozen consumers (e3h23 clones, erratum-3 rows,
# corrected environment); outputs e3h25/<tag>.e3.json; then the finding contexts
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 OWEN_H25_TREATMENT=1
cd $S/lab/sc
for line in "NpgsqlRest/NpgsqlRest 6cc6f55fa65b14e394fa1a71233db6be8674688e" "victor-wiki/DatabaseManager 032506d9068adb8e52902b7065f10775593872a8" "quartznet/quartznet 15d90a9c2681cd9e273dcd3901c0fbbdbdc5fe90" "JasperFx/weasel 73b158bf5a708059ebc543e93e9b45e40f12d8c4" "erikdarlingdata/PerformanceMonitor b342229e3c6bd07388adf5566fdd0c8ede3f71b0" "JasperFx/marten 7a6c9c3bb13dda406e12b297b51c59fca26c29ab" "JasperFx/wolverine 7ee3df905e8d852ba0b93e1c7c5b435e5fe0dac7" "mikependon/RepoDB edabfb2044cbbed70a37eb04488386835d202038"; do
  set -- $line; echo "=== H25E3 $1 $2 $(date -u +%H:%M:%S)"; timeout 7200 python3 e3scan.py "$1" "$2" 2>&1 | tail -3
done
python3 - <<'PY' > h25e3-context.txt 2>&1
import json,glob,os
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3h25'
for f in sorted(glob.glob(f'{E}/*.e3.json')):
    d=json.load(open(f)); W=f'{S}/lab/sc/e3h23/'+d['repo'].replace('/','__')
    for kind in ('new_findings','lost_findings'):
        for x in d[kind]:
            rel,tfm,file,line,rule,msg=x; path=os.path.join(W,file); print(f'=== {kind} {d["repo"]} {rel} {tfm} {file}:{line} {rule} {msg}')
            try:
                L=open(path,encoding='utf-8',errors='ignore').read().splitlines()
                for i in range(max(0,line-10),min(len(L),line+10)): print(f'{i+1:5d}{">" if i+1==line else " "} {L[i]}')
            except Exception as e: print('  (no source)',e)
PY
echo H25_E3_DONE
