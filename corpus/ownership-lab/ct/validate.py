"""CT novelty validation (frozen rule): for arms A, B_unvalidated, C_lr take the FIRST candidate of the arm's queue for
the first 10 libraries (alphabetical) with a non-empty queue; validate by the body proof (E1/E3 + H-20) over the
candidate type's source file at the pinned commit (path resolved by Sourcegraph type:path at that commit, fetched raw);
outcomes PROVED / REFUSED / NO_SOURCE / ERROR. A PROVED candidate is a NOVEL row (not among the applied rows)."""
import json, os, re, sys, subprocess, urllib.request, urllib.parse, time, glob, hashlib
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'; C=f'{S}/lab/ct'; R='/home/user/Own.NET'
g=json.load(open(f'{C}/gate0-results.json')); queues=g['novelty_queues']
ARMS=['A','B_unvalidated','C_lr']; N=10
plan=[]
for arm in ARMS:
    libs=[p for p in sorted(queues) if queues[p].get(arm)][:N]
    for p in libs: plan.append({'arm':arm,'package':p,'callable':queues[p][arm][0]})
def sg_path(owner_repo, commit, typename):
    q=f'repo:^github\\.com/{re.escape(owner_repo)}$@{commit} type:path file:(?i)(^|/){re.escape(typename)}\\.cs$ count:20'
    url='https://sourcegraph.com/.api/search/stream?'+urllib.parse.urlencode({'q':q})
    for attempt in range(4):
        try:
            req=urllib.request.Request(url,headers={'Accept':'text/event-stream','User-Agent':'own.net-ct'})
            with urllib.request.urlopen(req,timeout=120) as resp: txt=resp.read().decode('utf-8','replace')
            paths=[]; ev=None
            for line in txt.splitlines():
                if line.startswith('event: '): ev=line[7:].strip()
                elif line.startswith('data: ') and ev=='matches':
                    for m in json.loads(line[6:]):
                        if m.get('type')=='path': paths.append(m.get('path'))
            return paths
        except Exception as e: time.sleep(2*(attempt+1)); err=str(e)[:80]
    return []
def fetch(owner_repo, commit, path):
    url=f'https://raw.githubusercontent.com/{owner_repo}/{commit}/{path}'
    with urllib.request.urlopen(url,timeout=60) as r: return r.read()
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1','PYTHONPATH':R,'OWEN_RE_BODY':'1','OWEN_RE_MINTED_RETURN':'1','OWEN_RE_MIXED_RETURN':'1','OWEN_LAB_THROWEXIT':'1'}
for k in ('OWEN_RE_ORACLE','OWEN_P037X_RELATIONAL','OWEN_LAB_NULLINIT','OWEN_LAB_NULLGUARD'): env.pop(k,None)
results=[]; cache={}
for it in plan:
    p=it['package']; L=f'{D}/libs/{p}'; acq=json.load(open(f'{L}/acquire.json')); repo=(acq.get('repository_url') or '').replace('https://github.com/','').replace('.git','').rstrip('/'); commit=acq.get('repository_commit')
    cal=it['callable']; typ=cal.rsplit('.',1)[0]; simple=re.sub(r'<.*>','',typ.split('.')[-1]); res=dict(it); res['type']=typ
    if not repo or not commit: res['outcome']='NO_SOURCE'; res['why']='no repository pin'; results.append(res); print(json.dumps(res),flush=True); continue
    key=(p,simple)
    if key not in cache:
        paths=sg_path(repo,commit,simple); path=None
        pref=[x for x in paths if '/test' not in x.lower() and 'sample' not in x.lower()]
        if pref: path=sorted(pref,key=len)[0]
        elif paths: path=sorted(paths,key=len)[0]
        cache[key]=path
    path=cache[key]
    if not path: res['outcome']='NO_SOURCE'; res['why']='type file not found at the pinned commit'; results.append(res); print(json.dumps(res),flush=True); continue
    os.makedirs(f'{L}/src-ct',exist_ok=True); local=f'{L}/src-ct/{path.replace("/","__")}'
    try:
        if not os.path.exists(local): open(local,'wb').write(fetch(repo,commit,path))
    except Exception as e: res['outcome']='NO_SOURCE'; res['why']=f'fetch failed: {str(e)[:60]}'; results.append(res); print(json.dumps(res),flush=True); continue
    res['source']=path; res['source_sha256']=hashlib.sha256(open(local,'rb').read()).hexdigest()[:16]
    refdir=os.path.dirname(acq['main_assembly']); gl=f'{L}/src/__GlobalUsings.cs'
    facts=f'{L}/src-ct/facts.{simple}.json'
    argv=['dotnet',f'{R}/frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll','--flow-locals',local,gl,'-o',facts,'--ref-dir',refdir]
    e=dict(env); e['OWEN_RE_DUMP_EFFECTS']=f'{L}/src-ct/dump.{simple}.json'
    if p=='Microsoft.Data.Sqlite.Core': e['OWN_EXTRA_REF_DIRS']=f'{D}/deps/SQLitePCLRaw.core/lib/netstandard2.0'
    r=subprocess.run(argv,cwd=R,capture_output=True,text=True,env=e)
    summ=subprocess.run(['python3','-m','ownlang','summaries',facts],cwd=R,capture_output=True,text=True,env=env).stdout
    try: fresh={s['method'].split('(')[0] for s in json.loads(summ)['summaries'] if s.get('returns',{}).get('owned')=='fresh'}
    except Exception: fresh=set()
    census=re.search(r're-body:[^\n]*',r.stderr); res['re_body_census']=census.group(0) if census else None
    if cal in fresh: res['outcome']='PROVED'; res['provenance']='BODY_PROVED'
    else: res['outcome']='REFUSED'; res['fresh_in_file']=sorted(fresh)[:6]
    results.append(res); print(json.dumps(res),flush=True)
json.dump({'plan':plan,'results':results},open(f'{C}/ct-validation.json','w'),indent=1)
tal={}
for r in results: tal.setdefault(r['arm'],{}).setdefault(r['outcome'],0); tal[r['arm']][r['outcome']]+=1
print('TALLY',json.dumps(tal)); print('VALIDATE_DONE')
