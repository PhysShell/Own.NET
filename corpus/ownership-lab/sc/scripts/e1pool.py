"""Stage E1: public nomination pool. Per CURRENT trusted row (rows-applied of the 22 libraries, with rows-whole replacing
the 8 Stage B libraries; production-convention rows excluded), Sourcegraph stream (count 1000) aggregated per repository;
exclusions: the row libraries' own repositories, forks by name heuristics, mirrors/generated; the top 30 are frozen."""
import json, os, glob, time, urllib.request, urllib.parse, collections, re, sys
from concurrent.futures import ThreadPoolExecutor
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'
WHOLE={'SkiaSharp','RabbitMQ.Client','MailKit','StackExchange.Redis','Npgsql','MQTTnet','SSH.NET','LibGit2Sharp'}
ADO={'CreateCommand','BeginTransaction','ExecuteReader','ExecuteReaderAsync'}; ADOPK={'Npgsql','MySqlConnector','Microsoft.Data.Sqlite.Core'}
rows=[]; own=set()
for acq in sorted(glob.glob(f'{D}/libs/*/acquire.json')):
    L=os.path.dirname(acq); pid=os.path.basename(L); a=json.load(open(acq))
    if not a.get('main_assembly'): continue
    src=f'{L}/rows-whole.json' if pid in WHOLE else f'{L}/rows-applied.json'
    if not os.path.exists(src): continue
    ents=json.load(open(src)); ents=ents['rows'] if 'rows' in ents else ents['entries']
    api=json.load(open(f'{L}/api.json')) if os.path.exists(f'{L}/api.json') else {}; st={f['callable']:f.get('is_static',False) for f in api.get('factories',[])}
    rep=(a.get('repository_url') or '').replace('https://github.com/','').replace('.git','').rstrip('/').lower()
    if rep and 'go.microsoft' not in rep: own.add(rep)
    for e in ents:
        c=e['callable']; parts=c.split('.'); m=parts[-1]
        if m in ADO and pid in ADOPK: continue
        rows.append({'package':pid,'callable':c,'effect':e['effect'],'method':m,'type':parts[-2],'namespace':'.'.join(parts[:-2]),'is_static':bool(st.get(c,False)),'source':'whole' if pid in WHOLE else 'subset'})
own|={'mono/skiasharp','jstedfast/mailkit','k4os/k4os.compression.lz4'}
def q_for(r): return (f'"{r["type"]}.{r["method"]}(" lang:C#' if r['is_static'] else f'".{r["method"]}(" "using {r["namespace"]}" lang:C#')+' patterntype:keyword count:1000'
def stream(query):
    url='https://sourcegraph.com/.api/search/stream?'+urllib.parse.urlencode({'q':query,'display':'1000'}); txt=''
    for attempt in range(5):
        try:
            req=urllib.request.Request(url,headers={'Accept':'text/event-stream','User-Agent':'own.net-sc'})
            with urllib.request.urlopen(req,timeout=180) as resp: txt=resp.read().decode('utf-8','replace'); break
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
def work(r): p=stream(q_for(r)); time.sleep(0.2); return r,p
with ThreadPoolExecutor(3) as ex: done=list(ex.map(work,rows))
tot=collections.Counter(); rowsets=collections.defaultdict(set); pkgsets=collections.defaultdict(set)
for r,per in done:
    for repo,n in per.items(): tot[repo]+=n; rowsets[repo].add(r['callable']); pkgsets[repo].add(r['package'])
FORK=re.compile(r'(fork|mirror|-copy|backup|archive|vendor)',re.I)
def is_own(repo): rl=repo.lower().replace('github.com/',''); return any(rl==o or rl.startswith(o+'/') for o in own)
reps=[]
for k,v in tot.most_common(400):
    reps.append({'repo':k,'opportunities':v,'distinct_rows':len(rowsets[k]),'packages':sorted(pkgsets[k]),'excluded':'own' if is_own(k) else ('fork-or-mirror-by-name' if FORK.search(k) else None)})
pool=[x for x in reps if not x['excluded']][:30]
json.dump({'generated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'rows_queried':len(rows),'repositories':reps,'frozen_pool_top30':pool},open(f'{S}/lab/sc/e1pool.json','w'),indent=1)
print('E1POOL_DONE rows',len(rows)); [print(' ',x['repo'],x['opportunities'],x['distinct_rows'],x['packages']) for x in pool[:30]]
