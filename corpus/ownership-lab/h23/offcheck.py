"""OFF byte-identity on real consumers: for every unit dir of the kept E3 clones (NpgsqlRest, DatabaseManager), re-run the
extractor with the NEW builds exactly as e3scan did (OFF = no oracle; ON = oracle rows, seam off) and compare the facts
byte-for-byte with the stored off.facts.json / on.facts.json produced by the pre-change builds."""
import os, glob, subprocess, json, re, sys, hashlib
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; R='/home/user/Own.NET'; E=f'{S}/lab/sc/e3'
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1'}
for k in ('OWEN_RE_ORACLE','OWEN_H23A','OWEN_RE_ORACLE_HITLOG','OWEN_LAB_NULLINIT','OWEN_LAB_NULLGUARD','OWEN_RE_BODY','OWEN_RE_MINTED_RETURN','OWEN_RE_MIXED_RETURN','OWEN_LAB_THROWEXIT','OWEN_P037X_GUARDED','OWEN_P037X_RELATIONAL'): env.pop(k,None)
EXCL=re.compile(r'(^|/)(tests?|testing|samples?|benchmarks?|examples?|docs?|demo)(/|\.|$)',re.I)
res=[]
for tag in ('NpgsqlRest__NpgsqlRest','victor-wiki__DatabaseManager'):
    W=f'{E}/{tag}'; e2=json.load(open(f'{S}/lab/sc/e2/{tag}.e2.json'))
    projs=sorted(p for p in glob.glob(f'{W}/**/*.csproj',recursive=True)); prod=[p for p in projs if not EXCL.search(os.path.relpath(p,W))]
    for p in prod:
        rel=os.path.relpath(p,W)
        if rel not in e2['per_project'] or 'targets' not in e2['per_project'][rel]: continue
        for tfm0 in e2['per_project'][rel]['targets']:
            # the unit dir hash uses the FULL target key; recover it from the assets file
            a=None
            for cand in (os.path.join(os.path.dirname(p),'obj','project.assets.json'),):
                if os.path.exists(cand): a=json.load(open(cand))
            if a is None: continue
            for tfm in a['targets']:
                if tfm.split('/')[0]!=tfm0: continue
                refdir=f'{W}/.refs/{hashlib.sha256((rel+tfm).encode()).hexdigest()[:10]}'
                if not os.path.isdir(refdir) or not os.path.exists(f'{refdir}/off.facts.json'): continue
                srcs=sorted(x for x in glob.glob(os.path.join(os.path.dirname(p),'**','*.cs'),recursive=True) if '/obj/' not in x and '/bin/' not in x)
                m=re.match(r'net(\d+)\.',tfm0); major=int(m.group(1)) if m else 0
                XD=f'{S}/ext10/ownsharp-extract.dll' if major>=9 else f'{R}/frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll'
                for arm in ('off','on'):
                    e=dict(env)
                    if arm=='on': e['OWEN_RE_ORACLE']=f'{refdir}/rows.json'
                    out=f'{refdir}/{arm}.facts.h23check.json'
                    subprocess.run(['dotnet',XD,'--flow-locals',*srcs,'--ref-dir',refdir,'-o',out],cwd=R,capture_output=True,text=True,env=e,timeout=1500)
                    same=os.path.exists(out) and open(out,'rb').read()==open(f'{refdir}/{arm}.facts.json','rb').read()
                    res.append((tag,rel,tfm0,arm,same))
                    print(tag.split('__')[-1],rel.split('/')[-1],tfm0,arm,'IDENTICAL' if same else 'DIFFERS',flush=True)
json.dump(res,open(f'{S}/lab/h23/offcheck.json','w'),indent=1); print('OFFCHECK_DONE identical',sum(1 for r in res if r[4]),'of',len(res))
