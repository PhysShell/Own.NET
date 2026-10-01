"""Print every H-28 BORROW candidate (ESCAPE_UNTRACKED, caller NOTHING, callee BORROW body-proved) with source context for the manual refute-only read. usage: h27s4ctx.py [n_before n_after]"""
import json, sys, os
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3h23'
B=int(sys.argv[1]) if len(sys.argv)>1 else 6; A=int(sys.argv[2]) if len(sys.argv)>2 else 14
for i,s in enumerate(json.load(open(f'{S}/lab/h28/borrow-candidates.json'))):
    p=f"{E}/{s['repo'].replace('/','__')}/{s['file']}"
    try: lines=open(p,encoding='utf-8',errors='replace').read().split('\n')
    except Exception as e: print(f'## {i} {s["repo"]} {s["file"]}:{s["line"]} UNREADABLE {e}'); continue
    print(f"## {i} {s['repo']} {s['file']}:{s['line']} {s['member']} | local {s['local']} ({s['local_type']}, {s['acquire_shape']}) -> {s['callee']} param {s['parameter']} | caller_kinds={s['caller_kinds']} callee_uses={s['callee_use_kinds']} stmt={s['call_is_statement']}")
    for n in range(max(0,s['line']-1-B),min(len(lines),s['line']+A)): print(f"{n+1:5d}{'>' if n+1==s['line'] else ' '} {lines[n][:150]}")
    print()
