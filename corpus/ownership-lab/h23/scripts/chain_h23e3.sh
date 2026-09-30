#!/usr/bin/env bash
# after the treatment census: (1) re-census with the NARROWED build (xd.json) the consumers censused before the switch
# (weasel, NpgsqlRest, marten, wolverine: same rows/revisions; the hit log now labels assignment / assignment_nested /
# assignment_loop), (2) attribution, (3) OFF (rows, seam off) versus H23-ON (rows + seam) on every frozen consumer with
# >= 1 trusted opportunity; clones kept for triage; (4) the finding contexts
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 OWEN_H23A_TREATMENT=1
for i in $(seq 1 1080); do grep -q "^H23_E2_DONE" $S/lab/sc/h23.log 2>/dev/null && break; sleep 10; done
cd $S/lab/sc
prune() { avail=$(df -k / | tail -1 | awk '{print $4}'); if [ "$avail" -lt 6000000 ]; then echo "PRUNE cache"; rm -rf ~/.nuget/packages/* ~/.local/share/NuGet/http-cache 2>/dev/null; for d in $S/pkgrestore/r_*; do dotnet restore $d/r.csproj -nologo -v q >/dev/null 2>&1; done; fi; }
for line in "JasperFx/weasel 73b158bf5a708059ebc543e93e9b45e40f12d8c4" "NpgsqlRest/NpgsqlRest 6cc6f55fa65b14e394fa1a71233db6be8674688e" "JasperFx/marten 7a6c9c3bb13dda406e12b297b51c59fca26c29ab" "JasperFx/wolverine 7ee3df905e8d852ba0b93e1c7c5b435e5fe0dac7"; do
  set -- $line; prune; tag=${1//\//__}; echo "=== H23 RECENSUS(narrowed) $1 $2 $(date -u +%H:%M:%S)"; timeout 3600 python3 e2.py "$1" "$2" 2>&1 | tail -2; rm -rf "$S/lab/sc/e2h23/$tag"
done
echo H23_RECENSUS_DONE
python3 h23attrib.py > h23-attrib.log 2>&1
python3 - <<'PY' > h23e3-order.txt
import json,glob
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
for f in sorted(glob.glob(f'{S}/lab/sc/e2h23/*.e2.json')):
    d=json.load(open(f))
    if d['unit_count_trusted']>=1: print(d['repo'], d['sha'])
PY
while read -r repo sha || [ -n "$repo" ]; do [ -z "$repo" ] && continue
  prune; echo "=== H23E3 $repo $sha $(date -u +%H:%M:%S)"; timeout 5400 python3 e3scan.py "$repo" "$sha" 2>&1 | tail -3; done < h23e3-order.txt
python3 - <<'PY' > h23e3-context.txt 2>&1
import json,glob,os
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3h23'
for f in sorted(glob.glob(f'{E}/*.e3.json')):
    d=json.load(open(f)); W=f'{E}/'+d['repo'].replace('/','__')
    for kind in ('new_findings','lost_findings'):
        for x in d[kind]:
            rel,tfm,file,line,rule,msg=x; path=os.path.join(W,file); print(f'=== {kind} {d["repo"]} {rel} {tfm} {file}:{line} {rule} {msg}')
            try:
                L=open(path,encoding='utf-8',errors='ignore').read().splitlines()
                for i in range(max(0,line-10),min(len(L),line+10)): print(f'{i+1:5d}{">" if i+1==line else " "} {L[i]}')
            except Exception as e: print('  (no source)',e)
PY
echo H23_E3_DONE
