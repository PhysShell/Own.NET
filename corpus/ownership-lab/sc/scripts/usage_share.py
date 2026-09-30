"""Arm U: for each universe candidate, the share of public call-site lines that begin with 'using' (using statement /
using declaration) among the matched lines (Sourcegraph stream, count 300 per candidate)."""
import json, time, urllib.request, urllib.parse, collections, re, sys
from concurrent.futures import ThreadPoolExecutor
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
uni=json.load(open(f'{S}/lab/sc/stagec-universe.json'))['universe']
def q_for(u):
    parts=u['callable'].split('.'); m=parts[-1]; t=parts[-2]; ns='.'.join(parts[:-2])
    return (f'"{t}.{m}(" lang:C#' if u['is_static'] else f'".{m}(" "using {ns}" lang:C#')+' patterntype:keyword count:300'
def lines(query):
    url='https://sourcegraph.com/.api/search/stream?'+urllib.parse.urlencode({'q':query,'display':'300'}); txt=''
    for attempt in range(4):
        try:
            req=urllib.request.Request(url,headers={'Accept':'text/event-stream','User-Agent':'own.net-sc'})
            with urllib.request.urlopen(req,timeout=180) as resp: txt=resp.read().decode('utf-8','replace'); break
        except Exception: time.sleep(3*(attempt+1))
    out=[]; ev=None
    for line in txt.splitlines():
        if line.startswith('event: '): ev=line[7:].strip()
        elif line.startswith('data: ') and ev=='matches':
            try:
                for m in json.loads(line[6:]):
                    if m.get('type')=='content':
                        for lm in (m.get('lineMatches') or []): out.append(lm.get('line',''))
                        for cm in (m.get('chunkMatches') or []): out+= (cm.get('content','') or '').splitlines()
            except Exception: pass
    return out
def work(u):
    ls=[l.strip() for l in lines(q_for(u)) if l.strip()]; m=u['callable'].split('.')[-1]
    rel=[l for l in ls if ('.'+m+'(' in l) or (u['callable'].split('.')[-2]+'.'+m+'(' in l)]
    us=sum(1 for l in rel if l.startswith('using ') or l.startswith('using(') or ' using (' in l or ' using var ' in l or l.startswith('await using'))
    time.sleep(0.2); return {'callable':u['callable'],'lines':len(rel),'using_lines':us,'using_share':round(us/len(rel),3) if rel else None}
with ThreadPoolExecutor(3) as ex: rows=list(ex.map(work,uni))
json.dump({'rows':rows},open(f'{S}/lab/sc/usage-share.json','w'),indent=1); print('USAGE_DONE',len(rows))
