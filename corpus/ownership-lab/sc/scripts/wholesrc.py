"""Stage B: fetch every .cs file of the main library project at the pinned revision (paths via Sourcegraph type:path,
files via raw.githubusercontent.com), excluding test/sample/benchmark directories. Digests recorded."""
import json, os, sys, time, hashlib, urllib.request, urllib.parse, re
from concurrent.futures import ThreadPoolExecutor
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'
LIBS={'SkiaSharp':('mono/SkiaSharp','4783f51448f9b070dda4f87b83e941c9599e466e','binding/SkiaSharp/'),
 'RabbitMQ.Client':('rabbitmq/rabbitmq-dotnet-client','740faf07f04ade7d35d3539e20613c6ac6b9b46f','projects/RabbitMQ.Client/'),
 'MailKit':('jstedfast/MailKit','4.18.1','MailKit/'),
 'StackExchange.Redis':('StackExchange/StackExchange.Redis','0a92ae43b0f8e80467920115a54f9761cc04ee4c','src/StackExchange.Redis/'),
 'Npgsql':('npgsql/npgsql','d3768398c17877b3a916c3c4d87e8e11698991fc','src/Npgsql/'),
 'MQTTnet':('dotnet/MQTTnet','14463d1ef9f1f119514185c1832905b91bff827d','Source/MQTTnet/'),
 'SSH.NET':('sshnet/SSH.NET','7b2fd3dbf2c86a80a7b06cea020aa5f821c9902e','src/Renci.SshNet/'),
 'LibGit2Sharp':('libgit2/libgit2sharp','eaa698d078941fd5e3cc82b59b885cd35d8cc0f8','LibGit2Sharp/'),
 'Npgsql@9.0.4':('npgsql/npgsql','3b6c74c505c4dbc68a39b05e7440153b3bf511f4','src/Npgsql/'),
 'Npgsql@10.0.0':('npgsql/npgsql','a18021849f244716d3b68eefd705677f131f9ace','src/Npgsql/'),
 'SkiaSharp@4.148.0':('mono/SkiaSharp','4e4ce7af7ea8702593af5aeb25d05c65ffb74e90','binding/SkiaSharp/')}
EXCL=re.compile(r'(^|/)(tests?|samples?|benchmarks?|examples?|obj|bin)(/|$)',re.I)
def paths(repo, rev):
    q=f'repo:^github\\.com/{re.escape(repo)}$@{rev} file:\\.cs$ type:path count:all'
    url='https://sourcegraph.com/.api/search/stream?'+urllib.parse.urlencode({'q':q})
    req=urllib.request.Request(url,headers={'Accept':'text/event-stream','User-Agent':'own.net-sc'})
    with urllib.request.urlopen(req,timeout=300) as resp: txt=resp.read().decode('utf-8','replace')
    out=[]; ev=None
    for line in txt.splitlines():
        if line.startswith('event: '): ev=line[7:].strip()
        elif line.startswith('data: ') and ev=='matches':
            for m in json.loads(line[6:]):
                if m.get('type')=='path': out.append(m['path'])
    return out
def fetch(repo, rev, p):
    url=f'https://raw.githubusercontent.com/{repo}/{rev}/{p}'
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url,timeout=60) as r: return r.read()
        except Exception as e: time.sleep(1.5*(attempt+1)); err=str(e)[:60]
    return None
only=sys.argv[1:] or list(LIBS)
for pid in only:
    repo,rev,prefix=LIBS[pid]; d=f'{D}/libs/{pid}/src-whole'; os.makedirs(d,exist_ok=True)
    allp=paths(repo,rev); sel=[p for p in allp if p.startswith(prefix) and not EXCL.search(p[len(prefix):])]
    rec=[]
    def work(p):
        data=fetch(repo,rev,p)
        if data is None: return {'path':p,'error':'fetch failed'}
        open(f'{d}/{p.replace("/","__")}','wb').write(data); return {'path':p,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    with ThreadPoolExecutor(4) as ex: rec=list(ex.map(work,sel))
    ok=sum(1 for r in rec if 'sha256' in r)
    json.dump({'package':pid,'repo':repo,'rev':rev,'prefix':prefix,'cs_files_in_repo':len(allp),'selected':len(sel),'fetched':ok,'files':rec},open(f'{D}/libs/{pid}/sB-source.json','w'),indent=1)
    print(pid,'repo .cs',len(allp),'selected',len(sel),'fetched',ok,flush=True)
print('WHOLESRC_DONE')
