"""discovery S9 helper: print the source context of every NEW finding of a scan (for the experimenter's triage)."""
import sys, json, os
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'
pid, tag = sys.argv[1], sys.argv[2]; ctx=int(sys.argv[3]) if len(sys.argv)>3 else 6
r=json.load(open(f'{D}/libs/{pid}/s8-scan-{tag}.json'))
for kind in ('new_findings','lost_findings'):
    for f in r[kind]:
        fn, line, code, msg = f; path=f'{D}/libs/{pid}/consumers/{tag}/{fn}'
        print(f'==== {kind[:-9].upper()} {pid}/{tag}/{fn}:{line} [{code}] {msg[:110]}')
        if os.path.exists(path):
            lines=open(path,encoding='utf-8',errors='replace').read().splitlines()
            for i in range(max(0,line-1-ctx), min(len(lines), line+ctx)):
                print(f'{i+1:5d}{"*" if i+1==line else " "} {lines[i][:150]}')
