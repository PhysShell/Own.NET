"""Stage B: whole-source derivation with the frozen rules (E1/E2/E3 + H-20) over src-whole of each library; whole-set
extractor run; the per-file union is used only if the whole-set run fails. Rows = public factory-surface callables
proved fresh (E1/E3) + receiver releases proved by E2, pinned to the package assembly."""
import json, os, sys, glob, subprocess, time, re
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'; R='/home/user/Own.NET'
LIBS=sys.argv[1:] or ['SkiaSharp','RabbitMQ.Client','MailKit','StackExchange.Redis','Npgsql','MQTTnet','SSH.NET','LibGit2Sharp']
GL='// synthesised: SDK implicit usings\nglobal using System;\nglobal using System.Collections.Generic;\nglobal using System.IO;\nglobal using System.Linq;\nglobal using System.Net.Http;\nglobal using System.Threading;\nglobal using System.Threading.Tasks;\n'
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1','PYTHONPATH':R,'OWEN_RE_BODY':'1','OWEN_RE_MINTED_RETURN':'1','OWEN_RE_MIXED_RETURN':'1','OWEN_LAB_THROWEXIT':'1'}
for k in ('OWEN_RE_ORACLE','OWEN_P037X_RELATIONAL','OWEN_LAB_NULLINIT','OWEN_LAB_NULLGUARD'): env.pop(k,None)
DLL=f'{R}/frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll'
for pid in LIBS:
    L=f'{D}/libs/{pid}'; d=f'{L}/src-whole'; acq=json.load(open(f'{L}/acquire.json')); api=json.load(open(f'{L}/api.json'))
    open(f'{d}/__GlobalUsings.cs','w').write(GL); src=sorted(glob.glob(f'{d}/*.cs')); t0=time.time()
    refdir=os.path.dirname(acq['main_assembly']); e=dict(env); e['OWEN_RE_DUMP_EFFECTS']=f'{L}/dump-whole.json'
    r=subprocess.run(['dotnet',DLL,'--flow-locals',*src,'-o',f'{L}/facts-whole.json','--ref-dir',refdir],cwd=R,capture_output=True,text=True,env=e)
    open(f'{L}/derive-whole.err','w').write(r.stderr[-20000:])
    ok=os.path.exists(f'{L}/facts-whole.json') and r.returncode==0
    summ=subprocess.run(['python3','-m','ownlang','summaries',f'{L}/facts-whole.json'],cwd=R,capture_output=True,text=True,env=env).stdout if ok else ''
    try: summaries=json.loads(summ)['summaries']
    except Exception: summaries=[]
    fresh={s['method'].split('(')[0] for s in summaries if s.get('returns',{}).get('owned')=='fresh'}
    try: dump=json.load(open(f'{L}/dump-whole.json'))
    except Exception: dump={}
    rel={x['callable'] for x in dump.get('receiver_release',[]) if x.get('releases')}
    surface={f['callable'] for f in api['factories']}; relsurf={x['callable'] for x in api['release_name_candidates']}
    asm=(acq.get('identity') or {}).get('name') or pid; mvid=(acq.get('identity') or {}).get('mvid')
    rows=[{'callable':c,'effect':'return_fresh_owned','provenance':'BODY_PROVED','assembly':{'name':asm,'mvid':mvid},'derived_from':f'whole-source {acq.get("repository_url")}@{acq.get("repository_commit")} via E1/E3'} for c in sorted(fresh&surface)]
    rows+=[{'callable':c,'effect':'receiver_terminal_release','provenance':'BODY_PROVED','assembly':{'name':asm,'mvid':mvid},'derived_from':'whole-source via E2'} for c in sorted(rel&relsurf)]
    census=re.search(r're-body:[^\n]*',r.stderr); stats=None
    try: stats=json.load(open(f'{L}/facts-whole.json')).get('stats')
    except Exception: pass
    out={'package':pid,'files':len(src),'whole_set_ok':ok,'returncode':r.returncode,'seconds':round(time.time()-t0,1),'stats':stats,'re_body_census':census.group(0) if census else None,'fresh_all':sorted(fresh),'fresh_on_surface':sorted(fresh&surface),'fresh_not_on_public_surface':sorted(fresh-surface),'release_all':sorted(rel),'release_on_surface':sorted(rel&relsurf),'surface_factories':len(surface),'surface_release_candidates':len(relsurf),'rows':rows}
    json.dump(out,open(f'{L}/rows-whole.json','w'),indent=1)
    print(json.dumps({k:out[k] for k in ('package','files','whole_set_ok','seconds','stats','re_body_census','surface_factories')}),'fresh_all',len(fresh),'rows',len(rows),flush=True)
print('DERIVE_WHOLE_DONE')
