"""H-23A fixture runner: one configuration per call. Runs the extractor (flow locals, ref-dir = RLib, oracle rows,
hit log) and BOTH engines, maps findings to fixture methods, prints and stores a per-method table."""
import json, os, re, subprocess, sys
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; H=f'{S}/lab/h23'; R='/home/user/Own.NET'
cfg=sys.argv[1]; extra=dict(a.split('=',1) for a in sys.argv[2:])
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1','PYTHONPATH':R}
for k in ('OWEN_RE_ORACLE','OWEN_RE_BODY','OWEN_RE_MINTED_RETURN','OWEN_RE_MIXED_RETURN','OWEN_LAB_THROWEXIT','OWEN_LAB_NULLINIT','OWEN_LAB_NULLGUARD','OWEN_P037X_GUARDED','OWEN_P037X_RELATIONAL','OWEN_RE_ORACLE_HITLOG','OWEN_H23A'): env.pop(k,None)
env.update(extra)
out=f'{H}/out/{cfg}'; os.makedirs(out,exist_ok=True)
src=extra.get('SRC',f'{H}/fx/Fixture.cs'); refdir=extra.get('REFDIR',f'{H}/RLib/bin/Release/net8.0')
hit=f'{out}/hits.jsonl'; open(hit,'w').close(); env['OWEN_RE_ORACLE_HITLOG']=hit
XD=extra.get('XD',f'{R}/frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll')
p=subprocess.run(['dotnet',XD,'--flow-locals',src,'--ref-dir',refdir,'-o',f'{out}/facts.json'],cwd=R,capture_output=True,text=True,env=env)
open(f'{out}/extract.err','w').write(p.stderr)
FIND=re.compile(r'([^\s]+\.cs):(\d+): (\w+): \[(OWN\d+)\] (.*)')
def engine(cmd,e):
    r=subprocess.run(cmd,cwd=R,capture_output=True,text=True,env=e); return sorted(set((int(m.group(2)),m.group(4),m.group(5)) for m in FIND.finditer(r.stdout))), r.stdout, r.stderr
rs,rso,rse=engine([f'{R}/rust/target/release/own-cli','ownir',f'{out}/facts.json','--format','human','--severity','warning','--verbosity','verbose'],{**env,'OWEN_P037X_GUARDED':'0'})
py,pyo,pye=engine(['python3','-m','ownlang','ownir',f'{out}/facts.json','--format','human','--severity','warning','--verbosity','verbose'],env)
open(f'{out}/rust.out','w').write(rso+rse); open(f'{out}/python.out','w').write(pyo+pye)
# method spans
lines=open(src).read().splitlines(); meth={}
cur=None
for i,l in enumerate(lines,1):
    m=re.search(r'public static \w+ (\w+)\(',l)
    if m: cur=m.group(1); meth[cur]=[i,i]
    elif cur and l.strip().startswith('public static'): cur=None
    if cur: meth[cur][1]=i
def owner(line):
    for k,(a,b) in meth.items():
        if a<=line<=b: return k
    return None
table={}
for k in meth: table[k]={'rust':[],'python':[]}
for ln,rule,msg in rs:
    o=owner(ln); (table.setdefault(o,{'rust':[],'python':[]}))['rust'].append(f'{rule} {msg}')
for ln,rule,msg in py:
    o=owner(ln); (table.setdefault(o,{'rust':[],'python':[]}))['python'].append(f'{rule} {msg}')
hits=[json.loads(l) for l in open(hit) if l.strip()]
eng_err=[n for n,o in (('rust',rso+rse),('python',pyo+pye)) if 'error: internal' in o or 'OWN030' in o]
res={'config':cfg,'env':extra,'engine_internal_error':eng_err,'extractor_rc':p.returncode,'stderr_tail':p.stderr[-400:],'parity':rs==py,'findings_rust':rs,'findings_python':py,'per_method':table,'oracle_hits':[(h['line'],h.get('shape'),h['callable']) for h in hits]}
json.dump(res,open(f'{out}/result.json','w'),indent=1)
print(f'== {cfg} rc={p.returncode} parity={rs==py} engine_error={eng_err} hits={len(hits)} census={[l for l in p.stderr.splitlines() if l.startswith(("re-oracle","lab-","h23"))]}')
for k,v in table.items():
    if k: print(f'  {k:40s} {"; ".join(v["rust"]) or "clean"}' + ('' if v['rust']==v['python'] else f'   PY: {v["python"]}'))
