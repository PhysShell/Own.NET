"""H-25 await-wrapped acquire census (derived from the H-24 runner; harness invariant 0: the corrected environment is the default) over the kept H-23A scan clones (e3h23/<tag>): the SAME project/TFM units, reference
directories and trusted row files the OFF/ON scans used; runs the extractor once per unit with OWEN_RE_ORACLE=<unit
rows> and OWEN_H24_CENSUS=<unit>/h24.jsonl (census only, no engines), then aggregates one record per disposable local
with nested writes. usage: h24census.py <repo> [<repo> ...]"""
import json, os, sys, subprocess, glob, re, hashlib, time, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; R='/home/user/Own.NET'; E=f'{S}/lab/sc/e3h23'; E2=f'{S}/lab/sc/e2h23'
FIX=os.environ.get('H25_FIX_ENV','1')=='1'   # corrected compilation environment: SDK implicit global usings + the ASP.NET Core ref pack (erratum 2)
XD={'net8':f'{S}/ext8a/ownsharp-extract.dll','net10':f'{S}/ext10a/ownsharp-extract.dll'}
OUT=f'{S}/lab/h25/census' if FIX else f'{S}/lab/h25/census-asis'; os.makedirs(OUT,exist_ok=True)
sys.path.insert(0,f'{S}/lab/h24'); from implicit_usings import implicit_usings
def aspnet_ref(major):
    c=sorted(glob.glob(f'/root/.dotnet/packs/Microsoft.AspNetCore.App.Ref/{major}.*/ref/net{major}.0'))
    return c[-1] if c else None
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1','DOTNET_SKIP_FIRST_TIME_EXPERIENCE':'1'}
for k in ('OWEN_RE_ORACLE','OWEN_H23A','OWEN_RE_BODY','OWEN_RE_MINTED_RETURN','OWEN_RE_MIXED_RETURN','OWEN_LAB_THROWEXIT','OWEN_LAB_NULLINIT','OWEN_LAB_NULLGUARD','OWEN_P037X_GUARDED','OWEN_P037X_RELATIONAL','OWEN_RE_ORACLE_HITLOG','OWEN_H24_CENSUS','OWEN_H25_CENSUS'): env.pop(k,None)
EXCL=re.compile(r'(^|/)(tests?|testing|samples?|benchmarks?|examples?|docs?|demo)(/|\.|$)',re.I)
TESTP=re.compile(r'(test|tests|testing|benchmark|bench|sample|samples|example|examples|demo|playground)',re.I)
def assets_of(p,W):
    c=os.path.join(os.path.dirname(p),'obj','project.assets.json')
    if os.path.exists(c): return c
    pn=os.path.splitext(os.path.basename(p))[0]
    for c in glob.glob(f'{W}/**/artifacts/obj/{pn}/project.assets.json',recursive=True): return c
    return None
for repo in sys.argv[1:]:
    tag=repo.replace('/','__'); W=f'{E}/{tag}'; t0=time.time()
    e2=json.load(open(f'{E2}/{tag}.e2.json'))
    projs=sorted(p for p in glob.glob(f'{W}/**/*.csproj',recursive=True)); prod=[p for p in projs if not EXCL.search(os.path.relpath(p,W))]
    units=0; recs=[]; fails=0
    for p in prod:
        rel=os.path.relpath(p,W); assets=assets_of(p,W)
        if not assets or rel not in e2['per_project'] or 'targets' not in e2['per_project'][rel]: continue
        a=json.load(open(assets))
        for tfm in a['targets']:
            tfm0=tfm.split('/')[0]
            if tfm0 not in e2['per_project'][rel]['targets']: continue
            refdir=f'{W}/.refs/{hashlib.sha256((rel+tfm).encode()).hexdigest()[:10]}'; keyf=f'{refdir}/rows.json'
            if not os.path.exists(keyf): continue
            srcs=sorted(x for x in glob.glob(os.path.join(os.path.dirname(p),'**','*.cs'),recursive=True) if '/obj/' not in x and '/bin/' not in x)
            if not srcs: continue
            m=re.match(r'net(\d+)\.',tfm0); major=int(m.group(1)) if m else 0; xd=XD['net10'] if major>=9 else XD['net8']
            sfx='h25' if FIX else 'h25asis'; out=f'{refdir}/{sfx}.jsonl'; open(out,'w').close(); hits=f'{refdir}/{sfx}hits.jsonl'; open(hits,'w').close()
            e={**env,'OWEN_RE_ORACLE':keyf,'OWEN_H25_CENSUS':out,'OWEN_RE_ORACLE_HITLOG':hits}; extra=[]
            if FIX:
                ns=implicit_usings(p) or []
                if ns:
                    gu=f'{refdir}/GlobalUsings.g.cs'; open(gu,'w').write(''.join(f'global using {n};\n' for n in ns)); extra.append(gu)
                ar=aspnet_ref(major if major else 8)
                if ar: e['OWN_EXTRA_REF_DIRS']=ar
            try: pr=subprocess.run(['dotnet',xd,'--flow-locals',*srcs,*extra,'--ref-dir',refdir,'-o',f'{refdir}/{sfx}.facts.json'],cwd=R,capture_output=True,text=True,env=e,timeout=1500); rc=pr.returncode
            except subprocess.TimeoutExpired: rc='timeout'
            if rc!=0: fails+=1
            units+=1
            for l in open(out):
                if not l.strip(): continue
                j=json.loads(l); j['project']=rel; j['tfm']=tfm0; j['kind']='test' if TESTP.search(os.path.basename(rel)) or TESTP.search(os.path.relpath(j['file'],W) if j['file'].startswith(W) else j['file']) else 'production'
                j['file']=os.path.relpath(j['file'],W) if j['file'].startswith(W) else j['file']; recs.append(j)
    json.dump({'repo':repo,'sha':e2['sha'],'units':units,'extractor_failures':fails,'seconds':round(time.time()-t0),'environment':'corrected (implicit usings + aspnet ref pack)' if FIX else 'as-is','records':recs},open(f'{OUT}/{tag}.h25.json','w'),indent=1)
    c=collections.Counter((r['kind'],r['awaited'],bool(r['trusted_row'])) for r in recs)
    print('H25_DONE',repo,'units',units,'fails',fails,'await writes',len(recs),'by kind/awaited/trusted',dict(c),'production trusted',sum(1 for r in recs if r['kind']=='production' and r['trusted_row']),flush=True)
