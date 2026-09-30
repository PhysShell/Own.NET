"""Assemble paper-eval/ownership-lab/ct/ct-v1.json from the CT artefacts (census, Gate 0, validation, Skia witnesses,
IL-hash identity) and evaluate the frozen gates. Decisions are filled from the numbers; the wording of the
conclusions is written by the experimenter in the same file after reading them (recorded as such)."""
import json, os, glob, collections, datetime, sys
OD=collections.OrderedDict
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; C=f'{S}/lab/ct'; P='/home/user/Own.NET-paperwork'
now=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
def J(p): return json.load(open(p)) if os.path.exists(p) else None
cen=J(f'{C}/census.json'); g=J(f'{C}/gate0-results.json'); val=J(f'{C}/ct-validation.json'); wit=J(f'{C}/skia-witness-results.json'); wrows={r['id']:r for r in (J(f'{C}/skia-witness-rows.json') or [])}
# ---- CT-0 census
census=None
if cen:
    rows=cen['rows']; repos=cen['repositories']; ext=[x for x in repos if not x['is_row_library_repo']]
    mc=[(r['match_count'] or 0) for r in rows]
    census=OD([("rows_queried",len(rows)),("query_form","static: \"Type.Method(\" ; instance: \".Method(\" AND \"using Namespace\"; lang:C#; patterntype:keyword; GraphQL count:1000 (limit_hit recorded); stream count:1000 per row for the per-repository aggregation"),
      ("rows_with_zero_matches",sum(1 for m in mc if m==0)),("rows_with_lt10_matches",sum(1 for m in mc if m<10)),("rows_with_ge100_matches",sum(1 for m in mc if m>=100)),("rows_limit_hit_at_1000",sum(1 for r in rows if r.get('limit_hit'))),
      ("median_matches_per_row",sorted(mc)[len(mc)//2] if mc else None),("top_rows_by_matches",[(r['callable'],r['match_count'],r['repositories']) for r in sorted(rows,key=lambda r:-(r['match_count'] or 0))[:15]]),
      ("repositories_seen",len(repos)),("repos_ge100_excluding_own",cen['decision_inputs']['repos_ge100_excluding_own']),("repos_ge30_excluding_own",cen['decision_inputs']['repos_ge30_excluding_own']),
      ("top_repositories_excluding_own",[(x['repo'],x['opportunities'],x['distinct_rows']) for x in ext[:25]]),
      ("caveats","text search over-counts (other types' same-named methods, tests, forks, vendored copies, samples) and the per-row stream cap of 1000 matches under-counts the densest rows; instance-row queries require the namespace using directive in the same file")])
# ---- Gate 0
gate0=None
if g:
    gate0=OD([("libraries_evaluated",g['libraries_evaluated']),("surface_callables",g['surface_total']),("positives",g['positives_total']),("mean_over_libraries",g['mean_over_libraries']),("pooled",g['pooled']),("lr_top_weights",g['lr_top_weights_all_data']),("per_library",g['per_library'])])
# ---- validation
validation=None
if val:
    tal=OD()
    for r in val['results']:
        t=tal.setdefault(r['arm'],OD([("executions",0),("PROVED",0),("REFUSED",0),("NO_SOURCE",0),("ERROR",0)])); t['executions']+=1; t[r['outcome']]=t.get(r['outcome'],0)+1
    validation=OD([("rule","first candidate of each arm's queue for the first 10 libraries (alphabetical) with a non-empty queue; body proof (E1/E3 + H-20) over the candidate type's source file at the pinned commit (path resolved by Sourcegraph type:path at that commit); PROVED = a NOVEL BODY_PROVED row (not among the applied rows)"),("tallies",tal),("results",[OD([(k,r.get(k)) for k in ('arm','package','callable','outcome','source','why','fresh_in_file')]) for r in val['results']])])
# ---- Skia witnesses + IL hash
skia=None
if wit:
    by=collections.Counter((wrows[r['id']]['version_under_test'],'ns20' if 'NS20' in r['id'] else 'net6', r['verdict']) for r in wit)
    skia=OD([("witnesses",len(wit)),("verdicts",dict(collections.Counter(r['verdict'] for r in wit))),("by_version_asset",[{"version":k[0],"asset":k[1],"verdict":k[2],"n":v} for k,v in sorted(by.items())]),("mvids_witnessed",sorted({r.get('asm') for r in wit if r.get('asm')})),("refutations",sum(1 for r in wit if r['verdict']=='cached'))])
ilh=None
try:
    def load(tag):
        d=json.load(open(f'{C}/relh-SkiaSharp@{tag}.json')); return {(r['callable'],tuple(r['param_types'])):r['il_hash'] for r in d['records'] if r['has_body']}
    a=load('3.119.4@net6.0'); b=load('4.153.1@net6.0'); c=load('4.153.1@netstandard2.0'); d=load('4.152.0@net6.0')
    def cmp(x,y): common=set(x)&set(y); same=sum(1 for k in common if x[k]==y[k]); return {"common":len(common),"same":same,"different":len(common)-same}
    want=['SkiaSharp.SKBitmap.Decode','SkiaSharp.SKBitmap.FromImage','SkiaSharp.SKData.AsStream','SkiaSharp.SKFont.GetTextPath','SkiaSharp.SKPath.ParseSvgPathData','SkiaSharp.SKTypeface.ToFont']
    tabs={}
    for tag in ('3.119.4@net6.0','3.119.4@netstandard2.0','4.148.0@net6.0','4.148.0@netstandard2.0','4.152.0@net6.0','4.152.0@netstandard2.0','4.153.1@net6.0','4.153.1@netstandard2.0'):
        for k,h in load(tag).items():
            if k[0] in want: tabs.setdefault(k,{})[tag]=h
    rows_same=sum(1 for k,v in tabs.items() if len(v)==8 and len(set(v.values()))==1); rows_diff=sum(1 for k,v in tabs.items() if len(v)==8 and len(set(v.values()))>1)
    ilh=OD([("definition","SHA-256 over the sequence of (opcode, resolved operand name for method/field/type tokens) of the method body; tokens themselves are not hashed, so the hash is stable across assemblies that compile the same source"),("row_callables_overloads_with_one_hash_across_8_assets",rows_same),("row_callables_overloads_with_differing_hashes",rows_diff),("3.119.4_vs_4.153.1_net6",cmp(a,b)),("4.153.1_net6_vs_netstandard2.0",cmp(b,c)),("4.152.0_vs_4.153.1_net6",cmp(d,b))])
except Exception as e: ilh={"error":str(e)[:100]}
rec=OD([("schema","own.net/ownership-lab/ct/v1"),("track","ownership-semantics-lab (EXPLORATORY): H-21 relational candidate discovery under ct-prereg-v1.json (frozen 2026-09-30T09:10:55Z)"),("written_at_utc",now),
 ("CT0_census",census),("gate0",gate0),("novelty_validation",validation),("CT3_skia_challenge",skia),("identity_il_body_hash",ilh)])
json.dump(rec,open(f'{C}/ct-v1.draft.json','w'),indent=1); print('draft written; sections present:',[k for k,v in rec.items() if v])
