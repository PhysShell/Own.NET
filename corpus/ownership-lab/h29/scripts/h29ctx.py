"""Print every H-29 primary candidate (orphaned awaitable local, family A or B) with source context for the manual triage. usage: h27s4ctx.py [n_before n_after]"""
import json, sys, os
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3h23'
B=int(sys.argv[1]) if len(sys.argv)>1 else 6; A=int(sys.argv[2]) if len(sys.argv)>2 else 14
for i,s in enumerate(json.load(open(f'{S}/lab/h29/candidates.json'))):
    p=f"{E}/{s['repo'].replace('/','__')}/{s['file']}"
    try: lines=open(p,encoding='utf-8',errors='replace').read().split('\n')
    except Exception as e: print(f'## {i} {s["repo"]} {s["file"]}:{s["line"]} UNREADABLE {e}'); continue
    print(f"## {i} {s['repo']} {s['file']}:{s['line']} {s['member']} | local {s['local']} = {s['callee']} -> {s['return_type']} | family={s['family']} lifecycle={s['lifecycle_member']} async={s['in_async_member']} try={s['in_try']}")
    for n in range(max(0,s['line']-1-B),min(len(lines),s['line']+A)): print(f"{n+1:5d}{'>' if n+1==s['line'] else ' '} {lines[n][:150]}")
    print()
