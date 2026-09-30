"""discovery: assemble the per-library record (S1..S10) into discovery-v1.json from the pipeline artefacts and the
experimenter's triage file (triage.json: {"<pid>/<tag>": [{"finding": [file,line,code], "verdict": TRUE|BENIGN|FALSE,
"root_cause": ..., "severity": ..., "overlap": ..., "note": ...}]})."""
import json, os, glob, hashlib, datetime, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'
OD=collections.OrderedDict
ledger=json.load(open(f'{D}/s7-ledger.json')) if os.path.exists(f'{D}/s7-ledger.json') else {}
triage=json.load(open(f'{D}/triage.json')) if os.path.exists(f'{D}/triage.json') else {}
libs=OD()
for acq in sorted(glob.glob(f'{D}/libs/*/acquire.json')):
    L=os.path.dirname(acq); pid=os.path.basename(L); a=json.load(open(acq))
    api=json.load(open(f'{L}/api.json')) if os.path.exists(f'{L}/api.json') else {}
    s3=json.load(open(f'{L}/s3-llm-candidates.json')) if os.path.exists(f'{L}/s3-llm-candidates.json') else {}
    s4=json.load(open(f'{L}/s4-source.json')) if os.path.exists(f'{L}/s4-source.json') else {}
    ds=json.load(open(f'{L}/derive-summary.json')) if os.path.exists(f'{L}/derive-summary.json') else {}
    rows=json.load(open(f'{L}/rows-applied.json'))['entries'] if os.path.exists(f'{L}/rows-applied.json') else []
    scans=OD()
    for sc in sorted(glob.glob(f'{L}/s8-scan-*.json')):
        r=json.load(open(sc)); tag=r['consumer']
        cons=json.load(open(f'{L}/s8-consumers-{tag}.json')) if os.path.exists(f'{L}/s8-consumers-{tag}.json') else {}
        scans[tag]=OD([("files_scanned",r['files']),("files_fetched",len([x for x in cons.get('files',[]) if 'sha256' in x])),("off_findings",len(r['off']['findings'])),("key_findings",len(r['key_arm']['findings'])),("new",r['new_findings']),("lost",r['lost_findings']),("python_equals_rust",r['off']['python_equals_rust'] and r['key_arm']['python_equals_rust']),("key_census",r['key_arm']['census']),("triage",triage.get(f'{pid}/{tag}',[]))])
    adopt_bool=[c for c in api.get('adopting_ctors',[]) if c.get('bool_params')]
    if not a.get('main_assembly'):
        libs[pid]=OD([("version",a['version']),("nupkg_sha256",a['nupkg_sha256']),("status","meta-package without a lib assembly; substituted by Microsoft.Data.Sqlite.Core "+a['version']+" (the assembly-bearing package); not counted as a completed library")]); continue
    libs[pid]=OD([
        ("version",a['version']),("nupkg_sha256",a['nupkg_sha256']),("repository",a.get('repository_url')),("commit_pin",a.get('repository_commit') or 'tag (no nuspec commit)'),("assembly_mvid",(a.get('identity') or {}).get('mvid')),
        ("S2_surface",OD([("disposable_types",api.get('disposable_types')),("factory_candidates",len(api.get('factories',[]))),("adopting_ctors",len(api.get('adopting_ctors',[]))),("adopting_ctors_with_bool",len(adopt_bool)),("release_name_candidates",len(api.get('release_name_candidates',[])))])),
        ("S3_llm",OD([("suggested_rows",len(s3.get('suggested_rows',[]))),("suggested_negatives",len(s3.get('suggested_negatives',[]))),("written_before_bodies",s3.get('written_before_bodies'))])),
        ("S4_source",OD([("files_fetched",len([f for f in s4.get('files',[]) if 'sha256' in f])),("files_requested",len(s4.get('files',[])))])),
        ("S5_derivation",OD([("extractor_stats",ds.get('extractor_stats')),("re_body_census",ds.get('re_body_census')),("fresh_summaries_all",len(ds.get('fresh_summaries_all',[]))),("perfile_union_added",len(ds.get('perfile_union_added_fresh',[]))),("public_body_proved_rows",ds.get('public_rows'))])),
        ("S6_S7",ledger.get(pid,{})),
        ("applied_rows",[OD([("callable",e['callable']),("effect",e['effect']),("provenance",e['provenance'])]) for e in rows]),
        ("S8_scans",scans),
    ])
json.dump(OD([("schema","own.net/ownership-lab/discovery/v1"),("generated_utc",datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')),("libraries",libs)]), open(f'{D}/discovery-libs.json','w'), indent=1)
print('libraries recorded:', len(libs))
