"""CT-0 supplement: per-repository aggregation restricted to rows NOT already covered by the production ADO.NET
convention (IDbConnection.CreateCommand / BeginTransaction, IDbCommand.ExecuteReader*), which OFF Own.NET tracks
without any row; such sites never reach the row oracle, so they carry no 'semantic ammunition' from the rows."""
import json, collections, time, sys
sys.path.insert(0,'.')
from concurrent.futures import ThreadPoolExecutor
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; C=f'{S}/lab/ct'
cen=json.load(open(f'{C}/census.json'))
ADO={'CreateCommand','BeginTransaction','ExecuteReader','ExecuteReaderAsync'}; ADOPK={'Npgsql','MySqlConnector','Microsoft.Data.Sqlite.Core'}
rows=[r for r in cen['rows'] if not (r['method'] in ADO and r['package'] in ADOPK)]
covered=[r['callable'] for r in cen['rows'] if (r['method'] in ADO and r['package'] in ADOPK)]
import importlib.util
spec=importlib.util.spec_from_file_location('census',f'{C}/census.py')
# reuse the stream function without re-running the module body: copy of the function
import urllib.request, urllib.parse
def stream(query, n=1000):
    url='https://sourcegraph.com/.api/search/stream?'+urllib.parse.urlencode({'q':query+f' count:{n}','display':str(n)})
    txt=''
    for attempt in range(5):
        try:
            req=urllib.request.Request(url,headers={'Accept':'text/event-stream','User-Agent':'own.net-ct-census'})
            with urllib.request.urlopen(req,timeout=180) as resp: txt=resp.read().decode('utf-8','replace')
            break
        except Exception: time.sleep(3*(attempt+1))
    per=collections.Counter(); ev=None
    for line in txt.splitlines():
        if line.startswith('event: '): ev=line[7:].strip()
        elif line.startswith('data: ') and ev=='matches':
            try:
                for m in json.loads(line[6:]):
                    if m.get('type')=='content': per[m.get('repository','?')]+=len(m.get('lineMatches') or []) or len(m.get('chunkMatches') or []) or 1
            except Exception: pass
    return per
def work(r): return r, stream(r['query'])
with ThreadPoolExecutor(3) as ex: done=list(ex.map(work,rows))
tot=collections.Counter(); rowsets=collections.defaultdict(set)
for r,per in done:
    for repo,n in per.items(): tot[repo]+=n; rowsets[repo].add(r['callable'])
own=set(v for v in cen['own_repos'].values() if v)
def is_own(repo): rl=repo.lower().replace('github.com/',''); return any(rl==o or rl.startswith(o+'/') for o in own)
reps=[{'repo':k,'opportunities':v,'distinct_rows':len(rowsets[k]),'rows':sorted(rowsets[k])[:12],'is_row_library_repo':is_own(k)} for k,v in tot.most_common(300)]
ext=[x for x in reps if not x['is_row_library_repo']]
out={'rows_considered':len(rows),'rows_excluded_as_production_covered':covered,'repositories':reps,'repos_ge100_excluding_own':sum(1 for x in ext if x['opportunities']>=100),'repos_ge30_excluding_own':sum(1 for x in ext if x['opportunities']>=30),'top_excluding_own':[(x['repo'],x['opportunities'],x['distinct_rows']) for x in ext[:30]]}
json.dump(out,open(f'{C}/census2.json','w'),indent=1); print('CENSUS2_DONE rows',len(rows),'excluded',len(covered),'ge100',out['repos_ge100_excluding_own'],'ge30',out['repos_ge30_excluding_own']); [print(' ',x) for x in out['top_excluding_own'][:25]]
