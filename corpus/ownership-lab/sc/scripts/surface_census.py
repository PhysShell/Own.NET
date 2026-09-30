"""Stage B denominator: public-code call counts (Sourcegraph, capped 1000) for EVERY factory-surface callable of the
eight libraries (ApiList factories + release-name candidates, arity-insensitive), same query form as CT-0."""
import json, os, sys, time, urllib.request, urllib.parse, collections
from concurrent.futures import ThreadPoolExecutor
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'; OUT=f'{S}/lab/sc/surface-census.json'
LIBS=['SkiaSharp','RabbitMQ.Client','MailKit','StackExchange.Redis','Npgsql','MQTTnet','SSH.NET','LibGit2Sharp']
items={}
for pid in LIBS:
    api=json.load(open(f'{D}/libs/{pid}/api.json'))
    for f in api['factories']:
        c=f['callable']; parts=c.split('.'); items.setdefault(c,{'package':pid,'callable':c,'kind':'factory','is_static':bool(f.get('is_static')),'property':bool(f.get('property')),'method':parts[-1],'type':parts[-2],'namespace':'.'.join(parts[:-2])})
    for r in api['release_name_candidates']:
        c=r['callable']; parts=c.split('.'); items.setdefault(c,{'package':pid,'callable':c,'kind':'release','is_static':False,'property':False,'method':parts[-1],'type':parts[-2],'namespace':'.'.join(parts[:-2])})
def q_for(r):
    m=r['method'][4:] if r['property'] and r['method'].startswith('get_') else r['method']
    if r['property']: return f'".{m}" "using {r["namespace"]}" lang:C#'
    if r['is_static']: return f'"{r["type"]}.{m}(" lang:C#'
    return f'".{m}(" "using {r["namespace"]}" lang:C#'
def stream(query, n=1000):
    url='https://sourcegraph.com/.api/search/stream?'+urllib.parse.urlencode({'q':query+f' patterntype:keyword count:{n}','display':str(n)})
    txt=''
    for attempt in range(5):
        try:
            req=urllib.request.Request(url,headers={'Accept':'text/event-stream','User-Agent':'own.net-sc'})
            with urllib.request.urlopen(req,timeout=180) as resp: txt=resp.read().decode('utf-8','replace'); break
        except Exception: time.sleep(3*(attempt+1))
    per=collections.Counter(); matches=0; ev=None; prog={}
    for line in txt.splitlines():
        if line.startswith('event: '): ev=line[7:].strip()
        elif line.startswith('data: ') and ev=='matches':
            try:
                for m in json.loads(line[6:]):
                    if m.get('type')=='content':
                        n_=len(m.get('lineMatches') or []) or len(m.get('chunkMatches') or []) or 1; per[m.get('repository','?')]+=n_; matches+=n_
            except Exception: pass
        elif line.startswith('data: ') and ev=='progress':
            try: prog=json.loads(line[6:])
            except Exception: pass
    return matches, len(per), prog.get('matchCount'), per.most_common(5)
def work(r):
    q=q_for(r); m,nrep,mc,top=stream(q); time.sleep(0.2); return dict(r,query=q,line_matches=m,repositories=nrep,server_match_count=mc,top_repos=top)
rows=list(items.values()); print('callables',len(rows),file=sys.stderr,flush=True)
with ThreadPoolExecutor(3) as ex: res=list(ex.map(work,rows))
json.dump({'generated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'cap':1000,'rows':res},open(OUT,'w'),indent=1)
print('SURFACE_CENSUS_DONE',len(res),file=sys.stderr)
