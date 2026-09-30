"""discovery S5: derive BODY_PROVED rows from the fetched source files of one library through the research body arms
(E1 fresh returns, E2 receiver releases, E3 mixed returns) and pin them to the deployed assembly's MVID.
usage: derive.py <PackageId>  (reads libs/<id>/acquire.json and libs/<id>/src/**.cs)"""
import sys, os, json, subprocess, glob, re
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; R='/home/user/Own.NET'
pid=sys.argv[1]; d=f'{S}/lab/disc/libs/{pid}'; acq=json.load(open(f'{d}/acquire.json'))
open(f'{d}/src/__GlobalUsings.cs','w').write('// synthesised for the discovery derivation: the SDK implicit usings (ImplicitUsings=enable) the fetched files rely on\nglobal using System;\nglobal using System.Collections.Generic;\nglobal using System.IO;\nglobal using System.Linq;\nglobal using System.Net.Http;\nglobal using System.Threading;\nglobal using System.Threading.Tasks;\n')
src=sorted(glob.glob(f'{d}/src/**/*.cs', recursive=True))
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1','PYTHONPATH':R,
     'OWEN_RE_BODY':'1','OWEN_RE_MINTED_RETURN':'1','OWEN_RE_MIXED_RETURN':'1','OWEN_RE_DUMP_EFFECTS':f'{d}/dump.json'}
for k in ('OWEN_RE_ORACLE','OWEN_P037X_RELATIONAL','OWEN_LAB_NULLINIT','OWEN_LAB_NULLGUARD'): env.pop(k,None)
refdir=os.path.dirname(acq['main_assembly']) if acq.get('main_assembly') else None
argv=['dotnet',f'{R}/frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll','--flow-locals',*src,'-o',f'{d}/facts.json']
if refdir: argv+=['--ref-dir',refdir]
r=subprocess.run(argv,cwd=R,capture_output=True,text=True,env=env)
open(f'{d}/derive.err','w').write(r.stderr)
summ=subprocess.run(['python3','-m','ownlang','summaries',f'{d}/facts.json'],cwd=R,capture_output=True,text=True,env=env).stdout
try: summaries=json.loads(summ)['summaries']
except Exception: summaries=[]
# per-file union (E1/E2 proofs are local to a method body; a curated source SUBSET can make a created type's
# declaration incomplete and lose the whole-set record, so each file is also derived alone against the package
# assembly and the fresh/release results are unioned; the provenance stays BODY_PROVED)
perfile_fresh=set(); perfile_rel=[]
for f in src:
    argv1=['dotnet',f'{R}/frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll','--flow-locals',f,'-o',f'{d}/facts.one.json']
    if refdir: argv1+=['--ref-dir',refdir]
    e1={**env,'OWEN_RE_DUMP_EFFECTS':f'{d}/dump.one.json'}
    subprocess.run(argv1,cwd=R,capture_output=True,text=True,env=e1)
    s1=subprocess.run(['python3','-m','ownlang','summaries',f'{d}/facts.one.json'],cwd=R,capture_output=True,text=True,env=env).stdout
    try:
        for s in json.loads(s1)['summaries']:
            if s.get('returns',{}).get('owned')=='fresh': perfile_fresh.add(s['method'])
    except Exception: pass
    try:
        for e in json.load(open(f'{d}/dump.one.json')).get('receiver_release',[]):
            if e.get('releases'): perfile_rel.append(e)
    except Exception: pass
whole_fresh={s['method'] for s in summaries if s.get('returns',{}).get('owned')=='fresh'}
for m in sorted(perfile_fresh-whole_fresh):
    summaries.append({'method':m,'returns':{'owned':'fresh'},'source':'inferred (per-file run)'})
api=json.load(open(f'{d}/api.json')) if os.path.exists(f'{d}/api.json') else {'factories':[],'release_name_candidates':[],'types':[]}
public_callables={f['callable'] for f in api['factories']} | {r['callable'] for r in api['release_name_candidates']} | {f"{t['type']}.Dispose" for t in api['types']}
public_types={t['type'] for t in api['types']}
mvid=(acq.get('identity') or {}).get('mvid'); asm=acq['package']
rows=[]; seen=set()
for s in summaries:
    if s.get('returns',{}).get('owned')=='fresh':
        m=s['method'].split('(')[0]; sig=s.get('sig')
        # method summaries are keyed Namespace.Type.Method[(sig)]; keep only PUBLIC factories of the API surface;
        # explicit interface implementations (Type.IFace.Method) never match a public callable
        if m in public_callables and (m,'fresh') not in seen:
            seen.add((m,'fresh')); rows.append({'callable':m,'effect':'return_fresh_owned','provenance':'BODY_PROVED','assembly':{'name':asm,'mvid':mvid},'derived_from':f"{acq.get('repository_url')}@{acq.get('repository_commit')} via E1/E3 ({s.get('source')})"})
dump=json.load(open(f'{d}/dump.json')) if os.path.exists(f'{d}/dump.json') else {}
seen_rel={(e['callable'],e.get('arity')) for e in dump.get('receiver_release',[])}
for e in perfile_rel:
    if (e['callable'],e.get('arity')) not in seen_rel: dump.setdefault('receiver_release',[]).append(e); seen_rel.add((e['callable'],e.get('arity')))
for e in dump.get('receiver_release',[]):
    if e.get('releases') and e['callable'] in public_callables and not e['callable'].endswith('.Dispose') and (e['callable'],e.get('arity')) not in seen:
        seen.add((e['callable'],e.get('arity'))); rows.append({'callable':e['callable'],'effect':'receiver_terminal_release','arity':e.get('arity'),'provenance':'BODY_PROVED','assembly':{'name':asm,'mvid':mvid},'derived_from':f"{acq.get('repository_url')}@{acq.get('repository_commit')} via E2"})
census=re.search(r're-body: (.*)',r.stderr); stats=json.load(open(f'{d}/facts.json')).get('stats') if os.path.exists(f'{d}/facts.json') else None
key={'schema':'own.net/re-oracle/v1','label':f'discovery BODY_PROVED rows for {pid} {acq["version"]} (pinned to MVID {mvid})','entries':rows}
json.dump(key,open(f'{d}/rows-bodyproved.json','w'),indent=1)
fresh_all=[s['method'] for s in summaries if s.get('returns',{}).get('owned')=='fresh']
fresh_public_missing=[s['method'] for s in summaries if s.get('returns',{}).get('owned')=='fresh' and s['method'].split('(')[0] not in public_callables]
rel_all=[e['callable'] for e in dump.get('receiver_release',[]) if e.get('releases')]
json.dump({'source_files':len(src),'perfile_union_added_fresh':sorted(perfile_fresh-whole_fresh),'extractor_stats':stats,'re_body_census':census.group(1) if census else None,'fresh_summaries_all':fresh_all,'receiver_release_all':rel_all,'fresh_not_public_surface':fresh_public_missing,'instance_methods_evaluated':dump.get('instance_methods_evaluated'),'public_rows':len(rows)},open(f'{d}/derive-summary.json','w'),indent=1)
print(json.dumps({'package':pid,'files':len(src),'stats':stats,'census':census.group(1) if census else None,'fresh_all':len(fresh_all),'release_all':len(rel_all),'public_rows':len(rows)}))
for x in rows: print('  ROW', x['effect'], x['callable'], x.get('arity',''))
