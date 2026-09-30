"""discovery S8 (scan): OFF (no key) versus KEY (applied rows) over a consumer set; findings diffed per file (Rust engine,
guarded off); python==rust checked. usage: scan.py <pkg> <consumer-tag> [applied-rows.json]"""
import sys, os, json, subprocess, glob, re, hashlib
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; R='/home/user/Own.NET'
pid, tag = sys.argv[1], sys.argv[2]; L=f'{S}/lab/disc/libs/{pid}'
key = sys.argv[3] if len(sys.argv)>3 else f'{L}/rows-applied.json'
acq=json.load(open(f'{L}/acquire.json')); refdir=os.path.dirname(acq['main_assembly'])
files=sorted(glob.glob(f'{L}/consumers/{tag}/*.cs'))
DLL=f'{R}/frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll'; OWN=f'{R}/rust/target/release/own-cli'
FIND=re.compile(r'([^/\s]+\.cs):(\d+): (\w+): \[(OWN\d+)\] (.*)')
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1','PYTHONPATH':R}
for k in ('OWEN_RE_ORACLE','OWEN_RE_BODY','OWEN_RE_MINTED_RETURN','OWEN_RE_MIXED_RETURN','OWEN_P037X_RELATIONAL','OWEN_P037X_GUARDED','OWEN_LAB_NULLINIT','OWEN_LAB_NULLGUARD'): env.pop(k,None)
def run(arm, e):
    out=f'{L}/s8-{tag}.{arm}.facts.json'
    r=subprocess.run(['dotnet',DLL,'--flow-locals',*files,'--ref-dir',refdir,'-o',out],cwd=R,capture_output=True,text=True,env=e)
    census=re.findall(r'(re-oracle[^\n]*)',r.stderr)
    v=subprocess.run([OWN,'ownir',out,'--format','human','--severity','warning','--verbosity','verbose'],cwd=R,capture_output=True,text=True,env={**e,'OWEN_P037X_GUARDED':'0'}).stdout
    p=subprocess.run(['python3','-m','ownlang','ownir',out,'--format','human','--severity','warning','--verbosity','verbose'],cwd=R,capture_output=True,text=True,env=e).stdout
    f=sorted(set((m.group(1),int(m.group(2)),m.group(4),m.group(5)) for m in FIND.finditer(v)))
    fp=sorted(set((m.group(1),int(m.group(2)),m.group(4),m.group(5)) for m in FIND.finditer(p)))
    return {'findings':f,'python_equals_rust':f==fp,'census':census,'stats':json.load(open(out)).get('stats') if os.path.exists(out) else None}
off=run('off',env); key_=run('key',{**env,'OWEN_RE_ORACLE':key})
new=[x for x in key_['findings'] if x not in off['findings']]; lost=[x for x in off['findings'] if x not in key_['findings']]
res={'package':pid,'consumer':tag,'files':len(files),'key':key,'key_sha256':hashlib.sha256(open(key,'rb').read()).hexdigest(),'off':off,'key_arm':key_,'new_findings':new,'lost_findings':lost}
json.dump(res,open(f'{L}/s8-scan-{tag}.json','w'),indent=1)
print(json.dumps({'package':pid,'consumer':tag,'files':len(files),'off_findings':len(off['findings']),'key_findings':len(key_['findings']),'new':len(new),'lost':len(lost),'py==rs':off['python_equals_rust'] and key_['python_equals_rust'],'census':key_['census'],'stats':key_['stats']}))
for x in new: print('  NEW', x)
for x in lost: print('  LOST', x)
