"""After the H-26B census: find the units whose extractor run failed (no h26b.facts.json newer than h26b.jsonl), re-run them
with the FIXED build (ext8q2 / ext10q2: cross-file semantic model for field initializers), replace their records in the
census files and record the re-run (harness sanity gate: the unit record names the build)."""
import json, glob, os, re, subprocess, hashlib, sys, time
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; R='/home/user/Own.NET'; E=f'{S}/lab/sc/e3h23'
sys.path.insert(0,f'{S}/lab/h24'); from implicit_usings import implicit_usings
XD={'net8':f'{S}/ext8q2/ownsharp-extract.dll','net10':f'{S}/ext10q2/ownsharp-extract.dll'}
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1'}
TESTP=re.compile(r'(test|tests|testing|benchmark|bench|sample|samples|example|examples|demo|playground)',re.I)
log=[]
for cf in sorted(glob.glob(f'{S}/lab/h26b/census/*.h26b.json')):
    d=json.load(open(cf)); tag=d['repo'].replace('/','__'); W=f'{E}/{tag}'; fixed=0
    for rd in glob.glob(f'{W}/.refs/*/'):
        rd=rd.rstrip('/')
        if not os.path.exists(f'{rd}/h26b.jsonl'): continue
        ff=f'{rd}/h26b.facts.json'
        if os.path.exists(ff) and os.path.getmtime(ff)>=os.path.getmtime(f'{rd}/h26b.jsonl'): continue
        label=json.load(open(f'{rd}/rows.json'))['label']; m=re.match(r'E3 (\S+) (\S+) (\S+)',label); rel,tfm0=m.group(2),m.group(3)
        p=f'{W}/{rel}'; srcs=sorted(x for x in glob.glob(os.path.join(os.path.dirname(p),'**','*.cs'),recursive=True) if '/obj/' not in x and '/bin/' not in x)
        mm=re.match(r'net(\d+)\.',tfm0); major=int(mm.group(1)) if mm else 0; xd=XD['net10'] if major>=9 else XD['net8']
        ns=implicit_usings(p) or []; extra=[]
        if ns: gu=f'{rd}/GlobalUsings.g.cs'; open(gu,'w').write(''.join(f'global using {n};\n' for n in ns)); extra.append(gu)
        ar=sorted(glob.glob(f'/root/.dotnet/packs/Microsoft.AspNetCore.App.Ref/{major if major else 8}.*/ref/net{major if major else 8}.0')); e=dict(env)
        if ar: e['OWN_EXTRA_REF_DIRS']=ar[-1]
        out=f'{rd}/h26b.jsonl'; open(out,'w').close(); e.update({'OWEN_RE_ORACLE':f'{rd}/rows.json','OWEN_H26B_CENSUS':out})
        pr=subprocess.run(['dotnet',xd,'--flow-locals',*srcs,*extra,'--ref-dir',rd,'-o',ff],cwd=R,capture_output=True,text=True,env=e,timeout=1500)
        recs=[]
        for l in open(out):
            if not l.strip(): continue
            j=json.loads(l); j['project']=rel; j['tfm']=tfm0; j['kind']='test' if TESTP.search(os.path.basename(rel)) or TESTP.search(os.path.relpath(j['file'],W) if j['file'].startswith(W) else j['file']) else 'production'
            j['file']=os.path.relpath(j['file'],W) if j['file'].startswith(W) else j['file']; j['build']='ext_q2 (cross-file model fix)'; recs.append(j)
        d['records']=[r for r in d['records'] if not (r['project']==rel and r['tfm']==tfm0)]+recs
        log.append({'repo':d['repo'],'unit':f'{rel}|{tfm0}','rc':pr.returncode,'records':len(recs)}); fixed+=1 if pr.returncode==0 else 0
    d['extractor_failures_after_rerun']=d['extractor_failures']-fixed; d['rerun_with_fixed_build']=[x for x in log if x['repo']==d['repo']]
    json.dump(d,open(cf,'w'),indent=1)
json.dump(log,open(f'{S}/lab/h26b/rerun-log.json','w'),indent=1); print(json.dumps(log,indent=1))
