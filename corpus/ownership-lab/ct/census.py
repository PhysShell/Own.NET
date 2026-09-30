"""CT-0 semantic opportunity census over public C# code (Sourcegraph public search API).
Per trusted row callable: GraphQL matchCount/repositoriesCount (count:all), then the stream API for per-repository
line-match aggregation (count:1000). Static rows: "Type.Method(" ; instance rows: ".Method(" AND "using Namespace"."""
import json, os, glob, time, urllib.request, urllib.parse, collections, sys
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'; OUT=f'{S}/lab/ct/census.json'
rows=[]; own_repos={}
for acq in sorted(glob.glob(f'{D}/libs/*/acquire.json')):
    L=os.path.dirname(acq); pid=os.path.basename(L); a=json.load(open(acq))
    if not a.get('main_assembly') or not os.path.exists(f'{L}/rows-applied.json'): continue
    api=json.load(open(f'{L}/api.json')) if os.path.exists(f'{L}/api.json') else {}
    st={f['callable']:f.get('is_static',False) for f in api.get('factories',[])}
    own_repos[pid]=(a.get('repository_url') or '').replace('https://github.com/','').replace('.git','').lower()
    for e in json.load(open(f'{L}/rows-applied.json'))['entries']:
        c=e['callable']; parts=c.split('.'); method=parts[-1]; typ=parts[-2]; ns='.'.join(parts[:-2])
        rows.append({'package':pid,'callable':c,'effect':e['effect'],'provenance':e['provenance'],'method':method,'type':typ,'namespace':ns,'is_static':bool(st.get(c,False))})
def q_for(r):
    if r['is_static']: return f'"{r["type"]}.{r["method"]}(" lang:C#'
    return f'".{r["method"]}(" "using {r["namespace"]}" lang:C#'
def gql(query):
    body=json.dumps({"query":"query($q:String!){ search(query:$q, version:V3){ results{ matchCount limitHit repositoriesCount } } }","variables":{"q":query}}).encode()
    for attempt in range(5):
        try:
            req=urllib.request.Request('https://sourcegraph.com/.api/graphql',data=body,headers={'Content-Type':'application/json','User-Agent':'own.net-ct-census'})
            with urllib.request.urlopen(req,timeout=120) as resp: return json.loads(resp.read())['data']['search']['results']
        except Exception as ex:
            time.sleep(3*(attempt+1)); last=str(ex)[:120]
    return {'error':last}
def stream(query, n=1000):
    url='https://sourcegraph.com/.api/search/stream?'+urllib.parse.urlencode({'q':query+f' count:{n}','display':str(n)})
    for attempt in range(5):
        try:
            req=urllib.request.Request(url,headers={'Accept':'text/event-stream','User-Agent':'own.net-ct-census'})
            with urllib.request.urlopen(req,timeout=180) as resp: txt=resp.read().decode('utf-8','replace')
            break
        except Exception as ex:
            time.sleep(3*(attempt+1)); txt=''
    per=collections.Counter(); files=0
    ev=None
    for line in txt.splitlines():
        if line.startswith('event: '): ev=line[7:].strip()
        elif line.startswith('data: ') and ev=='matches':
            try:
                for m in json.loads(line[6:]):
                    if m.get('type')=='content':
                        n_lines=len(m.get('lineMatches') or []) or len(m.get('chunkMatches') or []) or 1
                        per[m.get('repository','?')]+=n_lines; files+=1
            except Exception: pass
    return per, files
out={'generated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'rows':[],'own_repos':own_repos}
repo_tot=collections.Counter(); repo_rows=collections.defaultdict(set)
from concurrent.futures import ThreadPoolExecutor
def work(r):
    q=q_for(r)+' patterntype:keyword'
    g=gql(q+' count:1000'); time.sleep(0.3)
    per,files=stream(q); time.sleep(0.3)
    return r,q,g,per,files
with ThreadPoolExecutor(3) as ex: done=list(ex.map(work,rows))
for i,(r,q,g,per,files) in enumerate(done):
    r2=dict(r); r2.update({'query':q,'match_count':g.get('matchCount'),'limit_hit':g.get('limitHit'),'repositories':g.get('repositoriesCount'),'error':g.get('error'),'stream_files':files,'stream_repos':len(per),'top_repos':per.most_common(8)})
    out['rows'].append(r2)
    for repo,n in per.items(): repo_tot[repo]+=n; repo_rows[repo].add(r['callable'])
    print(i+1,'/',len(rows),r['callable'],'matches',g.get('matchCount'),'repos',g.get('repositoriesCount'),'stream',files,file=sys.stderr,flush=True)
own=set(v for v in own_repos.values() if v)
def is_own(repo): rl=repo.lower().replace('github.com/',''); return any(rl==o or rl.startswith(o+'/') for o in own)
out['repositories']=[{'repo':k,'opportunities':v,'distinct_rows':len(repo_rows[k]),'is_row_library_repo':is_own(k)} for k,v in repo_tot.most_common(200)]
ext=[x for x in out['repositories'] if not x['is_row_library_repo']]
out['decision_inputs']={'repos_ge100_excluding_own':sum(1 for x in ext if x['opportunities']>=100),'repos_ge30_excluding_own':sum(1 for x in ext if x['opportunities']>=30),'rows_with_zero_matches':sum(1 for r in out['rows'] if not r['match_count']),'rows_with_lt10_matches':sum(1 for r in out['rows'] if (r['match_count'] or 0)<10),'stream_cap_per_row':1000,'graphql_count_cap':1000}
json.dump(out,open(OUT,'w'),indent=1); print('CENSUS_DONE rows',len(rows),file=sys.stderr)
