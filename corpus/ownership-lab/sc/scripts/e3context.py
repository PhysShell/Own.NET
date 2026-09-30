"""Print the source context of every NEW (ON-only) and LOST finding of the E3 scans, for manual classification."""
import json, glob, os, sys
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3'
for f in sorted(glob.glob(f'{E}/*.e3.json')):
    d=json.load(open(f)); W=f'{E}/'+d['repo'].replace('/','__')
    for kind in ('new_findings','lost_findings'):
        for x in d[kind]:
            rel,tfm,file,line,rule,msg=x; path=os.path.join(W,file)
            print(f'=== {kind} {d["repo"]} {rel} {tfm} {file}:{line} {rule} {msg}')
            try:
                L=open(path,encoding='utf-8',errors='ignore').read().splitlines()
                for i in range(max(0,line-8),min(len(L),line+8)): print(f'{i+1:5d}{">" if i+1==line else " "} {L[i]}')
            except Exception as e: print('  (no source)',e)
